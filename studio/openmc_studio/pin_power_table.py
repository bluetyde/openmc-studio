"""Pin-resolved mesh tally processing and power distribution tables.

Converts pin-resolved mesh tally results into table rows, computes relative
pin powers and uncertainties normalized by the mean of included pins, folds
four-fold symmetric cores into the lower-left quarter, evaluates the radial
peaking factor, checks lattice alignment, and sanitizes CSV exports against
formula injection.
"""
from __future__ import annotations

import math
from typing import Any


class TableError(ValueError):
    """Raised for any invalid input to pin power table functions."""


def _validate_pos_int(val: Any, name: str) -> int:
    if isinstance(val, bool) or not isinstance(val, int) or val < 1:
        raise TableError(f"{name} must be an integer >= 1 (no bools), got {val!r}")
    return val


def _validate_finite_num(val: Any, name: str) -> float:
    if isinstance(val, bool) or not isinstance(val, (int, float)) or not math.isfinite(val):
        raise TableError(f"{name} must be a finite number (no bools), got {val!r}")
    return float(val)


def _validate_pos_finite_num(val: Any, name: str) -> float:
    num = _validate_finite_num(val, name)
    if num <= 0:
        raise TableError(f"{name} must be a finite number > 0, got {val!r}")
    return num


def _validate_pair_numbers(
    val: Any, name: str, strictly_positive: bool = False
) -> tuple[float, float]:
    if not isinstance(val, (tuple, list)) or len(val) != 2:
        raise TableError(f"{name} must be an (x, y) pair of length 2, got {val!r}")
    x = _validate_finite_num(val[0], f"{name}[0]")
    y = _validate_finite_num(val[1], f"{name}[1]")
    if strictly_positive:
        if x <= 0:
            raise TableError(f"{name}[0] must be > 0, got {val[0]!r}")
        if y <= 0:
            raise TableError(f"{name}[1] must be > 0, got {val[1]!r}")
    return (x, y)


def _validate_pair_ints(val: Any, name: str) -> tuple[int, int]:
    if not isinstance(val, (tuple, list)) or len(val) != 2:
        raise TableError(f"{name} must be an (x, y) pair of length 2, got {val!r}")
    x = _validate_pos_int(val[0], f"{name}[0]")
    y = _validate_pos_int(val[1], f"{name}[1]")
    return (x, y)


def build_rows(
    values: list[float | int],
    sigmas: list[float | int],
    nx: int,
    ny: int,
    pitch_x_cm: float | int,
    pitch_y_cm: float | int,
    x0_cm: float | int = 0.0,
    y0_cm: float | int = 0.0,
    include: list[bool] | None = None,
) -> list[dict[str, Any]]:
    """Build pin power table rows from flat values and 1-sigma uncertainties.

    The relative power of an included pin is its value divided by the arithmetic
    mean of values of all included pins. The relative uncertainty of an included
    pin is its sigma divided by that same mean; the uncertainty of the mean itself
    is ignored. Masked pins (included=False) have relative_power and relative_sigma
    set to None.

    Lattice pin index is 0-based with x fastest: index = ix + nx * iy.
    Pin centres are located at:
      x_cm = x0_cm + (ix + 0.5) * pitch_x_cm
      y_cm = y0_cm + (iy + 0.5) * pitch_y_cm
    """
    _validate_pos_int(nx, "nx")
    _validate_pos_int(ny, "ny")
    _validate_pos_finite_num(pitch_x_cm, "pitch_x_cm")
    _validate_pos_finite_num(pitch_y_cm, "pitch_y_cm")
    _validate_finite_num(x0_cm, "x0_cm")
    _validate_finite_num(y0_cm, "y0_cm")

    n_total = nx * ny

    if not isinstance(values, list):
        raise TableError(f"values must be a list, got {type(values).__name__}")
    if len(values) != n_total:
        raise TableError(f"values length ({len(values)}) does not match nx * ny ({n_total})")

    for i, v in enumerate(values):
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            raise TableError(f"values[{i}] must be a finite number (no bools), got {v!r}")
        if v < 0:
            raise TableError(f"values[{i}] must be >= 0, got {v!r}")

    if not isinstance(sigmas, list):
        raise TableError(f"sigmas must be a list, got {type(sigmas).__name__}")
    if len(sigmas) != n_total:
        raise TableError(f"sigmas length ({len(sigmas)}) does not match nx * ny ({n_total})")

    for i, s in enumerate(sigmas):
        if isinstance(s, bool) or not isinstance(s, (int, float)) or not math.isfinite(s):
            raise TableError(f"sigmas[{i}] must be a finite number (no bools), got {s!r}")
        if s < 0:
            raise TableError(f"sigmas[{i}] must be >= 0, got {s!r}")

    if include is None:
        mask = [True] * n_total
    else:
        if not isinstance(include, list):
            raise TableError(f"include must be None or a list of bools, got {type(include).__name__}")
        if len(include) != n_total:
            raise TableError(f"include length ({len(include)}) does not match nx * ny ({n_total})")
        for i, inc in enumerate(include):
            if not isinstance(inc, bool):
                raise TableError(f"include[{i}] must be a bool, got {inc!r}")
        mask = include

    included_values = [values[i] for i in range(n_total) if mask[i]]
    if not included_values:
        raise TableError("include: at least one pin must be included")

    mean_val = sum(included_values) / len(included_values)
    if mean_val <= 0:
        raise TableError(f"values: mean of included values must be > 0, got {mean_val}")

    rows: list[dict[str, Any]] = []
    for iy in range(ny):
        for ix in range(nx):
            idx = ix + nx * iy
            is_inc = mask[idx]
            v = values[idx]
            s = sigmas[idx]
            rows.append({
                "ix": ix,
                "iy": iy,
                "x_cm": x0_cm + (ix + 0.5) * pitch_x_cm,
                "y_cm": y0_cm + (iy + 0.5) * pitch_y_cm,
                "value": v,
                "sigma": s,
                "included": is_inc,
                "relative_power": (v / mean_val) if is_inc else None,
                "relative_sigma": (s / mean_val) if is_inc else None,
            })

    return rows


def radial_peaking(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Find the maximum relative power among included pins.

    Returns {"max_relative_power", "ix", "iy", "n_used"}.
    Ties are broken by selecting the lowest index (earliest in rows).
    Raises TableError if rows is invalid or contains no included pin.
    """
    if not isinstance(rows, list):
        raise TableError(f"rows must be a list, got {type(rows).__name__}")
    if not rows:
        raise TableError("rows must not be empty")

    best_power: float | None = None
    best_ix: int | None = None
    best_iy: int | None = None
    n_used = 0

    for idx, r in enumerate(rows):
        if not isinstance(r, dict):
            raise TableError(f"rows[{idx}] must be a dict, got {type(r).__name__}")
        for key in ("ix", "iy", "included", "relative_power"):
            if key not in r:
                raise TableError(f"rows[{idx}] missing key {key!r}")

        if r["included"]:
            n_used += 1
            rp = r["relative_power"]
            if rp is None or isinstance(rp, bool) or not isinstance(rp, (int, float)) or not math.isfinite(rp):
                raise TableError(f"rows[{idx}] included row has invalid relative_power: {rp!r}")
            if best_power is None or rp > best_power:
                best_power = float(rp)
                best_ix = r["ix"]
                best_iy = r["iy"]

    if n_used == 0 or best_power is None:
        raise TableError("rows: no included rows found")

    return {
        "max_relative_power": best_power,
        "ix": best_ix,
        "iy": best_iy,
        "n_used": n_used,
    }


def fold_quarter(rows: list[dict[str, Any]], nx: int, ny: int) -> list[dict[str, Any]]:
    """Fold a symmetric core with mirror symmetry into its lower-left quarter.

    Quarter covers 0 <= ix < ceil(nx / 2) and 0 <= iy < ceil(ny / 2).
    Symmetry group of (ix, iy) consists of distinct pins among (ix, iy),
    (nx-1-ix, iy), (ix, ny-1-iy), and (nx-1-ix, ny-1-iy). Only included
    members are used.

    Returns one dict per quarter pin in index order (ix fastest):
      ix, iy, n_members, relative_power, relative_sigma, max_deviation.
    """
    _validate_pos_int(nx, "nx")
    _validate_pos_int(ny, "ny")
    n_total = nx * ny

    if not isinstance(rows, list):
        raise TableError(f"rows must be a list, got {type(rows).__name__}")
    if len(rows) != n_total:
        raise TableError(f"rows length ({len(rows)}) does not match nx * ny ({n_total})")

    for idx, r in enumerate(rows):
        if not isinstance(r, dict):
            raise TableError(f"rows[{idx}] must be a dict, got {type(r).__name__}")
        expected_ix = idx % nx
        expected_iy = idx // nx
        if r.get("ix") != expected_ix or r.get("iy") != expected_iy:
            raise TableError(
                f"rows must have entries in index order; mismatch at index {idx}: "
                f"expected (ix={expected_ix}, iy={expected_iy}), got (ix={r.get('ix')}, iy={r.get('iy')})"
            )
        for key in ("included", "relative_power", "relative_sigma"):
            if key not in r:
                raise TableError(f"rows[{idx}] missing key {key!r}")

    qx_max = math.ceil(nx / 2)
    qy_max = math.ceil(ny / 2)
    quarter_rows: list[dict[str, Any]] = []

    for qiy in range(qy_max):
        for qix in range(qx_max):
            candidates = [
                (qix, qiy),
                (nx - 1 - qix, qiy),
                (qix, ny - 1 - qiy),
                (nx - 1 - qix, ny - 1 - qiy),
            ]
            unique_coords: list[tuple[int, int]] = []
            for c in candidates:
                if c not in unique_coords:
                    unique_coords.append(c)

            inc_members = [
                rows[cx + nx * cy]
                for cx, cy in unique_coords
                if rows[cx + nx * cy]["included"] is True
            ]
            n_members = len(inc_members)

            if n_members == 0:
                rel_power = None
                rel_sigma = None
                max_dev = None
            else:
                powers = [float(m["relative_power"]) for m in inc_members]
                sigmas = [float(m["relative_sigma"]) for m in inc_members]
                mean_p = sum(powers) / n_members
                rel_power = mean_p
                rel_sigma = math.sqrt(sum(s ** 2 for s in sigmas)) / n_members
                if n_members == 1:
                    max_dev = 0.0
                else:
                    if mean_p > 0:
                        max_dev = max(abs(p - mean_p) for p in powers) / mean_p
                    else:
                        max_dev = 0.0

            quarter_rows.append({
                "ix": qix,
                "iy": qiy,
                "n_members": n_members,
                "relative_power": rel_power,
                "relative_sigma": rel_sigma,
                "max_deviation": max_dev,
            })

    return quarter_rows


def check_alignment(
    mesh_lower_left_cm: tuple[float, float] | list[float],
    mesh_upper_right_cm: tuple[float, float] | list[float],
    mesh_dims: tuple[int, int] | list[int],
    lattice_lower_left_cm: tuple[float, float] | list[float],
    pitch_cm: tuple[float, float] | list[float],
    lattice_dims: tuple[int, int] | list[int],
    tol_cm: float = 1e-6,
) -> list[dict[str, str]]:
    """Check whether a mesh tally grid lines up with the pin lattice.

    Mesh cell size is (upper_right - lower_left) / mesh_dims in each direction.
    Returns findings with level='error', empty list if fully aligned.
    Codes:
      'mesh-dims': mesh dimensions differ from lattice dimensions
      'mesh-pitch': mesh cell size differs from lattice pitch by > tol_cm
      'mesh-offset': lower-left coordinate offset divided by pitch is not within
                     tol_cm / pitch of an integer
    """
    m_ll = _validate_pair_numbers(mesh_lower_left_cm, "mesh_lower_left_cm")
    m_ur = _validate_pair_numbers(mesh_upper_right_cm, "mesh_upper_right_cm")
    m_dims = _validate_pair_ints(mesh_dims, "mesh_dims")
    l_ll = _validate_pair_numbers(lattice_lower_left_cm, "lattice_lower_left_cm")
    p_cm = _validate_pair_numbers(pitch_cm, "pitch_cm", strictly_positive=True)
    l_dims = _validate_pair_ints(lattice_dims, "lattice_dims")
    tol = _validate_pos_finite_num(tol_cm, "tol_cm")

    if m_ur[0] <= m_ll[0]:
        raise TableError(
            f"mesh_upper_right_cm[0] ({m_ur[0]}) must be > mesh_lower_left_cm[0] ({m_ll[0]})"
        )
    if m_ur[1] <= m_ll[1]:
        raise TableError(
            f"mesh_upper_right_cm[1] ({m_ur[1]}) must be > mesh_lower_left_cm[1] ({m_ll[1]})"
        )

    findings: list[dict[str, str]] = []

    if m_dims[0] != l_dims[0] or m_dims[1] != l_dims[1]:
        findings.append({
            "level": "error",
            "code": "mesh-dims",
            "message": (
                f"Mesh dimensions ({m_dims[0]}, {m_dims[1]}) differ from "
                f"lattice dimensions ({l_dims[0]}, {l_dims[1]})"
            ),
        })

    mesh_pitch_x = (m_ur[0] - m_ll[0]) / m_dims[0]
    mesh_pitch_y = (m_ur[1] - m_ll[1]) / m_dims[1]

    if abs(mesh_pitch_x - p_cm[0]) > tol:
        findings.append({
            "level": "error",
            "code": "mesh-pitch",
            "message": (
                f"Mesh cell size along x ({mesh_pitch_x} cm) differs from "
                f"lattice pitch ({p_cm[0]} cm) by {abs(mesh_pitch_x - p_cm[0])} cm "
                f"(tolerance {tol} cm)"
            ),
        })

    if abs(mesh_pitch_y - p_cm[1]) > tol:
        findings.append({
            "level": "error",
            "code": "mesh-pitch",
            "message": (
                f"Mesh cell size along y ({mesh_pitch_y} cm) differs from "
                f"lattice pitch ({p_cm[1]} cm) by {abs(mesh_pitch_y - p_cm[1])} cm "
                f"(tolerance {tol} cm)"
            ),
        })

    axes = [("x", 0), ("y", 1)]
    for axis_name, idx in axes:
        offset = m_ll[idx] - l_ll[idx]
        pitch = p_cm[idx]
        ratio = offset / pitch
        dev = abs(ratio - round(ratio))
        tol_frac = tol / pitch
        if dev > tol_frac:
            findings.append({
                "level": "error",
                "code": "mesh-offset",
                "message": (
                    f"Mesh lower-left along {axis_name} ({m_ll[idx]} cm) minus lattice "
                    f"lower-left ({l_ll[idx]} cm) divided by pitch ({pitch} cm) is {ratio:.6f}, "
                    f"differing from an integer by {dev:.6e} (tolerance {tol_frac:.6e})"
                ),
            })

    return findings


def csv_cell(value: Any) -> Any:
    """Sanitize a cell value against CSV formula injection.

    None produces an empty string. Strings whose first character is '=', '+',
    '-', '@', a tab ('\\t'), or a carriage return ('\\r') are returned with a
    single quote "'" prefixed. Any other string is returned unchanged.
    Non-string values (int, float, bool) are returned unchanged.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        if value and value[0] in ("=", "+", "-", "@", "\t", "\r"):
            return f"'{value}"
        return value
    return value


def csv_rows(rows: list[dict[str, Any]]) -> list[list[Any]]:
    """Format pin rows into CSV table rows with formula-injection defenses.

    Returns a header row followed by one list per row of build_rows output
    in the same order, each cell passed through csv_cell.
    """
    if not isinstance(rows, list):
        raise TableError(f"rows must be a list, got {type(rows).__name__}")

    header = [
        "ix",
        "iy",
        "x_cm",
        "y_cm",
        "value",
        "sigma",
        "included",
        "relative_power",
        "relative_sigma",
    ]
    out: list[list[Any]] = [list(header)]

    for idx, r in enumerate(rows):
        if not isinstance(r, dict):
            raise TableError(f"rows[{idx}] must be a dict, got {type(r).__name__}")
        for col in header:
            if col not in r:
                raise TableError(f"rows[{idx}] missing key {col!r}")
        out.append([csv_cell(r[col]) for col in header])

    return out
