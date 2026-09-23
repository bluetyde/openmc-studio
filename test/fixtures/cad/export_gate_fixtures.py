"""Write STEP fixtures for test/test_cad_jobs_engine.py. Run inside the CAD Python.

A module, not a -c script: importing FreeCAD clears names from __main__, so the
code that runs after that import must keep its globals in a module of its own.

Usage (CAD Python): python -c "import export_gate_fixtures as g; g.main(OUT)"
with this directory and <repo>/studio on sys.path.
"""
import json
from pathlib import Path


def main(out):
    from openmc_studio.cad.geouned_adapter import configure_runtime
    configure_runtime()
    import FreeCAD  # noqa: F401 - initializes the kernel before Part
    import Part
    from generate import make_fixture

    out = Path(out)
    meta = {}
    for name in ("drilled_block_rotated", "annular_cylinder"):
        shape, volume, probes = make_fixture(name)
        shape.exportStep(str(out / f"{name}.step"))
        meta[name] = {"volume_mm3": volume, "probes": [[list(p), bool(e)] for p, e in probes]}
    Part.makeTorus(10, 2).exportStep(str(out / "torus.step"))
    Part.makeCompound([Part.makeBox(1, 1, 1), Part.makeSphere(1)]).exportStep(str(out / "two_solids.step"))
    (out / "meta.json").write_text(json.dumps(meta))
