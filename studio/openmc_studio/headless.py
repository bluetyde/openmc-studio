"""Headless runner for one bounded OpenMC Studio case (the SEED integration entry point).

    python -m openmc_studio.headless describe
    python -m openmc_studio.headless validate PROJECT.json
    python -m openmc_studio.headless run MODEL.py PROJECT.json --out DIR --run-id ID [--timeout S] [--threads N]
    python -m openmc_studio.headless cancel DIR/ID

Every verb prints exactly one JSON line. The caller (SEED) has already checked that MODEL.py is what Studio's generator makes of
PROJECT.json; this runner trusts nothing else about the script beyond that and runs it as a child process in a new session.
First slice, refused explicitly outside it: fixed-source runs, no track output, bounded particles and batches.

A run folder DIR/ID holds model.py, project.json, run.log, statepoint.N.h5, results.json (tallies, deterministic), provenance.json,
child.json (the child's identity, for cancel) and manifest.json. The manifest is written LAST and atomically: while it says
"running" the run is not committed. Exit codes: 0 reply produced and ok, 1 reply produced and not ok, 2 bad usage.
"""
import argparse
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

FORMAT = "openmc-studio-headless-run"
VERSION = 1
MAX_PARTICLES = 1_000_000  # per batch
MAX_BATCHES = 1000
DEFAULT_TIMEOUT = 3600


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _atomic_write(path, text):
    path = Path(path)
    tmp = path.with_name("." + path.name + "." + str(os.getpid()) + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def _dump(obj):
    return json.dumps(obj, indent=2, sort_keys=True) + "\n"


def _reply(ok, **fields):
    print(json.dumps({"ok": ok, **fields}, sort_keys=True))
    return 0 if ok else 1


def _problem(code, path, message):
    return {"code": code, "path": path, "message": message}


def identity(pid):
    """The process's start time as the OS reports it, or None if it is gone. It survives exec (the child is a fork of this runner for
    a moment before it becomes `python model.py`, so a command line would change under us) and a recycled pid gets another value, so
    a stale record never matches a stranger. Linux reads /proc, elsewhere `ps`."""
    try:
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19]
    except (OSError, IndexError):
        pass
    try:
        r = subprocess.run(["ps", "-o", "lstart=", "-p", str(pid)], capture_output=True, text=True, timeout=10)
        return r.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def _openmc_version():
    try:
        import openmc
        return openmc.__version__
    except Exception:  # noqa: BLE001
        return None


def describe():
    from . import provenance
    env = provenance.environment()
    data = env.get("nuclear_data") or {}
    return _reply(True, format=FORMAT, version=VERSION, openmc=_openmc_version(), nuclearData=data,
                  runModes=["fixed source"], limits={"maxParticles": MAX_PARTICLES, "maxBatches": MAX_BATCHES, "maxTimeoutSeconds": DEFAULT_TIMEOUT * 24},
                  platform=env.get("platform"), python=env.get("python"))


def check_project(project):
    """First-slice refusals from the project's own settings. Nothing is executed."""
    problems = []
    st = (project or {}).get("settings")
    if not isinstance(st, dict):
        return [_problem("E_SCHEMA_INVALID", "/settings", "the project has no settings")]
    if st.get("runMode") != "fixed source":
        problems.append(_problem("E_UNSUPPORTED", "/settings/runMode", f"only fixed-source runs are supported, not {st.get('runMode')!r}"))
    for key, cap in (("particles", MAX_PARTICLES), ("batches", MAX_BATCHES)):
        v = st.get(key)
        if not isinstance(v, int) or isinstance(v, bool) or v < 1:
            problems.append(_problem("E_SCHEMA_INVALID", f"/settings/{key}", f"{key} must be a whole number of at least 1"))
        elif v > cap:
            problems.append(_problem("E_LIMIT", f"/settings/{key}", f"{key} {v} is over the limit {cap}"))
    if not isinstance(st.get("seed"), int) or isinstance(st.get("seed"), bool):
        problems.append(_problem("E_SCHEMA_INVALID", "/settings/seed", "a whole-number seed is required so the run can be repeated"))
    if (st.get("maxTracks") or 0) > 0:
        problems.append(_problem("E_UNSUPPORTED", "/settings/maxTracks", "track output is not supported"))
    if not (project.get("tallies") or []):
        problems.append(_problem("E_SCHEMA_INVALID", "/tallies", "the project has no tally, so the run would produce no result"))
    # then the errors the page and /api/run refuse too (prerun_check.py), after the capability checks above so their codes come first
    from . import prerun_check
    said = {"settings-particles": "/settings/particles", "settings-batches": "/settings/batches", "settings-seed": "/settings/seed"}
    for f in prerun_check.check(project):
        if f["code"] in said and any(x["path"] == said[f["code"]] for x in problems):
            continue  # already reported above with its own path
        problems.append(_problem("E_SCHEMA_INVALID", f["path"], f["message"]))
    return problems


def _setup_problems():
    if _openmc_version() is None:
        return [_problem("E_SETUP_REQUIRED", "", "openmc is not importable in this Python")]
    xs = os.environ.get("OPENMC_CROSS_SECTIONS")
    if not xs or not Path(xs).is_file():
        return [_problem("E_SETUP_REQUIRED", "", "OPENMC_CROSS_SECTIONS does not name a cross_sections.xml")]
    return []


def validate(project_path):
    try:
        project = json.loads(Path(project_path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return _reply(False, problems=[_problem("E_SCHEMA_INVALID", "", f"cannot read the project: {exc}")])
    problems = check_project(project)
    setup = _setup_problems()
    return _reply(not problems, problems=problems, setup=setup)


def _manifest(folder, status, run_id, started, **extra):
    files = []
    for p in sorted(folder.iterdir()):
        if p.is_file() and p.name not in ("manifest.json", "child.json", "cancel.flag") and not p.name.startswith("."):
            files.append({"path": p.name, "sha256": _sha256(p), "bytes": p.stat().st_size})
    doc = {"format": FORMAT, "version": VERSION, "runId": run_id, "status": status, "startedAt": started,
           "finishedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "files": files, **extra}
    _atomic_write(folder / "manifest.json", _dump(doc))
    return doc


def _log_tail(folder, n=12):
    try:
        return "\n".join((folder / "run.log").read_text(encoding="utf-8", errors="replace").splitlines()[-n:])
    except OSError:
        return ""


def _kill_group(pgid):
    for sig, wait in ((signal.SIGTERM, 5.0), (signal.SIGKILL, 5.0)):
        try:
            os.killpg(pgid, sig)
        except ProcessLookupError:
            return True
        end = time.time() + wait
        while time.time() < end:
            try:
                os.killpg(pgid, 0)
            except ProcessLookupError:
                return True
            time.sleep(0.1)
    return False


def run(model, project_path, out, run_id, timeout, threads):
    try:
        project = json.loads(Path(project_path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return _reply(False, errors=[_problem("E_SCHEMA_INVALID", "", f"cannot read the project: {exc}")])
    problems = check_project(project) + _setup_problems()
    if problems:
        return _reply(False, errors=problems)
    if not Path(model).is_file():
        return _reply(False, errors=[_problem("E_SCHEMA_INVALID", "", "the model script does not exist")])
    folder = Path(out) / run_id
    try:
        folder.mkdir(parents=True, exist_ok=False)
    except OSError as exc:
        return _reply(False, errors=[_problem("E_EXISTS", "", f"cannot create the run folder: {exc}")])
    shutil.copyfile(model, folder / "model.py")
    shutil.copyfile(project_path, folder / "project.json")
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    _atomic_write(folder / "manifest.json", _dump({"format": FORMAT, "version": VERSION, "runId": run_id, "status": "running", "startedAt": started, "files": []}))

    env = os.environ.copy()
    env.update(PYTHONUNBUFFERED="1", PYTHONDONTWRITEBYTECODE="1", OMP_NUM_THREADS=str(threads))
    env["PATH"] = os.path.dirname(sys.executable) + os.pathsep + env.get("PATH", "")  # model.run() finds `openmc` there, as in Studio's server
    t0 = time.time()
    with open(folder / "run.log", "w", encoding="utf-8") as log:
        proc = subprocess.Popen([sys.executable, "model.py"], cwd=folder, env=env, stdout=log, stderr=subprocess.STDOUT,
                                start_new_session=True)
        _atomic_write(folder / "child.json", _dump({"pid": proc.pid, "pgid": proc.pid, "identity": identity(proc.pid), "runner": os.getpid()}))
        timed_out = False
        while proc.poll() is None:
            if time.time() - t0 > timeout:
                timed_out = True
                _kill_group(proc.pid)
                break
            time.sleep(0.2)
        code = proc.wait()
    seconds = round(time.time() - t0, 1)
    cancelled = (folder / "cancel.flag").exists()
    summary = {"returncode": code, "seconds": seconds, "threads": threads}
    if cancelled:
        _manifest(folder, "cancelled", run_id, started, **summary)
        return _reply(False, status="cancelled", runId=run_id)
    if timed_out:
        _manifest(folder, "failed", run_id, started, error={"code": "E_TIMEOUT", "message": f"stopped after {timeout} seconds"}, **summary)
        return _reply(False, status="failed", runId=run_id, errors=[_problem("E_TIMEOUT", "", f"stopped after {timeout} seconds")])
    if code != 0:
        msg = f"model.py exited with code {code}: " + _log_tail(folder)
        _manifest(folder, "failed", run_id, started, error={"code": "E_APP_FAILED", "message": msg}, **summary)
        return _reply(False, status="failed", runId=run_id, errors=[_problem("E_APP_FAILED", "", msg)])
    try:
        results = _extract(folder, project)
    except Exception as exc:  # noqa: BLE001
        msg = f"the run finished but its results are not usable: {exc}"
        _manifest(folder, "failed", run_id, started, error={"code": "E_OUTPUT_INCOMPLETE", "message": msg}, **summary)
        return _reply(False, status="failed", runId=run_id, errors=[_problem("E_OUTPUT_INCOMPLETE", "", msg)])
    _atomic_write(folder / "results.json", _dump(results))
    from . import provenance
    provenance.write(folder, "run", project, files=("model.py", "project.json"))
    _manifest(folder, "completed", run_id, started, **summary)
    return _reply(True, status="completed", runId=run_id)


def _extract(folder, project):
    """results.json: Studio's own result loader, checked against what the project asked for. No wall-clock values inside, so two
    runs with the same seed give the same file."""
    from . import results
    out = results.load(str(folder))
    summary = out.get("summary")
    if not summary:
        raise ValueError("no statepoint file")
    st = project["settings"]
    for key, have in (("particles", "particles"), ("batches", "batches"), ("seed", "seed")):
        if summary.get(have) != st.get(key):
            raise ValueError(f"the statepoint says {have}={summary.get(have)}, the project asked for {st.get(key)}")
    if summary.get("run_mode") != "fixed source":
        raise ValueError(f"the statepoint is a {summary.get('run_mode')} run")
    if not out.get("tallies"):
        raise ValueError("the statepoint has no tallies")
    summary.pop("runtime_s", None)
    return {"summary": summary, "tallies": out["tallies"]}


def _pgid(pid):
    try:
        return os.getpgid(pid)
    except OSError:
        return None


def cancel(run_dir):
    folder = Path(run_dir)
    try:
        child = json.loads((folder / "child.json").read_text(encoding="utf-8"))
        manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _reply(False, errors=[_problem("E_NOT_FOUND", "", "no run to cancel in this folder")])
    if manifest.get("status") != "running":
        return _reply(True, status=manifest.get("status"), cancelled=False, stopped=True)
    now = identity(child["pid"])
    if now is None:  # the child is gone already
        stopped = True
    elif now != child.get("identity") or _pgid(child["pid"]) != child["pgid"]:
        return _reply(False, errors=[_problem("E_NOT_OWNED", "", "the process at the recorded pid is not this run's child")])
    else:
        _atomic_write(folder / "cancel.flag", "1\n")
        stopped = _kill_group(child["pgid"])
        if not stopped:
            return _reply(True, status="running", cancelled=False, stopped=False)
    # If the runner process survives it finalizes the manifest; if it is gone, do it here.
    end = time.time() + 5
    while time.time() < end and identity(child["runner"]) is not None and json.loads((folder / "manifest.json").read_text()).get("status") == "running":
        time.sleep(0.1)
    if json.loads((folder / "manifest.json").read_text()).get("status") == "running":
        _manifest(folder, "cancelled", manifest.get("runId"), manifest.get("startedAt"), returncode=None)
    return _reply(True, status="cancelled", cancelled=True, stopped=True)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="openmc_studio.headless")
    sub = ap.add_subparsers(dest="verb", required=True)
    sub.add_parser("describe")
    v = sub.add_parser("validate")
    v.add_argument("project")
    r = sub.add_parser("run")
    r.add_argument("model")
    r.add_argument("project")
    r.add_argument("--out", required=True)
    r.add_argument("--run-id", required=True)
    r.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    r.add_argument("--threads", type=int, default=1)
    c = sub.add_parser("cancel")
    c.add_argument("run_dir")
    try:
        a = ap.parse_args(argv)
    except SystemExit:
        return 2
    if a.verb == "describe":
        return describe()
    if a.verb == "validate":
        return validate(a.project)
    if a.verb == "run":
        if a.timeout < 1 or a.threads < 1 or a.threads > 256:
            return _reply(False, errors=[_problem("E_SCHEMA_INVALID", "", "timeout and threads must be positive (threads at most 256)")])
        return run(a.model, a.project, a.out, a.run_id, a.timeout, a.threads)
    return cancel(a.run_dir)


if __name__ == "__main__":
    sys.exit(main())
