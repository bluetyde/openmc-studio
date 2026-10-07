"""variance_stats.py: pure arithmetic for judging variance-reduction runs against analog runs.

Calculates figure of merit (FOM), FOM ratio, estimated histories needed to reach a target
relative error, bin-by-bin z-score comparisons, and unbiasedness summaries. Standard
library only; never runs OpenMC.
"""
import math

__all__ = [
    "VarianceError",
    "figure_of_merit",
    "fom_ratio",
    "histories_needed",
    "compare_bins",
    "unbiasedness_summary",
]


class VarianceError(ValueError):
    """Raised for invalid inputs to variance statistics functions, naming the argument."""
    pass


def _require_positive_finite(name: str, val) -> float:
    """Validate that val is a finite number > 0 and not a boolean."""
    if isinstance(val, bool) or not isinstance(val, (int, float)) or not math.isfinite(val) or val <= 0:
        raise VarianceError(f"'{name}' must be a finite number > 0, got {val!r}")
    return float(val)


def figure_of_merit(rel_error, time_s) -> float:
    """Calculate figure of merit FOM = 1 / (rel_error**2 * time_s)."""
    r = _require_positive_finite("rel_error", rel_error)
    t = _require_positive_finite("time_s", time_s)
    return 1.0 / (r * r * t)


def fom_ratio(fom_windowed, fom_analog) -> float:
    """Calculate the ratio fom_windowed / fom_analog."""
    fw = _require_positive_finite("fom_windowed", fom_windowed)
    fa = _require_positive_finite("fom_analog", fom_analog)
    return fw / fa


def histories_needed(rel_error_now, histories_now, rel_error_target) -> float:
    """Calculate estimated histories N_t = N_0 * (R_0 / R_t)**2 needed to reach target error."""
    r0 = _require_positive_finite("rel_error_now", rel_error_now)
    n0 = _require_positive_finite("histories_now", histories_now)
    rt = _require_positive_finite("rel_error_target", rel_error_target)
    return float(n0 * (r0 / rt) ** 2)


def compare_bins(analog, windowed) -> list[dict]:
    """Compare bin-by-bin results between analog and windowed runs.

    analog and windowed must be lists of (mean, sigma) pairs of the same non-zero length.
    Returns a list of dicts: {"bin": i, "analog": ma, "windowed": mw, "z": z, "empty": bool}.
    """
    if not isinstance(analog, list):
        raise VarianceError(f"'analog' must be a list, got {type(analog).__name__}")
    if not isinstance(windowed, list):
        raise VarianceError(f"'windowed' must be a list, got {type(windowed).__name__}")
    if len(analog) == 0:
        raise VarianceError("'analog' must contain at least 1 bin")
    if len(windowed) == 0:
        raise VarianceError("'windowed' must contain at least 1 bin")
    if len(analog) != len(windowed):
        raise VarianceError(f"'analog' and 'windowed' must have the same length ({len(analog)} != {len(windowed)})")

    bins = []
    for i, (pair_a, pair_w) in enumerate(zip(analog, windowed)):
        if not isinstance(pair_a, (list, tuple)) or len(pair_a) != 2:
            raise VarianceError(f"'analog' item at bin {i} must be a (mean, sigma) pair of length 2")
        if not isinstance(pair_w, (list, tuple)) or len(pair_w) != 2:
            raise VarianceError(f"'windowed' item at bin {i} must be a (mean, sigma) pair of length 2")

        ma, sa = pair_a
        mw, sw = pair_w

        if isinstance(ma, bool) or not isinstance(ma, (int, float)) or not math.isfinite(ma):
            raise VarianceError(f"'analog' mean at bin {i} must be a finite number, got {ma!r}")
        if isinstance(sa, bool) or not isinstance(sa, (int, float)) or not math.isfinite(sa) or sa < 0:
            raise VarianceError(f"'analog' sigma at bin {i} must be a finite number >= 0, got {sa!r}")

        if isinstance(mw, bool) or not isinstance(mw, (int, float)) or not math.isfinite(mw):
            raise VarianceError(f"'windowed' mean at bin {i} must be a finite number, got {mw!r}")
        if isinstance(sw, bool) or not isinstance(sw, (int, float)) or not math.isfinite(sw) or sw < 0:
            raise VarianceError(f"'windowed' sigma at bin {i} must be a finite number >= 0, got {sw!r}")

        ma = float(ma)
        sa = float(sa)
        mw = float(mw)
        sw = float(sw)

        empty = (ma == 0.0 and mw == 0.0 and sa == 0.0 and sw == 0.0)
        if empty:
            z = 0.0
        else:
            comb = math.sqrt(sa * sa + sw * sw)
            if comb == 0.0:
                if mw == ma:
                    z = 0.0
                elif mw > ma:
                    z = math.inf
                else:
                    z = -math.inf
            else:
                z = (mw - ma) / comb

        bins.append({
            "bin": i,
            "analog": ma,
            "windowed": mw,
            "z": z,
            "empty": empty,
        })

    return bins


def _validate_limits(limits):
    """Validate limits dictionary format and values."""
    if limits is None:
        return
    if not isinstance(limits, dict):
        raise VarianceError(f"'limits' must be None or a dict, got {type(limits).__name__}")
    allowed = {"rms_z_limit", "max_abs_z_limit"}
    for k, entry in limits.items():
        if k not in allowed:
            raise VarianceError(f"unknown limit name {k!r} in 'limits'")
        if not isinstance(entry, dict):
            raise VarianceError(f"limit entry {k!r} in 'limits' must be a dict")
        if set(entry.keys()) != {"value", "source"}:
            raise VarianceError(f"limit entry {k!r} in 'limits' must have exactly keys 'value' and 'source'")
        val = entry["value"]
        if isinstance(val, bool) or not isinstance(val, (int, float)) or not math.isfinite(val) or val <= 0:
            raise VarianceError(f"limit {k!r} 'value' in 'limits' must be a finite number > 0, got {val!r}")
        src = entry["source"]
        if not isinstance(src, str) or not src.strip():
            raise VarianceError(f"limit {k!r} 'source' in 'limits' must be a non-empty string, got {src!r}")


def unbiasedness_summary(analog, windowed, limits=None) -> dict:
    """Summarize unbiasedness across non-empty bins and compare against limits.

    Returns dict with keys:
      n_bins, n_used, mean_z, rms_z, max_abs_z, fraction_within_2, fraction_within_3,
      verdict, reasons
    """
    _validate_limits(limits)
    bins = compare_bins(analog, windowed)
    used_bins = [b for b in bins if not b["empty"]]
    if not used_bins:
        raise VarianceError("all bins are empty in 'analog' and 'windowed'")

    n_bins = len(bins)
    n_used = len(used_bins)
    z_vals = [b["z"] for b in used_bins]

    mean_z = sum(z_vals) / n_used
    rms_z = math.sqrt(sum(z * z for z in z_vals) / n_used)
    max_abs_z = max(abs(z) for z in z_vals)
    fraction_within_2 = sum(1 for z in z_vals if abs(z) <= 2.0) / n_used
    fraction_within_3 = sum(1 for z in z_vals if abs(z) <= 3.0) / n_used

    has_inf = any(math.isinf(z) for z in z_vals)

    if limits is None or len(limits) == 0:
        verdict = "not-compared"
        reasons = ["no limit with a source was supplied"]
    else:
        reasons = []
        if "rms_z_limit" in limits:
            lim_val = limits["rms_z_limit"]["value"]
            lim_src = limits["rms_z_limit"]["source"]
            if not (rms_z <= lim_val):
                reasons.append(
                    f"rms_z_limit {lim_val} exceeded by measured rms_z {rms_z} (source: {lim_src})"
                )
        if "max_abs_z_limit" in limits:
            lim_val = limits["max_abs_z_limit"]["value"]
            lim_src = limits["max_abs_z_limit"]["source"]
            if not (max_abs_z <= lim_val):
                reasons.append(
                    f"max_abs_z_limit {lim_val} exceeded by measured max_abs_z {max_abs_z} (source: {lim_src})"
                )

        if has_inf and not reasons:
            reasons.append("infinite z encountered")

        if reasons or has_inf:
            verdict = "inconsistent"
        else:
            verdict = "consistent"

    return {
        "n_bins": n_bins,
        "n_used": n_used,
        "mean_z": mean_z,
        "rms_z": rms_z,
        "max_abs_z": max_abs_z,
        "fraction_within_2": fraction_within_2,
        "fraction_within_3": fraction_within_3,
        "verdict": verdict,
        "reasons": reasons,
    }
