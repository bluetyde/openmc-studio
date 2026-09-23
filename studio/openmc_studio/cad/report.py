"""Build the per-solid report for the 'inspect' and 'native' CAD jobs.

Every source solid appears exactly once, with a status:

- accepted: recognized AND proven equivalent (validate.py); carries a Studio part;
- rejected: not a supported primitive, not a valid closed solid, or not
  equivalent to its reconstruction; carries the reasons;
- failed: an unexpected error while examining it; carries the error.

Nothing is dropped silently: the browser shows every row and commits only what the
user accepts, with the omitted solids recorded in the project.
"""
from .primitives import NotPrimitive, classify, emit_part
from .read import inventory, read_step
from .validate import NotEquivalent, check

ADAPTER_VERSION = "native-1"
CSG_HINT = "Analytical CSG import (a later stage) is the route for this solid."


def inspect(source, progress=None):
    solids, info = read_step(source)
    if progress:
        progress(f"read {len(solids)} solid(s)")
    return {**info, "adapter": ADAPTER_VERSION, "solids": inventory(solids)}


def native(source, progress=None):
    import FreeCAD as App  # noqa: F401 - initialized before Part
    import Part  # noqa: F401

    solids, info = read_step(source)
    rows = inventory(solids)
    for i, (s, row) in enumerate(zip(solids, rows)):
        if progress:
            progress(f"checking solid {i + 1} of {len(solids)}")
        if row["reasons"]:
            row["status"] = "rejected"
            continue
        try:
            candidate = classify(s.shape)
            part = emit_part(candidate, row["label"] or "Imported part")
            evidence = check(s.shape, part, candidate["tol"])
            row.update(status="accepted", kind=candidate["shape"], part=part, evidence=evidence)
        except NotPrimitive as exc:
            row.update(status="rejected", reasons=[f"not a supported primitive: {exc}", CSG_HINT])
        except NotEquivalent as exc:
            row.update(status="rejected", reasons=[f"recognized, but the rebuilt part doesn't match: {exc}"])
        except Exception as exc:  # noqa: BLE001 - a per-solid failure never ends the job
            row.update(status="failed", reasons=[f"{type(exc).__name__}: {exc}"[:300]])

    overlaps = _overlaps(solids, rows)
    counts = {k: sum(r["status"] == k for r in rows) for k in ("accepted", "rejected", "failed")}
    return {**info, "adapter": ADAPTER_VERSION, "solids": rows, "overlaps": overlaps, "counts": counts}


def _overlaps(solids, rows):
    """Pairs of accepted solids that share volume. CAD assemblies shouldn't have
    any; Studio would give the overlap to whichever part is listed first, so the
    user has to see it before committing."""
    idx = [i for i, r in enumerate(rows) if r["status"] == "accepted"]
    found = []
    for n, i in enumerate(idx):
        for j in idx[n + 1:]:
            a, b = solids[i].shape, solids[j].shape
            if not a.BoundBox.intersect(b.BoundBox):
                continue
            tol = max(rows[i]["evidence"]["tolerance_mm"], rows[j]["evidence"]["tolerance_mm"])
            try:
                v = a.common(b).Volume
            except Exception:  # noqa: BLE001 - can't tell: say so rather than guess
                found.append({"a": rows[i]["key"], "b": rows[j]["key"], "volume_cm3": None,
                              "note": "the overlap check failed; inspect these two"})
                continue
            if v > max(a.Area, b.Area) * tol * 4:
                found.append({"a": rows[i]["key"], "b": rows[j]["key"], "volume_cm3": v / 1000})
    return found
