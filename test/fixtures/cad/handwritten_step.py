"""An independent STEP writer for boxes: plain Python, no OpenCASCADE.

The CAD import plan asks for fixtures "produced by other CAD tools", because a
file written and read by the same kernel can reproduce one bug twice. This writer
shares no code with FreeCAD/OCCT: it emits AP214 manifold B-rep boxes with their
coordinates in the file's own declared unit (mm, cm, m or inch). If the reader
mishandled a unit, the recovered box would come out the wrong size.

It can also put several solids in ONE product and shape representation - one
object holding several solids - which some CAD tools write and FreeCAD's own
exporter never does.

Run:  python test/fixtures/cad/handwritten_step.py
to regenerate the committed files in test/fixtures/cad/external/ and their
expected values in test/fixtures/cad/expected/external.json.
"""
import json
import math
from pathlib import Path

UNITS = {  # declared unit -> (STEP unit entity, millimetres per file unit)
    "MM": ("SI_UNIT(.MILLI.,.METRE.)", 1.0),
    "CM": ("SI_UNIT(.CENTI.,.METRE.)", 10.0),
    "M": ("SI_UNIT($,.METRE.)", 1000.0),
    "INCH": (None, 25.4),
}


def real(x):
    s = repr(float(x))
    if s in ("-0.0", "0.0"):
        return "0."
    if "e" in s:
        mant, exp = s.split("e")
        if "." not in mant:
            mant += "."
        return f"{mant}E{exp}"
    return s if "." in s else s + "."


def rot(rx, ry, rz):
    """Rz * Ry * Rx, written out independently of the code under test."""
    a, b, c = (math.radians(t) for t in (rx, ry, rz))
    Rx = [[1, 0, 0], [0, math.cos(a), -math.sin(a)], [0, math.sin(a), math.cos(a)]]
    Ry = [[math.cos(b), 0, math.sin(b)], [0, 1, 0], [-math.sin(b), 0, math.cos(b)]]
    Rz = [[math.cos(c), -math.sin(c), 0], [math.sin(c), math.cos(c), 0], [0, 0, 1]]
    mm = lambda A, B: [[sum(A[i][k] * B[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
    return mm(Rz, mm(Ry, Rx))


class Writer:
    def __init__(self):
        self.lines, self.n = [], 0

    def add(self, text):
        self.n += 1
        self.lines.append(f"#{self.n}={text};")
        return f"#{self.n}"

    def point(self, p):
        return self.add(f"CARTESIAN_POINT('',({real(p[0])},{real(p[1])},{real(p[2])}))")

    def direction(self, d):
        return self.add(f"DIRECTION('',({real(d[0])},{real(d[1])},{real(d[2])}))")


def solid(w, size, center, angles, label):
    """One MANIFOLD_SOLID_BREP box in the file's unit; returns its reference."""
    R = rot(*angles)

    def world(local):
        return [center[i] + sum(R[i][k] * local[k] for k in range(3)) for i in range(3)]

    def world_dir(local):
        return [sum(R[i][k] * local[k] for k in range(3)) for i in range(3)]

    half = [s / 2 for s in size]
    corners = {}
    for bits in range(8):
        sgn = [1 if bits >> k & 1 else -1 for k in range(3)]
        corners[bits] = world([sgn[k] * half[k] for k in range(3)])
    vertex = {b: w.add(f"VERTEX_POINT('',{w.point(p)})") for b, p in corners.items()}
    edges = {}
    for b in range(8):
        for k in range(3):
            if not b >> k & 1:
                e = b | 1 << k
                p0, p1 = corners[b], corners[e]
                d = [p1[i] - p0[i] for i in range(3)]
                L = math.sqrt(sum(x * x for x in d))
                vec = w.add(f"VECTOR('',{w.direction([x / L for x in d])},{real(L)})")
                line = w.add(f"LINE('',{w.point(p0)},{vec})")
                edges[(b, e)] = w.add(f"EDGE_CURVE('',{vertex[b]},{vertex[e]},{line},.T.)")
    faces = []
    for k in range(3):
        for side in (0, 1):
            n_local = [0, 0, 0]
            n_local[k] = 1 if side else -1
            n = world_dir(n_local)
            members = [b for b in range(8) if (b >> k & 1) == side]
            ref = world_dir([1 if i == (k + 1) % 3 else 0 for i in range(3)])
            other = [n[1] * ref[2] - n[2] * ref[1], n[2] * ref[0] - n[0] * ref[2], n[0] * ref[1] - n[1] * ref[0]]
            cen = [sum(corners[b][i] for b in members) / 4 for i in range(3)]
            # Counter-clockwise about the outward normal: the outer loop of a same-sense face.
            ang = lambda b: math.atan2(sum((corners[b][i] - cen[i]) * other[i] for i in range(3)),
                                       sum((corners[b][i] - cen[i]) * ref[i] for i in range(3)))
            loop = sorted(members, key=ang)
            oriented = []
            for i in range(4):
                a, b = loop[i], loop[(i + 1) % 4]
                if (a, b) in edges:
                    oriented.append(w.add(f"ORIENTED_EDGE('',*,*,{edges[(a, b)]},.T.)"))
                else:
                    oriented.append(w.add(f"ORIENTED_EDGE('',*,*,{edges[(b, a)]},.F.)"))
            eloop = w.add(f"EDGE_LOOP('',({','.join(oriented)}))")
            bound = w.add(f"FACE_OUTER_BOUND('',{eloop},.T.)")
            place = w.add(f"AXIS2_PLACEMENT_3D('',{w.point(cen)},{w.direction(n)},{w.direction(ref)})")
            plane = w.add(f"PLANE('',{place})")
            faces.append(w.add(f"ADVANCED_FACE('',({bound}),{plane},.T.)"))
    shell = w.add(f"CLOSED_SHELL('',({','.join(faces)}))")
    return w.add(f"MANIFOLD_SOLID_BREP('{label}',{shell})")


def box_step(name, boxes, unit):
    """boxes: [(size, center, angles)] in the file's unit, all in one product."""
    unit_entity, _ = UNITS[unit]
    w = Writer()
    ctx_app = w.add("APPLICATION_CONTEXT('automotive design')")
    w.add(f"APPLICATION_PROTOCOL_DEFINITION('international standard','automotive_design',2000,{ctx_app})")
    pctx = w.add(f"PRODUCT_CONTEXT('',{ctx_app},'mechanical')")
    prod = w.add(f"PRODUCT('{name}','{name}','',({pctx}))")
    pdctx = w.add(f"PRODUCT_DEFINITION_CONTEXT('part definition',{ctx_app},'design')")
    pdf = w.add(f"PRODUCT_DEFINITION_FORMATION('','',{prod})")
    pd = w.add(f"PRODUCT_DEFINITION('design','',{pdf},{pdctx})")
    pds = w.add(f"PRODUCT_DEFINITION_SHAPE('','',{pd})")
    # Units: the length unit is whatever the file declares; coordinates use it.
    if unit_entity:
        length = w.add(f"( LENGTH_UNIT() NAMED_UNIT(*) {unit_entity} )")
    else:
        mmu = w.add("( LENGTH_UNIT() NAMED_UNIT(*) SI_UNIT(.MILLI.,.METRE.) )")
        mwu = w.add(f"LENGTH_MEASURE_WITH_UNIT(LENGTH_MEASURE(25.4),{mmu})")
        dim = w.add("DIMENSIONAL_EXPONENTS(1.,0.,0.,0.,0.,0.,0.)")
        length = w.add(f"( CONVERSION_BASED_UNIT('INCH',{mwu}) LENGTH_UNIT() NAMED_UNIT({dim}) )")
    angle = w.add("( NAMED_UNIT(*) PLANE_ANGLE_UNIT() SI_UNIT($,.RADIAN.) )")
    solid_angle = w.add("( NAMED_UNIT(*) SI_UNIT($,.STERADIAN.) SOLID_ANGLE_UNIT() )")
    unc = w.add(f"UNCERTAINTY_MEASURE_WITH_UNIT(LENGTH_MEASURE(1.E-09),{length},'distance_accuracy_value','')")
    ctx = w.add(f"( GEOMETRIC_REPRESENTATION_CONTEXT(3) GLOBAL_UNCERTAINTY_ASSIGNED_CONTEXT(({unc})) "
                f"GLOBAL_UNIT_ASSIGNED_CONTEXT(({length},{angle},{solid_angle})) "
                f"REPRESENTATION_CONTEXT('Context #1','3D Context with UNIT and UNCERTAINTY') )")
    breps = [solid(w, size, center, angles, name if i == 0 else f"{name} {i + 1}")
             for i, (size, center, angles) in enumerate(boxes)]
    origin = w.add(f"AXIS2_PLACEMENT_3D('',{w.point([0, 0, 0])},{w.direction([0, 0, 1])},{w.direction([1, 0, 0])})")
    rep = w.add(f"ADVANCED_BREP_SHAPE_REPRESENTATION('',({','.join(breps)},{origin}),{ctx})")
    w.add(f"SHAPE_DEFINITION_REPRESENTATION({pds},{rep})")
    header = ("ISO-10303-21;\nHEADER;\n"
              "FILE_DESCRIPTION(('OpenMC Studio independent test writer'),'2;1');\n"
              f"FILE_NAME('{name}.step','2026-09-23T00:00:00',('OpenMC Studio tests'),(''),"
              "'handwritten_step.py','handwritten_step.py','');\n"
              "FILE_SCHEMA(('AUTOMOTIVE_DESIGN { 1 0 10303 214 1 1 1 1 }'));\nENDSEC;\nDATA;\n")
    return header + "\n".join(w.lines) + "\nENDSEC;\nEND-ISO-10303-21;\n"


# name: ([(size, center, angles), ...], unit), sizes and centres in that unit.
CASES = {
    "box_inch": ([((1.0, 2.0, 0.5), (3.0, -1.0, 10.0), (0, 0, 0))], "INCH"),
    "box_cm_rotated": ([((4.0, 2.0, 1.0), (10.0, 5.0, -2.0), (25.0, -40.0, 70.0))], "CM"),
    "box_m_far": ([((0.3, 0.2, 0.1), (12.0, -7.0, 3.0), (0, 90, 0))], "M"),
    "box_mm_rotated": ([((20.0, 10.0, 5.0), (-3.0, 4.0, 5.0), (10.0, 20.0, 30.0))], "MM"),
    "two_boxes_one_product": ([((10.0, 10.0, 10.0), (0.0, 0.0, 0.0), (0, 0, 0)),
                               ((4.0, 6.0, 8.0), (30.0, 0.0, 0.0), (0, 0, 45))], "MM"),
}


def expected_box(size, center, angles, to_cm):
    R = rot(*angles)
    axes = [[R[i][k] for i in range(3)] for k in range(3)]  # local axes in world
    return {"shape": "box", "center_cm": [c * to_cm for c in center],
            "axes": [{"dir": axes[k], "size_cm": size[k] * to_cm} for k in range(3)],
            "volume_cm3": math.prod(size) * to_cm ** 3}


def expected():
    """Studio centimetres, derived only from the construction parameters.

    Keyed by file, then by the solid's key: one solid -> "". FreeCAD 26.3's reader
    turns several solids in one product into child objects of that product, so
    they come back as "<product> / <product> [1]", "[2]", ... in file order."""
    out = {}
    for name, (boxes, unit) in CASES.items():
        to_cm = UNITS[unit][1] / 10
        rows = [expected_box(*b, to_cm) for b in boxes]
        solids = {"": rows[0]} if len(rows) == 1 else {
            f"{name} / {name} [{i + 1}]": r for i, r in enumerate(rows)}
        out[name] = {"unit": unit, "solids": solids}
    return out


def main():
    here = Path(__file__).resolve().parent
    (here / "external").mkdir(exist_ok=True)
    (here / "expected").mkdir(exist_ok=True)
    for name, (boxes, unit) in CASES.items():
        (here / "external" / f"{name}.step").write_text(box_step(name, boxes, unit), newline="\n")
    (here / "expected" / "external.json").write_text(json.dumps(expected(), indent=2) + "\n", newline="\n")
    print(f"wrote {len(CASES)} files")


if __name__ == "__main__":
    main()
