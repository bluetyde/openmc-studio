"""The pin-power view of a mesh tally: relative power of each cell of a pin-resolved mesh, its peaking and what noise alone could lift it.

Glue between a results payload (results.py: one mesh tally with `values` and `std` per score, in grid order, x fastest) and two modules that know
nothing about Studio: pin_power_table (rows, relative power, the quarter fold, CSV) and peak_stats (the peaking factor and the noise allowance).

The mesh must be one cell per pin and line up with the lattice; Studio does not check the lattice (see `alignment` below: not applied), so the
view says what it assumes. A cell with no score (a guide tube, an empty site) is left out of the mean, and the view says how many.
"""
from . import peak_stats, pin_power_table


class PinPowerError(ValueError):
    """The mesh cannot be read as a pin map, and the message says why."""


ASSUMES = ("each cell of the mesh is one pin, so the mesh must be laid on the lattice (same pitch, same corner); cells that scored nothing are "
           "left out of the mean")
Z_SYMMETRY = 3.0


def analyse(tally, score=None, layer=0):
    """Rows, peaking and symmetry for one score and one axial layer of a regular mesh tally payload.

    tally: {"name", "kind": "mesh", "mesh_type": "regular", "dims": [nx, ny, nz], "lower", "upper", "scores", "values": {score: [...]}, "std": {score: [...]}}
    Raises PinPowerError for anything that is not a regular mesh with more than one cell in x and in y."""
    if not isinstance(tally, dict) or tally.get("kind") != "mesh":
        raise PinPowerError("not a mesh tally")
    if tally.get("mesh_type") != "regular":
        raise PinPowerError("a pin map needs a regular (box) mesh; this one is cylindrical")
    nx, ny, nz = (int(d) for d in tally["dims"])
    if nx < 2 or ny < 2:
        raise PinPowerError(f"a pin map needs more than one mesh cell in x and in y; this mesh is {nx} x {ny} x {nz}")
    scores = list(tally.get("scores") or [])
    score = score if score is not None else (scores[0] if scores else None)
    if score not in scores:
        raise PinPowerError(f"the tally has no score {score!r} (it has {', '.join(scores) or 'none'})")
    if isinstance(layer, bool) or not isinstance(layer, int) or not 0 <= layer < nz:
        raise PinPowerError(f"layer {layer!r} is not one of the {nz} axial layers (0 to {nz - 1})")
    vals, sds = tally["values"][score], tally["std"][score]
    lo, hi = tally["lower"], tally["upper"]
    n = nx * ny
    flat = slice(layer * n, (layer + 1) * n)
    values, sigmas = [float(v) for v in vals[flat]], [float(s) for s in sds[flat]]
    if len(values) != n or len(sigmas) != n:
        raise PinPowerError("the tally's values do not fill its mesh")
    include = [v > 0 for v in values]
    if not any(include):
        raise PinPowerError("no cell of this layer scored anything")
    px, py = (hi[0] - lo[0]) / nx, (hi[1] - lo[1]) / ny
    try:
        rows = pin_power_table.build_rows(values, sigmas, nx, ny, px, py, lo[0], lo[1], include)
        peak = pin_power_table.radial_peaking(rows)
        quarter = pin_power_table.fold_quarter(rows, nx, ny)
        excluded = [i for i, inc in enumerate(include) if not inc]
        noise = peak_stats.peaking_summary([r["relative_power"] if r["included"] else 0.0 for r in rows],
                                           [r["relative_sigma"] if r["included"] else 0.0 for r in rows], excluded)
    except (pin_power_table.TableError, ValueError) as exc:
        raise PinPowerError(str(exc)) from exc
    # Symmetry: among the pins a four-fold symmetric layout would make equal, how far apart are they, in units of the pin's own sigma?
    max_z, max_dev, no_sigma = 0.0, 0.0, False
    for qr in quarter:
        if qr["n_members"] < 2 or qr["max_deviation"] is None:
            continue
        group = _members(rows, nx, ny, qr["ix"], qr["iy"])
        mean = sum(g["relative_power"] for g in group) / len(group)
        sigma = max(g["relative_sigma"] for g in group)
        spread = max(abs(g["relative_power"] - mean) for g in group)
        max_dev = max(max_dev, qr["max_deviation"])
        if sigma > 0:
            max_z = max(max_z, spread / sigma)
        elif spread > 0:
            no_sigma = True  # they differ and nothing says by how much noise: not a pass
    return {
        "tally": tally.get("name"), "score": score, "layer": layer, "layers": nz, "nx": nx, "ny": ny,
        "pitch_cm": [px, py], "lower_cm": [lo[0], lo[1]],
        "rows": rows,
        "peak": {"relative_power": peak["max_relative_power"], "ix": peak["ix"], "iy": peak["iy"], "n_used": peak["n_used"],
                 "n_excluded": n - peak["n_used"]},
        # the relative powers have mean 1, so the allowance is already relative to the mean power
        "noise": {"peaking_factor": noise["peaking_factor"], "noise_allowance": noise["noise_allowance_relative"]},
        "quarter": quarter,
        "symmetry": {"max_deviation": max_dev, "max_z": None if no_sigma else max_z, "within_noise": not no_sigma and max_z <= Z_SYMMETRY,
                     "note": "if the layout is four-fold symmetric, pins that should match differ by this many of their own sigma at most"},
        "assumes": ASSUMES,
        "alignment": "not checked: Studio does not compare the mesh with the lattice",
    }


def _members(rows, nx, ny, qix, qiy):
    coords = []
    for c in ((qix, qiy), (nx - 1 - qix, qiy), (qix, ny - 1 - qiy), (nx - 1 - qix, ny - 1 - qiy)):
        if c not in coords:
            coords.append(c)
    return [rows[cx + nx * cy] for cx, cy in coords if rows[cx + nx * cy]["included"]]


def csv_text(analysis):
    """The rows as CSV text (every cell passed through pin_power_table.csv_cell, so a name cannot become a formula)."""
    lines = []
    for r in pin_power_table.csv_rows(analysis["rows"]):
        lines.append(",".join(_quote(c) for c in r))
    return "\n".join(lines) + "\n"


def _quote(cell):
    text = repr(cell) if isinstance(cell, float) else str(cell)
    return '"' + text.replace('"', '""') + '"' if any(ch in text for ch in ',"\n\r') else text
