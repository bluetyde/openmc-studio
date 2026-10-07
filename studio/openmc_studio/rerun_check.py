"""rerun_check: verify file hashes and environment of a previous run or export against the current machine.

Reads <run_dir>/provenance.json, hashes files inside run_dir to detect changes, compares the recorded
environment against current software/data versions, and reports differences without modifying files or running OpenMC.
"""
import argparse
import json
import sys
from pathlib import Path

from . import provenance


def _empty_counts():
    return {
        "files_changed": 0,
        "files_missing": 0,
        "files_other": 0,
        "environment_warnings": 0,
        "environment_info": 0,
    }


def _flatten(obj, prefix=""):
    leaves = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            path = f"{prefix}.{k}" if prefix else str(k)
            leaves.update(_flatten(v, path))
    else:
        leaves[prefix] = obj
    return leaves


def check(run_dir, current=None) -> dict:
    run_path = Path(run_dir)
    prov_file = run_path / "provenance.json"

    try:
        exists = prov_file.exists()
    except OSError:
        return {
            "status": "bad-record",
            "run_dir": str(run_dir),
            "recorded": None,
            "files": [],
            "environment": [],
            "notes": ["cannot access provenance.json"],
            "counts": _empty_counts(),
        }

    if not exists:
        return {
            "status": "no-record",
            "run_dir": str(run_dir),
            "recorded": None,
            "files": [],
            "environment": [],
            "notes": [],
            "counts": _empty_counts(),
        }

    try:
        content = prov_file.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {
            "status": "no-record",
            "run_dir": str(run_dir),
            "recorded": None,
            "files": [],
            "environment": [],
            "notes": [],
            "counts": _empty_counts(),
        }
    except OSError as exc:
        return {
            "status": "bad-record",
            "run_dir": str(run_dir),
            "recorded": None,
            "files": [],
            "environment": [],
            "notes": [f"cannot read provenance.json: {exc}"],
            "counts": _empty_counts(),
        }

    try:
        rec = json.loads(content)
    except (json.JSONDecodeError, ValueError) as exc:
        return {
            "status": "bad-record",
            "run_dir": str(run_dir),
            "recorded": None,
            "files": [],
            "environment": [],
            "notes": [f"provenance.json is not valid JSON: {exc}"],
            "counts": _empty_counts(),
        }

    if not isinstance(rec, dict):
        return {
            "status": "bad-record",
            "run_dir": str(run_dir),
            "recorded": None,
            "files": [],
            "environment": [],
            "notes": ["provenance.json is not a JSON object"],
            "counts": _empty_counts(),
        }

    if "error" in rec:
        return {
            "status": "bad-record",
            "run_dir": str(run_dir),
            "recorded": None,
            "files": [],
            "environment": [],
            "notes": [f"record contains error: {rec['error']}"],
            "counts": _empty_counts(),
        }

    if "environment" not in rec or not isinstance(rec["environment"], dict):
        return {
            "status": "bad-record",
            "run_dir": str(run_dir),
            "recorded": None,
            "files": [],
            "environment": [],
            "notes": ["environment in provenance.json is not an object"],
            "counts": _empty_counts(),
        }

    if "files" in rec and not isinstance(rec["files"], dict):
        return {
            "status": "bad-record",
            "run_dir": str(run_dir),
            "recorded": None,
            "files": [],
            "environment": [],
            "notes": ["files in provenance.json is present and not an object"],
            "counts": _empty_counts(),
        }

    recorded = {
        "kind": rec.get("kind"),
        "written": rec.get("written"),
    }

    try:
        resolved_run_dir = run_path.resolve()
    except OSError:
        resolved_run_dir = run_path

    files_map = rec.get("files") or {}
    files_list = []
    files_changed = 0
    files_missing = 0
    files_other = 0

    for name in sorted(files_map.keys()):
        expected = files_map[name]
        is_inside = False
        target = run_path / name

        try:
            target_resolved = target.resolve()
            if (
                not Path(name).is_absolute()
                and target_resolved != resolved_run_dir
                and target_resolved.is_relative_to(resolved_run_dir)
            ):
                is_inside = True
        except (OSError, ValueError):
            is_inside = False

        if not is_inside:
            state = "rejected"
            actual = None
            files_other += 1
        elif not target.exists():
            state = "missing"
            actual = None
            files_missing += 1
        else:
            try:
                digest = provenance.sha256(target)
                actual = digest
                if digest == expected:
                    state = "ok"
                else:
                    state = "changed"
                    files_changed += 1
            except OSError:
                state = "unreadable"
                actual = None
                files_other += 1

        files_list.append({
            "name": name,
            "state": state,
            "expected": expected,
            "actual": actual,
        })

    notes = []
    recorded_env = rec["environment"]

    exporter = None
    rec_exporter = recorded_env.get("exporter")
    if isinstance(rec_exporter, dict) and "path" in rec_exporter and rec_exporter["path"] is not None:
        exp_path = Path(rec_exporter["path"])
        try:
            if exp_path.is_dir():
                exporter = exp_path
            else:
                notes.append(f"recorded exporter path does not exist: {rec_exporter['path']}")
        except OSError:
            notes.append(f"recorded exporter path does not exist: {rec_exporter['path']}")

    if current is not None:
        cur_env = current
    else:
        cur_env = provenance.environment(exporter=exporter)

    rec_leaves = _flatten(recorded_env)
    cur_leaves = _flatten(cur_env)

    all_paths = sorted(set(rec_leaves.keys()) | set(cur_leaves.keys()))
    env_diffs = []
    env_warnings = 0
    env_info = 0

    for path in all_paths:
        rec_val = rec_leaves.get(path)
        cur_val = cur_leaves.get(path)
        if rec_val != cur_val:
            last = path.split(".")[-1]
            level = "info" if last in ("executable", "path", "cross_sections") else "warning"
            if level == "warning":
                env_warnings += 1
            else:
                env_info += 1
            env_diffs.append({
                "path": path,
                "recorded": rec_val,
                "current": cur_val,
                "level": level,
            })

    counts = {
        "files_changed": files_changed,
        "files_missing": files_missing,
        "files_other": files_other,
        "environment_warnings": env_warnings,
        "environment_info": env_info,
    }

    has_file_diffs = any(f["state"] != "ok" for f in files_list)
    if has_file_diffs or env_warnings > 0:
        status = "differences"
    else:
        status = "match"

    return {
        "status": status,
        "run_dir": str(run_dir),
        "recorded": recorded,
        "files": files_list,
        "environment": env_diffs,
        "notes": notes,
        "counts": counts,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify recorded provenance against current environment and files."
    )
    parser.add_argument("run_dir", metavar="RUN_DIR", help="Folder containing provenance.json")
    parser.add_argument("--json", action="store_true", help="Output results as JSON")
    args = parser.parse_args(argv)

    res = check(args.run_dir)
    if args.json:
        print(json.dumps(res, indent=1))
    else:
        print(f"status: {res['status']} {res['run_dir']}")
        for f in res["files"]:
            if f["state"] != "ok":
                print(f"file {f['name']}: {f['state']}")
        for diff in res["environment"]:
            print(f"{diff['level']}: {diff['path']}: recorded {diff['recorded']}, current {diff['current']}")
        for note in res["notes"]:
            print(note)

    if res["status"] == "match":
        return 0
    if res["status"] == "differences":
        return 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
