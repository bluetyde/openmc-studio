"""boron_search.py: reactivity worth and critical boron search for Monte Carlo runs.

Provides pure arithmetic for soluble boron studies: conversion of k to reactivity in pcm,
boron reactivity worth (pcm/ppm) with propagated or regression uncertainty, and Illinois
regula falsi search for critical boron concentration without chasing Monte Carlo noise.
"""
import math

__all__ = ["SearchError", "reactivity_pcm", "boron_worth", "find_critical"]


class SearchError(ValueError):
    """Raised when an argument to a boron search function is invalid."""


def _is_finite_num(val) -> bool:
    """Return True if val is a finite real number (not bool, nan, or inf)."""
    return not isinstance(val, bool) and isinstance(val, (int, float)) and math.isfinite(val)


def reactivity_pcm(k: float, sigma_k: float) -> tuple[float, float]:
    """Calculate reactivity in pcm and its propagated uncertainty.

    Reactivity is rho = (k - 1) / k, so in pcm rho_pcm = 1e5 * (k - 1) / k.
    By first-order propagation, sigma_rho_pcm = 1e5 * sigma_k / k**2.

    Parameters:
        k: Multiplication factor, finite and > 0.
        sigma_k: Standard deviation on k, finite and >= 0.

    Returns:
        (rho_pcm, sigma_rho_pcm) as floats.

    Raises:
        SearchError: If k or sigma_k is not a valid finite number in range.
    """
    if not _is_finite_num(k) or k <= 0:
        raise SearchError(f"k must be finite and > 0, got {k!r}")
    if not _is_finite_num(sigma_k) or sigma_k < 0:
        raise SearchError(f"sigma_k must be finite and >= 0, got {sigma_k!r}")
    k_float = float(k)
    rho_pcm = 1e5 * (k_float - 1.0) / k_float
    sigma_rho_pcm = 1e5 * float(sigma_k) / (k_float ** 2)
    return (float(rho_pcm), float(sigma_rho_pcm))


def boron_worth(points: list[tuple[float, float, float]]) -> dict:
    """Calculate boron reactivity worth (pcm per ppm) and uncertainty.

    Converts each (ppm, k, sigma_k) point to (ppm, rho_pcm, sigma_rho_pcm).
    With 2 points, calculates two-point slope and propagated standard error:
        slope = (rho2 - rho1) / (c2 - c1)
        sigma_slope = sqrt(s1**2 + s2**2) / abs(c2 - c1)
    With 3+ points, performs ordinary least squares regression of rho_pcm on ppm:
        slope = Sxy / Sxx
        s2 = RSS / (n - 2)
        sigma_slope = sqrt(s2 / Sxx) (0.0 for collinear points)

    Parameters:
        points: List of at least 2 distinct (ppm, k, sigma_k) triples with ppm >= 0,
            k > 0, and sigma_k >= 0.

    Returns:
        Dictionary with keys:
            "slope_pcm_per_ppm": float
            "sigma_pcm_per_ppm": float
            "n_points": int
            "method": "two-point" or "least-squares"

    Raises:
        SearchError: If points is malformed, has < 2 points, duplicate ppm values,
            or invalid coordinates.
    """
    if not isinstance(points, (list, tuple)):
        raise SearchError(f"points must be a list of triples, got {type(points).__name__}")
    if len(points) < 2:
        raise SearchError(f"points must contain at least 2 points, got {len(points)}")

    converted: list[tuple[float, float, float]] = []
    seen_ppm: set[float] = set()

    for item in points:
        if not isinstance(item, (list, tuple)) or len(item) != 3:
            raise SearchError(f"points entry must be a (ppm, k, sigma_k) triple, got {item!r}")
        ppm, k, sigma_k = item
        if not _is_finite_num(ppm) or ppm < 0:
            raise SearchError(f"points ppm must be finite and >= 0, got {ppm!r}")
        if not _is_finite_num(k) or k <= 0:
            raise SearchError(f"points k must be finite and > 0, got {k!r}")
        if not _is_finite_num(sigma_k) or sigma_k < 0:
            raise SearchError(f"points sigma_k must be finite and >= 0, got {sigma_k!r}")

        ppm_float = float(ppm)
        if ppm_float in seen_ppm:
            raise SearchError(f"points contains duplicate ppm: {ppm}")
        seen_ppm.add(ppm_float)

        rho, s_rho = reactivity_pcm(k, sigma_k)
        converted.append((ppm_float, rho, s_rho))

    if len(converted) == 2:
        (c1, rho1, s1), (c2, rho2, s2) = converted
        slope = (rho2 - rho1) / (c2 - c1)
        sigma_slope = math.sqrt(s1 ** 2 + s2 ** 2) / abs(c2 - c1)
        return {
            "slope_pcm_per_ppm": float(slope),
            "sigma_pcm_per_ppm": float(sigma_slope),
            "n_points": 2,
            "method": "two-point",
        }

    n = len(converted)
    xs = [pt[0] for pt in converted]
    ys = [pt[1] for pt in converted]
    x_bar = sum(xs) / n
    y_bar = sum(ys) / n
    sxx = sum((x - x_bar) ** 2 for x in xs)
    sxy = sum((x - x_bar) * (y - y_bar) for x, y in zip(xs, ys))
    if sxx == 0.0:
        raise SearchError("points have zero variance in ppm")
    slope = sxy / sxx
    intercept = y_bar - slope * x_bar
    rss = max(0.0, sum((y - (intercept + slope * x)) ** 2 for x, y in zip(xs, ys)))
    if rss == 0.0:
        sigma_slope = 0.0
    else:
        s2 = rss / (n - 2)
        sigma_slope = math.sqrt(s2 / sxx)
        if sigma_slope < 1e-12:
            sigma_slope = 0.0

    return {
        "slope_pcm_per_ppm": float(slope),
        "sigma_pcm_per_ppm": float(sigma_slope),
        "n_points": n,
        "method": "least-squares",
    }


def find_critical(
    run,
    target_k: float,
    lo: float,
    hi: float,
    tolerance_sigma: float = 2.0,
    max_runs: int = 12,
) -> dict:
    """Search for the boron concentration giving target_k without chasing noise.

    Uses the Illinois variant of regula falsi within bracket [lo, hi], stopping
    when |k - target_k| <= tolerance_sigma * sigma_k (or 1e-12 if sigma_k == 0).

    Parameters:
        run: Callable run(x) -> (k, sigma_k) for boron concentration x.
        target_k: Target multiplication factor, finite and > 0.
        lo: Lower bound of search bracket, finite.
        hi: Upper bound of search bracket, finite, lo < hi.
        tolerance_sigma: Statistical tolerance multiplier, finite and > 0 (default 2.0).
        max_runs: Maximum number of calls to run, integer >= 2 (default 12).

    Returns:
        Dictionary with keys:
            "status": "converged", "not-bracketed", "bracket-collapsed", or "max-runs"
            "x": float (ppm concentration)
            "k": float (evaluated k)
            "sigma_k": float (uncertainty on k)
            "runs": list of (x, k, sigma_k) tuples in order evaluated
            "interval": [x - dx, x + dx] or None

    Raises:
        SearchError: If any argument is invalid, or if run(x) returns invalid output.
    """
    if not callable(run):
        raise SearchError(f"run must be callable, got {type(run).__name__}")
    if not _is_finite_num(target_k) or target_k <= 0:
        raise SearchError(f"target_k must be finite and > 0, got {target_k!r}")
    if not _is_finite_num(lo):
        raise SearchError(f"lo must be finite, got {lo!r}")
    if not _is_finite_num(hi):
        raise SearchError(f"hi must be finite, got {hi!r}")
    if lo >= hi:
        raise SearchError(f"lo ({lo}) must be strictly less than hi ({hi})")
    if not _is_finite_num(tolerance_sigma) or tolerance_sigma <= 0:
        raise SearchError(f"tolerance_sigma must be finite and > 0, got {tolerance_sigma!r}")
    if isinstance(max_runs, bool) or not isinstance(max_runs, int) or max_runs < 2:
        raise SearchError(f"max_runs must be an integer >= 2, got {max_runs!r}")

    def _call_run(x_val: float) -> tuple[float, float]:
        res = run(x_val)
        if not isinstance(res, (tuple, list)) or len(res) != 2:
            raise SearchError(f"run at x={x_val!r} must return a (k, sigma_k) pair, got {res!r}")
        k_val, s_val = res
        if not _is_finite_num(k_val) or k_val <= 0:
            raise SearchError(f"run at x={x_val!r} returned invalid k={k_val!r}, must be finite and > 0")
        if not _is_finite_num(s_val) or s_val < 0:
            raise SearchError(f"run at x={x_val!r} returned invalid sigma_k={s_val!r}, must be finite and >= 0")
        return float(k_val), float(s_val)

    def _is_converged(k_val: float, s_val: float) -> bool:
        tol = 1e-12 if s_val == 0.0 else tolerance_sigma * s_val
        return abs(k_val - target_k) <= tol

    def _best_point(pts: list[tuple[float, float, float]]) -> tuple[float, float, float]:
        return min(pts, key=lambda pt: abs(pt[1] - target_k) / max(pt[2], 1e-12))

    def _make_interval(center_x: float, s_val: float, slp: float) -> list[float] | None:
        if slp == 0.0:
            return None
        dx = s_val / abs(slp)
        return [center_x - dx, center_x + dx]

    # Step 1: Evaluate lo and hi
    k_lo, s_lo = _call_run(lo)
    runs = [(float(lo), k_lo, s_lo)]
    k_hi, s_hi = _call_run(hi)
    runs.append((float(hi), k_hi, s_hi))

    # Step 2: Test convergence at the ends
    lo_conv = _is_converged(k_lo, s_lo)
    hi_conv = _is_converged(k_hi, s_hi)
    if lo_conv or hi_conv:
        if lo_conv and hi_conv:
            score_lo = abs(k_lo - target_k) / max(s_lo, 1e-12)
            score_hi = abs(k_hi - target_k) / max(s_hi, 1e-12)
            bx, bk, bs = (lo, k_lo, s_lo) if score_lo <= score_hi else (hi, k_hi, s_hi)
        elif lo_conv:
            bx, bk, bs = (lo, k_lo, s_lo)
        else:
            bx, bk, bs = (hi, k_hi, s_hi)

        end_slope = (k_hi - k_lo) / (hi - lo)
        return {
            "status": "converged",
            "x": float(bx),
            "k": float(bk),
            "sigma_k": float(bs),
            "runs": runs,
            "interval": _make_interval(bx, bs, end_slope),
        }

    # Step 1 continued: Test bracketing
    min_k = min(k_lo, k_hi)
    max_k = max(k_lo, k_hi)
    if not (min_k <= target_k <= max_k):
        bx, bk, bs = _best_point(runs)
        return {
            "status": "not-bracketed",
            "x": float(bx),
            "k": float(bk),
            "sigma_k": float(bs),
            "runs": runs,
            "interval": None,
        }

    # If max_runs == 2, cannot iterate further
    if len(runs) >= max_runs:
        bx, bk, bs = _best_point(runs)
        end_slope = (k_hi - k_lo) / (hi - lo)
        return {
            "status": "max-runs",
            "x": float(bx),
            "k": float(bk),
            "sigma_k": float(bs),
            "runs": runs,
            "interval": _make_interval(bx, bs, end_slope),
        }

    # Step 3: Iterate with Illinois regula falsi
    a = float(lo)
    b = float(hi)
    fa = k_lo - target_k
    fb = k_hi - target_k
    wa = fa
    wb = fb
    side = 0
    orig_width = float(hi - lo)

    while True:
        if (b - a) < 1e-9 * orig_width:
            status = "bracket-collapsed"
            break
        if len(runs) >= max_runs:
            status = "max-runs"
            break

        denom = wb - wa
        x = (a * wb - b * wa) / denom
        if x <= a or x >= b:
            x = 0.5 * (a + b)

        k, sigma_k = _call_run(x)
        runs.append((float(x), k, sigma_k))
        fx = k - target_k

        if _is_converged(k, sigma_k):
            bracket_slope = (fb - fa) / (b - a)
            return {
                "status": "converged",
                "x": float(x),
                "k": float(k),
                "sigma_k": float(sigma_k),
                "runs": runs,
                "interval": _make_interval(x, sigma_k, bracket_slope),
            }

        if fx * wb > 0:
            b, fb, wb = x, fx, fx
            if side == -1:
                wa = wa / 2.0
            side = -1
        elif fx * wa > 0:
            a, fa, wa = x, fx, fx
            if side == +1:
                wb = wb / 2.0
            side = +1
        else:  # fx == 0 exactly
            bracket_slope = (fb - fa) / (b - a)
            return {
                "status": "converged",
                "x": float(x),
                "k": float(k),
                "sigma_k": float(sigma_k),
                "runs": runs,
                "interval": _make_interval(x, sigma_k, bracket_slope),
            }

    bx, bk, bs = _best_point(runs)
    final_slope = (fb - fa) / (b - a)
    return {
        "status": status,
        "x": float(bx),
        "k": float(bk),
        "sigma_k": float(bs),
        "runs": runs,
        "interval": _make_interval(bx, bs, final_slope),
    }
