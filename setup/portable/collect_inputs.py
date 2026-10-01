"""Collect immutable build inputs; never copy an installed environment or user home.

Run on the maintainer's Linux build host. The output is private build staging,
not the end-user package. Conda packages are verified against installed records.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess


def digest(path, algorithm="sha256"):
    h = hashlib.new(algorithm)
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def collect(env, cache, output, label, locks):
    records = sorted((json.loads(p.read_text()) for p in (env / "conda-meta").glob("*.json")),
                     key=lambda r: r["name"])
    if not records:
        raise ValueError(f"No conda package records: {env}")
    public, local, inventory = ["@EXPLICIT"], ["@EXPLICIT"], []
    for r in records:
        filename = r["fn"]
        source = cache / filename
        algorithm = "sha256" if r.get("sha256") else "md5"
        expected = r[algorithm]
        if not source.is_file() or digest(source, algorithm) != expected:
            raise ValueError(f"Missing or corrupt cached package: {source}")
        target = output / "packages" / filename
        if not target.exists():
            shutil.copyfile(source, target)
        public.append(r["url"] + "#" + r["md5"])
        local.append("file:///build/packages/" + filename + "#" + r["md5"])
        inventory.append({k: r.get(k) for k in ("name", "version", "build", "url", "sha256", "license")})
        extracted = cache / filename.removesuffix(".conda").removesuffix(".tar.bz2") / "info"
        notice = output / "notices" / label / (r["name"] + "-" + r["version"])
        notice.mkdir(parents=True, exist_ok=True)
        for item in ("licenses", "recipe", "about.json"):
            src = extracted / item
            if src.is_dir():
                shutil.copytree(src, notice / item, dirs_exist_ok=True)
            elif src.is_file():
                shutil.copyfile(src, notice / item)
    (locks / f"{label}.explicit.txt").write_text("\n".join(public) + "\n")
    (output / f"{label}.explicit.txt").write_text("\n".join(local) + "\n")
    (output / "notices" / f"{label}.json").write_text(json.dumps(inventory, indent=2) + "\n")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--conda", type=Path, required=True)
    p.add_argument("--exporter", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=True)
    (a.output / "packages").mkdir(exist_ok=True)
    (a.output / "notices").mkdir(exist_ok=True)
    locks = Path(__file__).parent / "locks"
    for label in ("openmc-mcnp", "openmc-cad"):
        collect(a.conda / "envs" / label, a.conda / "pkgs", a.output, label, locks)
    status = subprocess.check_output(["git", "-C", str(a.exporter), "status", "--porcelain"], text=True)
    if status.strip():
        raise ValueError("Exporter checkout must be clean")
    subprocess.run(["git", "-C", str(a.exporter), "archive", "--format=tar",
                    "--output=" + str(a.output / "exporter.tar"), "HEAD"], check=True)
    revision = subprocess.check_output(["git", "-C", str(a.exporter), "rev-parse", "HEAD"], text=True).strip()
    (a.output / "exporter-revision.txt").write_text(revision + "\n")
    print("Build inputs verified:", a.output)


if __name__ == "__main__":
    main()
