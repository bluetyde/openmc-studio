"""Long-running CAD translation worker for OpenMC Studio.

Exports supported primitive solids through FreeCAD. CAD import is unavailable
until a geometry-preserving adapter exists; never substitute surface bounds.

Communicates with server.py over stdin/stdout using JSON lines:
  @@PROGRESS {"id": 1, "step": 1, "total": 4, "stage": "...", "text": "...", "elapsed": 0.5}
  @@RESULT   {"id": 1, "ok": true, ...}
"""
import json
import math
import os
import sys
import time
from pathlib import Path

_real_stdout = sys.stdout


def emit(obj):
    _real_stdout.write("@@RESULT " + json.dumps(obj) + "\n")
    _real_stdout.flush()


def emit_progress(job_id, step, total, stage, text, t0=None):
    elapsed = round(time.time() - t0, 1) if t0 else 0
    _real_stdout.write("@@PROGRESS " + json.dumps({
        "id": job_id, "step": step, "total": total, "stage": stage, "text": text, "elapsed": elapsed
    }) + "\n")
    _real_stdout.flush()


# CAD conversion must fail closed: surfaces and bounding boxes are not solids.
IMPORT_ERROR = (
    "CAD import is unavailable: a geometry-preserving STEP/IGES-to-Studio adapter "
    "is not implemented. No geometry was imported. Use an OpenMC Studio project instead."
)
EXPORT_ERROR = (
    "STEP export requires FreeCAD in the CAD worker Python environment. "
    "Set OPENMC_CAD_PYTHON to that Python interpreter, or export STL."
)
SUPPORTED_SHAPES = {"box", "sphere", "cylinder", "cone"}


def probe_environment():
    freecad_version = None
    try:
        import FreeCAD
        import Part
        freecad_version = ".".join(FreeCAD.Version()[:3])
    except (ImportError, OSError):
        pass
    return {
        "ready": True, "engine": "freecad" if freecad_version else "unavailable",
        "freecad": freecad_version, "geouned": None,
        "can_import": False, "can_export": bool(freecad_version),
        "supported_inputs": [], "supported_outputs": [".step", ".stp"] if freecad_version else [],
        "export_shapes": sorted(SUPPORTED_SHAPES),
        "instructions": EXPORT_ERROR, "import_error": IMPORT_ERROR,
    }


def export_step_analytical(*args, **kwargs):
    # Kept as a rejecting compatibility entry point for old callers.
    raise ValueError(EXPORT_ERROR)


def parse_step_analytical(*args, **kwargs):
    raise ValueError(IMPORT_ERROR)


def run_cad_to_csg(job_id, file_path, options, t0):
    return {"id": job_id, "ok": False, "error": IMPORT_ERROR}


def part_dimensions(p):
    shape = p.get("shape")
    if shape not in SUPPORTED_SHAPES:
        raise ValueError(f"{p.get('name', 'Part')}: STEP export does not support {shape}. Use STL instead.")
    keys = {"box": ["sx", "sy", "sz"], "sphere": ["r"],
            "cylinder": ["r", "h"], "cone": ["r", "r2", "h"]}[shape]
    values = {}
    for key in keys:
        value = float(p[key])
        if not math.isfinite(value) or value < 0 or (value == 0 and not (shape == "cone" and key in ("r", "r2"))):
            raise ValueError(f"Invalid {key} for {p.get('name', 'Part')}")
        values[key] = value * 10  # Studio cm -> FreeCAD mm, independent of STEP display units.
    if shape == "cone" and values["r"] == values["r2"] == 0:
        raise ValueError("A cone needs a positive radius.")
    for key in ("x", "y", "z", "rx", "ry", "rz"):
        if not math.isfinite(float(p.get(key, 0))):
            raise ValueError(f"Invalid {key} for {p.get('name', 'Part')}")
    if shape == "cylinder" and p.get("axis", "z") not in ("x", "y", "z"):
        raise ValueError("Invalid cylinder axis")
    return values


def make_cad_solid(p, FreeCAD, Part):
    d = part_dimensions(p)
    vec = FreeCAD.Vector
    shape = p["shape"]
    if shape == "sphere":
        solid = Part.makeSphere(d["r"])
    elif shape == "box":
        solid = Part.makeBox(d["sx"], d["sy"], d["sz"])
        solid.translate(vec(-d["sx"] / 2, -d["sy"] / 2, -d["sz"] / 2))
    else:
        if shape == "cylinder" or d["r"] == d.get("r2"):
            solid = Part.makeCylinder(d["r"], d["h"])
        else:
            solid = Part.makeCone(d["r"], d["r2"], d["h"])
        solid.translate(vec(0, 0, -d["h"] / 2))
    # Same local frame as Studio: Rz * Ry * Rx * cylinder-axis base.
    origin = vec(0, 0, 0)
    if shape == "cylinder":
        if p.get("axis") == "x":
            solid.rotate(origin, vec(0, 1, 0), 90)
        elif p.get("axis") == "y":
            solid.rotate(origin, vec(1, 0, 0), -90)
    for key, axis in (("rx", (1, 0, 0)), ("ry", (0, 1, 0)), ("rz", (0, 0, 1))):
        angle = float(p.get(key, 0))
        if angle:
            solid.rotate(origin, vec(*axis), angle)
    solid.translate(vec(*(float(p.get(k, 0)) * 10 for k in ("x", "y", "z"))))
    if solid.isNull() or not solid.isValid():
        raise ValueError(f"FreeCAD could not construct {p.get('name', 'Part')} as a valid solid.")
    return solid


def run_csg_to_cad(job_id, project, out_path, options, t0):
    if (project.get("csg") or {}).get("components"):
        return {"id": job_id, "ok": False, "error": "STEP export of imported CAD components is not supported yet. Nothing was exported."}
    try:
        parts = project.get("parts", [])
        if not parts:
            raise ValueError("No parts to export.")
        if options.get("units", "mm") != "mm":
            raise ValueError("FreeCAD STEP export uses millimeters. Studio dimensions are converted from centimeters.")
        for p in parts:
            part_dimensions(p)  # Validate the entire request before writing anything.
        if not probe_environment()["can_export"]:
            raise ValueError(EXPORT_ERROR)
        import FreeCAD
        import Part
        emit_progress(job_id, 1, 2, "export", "Building STEP solids in millimeters...", t0)
        shapes = [make_cad_solid(p, FreeCAD, Part) for p in parts]
        compound = Part.makeCompound(shapes)
        compound.exportStep(str(out_path))
        # Refuse output with different units instead of mislabeling a download.
        import re
        text = Path(out_path).read_text(encoding="utf-8", errors="replace")
        if not re.search(r"SI_UNIT\s*\(\s*\.MILLI\.\s*,\s*\.METRE\.\s*\)", text):
            raise ValueError("The STEP writer did not declare millimeters; no download was produced.")
        reread = Part.read(str(out_path))
        expected, actual = compound.BoundBox, reread.BoundBox
        for key in ("XMin", "XMax", "YMin", "YMax", "ZMin", "ZMax"):
            if not math.isclose(getattr(expected, key), getattr(actual, key), rel_tol=1e-7, abs_tol=1e-6):
                raise ValueError("STEP roundtrip changed the geometry bounds; no download was produced.")
        if not math.isclose(compound.Volume, reread.Volume, rel_tol=1e-7, abs_tol=1e-9):
            raise ValueError("STEP roundtrip changed the solid volume; no download was produced.")
        size = Path(out_path).stat().st_size
        if not size:
            raise ValueError("FreeCAD produced an empty STEP file.")
        emit_progress(job_id, 2, 2, "done", "STEP primitive solids exported.", t0)
        return {"id": job_id, "ok": True, "engine": "freecad", "out_path": str(out_path),
                "size": size, "parts": len(parts), "units": "mm"}
    except Exception as err:
        return {"id": job_id, "ok": False, "error": str(err)}


# ── Main Worker Loop ──
def main():
    emit({"ready": True, "info": "OpenMC Studio CAD Worker Active", "env": probe_environment()})

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except Exception as e:
            emit({"ok": False, "error": f"Invalid JSON request: {e}"})
            continue

        cmd = req.get("cmd")
        job_id = req.get("id", 0)
        t0 = time.time()

        if cmd == "status":
            emit({"id": job_id, "ok": True, "env": probe_environment()})
        elif cmd == "cad_to_csg":
            file_path = req.get("file_path")
            options = req.get("options", {})
            if not file_path or not os.path.isfile(file_path):
                emit({"id": job_id, "ok": False, "error": f"File not found: {file_path}"})
            else:
                try:
                    res = run_cad_to_csg(job_id, file_path, options, t0)
                    emit(res)
                except Exception as err:
                    emit({"id": job_id, "ok": False, "error": str(err)})
        elif cmd == "csg_to_cad":
            project = req.get("project", {})
            out_path = req.get("out_path")
            options = req.get("options", {})
            if not out_path:
                emit({"id": job_id, "ok": False, "error": "Missing out_path parameter"})
            else:
                try:
                    res = run_csg_to_cad(job_id, project, out_path, options, t0)
                    emit(res)
                except Exception as err:
                    emit({"id": job_id, "ok": False, "error": str(err)})
        else:
            emit({"id": job_id, "ok": False, "error": f"Unknown command: {cmd}"})


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--job":
        from .cad.job_worker import run
        run(sys.argv[2])
    else:
        main()
