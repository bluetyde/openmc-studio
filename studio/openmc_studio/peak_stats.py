"""Peak statistics and noise analysis for relative pin powers.

Provides expected normal order statistics by numerical integration and Blom
approximation, relative pin power summary metrics with exclusion filtering, and
CSV formula injection protection for spreadsheet export.
"""
from collections.abc import Iterable
import math
import statistics


def expected_max_normal(m: int) -> float:
    """Expected value of the maximum of m independent standard normal variables.

    Computed by composite Simpson's rule on [-10, 10] with 40,000 intervals
    applied to m * x * phi(x) * Phi(x)**(m - 1).

    m must be an integer >= 1 and <= 100000 (not a bool).
    """
    if isinstance(m, bool) or not isinstance(m, int):
        raise ValueError(f"m must be an integer, not {type(m).__name__}")
    if m < 1:
        raise ValueError(f"m must be >= 1 (got {m})")
    if m > 100000:
        raise ValueError(f"m must be <= 100000 (got {m})")
    if m == 1:
        return 0.0

    a = -10.0
    b = 10.0
    n = 40000
    h = (b - a) / n
    inv_sqrt_2pi = 1.0 / math.sqrt(2.0 * math.pi)
    sqrt_2 = math.sqrt(2.0)

    s_odd = 0.0
    s_even = 0.0
    for k in range(1, n, 2):
        x = a + k * h
        p = 0.5 * (1.0 + math.erf(x / sqrt_2))
        if p > 0.0:
            s_odd += x * math.exp(-0.5 * x * x) * (p ** (m - 1))

    for k in range(2, n, 2):
        x = a + k * h
        p = 0.5 * (1.0 + math.erf(x / sqrt_2))
        if p > 0.0:
            s_even += x * math.exp(-0.5 * x * x) * (p ** (m - 1))

    pa = 0.5 * (1.0 + math.erf(a / sqrt_2))
    fa = a * math.exp(-0.5 * a * a) * (pa ** (m - 1)) if pa > 0.0 else 0.0
    pb = 0.5 * (1.0 + math.erf(b / sqrt_2))
    fb = b * math.exp(-0.5 * b * b) * (pb ** (m - 1))

    total = fa + fb + 4.0 * s_odd + 2.0 * s_even
    return m * inv_sqrt_2pi * total * (h / 3.0)


def expected_max_normal_blom(m: int) -> float:
    """Blom (1958) approximation for expected maximum of m standard normal variables.

    Approximates E[max] as Phi^-1((m - 0.375) / (m + 0.25)) using
    statistics.NormalDist().inv_cdf.

    m must be an integer >= 1 (not a bool).
    """
    if isinstance(m, bool) or not isinstance(m, int):
        raise ValueError(f"m must be an integer, not {type(m).__name__}")
    if m < 1:
        raise ValueError(f"m must be >= 1 (got {m})")
    if m == 1:
        return 0.0
    p = (m - 0.375) / (m + 0.25)
    return statistics.NormalDist().inv_cdf(p)


def peaking_summary(values, sigmas, excluded=()) -> dict:
    """Summary of relative pin powers and statistical noise allowance.

    Parameters:
      values: list or tuple of relative pin powers (floats or ints, finite, not bools).
      sigmas: list or tuple of 1-sigma uncertainties (non-negative, same length).
      excluded: iterable of indices of pins to leave out.

    noise_allowance is how much noise alone would be expected to lift the
    largest of n pins above their common true value if all n true values
    were equal. It shows the size of the effect. It is NOT a correction to
    subtract from max, and for pins whose true powers differ the real lift
    is smaller.

    Returns a dict with:
      n_total, n_used, n_excluded, mean, max, max_index, peaking_factor,
      noise_allowance, noise_allowance_relative.
    """
    if not isinstance(values, (list, tuple)):
        raise ValueError(f"values must be a list or tuple (got {type(values).__name__})")
    if not isinstance(sigmas, (list, tuple)):
        raise ValueError(f"sigmas must be a list or tuple (got {type(sigmas).__name__})")
    if len(values) == 0:
        raise ValueError("values cannot be empty")
    if len(values) != len(sigmas):
        raise ValueError(
            f"values and sigmas must have the same length (got {len(values)} vs {len(sigmas)})"
        )

    for idx, v in enumerate(values):
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            raise ValueError(f"values[{idx}] must be a finite number, not a bool (got {v!r})")

    for idx, s in enumerate(sigmas):
        if isinstance(s, bool) or not isinstance(s, (int, float)) or not math.isfinite(s):
            raise ValueError(f"sigmas[{idx}] must be a finite number, not a bool (got {s!r})")
        if s < 0:
            raise ValueError(f"sigmas[{idx}] must be >= 0 (got {s})")

    if isinstance(excluded, (str, bytes, bool)) or not isinstance(excluded, Iterable):
        raise ValueError(f"excluded must be an iterable of indices (got {type(excluded).__name__})")

    excluded_list = list(excluded)
    for idx in excluded_list:
        if isinstance(idx, bool) or not isinstance(idx, int):
            raise ValueError(f"excluded indices must be ints, not bools (got {type(idx).__name__})")
        if idx < 0 or idx >= len(values):
            raise ValueError(f"excluded index {idx} out of range [0, {len(values) - 1}]")

    excluded_set = set(excluded_list)
    n_total = len(values)
    n_excluded = len(excluded_set)
    used = [i for i in range(n_total) if i not in excluded_set]
    n_used = len(used)

    if n_used == 0:
        raise ValueError("all pins are excluded; at least one pin must remain")

    mean = math.fsum(values[i] for i in used) / n_used
    if mean <= 0:
        raise ValueError(f"mean of used pin powers must be > 0 (got {mean})")

    max_index = max(used, key=lambda i: values[i])
    max_val = values[max_index]
    peaking_factor = max_val / mean

    rms_sigma = math.sqrt(math.fsum(sigmas[i] ** 2 for i in used) / n_used)
    noise_allowance = rms_sigma * expected_max_normal(n_used)
    noise_allowance_relative = noise_allowance / mean

    return {
        "n_total": n_total,
        "n_used": n_used,
        "n_excluded": n_excluded,
        "mean": mean,
        "max": max_val,
        "max_index": max_index,
        "peaking_factor": peaking_factor,
        "noise_allowance": noise_allowance,
        "noise_allowance_relative": noise_allowance_relative,
    }


def csv_safe_cell(value):
    """Sanitize a cell value for safe export to CSV files opened by spreadsheets.

    A leading '=', '+', '-', '@', '\t', or '\r' on string values is prefixed
    with a single quote (') to mitigate spreadsheet formula injection.
    Non-string values are returned unchanged, and None returns an empty string.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        if value and value[0] in ("=", "+", "-", "@", "\t", "\r"):
            return "'" + value
        return value
    return value
