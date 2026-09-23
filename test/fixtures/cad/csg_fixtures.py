"""Stage-3 fixtures: real 'csg' conversions plus FreeCAD ground truth. Run in the CAD Python.

For each case this writes the STEP file, runs the real csg.convert on it, and
samples points in the padded bounds of all its solids, recording which source
solid (by key) FreeCAD says contains each point - or none. Points within the
tolerance band of any solid's boundary are left out. test_cad_csg_gate.cjs then
feeds each report through Studio's own commitCsgImport and buildScript and checks
the generated model.py against this truth in OpenMC.

A module (FreeCAD clears __main__). Usage, with this directory and <repo>/studio
on sys.path:  import csg_fixtures; csg_fixtures.main(OUT)  -> OUT/gate.json
"""
import json
import random
import shutil
from pathlib import Path

SEED = 20260923
POINTS = 3000


def main(out):
    from openmc_studio.cad.geouned_adapter import configure_runtime
    configure_runtime()
    import FreeCAD as App
    import Part
    from generate import make_fixture
    from openmc_studio.cad.csg import band_mm, convert
    from openmc_studio.cad.read import read_step

    V = App.Vector
    out = Path(out)
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    here = Path(__file__).resolve().parent
    cases, probes = {}, {}
    for name in ("drilled_block", "annular_cylinder", "drilled_block_rotated", "annular_cylinder_rotated"):
        shape, _, pts = make_fixture(name)
        shape.exportStep(str(out / f"{name}.step"))
        cases[name] = out / f"{name}.step"
        probes[name] = pts  # stage-0 hole and material points, well clear of any boundary
    Part.makeSphere(12).cut(Part.makeSphere(9)).exportStep(str(out / "hollow_sphere.step"))
    cases["hollow_sphere"] = out / "hollow_sphere.step"
    # A TRISO-scale coating shell: 0.425 mm to 0.46 mm radius.
    Part.makeSphere(0.46).cut(Part.makeSphere(0.425)).exportStep(str(out / "triso_coating.step"))
    cases["triso_coating"] = out / "triso_coating.step"
    Part.makeTorus(10, 2).exportStep(str(out / "torus.step"))
    cases["torus"] = out / "torus.step"
    shutil.copy(here / "mixed.step", out / "mixed.step")   # has an overlap: the commit must refuse it
    cases["mixed"] = out / "mixed.step"
    # A clean assembly: blocks, a rod, a drilled plate and a collar, nothing overlapping.
    App.ParamGet("User parameter:BaseApp/Preferences/Document").SetBool("DuplicateLabels", True)
    doc = App.newDocument("clean")
    for label, shape in (("Shield block", Part.makeBox(20, 10, 5)),
                         ("Fuel rod", Part.makeCylinder(2, 30, V(40, 0, 0))),
                         ("Drilled plate", Part.makeBox(10, 10, 2, V(0, 30, 0)).cut(Part.makeCylinder(1, 10, V(5, 35, -4)))),
                         ("Collar", Part.makeCylinder(6, 4, V(0, -30, 0)).cut(Part.makeCylinder(4, 4, V(0, -30, 0))))):
        o = doc.addObject("Part::Feature", label.replace(" ", ""))
        o.Shape = shape
        o.Label = label
    doc.recompute()
    import Import
    Import.export(list(doc.Objects), str(out / "clean_assembly.step"))
    App.closeDocument(doc.Name)
    cases["clean_assembly"] = out / "clean_assembly.step"

    result = {}
    for name, path in cases.items():
        report = convert(path, out / f"work-{name}")
        solids, _ = read_step(path)
        shapes = [(s.key, s.shape) for s in solids if not s.reasons]
        skins = [(key, sh, Part.Compound(sh.Faces), band_mm(sh)) for key, sh in shapes]
        box = shapes[0][1].BoundBox
        for _, sh in shapes[1:]:
            box.add(sh.BoundBox)

        def padded(b):
            pad = [0.1 * b.XLength, 0.1 * b.YLength, 0.1 * b.ZLength]
            return ([b.XMin - pad[0], b.YMin - pad[1], b.ZMin - pad[2]], [b.XMax + pad[0], b.YMax + pad[1], b.ZMax + pad[2]])

        # Half the points over the whole model, half inside each solid's own (padded)
        # bounds, so thin shells and spread-out assemblies are sampled inside too.
        regions = [padded(box)] * len(shapes) + [padded(sh.BoundBox) for _, sh in shapes]
        rng = random.Random(SEED)
        truth = []
        while len(truth) < POINTS:
            lo, hi = regions[len(truth) % len(regions)]
            p = [rng.uniform(lo[k], hi[k]) for k in range(3)]
            v = V(*p)
            if any(skin.distToShape(Part.Vertex(v))[0] < band for _, _, skin, band in skins):
                continue
            owner = [key for key, sh, _, _ in skins if sh.isInside(v, 1e-7, False)]
            truth.append({"p_cm": [c / 10 for c in p], "key": owner[0] if owner else None, "n": len(owner)})
        for point, inside in probes.get(name, []):
            truth.append({"p_cm": [c / 10 for c in point], "key": shapes[0][0] if inside else None,
                          "n": int(inside), "probe": "hole" if not inside else "material"})
        result[name] = {"report": report, "truth": truth}
    # Nothing GEOUNED could have generated as Python may exist, let alone run.
    python_files = sorted(str(q.relative_to(out)) for q in out.rglob("*.py"))
    (out / "gate.json").write_text(json.dumps({"cases": result, "python_files": python_files}))
    return {k: v["report"]["counts"] for k, v in result.items()}


def browser_reports(fixtures_dir):
    """Real 'csg' reports (with preview meshes) for the browser tests and screenshots.

    Writes clean_assembly.step and triso_layers.step (a TRISO particle as five nested
    solids at the dimensions of examples/triso-particle: kernel 0.25 mm, buffer to
    0.35, IPyC to 0.39, SiC to 0.425, OPyC to 0.46) next to this module, and their
    csg reports to expected/csg_report_*.json. Regenerate after changing csg.py."""
    from openmc_studio.cad.geouned_adapter import configure_runtime
    configure_runtime()
    import FreeCAD as App
    import Import
    import Part
    from openmc_studio.cad.csg import convert

    V = App.Vector
    fx = Path(fixtures_dir)
    App.ParamGet("User parameter:BaseApp/Preferences/Document").SetBool("DuplicateLabels", True)
    builds = {
        "clean_assembly": [("Shield block", Part.makeBox(20, 10, 5)),
                           ("Fuel rod", Part.makeCylinder(2, 30, V(40, 0, 0))),
                           ("Drilled plate", Part.makeBox(10, 10, 2, V(0, 30, 0)).cut(Part.makeCylinder(1, 10, V(5, 35, -4)))),
                           ("Collar", Part.makeCylinder(6, 4, V(0, -30, 0)).cut(Part.makeCylinder(4, 4, V(0, -30, 0))))],
        "triso_layers": [("UCO kernel", Part.makeSphere(0.25))] + [
            (label, Part.makeSphere(r_out).cut(Part.makeSphere(r_in)))
            for label, r_in, r_out in (("Porous carbon buffer", 0.25, 0.35), ("Inner pyrocarbon (IPyC)", 0.35, 0.39),
                                       ("Silicon carbide (SiC)", 0.39, 0.425), ("Outer pyrocarbon (OPyC)", 0.425, 0.46))],
    }
    work = fx / "_csg_tmp"
    shutil.rmtree(work, ignore_errors=True)
    for name, items in builds.items():
        doc = App.newDocument(name)
        objs = []
        for label, shape in items:
            o = doc.addObject("Part::Feature", "".join(ch for ch in label if ch.isalnum()))
            o.Shape = shape
            o.Label = label
            objs.append(o)
        doc.recompute()
        Import.export(objs, str(fx / f"{name}.step"))
        App.closeDocument(doc.Name)
        report = convert(fx / f"{name}.step", work / name)
        (fx / "expected" / f"csg_report_{name}.json").write_text(json.dumps(report) + "\n", newline="\n")
    shutil.rmtree(work, ignore_errors=True)
