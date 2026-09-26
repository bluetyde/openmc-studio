"""provenance.json: what produced a run or an export, so its numbers can be reproduced and compared.

Written into every run folder (when it starts, completed when it ends) and every Export > MCNP input deck
folder. It records the Studio and companion-exporter commits, the OpenMC, MontePy and Python versions, which
nuclear data was used (the cross_sections.xml path and its SHA-256), the model's run settings and seed, the
normalization conventions Studio's results use, and hashes of model.py, the project and any deck. Reading it
never changes a result; it is a record.
"""
import functools
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

from . import __version__

NORMALIZATION = {
    "tallies": "per source particle (source strengths are scaled to sum to 1 in model.py, as MCNP tallies are)",
    "dose": "pSv per source particle, or Sv/h when Settings > Source emission rate is set (x rate x 3600 x 1e-12)",
    "cell_dose_volume": "OpenMC stochastic volume calculation, 200000 samples in each dosed part's box (dose.json)",
    "mesh_values": "OpenMC mesh tallies are volume-integrated; MCNP FMESH divides by the voxel volume",
    "source_spectrum": "tabulated spectra are bin probabilities (MCNP SP D); model.py divides by bin width",
}


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _git(folder):
    """{commit, dirty} of the git checkout holding `folder`, or None when it isn't one (an installed package)."""
    try:
        run = lambda *a: subprocess.run(["git", "-C", str(folder), *a], capture_output=True, text=True, timeout=10)
        c = run("rev-parse", "HEAD")
        if c.returncode:
            return None
        return {"commit": c.stdout.strip(), "dirty": bool(run("status", "--porcelain").stdout.strip())}
    except (OSError, subprocess.SubprocessError):
        return None


def _version(dist):
    try:
        from importlib.metadata import version
        return version(dist)
    except Exception:
        return None


@functools.lru_cache(maxsize=None)
def _openmc_exe():
    """`openmc --version` of the executable next to this Python (as model.run() finds it), first line only."""
    exe = Path(sys.executable).with_name("openmc")
    try:
        r = subprocess.run([str(exe) if exe.exists() else "openmc", "--version"], capture_output=True, text=True, timeout=30)
        return (r.stdout or r.stderr).strip().splitlines()[0] if r.returncode == 0 else None
    except (OSError, subprocess.SubprocessError, IndexError):
        return None


@functools.lru_cache(maxsize=None)
def _nuclear_data(path):
    if not path:
        return {"cross_sections": None, "note": "OPENMC_CROSS_SECTIONS is not set"}
    p = Path(path)
    if not p.is_file():
        return {"cross_sections": path, "note": "not found"}
    lib = None
    try:
        import xml.etree.ElementTree as ET
        root = ET.parse(p).getroot()
        lib = {"libraries": len(root.findall("library"))}
    except Exception:
        pass
    return {"cross_sections": str(p), "sha256": sha256(p), "size": p.stat().st_size, **(lib or {})}


def environment(exporter=None):
    """The software and data this machine would use now."""
    pkg = Path(__file__).resolve().parent
    out = {
        "studio": {"version": __version__, "git": _git(pkg)},
        "python": sys.version.split()[0], "platform": f"{platform.system()} {platform.release()} {platform.machine()}",
        "openmc": {"python": _version("openmc"), "executable": _openmc_exe()},
        "nuclear_data": _nuclear_data(os.environ.get("OPENMC_CROSS_SECTIONS")),
    }
    if exporter:
        out["exporter"] = {"path": str(exporter), "git": _git(exporter)}
        out["montepy"] = _version("montepy")
    return out


def _settings(project):
    st = (project or {}).get("settings") or {}
    keys = ("runMode", "particles", "batches", "inactive", "seed", "photon", "photonCutoff", "sourceRate",
            "fissionNeutrons", "temperatureDefault")
    return {k: st.get(k) for k in keys if k in st}


def write(folder, kind, project=None, files=(), extra=None, exporter=None):
    """Write <folder>/provenance.json. `files`: names in the folder to hash (those that exist). A record that
    can't be made never stops the run or export: the file then says why."""
    try:
        return _write(Path(folder), kind, project, files, extra, exporter)
    except Exception as exc:  # noqa: BLE001
        try:
            (Path(folder) / "provenance.json").write_text(json.dumps({"kind": kind, "error": repr(exc)}) + "\n")
        except OSError:
            pass
        return None


def _write(folder, kind, project, files, extra, exporter):
    rec = {
        "kind": kind, "written": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "environment": environment(exporter),
        "settings": _settings(project), "normalization": NORMALIZATION,
        "files": {f: sha256(folder / f) for f in files if (folder / f).is_file()},
    }
    if project is not None:
        rec["project_sha256"] = hashlib.sha256(json.dumps(project, sort_keys=True).encode("utf-8")).hexdigest()
    rec.update(extra or {})
    (folder / "provenance.json").write_text(json.dumps(rec, indent=1) + "\n", encoding="utf-8")
    return rec


def update(folder, **fields):
    """Add fields to an existing provenance.json (e.g. a run's outcome); no-op if it isn't there."""
    p = Path(folder) / "provenance.json"
    try:
        rec = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    rec.update(fields)
    p.write_text(json.dumps(rec, indent=1) + "\n", encoding="utf-8")
    return rec
