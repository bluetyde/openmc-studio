"""Disposable job entry point, imported so FreeCAD cannot erase our globals.

Runs in the job's private working directory (the supervisor sets cwd). Reads the
server-written request.json, does one job, and always leaves a result.json that
names the job: ok true with a report, or ok false with the reason. The supervisor
trusts nothing else, and anything written after cancellation is discarded.
"""
import json
from pathlib import Path


def write_atomic(path, value):
    path = Path(path)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value), encoding="utf-8")
    temporary.replace(path)


def probe(progress):
    """A real end-to-end conversion of a small drilled block built here, so a
    healthy result means FreeCAD built a solid, wrote STEP, GEOUNED converted it
    and the emitted region keeps its hole. Importable modules alone prove nothing."""
    from .geouned_adapter import configure_runtime, convert_step
    configure_runtime()
    import FreeCAD as App
    import Part
    import openmc
    import xml.etree.ElementTree as ET

    progress("building probe solid")
    block = Part.makeBox(10, 10, 10)                              # mm
    hole = Part.makeCylinder(2, 14, App.Vector(5, 5, -2))         # through the block along z
    solid = block.cut(hole)
    solid.exportStep("source.step")
    report = convert_step("source.step", "conversion", progress=progress)
    progress("checking probe regions")
    tree = ET.parse(report["xml"])
    surfaces = {int(e.attrib["id"]): openmc.Surface.from_xml_element(e) for e in tree.findall("surface")}
    cells = tree.findall("cell")
    if len(cells) != 1:
        raise ValueError(f"Probe expected one cell, got {len(cells)}")
    region = openmc.Region.from_expression(cells[0].attrib["region"], surfaces)
    # (point in mm, inside?) - material, the hole, and outside the block.
    for point, expected in (((1, 1, 5), True), ((5, 5, 5), False), ((20, 20, 20), False)):
        if (tuple(c / 10 for c in point) in region) != expected:
            raise ValueError(f"Probe region is wrong at {point} mm")
    report["probe"] = {"solid": "10 mm cube with a 2 mm radius through-hole", "points_checked": 3}
    return report


def csg_xml(progress):
    from .geouned_adapter import convert_step
    return convert_step("source.step", "conversion", progress=progress)


def inspect(progress):
    from .geouned_adapter import configure_runtime
    configure_runtime()
    import FreeCAD  # noqa: F401 - initialize the kernel before Part and Import
    from .report import inspect as run_inspect
    return run_inspect("source.step", progress=progress)


def native(progress):
    from .geouned_adapter import configure_runtime
    configure_runtime()
    import FreeCAD  # noqa: F401
    from .report import native as run_native
    return run_native("source.step", progress=progress)


MODES = {"probe": probe, "csg-xml": csg_xml, "inspect": inspect, "native": native}


def run(job_id):
    def progress(stage):
        write_atomic("progress.json", {"id": job_id, "stage": stage})
    try:
        request = json.loads(Path("request.json").read_text(encoding="utf-8"))
        if request.get("id") != job_id:
            raise ValueError("request.json names a different job")
        mode = request.get("mode")
        if mode not in MODES:
            raise ValueError(f"Unknown job mode {mode!r}")
        progress("loading")
        report = MODES[mode](progress)
        report.update(id=job_id, ok=True, mode=mode)
        write_atomic("result.json", report)
        progress("converted")
    except BaseException as exc:  # includes KeyboardInterrupt/SystemExit from engines
        write_atomic("result.json", {"id": job_id, "ok": False,
                                     "error": f"{type(exc).__name__}: {exc}"[:500]})
        raise SystemExit(2)
