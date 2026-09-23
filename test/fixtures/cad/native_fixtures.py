"""Stage-2 fixture corpus, written with FreeCAD. Run inside the CAD Python.

Each case builds solids from known construction parameters and records what a
correct native import must produce, derived from those parameters with this
module's own arithmetic (handwritten_step.rot), never from the recognizer. The
companion handwritten_step.py covers files written without FreeCAD at all.

A module, not a -c script: importing FreeCAD clears names from __main__.
Usage (CAD Python, with this directory and <repo>/studio on sys.path):
    import native_fixtures; native_fixtures.main("/some/output/dir")
"""
import json
import math
from pathlib import Path

from handwritten_step import rot


def _apply(R, v):
    return [sum(R[i][k] * v[k] for k in range(3)) for i in range(3)]


def _cm(v):
    return [x / 10 for x in v]


def _runtime():
    from openmc_studio.cad.geouned_adapter import configure_runtime
    configure_runtime()


def main(out):
    _runtime()
    import FreeCAD as App
    import Import
    import Part

    V = App.Vector
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    App.ParamGet("User parameter:BaseApp/Preferences/Document").SetBool("DuplicateLabels", True)
    cases = {}

    def place(shape, angles=(0, 0, 0), move=(0, 0, 0)):
        s = shape.copy()
        for axis, ang in zip(((1, 0, 0), (0, 1, 0), (0, 0, 1)), angles):
            if ang:
                s.rotate(V(0, 0, 0), V(*axis), ang)  # extrinsic x, then y, then z: Rz*Ry*Rx
        s.translate(V(*move))
        return s

    def save(name, shape, solids, unit="MM"):
        Part.setStaticValue("write.step.unit", unit)
        try:
            shape.exportStep(str(out / f"{name}.step"))
        finally:
            Part.setStaticValue("write.step.unit", "MM")
        cases[name] = {"file": f"{name}.step", "unit": unit, "solids": solids}

    # ── expected-value helpers (millimetre construction -> Studio centimetres) ──
    def box(size, angles=(0, 0, 0), move=(0, 0, 0)):
        R = rot(*angles)
        c = [a + b for a, b in zip(_apply(R, [s / 2 for s in size]), move)]
        return {"status": "accepted", "shape": "box", "center_cm": _cm(c),
                "axes": [{"dir": [R[i][k] for i in range(3)], "size_cm": size[k] / 10} for k in range(3)]}

    def sphere(r, move=(0, 0, 0)):
        return {"status": "accepted", "shape": "sphere", "center_cm": _cm(move), "r_cm": r / 10}

    def cylinder(r, h, angles=(0, 0, 0), move=(0, 0, 0)):
        R = rot(*angles)
        c = [a + b for a, b in zip(_apply(R, [0, 0, h / 2]), move)]
        return {"status": "accepted", "shape": "cylinder", "center_cm": _cm(c), "axis": _apply(R, [0, 0, 1]),
                "r_cm": r / 10, "h_cm": h / 10}

    def cone(r1, r2, h, angles=(0, 0, 0), move=(0, 0, 0)):
        R = rot(*angles)
        up = _apply(R, [0, 0, 1])
        c = [a + b for a, b in zip(_apply(R, [0, 0, h / 2]), move)]
        if r1 >= r2:
            return {"status": "accepted", "shape": "cone", "center_cm": _cm(c), "axis": up,
                    "r_cm": r1 / 10, "r2_cm": r2 / 10, "h_cm": h / 10}
        return {"status": "accepted", "shape": "cone", "center_cm": _cm(c), "axis": [-x for x in up],
                "r_cm": r2 / 10, "r2_cm": r1 / 10, "h_cm": h / 10}

    def rejected(*phrases):
        return {"status": "rejected", "reason_contains": list(phrases)}

    # ── units: one box, four declared units ──
    for unit in ("MM", "CM", "M", "INCH"):
        save(f"units_{unit.lower()}", place(Part.makeBox(10, 20, 30), (15, 25, 35), (100, -50, 7)),
             {"": box((10, 20, 30), (15, 25, 35), (100, -50, 7))}, unit)

    # ── primitives, axis-aligned, rotated, translated and at extreme scales ──
    save("box_axis", place(Part.makeBox(10, 20, 30), move=(5, 5, 5)), {"": box((10, 20, 30), move=(5, 5, 5))})
    save("box_rot", place(Part.makeBox(10, 20, 30), (30, -60, 145), (-40, 12, 3)),
         {"": box((10, 20, 30), (30, -60, 145), (-40, 12, 3))})
    save("box_gimbal", place(Part.makeBox(10, 20, 30), (17, 90, 0), (1, 2, 3)),
         {"": box((10, 20, 30), (17, 90, 0), (1, 2, 3))})
    split = Part.makeBox(10, 20, 30).fuse(Part.makeBox(10, 20, 30, V(10, 0, 0)))  # coplanar faces kept split
    save("box_split_faces", split, {"": box((20, 20, 30))})
    save("sphere", place(Part.makeSphere(12.5), move=(3, 4, 5)), {"": sphere(12.5, (3, 4, 5))})
    save("sphere_micro", place(Part.makeSphere(0.25), move=(0.1, 0.2, 0.3)), {"": sphere(0.25, (0.1, 0.2, 0.3))})
    save("cyl_axis_x", place(Part.makeCylinder(4, 50), (0, 90, 0)), {"": cylinder(4, 50, (0, 90, 0))})
    save("cyl_axis_y", place(Part.makeCylinder(4, 50), (-90, 0, 0), (0, 0, 7)), {"": cylinder(4, 50, (-90, 0, 0), (0, 0, 7))})
    save("cyl_rot", place(Part.makeCylinder(4, 50), (37, 0, 12), (0, 0, 100)), {"": cylinder(4, 50, (37, 0, 12), (0, 0, 100))})
    save("cyl_thin_cap", Part.makeCylinder(50, 0.01), {"": cylinder(50, 0.01)})
    far = (1e5, -2e5, 3e5)
    save("cyl_far", place(Part.makeCylinder(4, 50), (20, 30, 40), far), {"": cylinder(4, 50, (20, 30, 40), far)})
    save("cone_frustum", place(Part.makeCone(10, 4, 25), (0, 60, 0), (5, 5, 5)), {"": cone(10, 4, 25, (0, 60, 0), (5, 5, 5))})
    save("cone_inverted", place(Part.makeCone(4, 10, 25), (20, 30, 40)), {"": cone(4, 10, 25, (20, 30, 40))})
    save("cone_apex", place(Part.makeCone(0, 6, 15), (180, 0, 0)), {"": cone(0, 6, 15, (180, 0, 0))})

    # ── near misses: each must be rejected, with a reason ──
    b = Part.makeBox(10, 10, 10)
    save("near_chamfer", b.makeChamfer(0.01, [b.Edges[0]]), {"": rejected("distinct planes")})
    b = Part.makeBox(10, 10, 10)
    save("near_fillet", b.makeFillet(0.5, [b.Edges[0]]), {"": rejected("not a supported primitive")})
    save("near_drilled_box", Part.makeBox(10, 10, 10).cut(Part.makeCylinder(1, 20, V(5, 5, -5))),
         {"": rejected("not a supported primitive")})
    save("near_annular", Part.makeCylinder(10, 20).cut(Part.makeCylinder(8, 20)), {"": rejected("different cylinders")})
    save("near_triso_coating", Part.makeSphere(0.46).cut(Part.makeSphere(0.425)), {"": rejected("internal void")})
    save("near_cut_sphere", Part.makeSphere(10).cut(Part.makeBox(30, 30, 30, V(-15, -15, 5))),
         {"": rejected("not a supported primitive")})
    save("near_stepped_shaft", Part.makeCylinder(5, 10).fuse(Part.makeCylinder(3, 10, V(0, 0, 10))),
         {"": rejected("different cylinders")})
    # A parallelepiped: a box whose x faces lean 0.5 degrees.
    lean = 10 * math.tan(math.radians(0.5))
    p = [V(0, 0, 0), V(10, 0, 0), V(10 + lean, 0, 10), V(lean, 0, 10)]
    skew = Part.Face(Part.makePolygon(p + [p[0]])).extrude(V(0, 10, 0))
    save("near_skewed_box", skew, {"": rejected("perpendicular")})
    tilted_cap = Part.makeCylinder(5, 20).cut(place(Part.makeBox(40, 40, 40, V(-20, -20, 0)), (1, 0, 0), (0, 0, 18)))
    save("near_sheared_cylinder", tilted_cap, {"": rejected("not perpendicular")})
    ell = Part.Face(Part.Wire(Part.Ellipse(V(0, 0, 0), 6, 4).toShape())).extrude(V(0, 0, 10))
    save("near_elliptic_cylinder", ell, {"": rejected("surface")})
    save("near_torus", Part.makeTorus(10, 2), {"": rejected("Toroid")})
    m = App.Matrix()
    m.scale(1, 1, 1.0000001)
    save("near_bspline_box", Part.makeBox(10, 10, 10).transformGeometry(m), {"": rejected("BSplineSurface")})

    # ── an assembly: nesting, duplicate labels, repeated instances, a multi-solid object ──
    doc = App.newDocument("fixture_assembly")
    rod = doc.addObject("Part::Feature", "RodShape")
    rod.Shape = Part.makeCylinder(2, 30)
    rod.Label = "Fuel rod"
    pair = doc.addObject("App::Part", "Pair")
    pair.Label = "Rod pair"
    pair.Placement = App.Placement(V(0, 100, 0), App.Rotation(V(0, 0, 1), 90))
    links = []
    for i, x in enumerate((10, 20)):
        link = doc.addObject("App::Link", f"L{i}")
        link.LinkedObject = rod
        link.Label = "Fuel rod"
        link.Placement = App.Placement(V(x, 0, 0), App.Rotation())
        links.append(link)
    pair.addObjects(links)
    shield = doc.addObject("Part::Feature", "Shield")
    shield.Shape = Part.makeBox(20, 10, 5)
    shield.Label = "Shield block"
    shield.Placement = App.Placement(V(-50, 0, 0), App.Rotation())
    beads = doc.addObject("Part::Feature", "Beads")
    beads.Shape = Part.makeCompound([Part.makeSphere(1, V(0, -30, 0)), Part.makeSphere(1, V(5, -30, 0))])
    beads.Label = "Beads"
    core = doc.addObject("App::Part", "Core")
    core.Label = "Core"
    core.addObjects([pair, shield, beads])
    doc.recompute()
    Import.export([core], str(out / "assembly.step"))
    App.closeDocument(doc.Name)
    Rz90 = rot(0, 0, 90)
    rod_center = [a + b for a, b in zip(_apply(Rz90, [10, 0, 15]), (0, 100, 0))]
    rod2_center = [a + b for a, b in zip(_apply(Rz90, [20, 0, 15]), (0, 100, 0))]
    cases["assembly"] = {"file": "assembly.step", "unit": "MM", "solids": {
        # Two instances of one linked part, both labelled "Fuel rod": numbered in file order.
        "Core / Rod pair / Fuel rod [1]":
            {"status": "accepted", "shape": "cylinder", "center_cm": _cm(rod_center), "axis": [0, 0, 1], "r_cm": 0.2, "h_cm": 3.0},
        "Core / Rod pair / Fuel rod [2]":
            {"status": "accepted", "shape": "cylinder", "center_cm": _cm(rod2_center), "axis": [0, 0, 1], "r_cm": 0.2, "h_cm": 3.0},
        "Core / Shield block": box((20, 10, 5), move=(-50, 0, 0)),
        # FreeCAD exports a two-solid compound as a sub-assembly of two "Beads".
        "Core / Beads / Beads [1]": sphere(1, (0, -30, 0)),
        "Core / Beads / Beads [2]": sphere(1, (5, -30, 0)),
    }}

    # ── a loose face beside a solid: the face is reported, never dropped ──
    doc = App.newDocument("fixture_loose")
    solid = doc.addObject("Part::Feature", "Solid")
    solid.Shape = Part.makeBox(5, 5, 5)
    solid.Label = "Good block"
    face = doc.addObject("Part::Feature", "Face")
    face.Shape = Part.makePlane(10, 10, V(20, 0, 0))
    face.Label = "Stray face"
    doc.recompute()
    Import.export([solid, face], str(out / "loose_face.step"))
    App.closeDocument(doc.Name)
    cases["loose_face"] = {"file": "loose_face.step", "unit": "MM", "solids": {
        # Exporting several objects wraps them in a root named after the document.
        "fixture_loose / Good block": box((5, 5, 5)),
        "fixture_loose / Stray face": rejected("not part of any closed solid")}}

    # ── overlapping solids: both import, and the overlap is reported ──
    doc = App.newDocument("fixture_overlap")
    for name, origin in (("Left", V(0, 0, 0)), ("Right", V(5, 0, 0))):
        o = doc.addObject("Part::Feature", name)
        o.Shape = Part.makeBox(10, 10, 10, origin)
        o.Label = name
    doc.recompute()
    Import.export(list(doc.Objects), str(out / "overlap.step"))
    App.closeDocument(doc.Name)
    cases["overlap"] = {"file": "overlap.step", "unit": "MM", "overlap_cm3": 0.5, "solids": {
        "fixture_overlap / Left": box((10, 10, 10)),
        "fixture_overlap / Right": box((10, 10, 10), move=(5, 0, 0))}}

    # ── not STEP at all ──
    (out / "malformed.step").write_text("ISO-10303-21;\nthis is not a STEP file\n")
    cases["malformed"] = {"file": "malformed.step", "job_fails": True}

    (out / "expected.json").write_text(json.dumps(cases, indent=2))
    return cases


def teeth(out):
    """The equivalence check must reject near-correct parts, not just wrong ones.

    For real solids, take the recognizer's (accepted) part, nudge one value by a
    hair, and require validate.check to refuse it. Returns {case: outcome}."""
    import copy
    _runtime()
    import FreeCAD as App  # noqa: F401
    import Part
    from openmc_studio.cad.primitives import classify, emit_part
    from openmc_studio.cad.validate import NotEquivalent, check

    V = App.Vector
    b = Part.makeBox(10, 20, 30)
    for axis, ang in (((1, 0, 0), 30), ((0, 1, 0), -60), ((0, 0, 1), 145)):
        b.rotate(V(0, 0, 0), V(*axis), ang)
    c = Part.makeCylinder(4, 50)
    c.rotate(V(0, 0, 0), V(1, 0, 0), 37)
    k = Part.makeCone(10, 4, 25)
    k.rotate(V(0, 0, 0), V(0, 1, 0), 60)
    solids = {"box": b, "cylinder": c, "cone": k, "sphere": Part.makeSphere(0.25)}
    far = c.copy()
    far.translate(V(1e5, -2e5, 3e5))
    solids["far_cylinder"] = far
    nudges = {  # (field, change in Studio units) - each is far below any visible size
        "box": [("x", 1e-4), ("sy", 1e-4), ("rz", 0.01), ("swap", None)],
        "cylinder": [("z", 1e-4), ("r", 1e-4), ("h", 1e-4), ("rx", 0.01)],
        "cone": [("x", 1e-4), ("r2", 1e-4), ("ry", 0.01), ("flip", None)],
        "sphere": [("x", 1e-5), ("r", 1e-5)],  # a TRISO-kernel sphere: 0.1 um nudges
        "far_cylinder": [("y", 1e-4), ("r", 1e-4)],
    }
    results = {}
    for name, shape in solids.items():
        cand = classify(shape)
        good = emit_part(cand, name)
        check(shape, good, cand["tol"])  # the unmodified part must pass
        results[f"{name}: unmodified"] = "accepted"
        for field, delta in nudges[name]:
            bad = copy.deepcopy(good)
            if field == "swap":
                bad["sx"], bad["sy"] = bad["sy"], bad["sx"]
            elif field == "flip":
                bad["r"], bad["r2"] = bad["r2"], bad["r"]
            else:
                bad[field] = bad[field] + delta
            try:
                check(shape, bad, cand["tol"])
                results[f"{name}: {field}"] = "ACCEPTED (wrong)"
            except NotEquivalent as exc:
                results[f"{name}: {field}"] = f"rejected: {str(exc)[:60]}"
    # Same bounding box, different shape: only the deeper checks can tell these apart.
    ball = Part.makeSphere(5)
    cube = {"name": "cube", "shape": "box", "x": 0.0, "y": 0.0, "z": 0.0, "rx": 0.0, "ry": 0.0, "rz": 0.0,
            "sx": 1.0, "sy": 1.0, "sz": 1.0}
    try:
        check(ball, cube, {"linear_mm": 1e-6})
        results["sphere vs box, equal bounds"] = "ACCEPTED (wrong)"
    except NotEquivalent as exc:
        results["sphere vs box, equal bounds"] = f"rejected: {str(exc)[:60]}"
    return results
