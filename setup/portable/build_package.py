"""Assemble a versioned offline folder from reviewed code and a verified WSL export.

Run with maintainer Python; end users need only Windows PowerShell and WSL2.
Never overwrites an existing delivery folder or copies development/user files.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

from runtime import nuclear_files


def record(path, root):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(4 * 1024 * 1024), b""):
            h.update(chunk)
    return {"path": path.relative_to(root).as_posix(), "bytes": path.stat().st_size,
            "sha256": h.hexdigest()}


def assemble(repo, data, archive, notices, output, runtime_id):
    # Validate before creating the destination, especially a partial data copy.
    nuclear_files(data)
    if output.exists():
        raise ValueError("Output already exists; choose a new version folder. User data is never overwritten.")
    if not archive.is_file() or archive.stat().st_size < 1024:
        raise ValueError("Missing runtime export")
    git = ["git", "-c", f"safe.directory={repo.as_posix()}", "-C", str(repo)]
    files = subprocess.check_output(git + ["ls-files", "-z"], text=True).split("\0")
    untracked = subprocess.check_output(git + ["ls-files", "--others", "--exclude-standard", "-z"], text=True).split("\0")
    # Only explicit production trees and licensing material. New portable files
    # can be packaged for testing before committing; manifest hashes record them.
    selected = sorted({name for name in files + untracked if name and
                       (name.startswith(("studio/", "examples/", "setup/portable/")) or
                        name in {"LICENSE", "THIRD_PARTY_NOTICES.md"})})
    if not selected:
        raise ValueError("Empty app snapshot")
    output.mkdir(parents=True)
    for name in selected:
        source = repo / name
        if source.is_symlink():
            raise ValueError(f"Unexpected app symlink: {name}")
        dest = output / "app" / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, dest)
    for name in ("Start Studio.cmd", "Start-Studio.ps1"):
        shutil.copyfile(repo / "setup/portable" / name, output / name)
    shutil.copyfile(repo / "setup/portable/USER-README.txt", output / "READ ME.txt")
    shutil.copyfile(repo / "setup/portable/VERIFICATION.md", output / "VERIFICATION.md")
    print("Copying nuclear data...", flush=True)
    shutil.copytree(data, output / "nuclear_data", ignore=shutil.ignore_patterns("._*", ".DS_Store"))
    nuclear_files(output / "nuclear_data")
    shutil.copytree(notices, output / "licenses")
    (output / "runtime").mkdir()
    print("Copying runtime...", flush=True)
    runtime = output / "runtime" / "studio-linux64.tar"
    shutil.copyfile(archive, runtime)
    print("Hashing package contents...", flush=True)
    records = [record(p, output) for p in sorted(output.rglob("*")) if p.is_file() and p != runtime]
    runtime_record = record(runtime, output)
    runtime_record.update(id=runtime_id, requiredFreeBytes=max(20 * 1024**3, runtime.stat().st_size * 2))
    revision = subprocess.check_output(git + ["rev-parse", "HEAD"], text=True).strip()
    manifest = {"schema": 1, "platform": "windows-x86_64-wsl2", "studioRevision": revision,
                "runtime": runtime_record, "files": records}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    checksums = records + [runtime_record, record(output / "manifest.json", output)]
    (output / "SHA256SUMS").write_text("".join(f"{r['sha256']}  {r['path']}\n" for r in checksums), encoding="utf-8")
    for name in ("projects", "results", "logs"):
        (output / name).mkdir()
    print(f"Package assembled: {output}; {len(records)} files plus runtime. Run acceptance checks before release.")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("data", "runtime", "notices", "output"):
        p.add_argument("--" + name, type=Path, required=True)
    p.add_argument("--runtime-id", required=True)
    a = p.parse_args()
    try:
        assemble(Path(__file__).resolve().parents[2], a.data.resolve(), a.runtime.resolve(),
                 a.notices.resolve(), a.output.resolve(), a.runtime_id)
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"Package build failed: {exc}", file=sys.stderr)
        sys.exit(1)
