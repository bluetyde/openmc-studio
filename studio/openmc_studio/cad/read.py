"""Read a STEP file into an inventory of placed solids. Run only in the CAD worker.

Uses FreeCAD's own reader for units and assembly placements: the kernel returns
millimetres whatever the file declares (checked for mm/cm/m/inch files), so the
only unit conversion in Studio's CAD path is mm -> cm, once, at the boundary.

Every solid keeps a stable source path: the chain of labels from the assembly root
plus an index, so two parts both called "Fuel rod" stay distinguishable. The
document walk is cross-checked against an independent flat read of the same file;
if the two disagree about how many solids there are or where they are, the file
is refused rather than half-imported.
"""
from dataclasses import dataclass, field
import hashlib
from pathlib import Path

MAX_SOLIDS = 500
SKIP_TYPES = {"App::Origin", "App::Line", "App::Plane", "App::Point"}


@dataclass
class SourceSolid:
    path: list          # labels from the root to the owning object
    index: int          # position among the solids of that object
    shape: object       # FreeCAD solid in global coordinates (mm)
    reasons: list = field(default_factory=list)  # why it can't be imported, if anything
    occurrence: int = 0  # 1, 2, ... when several objects share this label path (repeated instances)

    @property
    def key(self):
        key = " / ".join(self.path)
        if self.occurrence:
            key += f" [{self.occurrence}]"
        return key + (f" #{self.index + 1}" if self.index else "")


def _global_shape(obj, solid):
    shape = solid.copy()
    # obj.Shape carries obj.Placement; the global placement also includes every parent.
    shape.Placement = obj.getGlobalPlacement().multiply(obj.Placement.inverse()).multiply(solid.Placement)
    return shape


def read_step(source, max_solids=MAX_SOLIDS):
    """Return (solids, info). Raises ValueError for files that can't be inventoried."""
    import FreeCAD as App
    import Import
    import Part

    source = Path(source).resolve(strict=True)
    if source.suffix.lower() not in {".step", ".stp"}:
        raise ValueError("Only STEP/STP files are accepted")
    # Keep duplicate labels as the author wrote them; the path index disambiguates.
    App.ParamGet("User parameter:BaseApp/Preferences/Document").SetBool("DuplicateLabels", True)
    doc = App.newDocument("studio_import")
    try:
        try:
            Import.insert(str(source), doc.Name)
        except Exception as exc:  # noqa: BLE001 - a malformed file is a user error, not a crash
            raise ValueError(f"FreeCAD could not read this STEP file ({exc})") from None
        doc.recompute()
        solids = []

        def walk(obj, path):
            if obj.TypeId in SKIP_TYPES:
                return
            children = [c for c in (getattr(obj, "Group", None) or []) if c.TypeId not in SKIP_TYPES]
            here = path + [obj.Label]
            if children:
                for child in children:
                    walk(child, here)
                return
            shape = getattr(obj, "Shape", None)
            if shape is None or shape.isNull():
                return
            for i, s in enumerate(shape.Solids):
                if len(solids) >= max_solids:
                    raise ValueError(f"The file has more than {max_solids} solids")
                solids.append(SourceSolid(here, i, _global_shape(obj, s)))
            # Open faces or shells that aren't part of a solid are geometry we'd drop.
            loose = len(shape.Faces) - sum(len(s.Faces) for s in shape.Solids)
            if loose > 0:
                solids.append(SourceSolid(here, len(shape.Solids), shape,
                                          [f"{loose} face(s) are not part of any closed solid"]))

        for root in [o for o in doc.Objects if not o.InList]:
            walk(root, [])
        if not solids:
            raise ValueError("The file contains no solids")
        # Repeated instances share a label path; number them in file order so every
        # solid keeps a distinct, reproducible key.
        owners = {}
        for s in solids:
            owners.setdefault(tuple(s.path), []).append(s)
        for group in owners.values():
            firsts = [s for s in group if s.index == 0]
            if len(firsts) > 1:
                n = 0
                for s in group:
                    if s.index == 0:
                        n += 1
                    s.occurrence = n

        # Independent check: a flat read of the same file must see the same solids.
        flat = Part.read(str(source))
        closed = [s for s in solids if not s.reasons]
        if len(flat.Solids) != len(closed):
            raise ValueError(f"The assembly walk found {len(closed)} solids but the file holds "
                             f"{len(flat.Solids)}; refusing a partial read")
        want = sorted(_bounds(s) for s in flat.Solids)
        got = sorted(_bounds(s.shape) for s in closed)
        scale = max([1.0] + [abs(v) for b in want for v in b])
        if any(abs(a - b) > 1e-6 * scale for wa, ga in zip(want, got) for a, b in zip(wa, ga)):
            raise ValueError("Assembly placements disagree with the flat read of the file; refusing")
        info = {"source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "kernel_units": "mm", "studio_units": "cm", "solid_count": len(solids)}
        return solids, info
    finally:
        App.closeDocument(doc.Name)


def _bounds(shape):
    b = shape.BoundBox
    return (round(b.XMin, 6), round(b.YMin, 6), round(b.ZMin, 6),
            round(b.XMax, 6), round(b.YMax, 6), round(b.ZMax, 6))


def proper_rotation(m, tol=1e-9):
    """True if a FreeCAD Matrix is a rotation plus translation: orthonormal, det +1.
    FreeCAD's reader bakes mirrors and scales into geometry today; this guard keeps
    a reflected or scaled instance from ever being imported as if it weren't."""
    rows = [(m.A11, m.A12, m.A13), (m.A21, m.A22, m.A23), (m.A31, m.A32, m.A33)]
    for i in range(3):
        for j in range(3):
            dot = sum(rows[i][k] * rows[j][k] for k in range(3))
            if abs(dot - (1.0 if i == j else 0.0)) > tol:
                return False
    det = (rows[0][0] * (rows[1][1] * rows[2][2] - rows[1][2] * rows[2][1])
           - rows[0][1] * (rows[1][0] * rows[2][2] - rows[1][2] * rows[2][0])
           + rows[0][2] * (rows[1][0] * rows[2][1] - rows[1][1] * rows[2][0]))
    return det > 0


def inventory(solids):
    """Per-solid diagnostics without classification (the 'inspect' job)."""
    rows = []
    for s in solids:
        sh = s.shape
        reasons = list(s.reasons)
        if not reasons and not proper_rotation(sh.Matrix):
            reasons.append("a mirrored or scaled instance; only rotations and translations are supported")
        if not reasons:
            if not sh.isValid():
                reasons.append("the solid is not valid")
            if not sh.isClosed():
                reasons.append("the solid is not closed")
        b = sh.BoundBox
        rows.append({
            "path": s.path, "index": s.index, "key": s.key, "label": s.path[-1] if s.path else "",
            "valid": not reasons,
            "surface_types": sorted({type(f.Surface).__name__ for f in sh.Faces}),
            "faces": len(sh.Faces),
            "volume_cm3": (sh.Volume / 1000) if not s.reasons else None,
            "bounds_cm": [b.XMin / 10, b.YMin / 10, b.ZMin / 10, b.XMax / 10, b.YMax / 10, b.ZMax / 10],
            "reasons": reasons,
        })
    return rows
