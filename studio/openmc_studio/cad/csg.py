"""The 'csg' job: every solid of a STEP file through GEOUNED, as validated components.

Each valid solid is exported on its own, in global coordinates, and converted by
GEOUNED separately. That makes the cell-to-source mapping exact (one source solid
-> one component with one or more cells) and keeps one bad solid from spoiling the
rest. The resulting component is then checked with Studio's OWN region evaluator
(schema.contains) against FreeCAD's containment of the source solid: the
representation Studio stores is what gets validated, not GEOUNED's raw XML.

Checks per component, all required:
- deterministic grid plus seeded random points, away from a tolerance band around
  the source boundary, agree on inside/outside;
- no point lies in two cells of the component (its cells partition the solid);
- the sampled volume agrees with the source volume within six standard errors.

The band allows for GEOUNED writing plane coefficients with 8 significant digits.
Sampling is evidence within stated tolerances, not a proof of equivalence.
"""
import math
import random
from pathlib import Path

from .read import inventory, read_step
from .schema import AdapterError, IR_VERSION, component_contains, read_openmc_xml

ADAPTER_VERSION = "csg-1"
SEED = 20260923
GRID = 10
RANDOM = 2000


class NotEquivalent(Exception):
    pass


def band_mm(shape):
    b = shape.BoundBox
    far = max(abs(b.XMin), abs(b.XMax), abs(b.YMin), abs(b.YMax), abs(b.ZMin), abs(b.ZMax))
    return max(1e-3, 1e-4 * b.DiagonalLength, 1e-7 * far)


def validate(shape, component):
    import FreeCAD as App
    import Part

    band = band_mm(shape)
    skin = Part.Compound(shape.Faces)
    b = shape.BoundBox
    lo = [b.XMin, b.YMin, b.ZMin]
    hi = [b.XMax, b.YMax, b.ZMax]
    pad = [0.05 * (h - l) + band for l, h in zip(lo, hi)]
    lo = [l - p for l, p in zip(lo, pad)]
    hi = [h + p for h, p in zip(hi, pad)]
    rng = random.Random(SEED)
    grid = [[lo[k] + (hi[k] - lo[k]) * (i + 0.5) / GRID for k, i in enumerate(ijk)]
            for ijk in ((i, j, k) for i in range(GRID) for j in range(GRID) for k in range(GRID))]
    rand = [[rng.uniform(lo[k], hi[k]) for k in range(3)] for _ in range(RANDOM)]
    compared = inside = random_inside = random_compared = worst_overlap = 0
    for n, xyz in enumerate(grid + rand):
        p = App.Vector(*xyz)
        if skin.distToShape(Part.Vertex(p))[0] < band:
            continue
        cad_in = shape.isInside(p, 1e-7, False)
        cells = component_contains(component, xyz[0] / 10, xyz[1] / 10, xyz[2] / 10)
        worst_overlap = max(worst_overlap, len(cells))
        if len(cells) > 1:
            raise NotEquivalent(f"cells {cells} of the conversion overlap at {tuple(round(c, 4) for c in xyz)} mm")
        if cad_in != bool(cells):
            raise NotEquivalent(f"the conversion and the CAD solid disagree at {tuple(round(c, 4) for c in xyz)} mm "
                                f"(CAD says {'inside' if cad_in else 'outside'})")
        compared += 1
        inside += cad_in
        if n >= len(grid):
            random_compared += 1
            random_inside += cad_in
    if compared < (len(grid) + len(rand)) // 2 or inside == 0:
        raise NotEquivalent("too few decisive test points to compare the shapes")
    # Volume from the random points only (the grid is not an unbiased estimator).
    box = math.prod(h - l for l, h in zip(lo, hi))
    frac = random_inside / max(random_compared, 1)
    sampled = box * frac
    sigma = box * math.sqrt(max(frac * (1 - frac), 1e-12) / max(random_compared, 1))
    if abs(sampled - shape.Volume) > 6 * sigma + box * 1e-9:
        raise NotEquivalent(f"sampled volume {sampled:.4g} mm^3 differs from the solid's {shape.Volume:.4g}")
    return {"band_mm": band, "points_compared": compared, "points_inside": inside, "seed": SEED,
            "sampled_volume_cm3": sampled / 1000, "volume_sigma_cm3": sigma / 1000,
            "cad_volume_cm3": shape.Volume / 1000, "max_cells_at_a_point": worst_overlap}


MESH_DEFLECTION = 0.01    # relative to each face's size: scale-independent (0.25 mm and 25 cm spheres alike)
MESH_TRIANGLES = 200_000  # per solid; a finer mesh is refused, not truncated


def display_mesh(shape, conversion):
    """A triangle mesh of the SOURCE solid for the 3D preview, in cm. A display asset,
    never transport geometry: tagged with the conversion it belongs to so the
    browser can refuse a mesh that doesn't match its component. MeshPart's relative
    deflection is used because absolute deflection stalls OCCT on sub-mm spheres."""
    import MeshPart
    mesh = MeshPart.meshFromShape(Shape=shape, LinearDeflection=MESH_DEFLECTION, AngularDeflection=0.35, Relative=True)
    if mesh.CountFacets > MESH_TRIANGLES:
        raise ValueError(f"its preview mesh needs {mesh.CountFacets} triangles (limit {MESH_TRIANGLES})")
    points = [float(c / 10) for p in mesh.Points for c in (p.x, p.y, p.z)]
    triangles = [i for f in mesh.Facets for i in f.PointIndices]
    return {"positions_cm": points, "triangles": triangles, "count": mesh.CountFacets,
            "deflection": {"relative": MESH_DEFLECTION, "angular_rad": 0.35}, "conversion": conversion,
            "note": "display only; the analytical regions are the geometry"}


def convert(source, workdir, progress=None):
    """The report for the 'csg' job. workdir: a fresh private directory."""
    import FreeCAD as App  # noqa: F401 - initialized before Part
    from .geouned_adapter import convert_step

    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    solids, info = read_step(source)
    rows = inventory(solids)
    versions = None
    for i, (s, row) in enumerate(zip(solids, rows)):
        if progress:
            progress(f"converting solid {i + 1} of {len(solids)}")
        if row["reasons"]:
            row["status"] = "rejected"
            continue
        try:
            one = workdir / f"solid-{i}.step"
            s.shape.exportStep(str(one))
            result = convert_step(one, workdir / f"solid-{i}")
            versions = versions or result.get("versions")
            component = read_openmc_xml((workdir / f"solid-{i}" / "geometry.xml").read_bytes())
            label = row["label"] or "Imported solid"
            for k, cell in enumerate(component["cells"]):
                cell["name"] = label if len(component["cells"]) == 1 else f"{label} ({k + 1})"
            component.update(name=label, bounds_cm=row["bounds_cm"])
            evidence = validate(s.shape, component)
            component["display"] = display_mesh(s.shape, f"{info['source_sha256']}|{row['key']}")
            row.update(status="accepted", kind="csg", component=component, evidence=evidence)
        except (AdapterError, NotEquivalent) as exc:
            row.update(status="rejected", reasons=[str(exc)])
        except ValueError as exc:  # the pinned adapter's own refusals (unsupported surfaces, suspicious output)
            row.update(status="rejected", reasons=[f"GEOUNED could not convert it: {exc}"])
        except Exception as exc:  # noqa: BLE001 - one solid never ends the job
            row.update(status="failed", reasons=[f"{type(exc).__name__}: {exc}"[:300]])
    overlaps = _overlaps(solids, rows)
    counts = {k: sum(r["status"] == k for r in rows) for k in ("accepted", "rejected", "failed")}
    return {**info, "adapter": ADAPTER_VERSION, "ir_version": IR_VERSION, "units": "cm", "versions": versions,
            "solids": rows, "overlaps": overlaps, "counts": counts}


def _overlaps(solids, rows):
    idx = [i for i, r in enumerate(rows) if r["status"] == "accepted"]
    found = []
    for n, i in enumerate(idx):
        for j in idx[n + 1:]:
            a, b = solids[i].shape, solids[j].shape
            if not a.BoundBox.intersect(b.BoundBox):
                continue
            try:
                v = a.common(b).Volume
            except Exception:  # noqa: BLE001
                found.append({"a": rows[i]["key"], "b": rows[j]["key"], "volume_cm3": None,
                              "note": "the overlap check failed; inspect these two"})
                continue
            if v > max(a.Area, b.Area) * max(band_mm(a), band_mm(b)) * 4:
                found.append({"a": rows[i]["key"], "b": rows[j]["key"], "volume_cm3": v / 1000})
    return found
