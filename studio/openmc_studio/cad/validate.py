"""Prove a recognized primitive is the source solid, within recorded tolerances.

The candidate is rebuilt through the same Studio-part -> FreeCAD mapping that STEP
export uses (cad_worker.make_cad_solid), so what is compared is what Studio will
actually model, not what the recognizer thinks it found. Checks, all required:

- the rebuilt solid is valid and closed;
- bounding boxes agree;
- the symmetric difference (source - rebuilt, rebuilt - source) has no volume
  beyond what a surface shift of one tolerance could produce;
- boundary points of each solid lie on the other's boundary;
- deterministic grid and seeded random points away from the boundary band agree
  on inside/outside.

Volume alone would pass a displaced hole or a different shape of equal volume;
the point and distance checks are what catch those. A Boolean that fails or
returns an invalid shape is an uncertain comparison and rejects the candidate.
This is sampled evidence within stated tolerances, not a proof of exact equality.
"""
import random

SEED = 20260923
GRID = 8          # 8^3 lattice points in the padded bounding box
RANDOM = 256      # plus this many seeded random points
BOUNDARY = 24     # boundary sample points per face, each way


class NotEquivalent(Exception):
    pass


def _boundary_points(shape, per_face):
    """Points on every face: its vertices plus a grid in the face's own (u, v)
    parameters, kept only where the trimmed face really is. No meshing: OCCT's
    mesher stalls on sub-millimetre spheres (a TRISO kernel), and a parametric grid
    doesn't care about scale."""
    pts = []
    n = max(2, int(per_face ** 0.5))
    for face in shape.Faces:
        pts.extend(v.Point for v in face.Vertexes)
        u0, u1, v0, v1 = face.ParameterRange
        kept = 0
        for i in range(n):
            for j in range(n):
                u = u0 + (u1 - u0) * (i + 0.5) / n
                v = v0 + (v1 - v0) * (j + 0.5) / n
                if face.isPartOfDomain(u, v):
                    pts.append(face.valueAt(u, v))
                    kept += 1
        if not kept:  # a sliver whose grid misses it: its centre of mass is on it
            pts.append(face.CenterOfMass)
    return pts


def check(source, part, tol):
    """Return evidence for the report, or raise NotEquivalent."""
    import FreeCAD as App
    import Part
    from ..cad_worker import make_cad_solid

    lin = tol["linear_mm"]
    try:
        rebuilt = make_cad_solid(part, App, Part)
    except Exception as exc:  # noqa: BLE001
        raise NotEquivalent(f"Studio could not rebuild it: {exc}") from None
    if not rebuilt.isValid() or not rebuilt.isClosed():
        raise NotEquivalent("the rebuilt part is not a valid closed solid")
    # Compare in a local frame. OCCT Booleans of nearly coincident solids hundreds
    # of metres from the origin return nonsense (a whole cylinder's volume as the
    # difference); moving both by the same exact translation keeps them reliable.
    shift = App.Vector(source.BoundBox.Center) * -1
    source = source.copy()
    source.translate(shift)
    rebuilt = rebuilt.copy()
    rebuilt.translate(shift)

    a, b = source.BoundBox, rebuilt.BoundBox
    worst = max(abs(getattr(a, k) - getattr(b, k)) for k in ("XMin", "YMin", "ZMin", "XMax", "YMax", "ZMax"))
    if worst > 10 * lin:
        raise NotEquivalent(f"bounds differ by {worst:.3g} mm")

    # Symmetric difference: a displacement of lin over the whole surface.
    allowed = max(source.Area, rebuilt.Area) * lin * 4
    try:
        extra = source.cut(rebuilt)
        missing = rebuilt.cut(source)
        if not extra.isValid() or not missing.isValid():
            raise NotEquivalent("the Boolean comparison was not reliable")
        sym = extra.Volume + missing.Volume
    except NotEquivalent:
        raise
    except Exception as exc:  # noqa: BLE001
        raise NotEquivalent(f"the Boolean comparison failed ({exc})") from None
    if sym > allowed:
        raise NotEquivalent(f"the shapes differ by {sym:.3g} mm^3 (allowed {allowed:.3g})")

    # Distances are to the other solid's BOUNDARY: distToShape against a solid is
    # zero for every interior point, which would make both checks below vacuous.
    skin = {id(source): Part.Compound(source.Faces), id(rebuilt): Part.Compound(rebuilt.Faces)}

    # Each boundary lies on the other.
    worst = 0.0
    for here, there in ((source, rebuilt), (rebuilt, source)):
        for p in _boundary_points(here, BOUNDARY):
            d = skin[id(there)].distToShape(Part.Vertex(p))[0]
            worst = max(worst, d)
            if d > 10 * lin:
                raise NotEquivalent(f"a boundary point is {d:.3g} mm off the other surface")

    # Inside/outside away from the tolerance band.
    lo = [a.XMin, a.YMin, a.ZMin]
    hi = [a.XMax, a.YMax, a.ZMax]
    pad = [0.05 * (h - l) + lin for l, h in zip(lo, hi)]
    lo = [l - p for l, p in zip(lo, pad)]
    hi = [h + p for h, p in zip(hi, pad)]
    rng = random.Random(SEED)
    points = [[lo[k] + (hi[k] - lo[k]) * (i + 0.5) / GRID for k, i in enumerate(ijk)]
              for ijk in ((i, j, k) for i in range(GRID) for j in range(GRID) for k in range(GRID))]
    points += [[rng.uniform(lo[k], hi[k]) for k in range(3)] for _ in range(RANDOM)]
    band = 10 * lin
    compared = inside = 0
    for xyz in points:
        p = App.Vector(*xyz)
        if skin[id(source)].distToShape(Part.Vertex(p))[0] < band:
            continue
        s_in = source.isInside(p, lin, False)
        if s_in != rebuilt.isInside(p, lin, False):
            raise NotEquivalent(f"the shapes disagree about the point {tuple(round(c, 6) for c in xyz)} mm")
        compared += 1
        inside += s_in
    if compared < len(points) // 2 or inside == 0:
        raise NotEquivalent("too few decisive test points to compare the shapes")
    return {"tolerance_mm": lin, "symmetric_difference_mm3": sym, "allowed_mm3": allowed,
            "max_boundary_distance_mm": worst, "points_compared": compared, "points_inside": inside,
            "seed": SEED}
