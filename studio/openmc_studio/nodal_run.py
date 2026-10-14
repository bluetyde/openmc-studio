"""The server side of the Core (nodal) tab: is the nodal package there, what a request may ask, and the command that runs it.

The nodal solve needs openndm, which is not in the Python that runs Studio's server (that one has OpenMC). `OPENNDM_PYTHON` names a Python that has both openmc and openndm
0.3.x; without it the server's own Python is tried. The driver (`nodal_driver`) runs in that Python as a child process of the run, in its own run folder like any other run,
and writes `nodal.json` there. Nothing here imports openndm.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

PACKAGE_PARENT = str(Path(__file__).resolve().parent.parent)        # the folder holding openmc_studio, for PYTHONPATH of the child
KERNELS = ("sanm", "nem", "fdm")
FACES = ("x_min", "x_max", "y_min", "y_max")
LIMITS = {"particles": (100, 200_000), "batches": (10, 500)}
_cache = {"at": 0.0, "key": None, "value": None}


def nodal_python(environ=None) -> str:
    env = os.environ if environ is None else environ
    return env.get("OPENNDM_PYTHON") or sys.executable


def availability(environ=None, max_age=60.0) -> dict:
    """{"available": bool, "python": path, "openndm": version | None, "openmc": version | None, "reason": text | None}. Asks the nodal Python to import both packages (a second or two,
    cached for a minute)."""
    py = nodal_python(environ)
    now = time.time()
    if _cache["key"] == py and now - _cache["at"] < max_age:
        return _cache["value"]
    code = ("import json,sys\nout={}\nfor n in ('openndm','openmc'):\n  try:\n    m=__import__(n); out[n]=getattr(m,'__version__','?')\n  except Exception as e:\n    out[n]=None; out[n+'_error']=str(e)[:200]\nprint(json.dumps(out))")
    try:
        r = subprocess.run([py, "-c", code], capture_output=True, text=True, timeout=60)
        import json
        got = json.loads(r.stdout.strip().splitlines()[-1])
    except (OSError, ValueError, IndexError, subprocess.TimeoutExpired) as e:
        got = {"openndm": None, "openmc": None, "openndm_error": f"could not start {py}: {e}"}
    reason = None
    if got.get("openndm") is None:
        reason = "The nodal package (openndm 0.3.x) is not installed in " + py + ". Set OPENNDM_PYTHON to a Python that has openmc and openndm."
    elif got.get("openmc") is None:
        reason = "OpenMC cannot be imported by " + py + "."
    else:
        reason = version_problem(got["openndm"])
    val = {"available": reason is None, "python": py, "openndm": got.get("openndm"), "openmc": got.get("openmc"), "reason": reason}
    _cache.update(at=now, key=py, value=val)
    return val


def version_problem(version) -> str | None:
    """None for openndm 0.3.x, else why not: the reading rules were checked on that line only."""
    ver = tuple(int("".join(c for c in p if c.isdigit()) or 0) for p in str(version).split(".")[:2])
    return None if ver == (0, 3) else f"openndm {version} is installed; the nodal rules were checked on 0.3.x only."


class NodalRequestError(ValueError):
    pass


def clean_settings(s) -> dict:
    """The request's settings, checked and with defaults; raises NodalRequestError naming the field."""
    if s is None:
        s = {}
    if not isinstance(s, dict):
        raise NodalRequestError("settings must be an object")
    extra = set(s) - {"particles", "batches", "inactive", "seed", "kernel", "reflective", "vacuum", "lattice", "threads"}
    if extra:
        raise NodalRequestError(f"unknown setting(s): {sorted(extra)}")

    def whole(name, default, lo, hi):
        v = s.get(name, default)
        if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
            raise NodalRequestError(f"{name} must be a whole number from {lo} to {hi}")
        return v
    particles = whole("particles", 6000, *LIMITS["particles"])
    batches = whole("batches", 60, *LIMITS["batches"])
    inactive = whole("inactive", 15, 0, batches - 1)
    seed = whole("seed", 1, 1, 2**31 - 1)
    threads = whole("threads", min(4, os.cpu_count() or 1), 1, 256)
    kernel = s.get("kernel", "sanm")
    if kernel not in KERNELS:
        raise NodalRequestError(f"kernel must be one of {KERNELS}")
    forced = {}
    for key in ("reflective", "vacuum"):
        lst = s.get(key, [])
        if not isinstance(lst, list) or any(f not in FACES for f in lst) or len(set(lst)) != len(lst):
            raise NodalRequestError(f"{key} must be a list of distinct faces from {FACES}")
        forced[key] = lst
    if set(forced["reflective"]) & set(forced["vacuum"]):
        raise NodalRequestError("a face cannot be both reflective and vacuum")
    refl = forced["reflective"]
    lattice = s.get("lattice")
    if lattice is not None and (not isinstance(lattice, str) or not 1 <= len(lattice) <= 120):
        raise NodalRequestError("lattice must be a name of 1 to 120 characters")
    return {"particles": particles, "batches": batches, "inactive": inactive, "seed": seed, "threads": threads, "kernel": kernel, "reflective": list(refl), "vacuum": list(forced["vacuum"]), "lattice": lattice}


def command(settings: dict, environ=None) -> list:
    """The argv of the child (run in the run folder, where model.py is)."""
    argv = [nodal_python(environ), "-W", "ignore", "-m", "openmc_studio.nodal_driver", "model.py", "--workdir", "pieces", "--out", "nodal.json",
            "--particles", str(settings["particles"]), "--batches", str(settings["batches"]), "--inactive", str(settings["inactive"]), "--seed", str(settings["seed"]),
            "--threads", str(settings["threads"]), "--kernel", settings["kernel"]]
    if settings.get("lattice"):
        argv += ["--lattice", settings["lattice"]]
    if settings["reflective"]:
        argv += ["--reflective", *settings["reflective"]]
    if settings.get("vacuum"):
        argv += ["--vacuum", *settings["vacuum"]]
    return argv


def child_env(environ=None) -> dict:
    """The child's environment: the nodal Python's folder first on PATH (its `openmc` executable), then the server Python's, and the package on PYTHONPATH."""
    env = dict(os.environ if environ is None else environ)
    py = nodal_python(environ)
    env["PATH"] = os.pathsep.join(p for p in (os.path.dirname(py), os.path.dirname(sys.executable), env.get("PATH", "")) if p)
    env["PYTHONPATH"] = PACKAGE_PARENT + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env["PYTHONUNBUFFERED"] = "1"
    env["OMP_NUM_THREADS"] = env.get("OMP_NUM_THREADS") or "4"
    return env
