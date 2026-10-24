"""mc_result_checks.py: quality and trustworthiness checks for OpenMC eigenvalue runs.

Evaluates a finished OpenMC eigenvalue run summary against caller-provided thresholds
with documented sources (lost particles, particles per batch, active batches, Shannon
entropy settling) and formats k with standard uncertainty per JCGM 100:2008 (GUM).
"""
import decimal
from decimal import Decimal, ROUND_HALF_UP
import math
import statistics

ALLOWED_THRESHOLDS = {
    "bias_particles_per_batch",
    "recommended_particles_per_batch",
    "min_particles_per_batch",
    "min_active_batches",
    "entropy_band_sigma",
}


def _validate_thresholds(thresholds: dict | None) -> dict:
    """Validate thresholds dict on entry or return empty dict if None."""
    if thresholds is None:
        return {}
    if not isinstance(thresholds, dict):
        raise ValueError("thresholds must be None or a dict")
    for name, entry in thresholds.items():
        if name not in ALLOWED_THRESHOLDS:
            raise ValueError(f"unknown threshold name: {name!r}")
        if not isinstance(entry, dict) or set(entry.keys()) != {"value", "source"}:
            raise ValueError(f"threshold {name!r} must be a dict with exactly 'value' and 'source' keys")
        val = entry["value"]
        if isinstance(val, bool) or not isinstance(val, (int, float)) or not math.isfinite(val) or val <= 0:
            raise ValueError(f"threshold {name!r} value must be a positive finite number")
        src = entry["source"]
        if not isinstance(src, str) or not src.strip():
            raise ValueError(f"threshold {name!r} source must be a non-empty string")
    return thresholds


def format_k(nominal: float, std: float) -> str:
    """Format nominal k and standard uncertainty per JCGM 100:2008 (GUM 7.2.6).

    Rounds std to two significant digits and nominal to the same decimal place using
    ROUND_HALF_UP. Returns '<k> +/- <std>' in plain notation. If std is not finite
    or <= 0, returns '<k> (uncertainty not available)'.
    """
    if isinstance(nominal, bool) or not isinstance(nominal, (int, float)) or not math.isfinite(nominal):
        raise ValueError("nominal k must be a finite number")
    if isinstance(std, bool) or not isinstance(std, (int, float)) or not math.isfinite(std) or std <= 0:
        return format(nominal, ".6g") + " (uncertainty not available)"

    d = Decimal(repr(float(std)))
    exp = d.adjusted() - 1
    if exp > 0:
        raise ValueError(f"uncertainty exponent {exp} > 0 is not a valid k estimate")

    q = d.quantize(Decimal(1).scaleb(exp), ROUND_HALF_UP)
    if q.adjusted() > d.adjusted():
        exp += 1
        if exp > 0:
            raise ValueError(f"uncertainty exponent {exp} > 0 is not a valid k estimate")
        q = d.quantize(Decimal(1).scaleb(exp), ROUND_HALF_UP)

    nom_d = Decimal(repr(float(nominal)))
    nom_q = nom_d.quantize(Decimal(1).scaleb(exp), ROUND_HALF_UP)
    return f"{nom_q:f} +/- {q:f}"


def entropy_settling_batch(entropy: list[float], band_sigma: float) -> int | None:
    """Estimate the 0-based batch index where Shannon entropy settled into a final band.

    This is an own heuristic, not a standard. Known limit: with unbounded noise a single
    late point outside the band moves the start later, so it errs toward 'not settled'.

    Returns None if len(entropy) < 4 or if the sample standard deviation of the final
    half is 0. Otherwise returns the smallest 0-based index i such that every j >= i
    satisfies abs(entropy[j] - mean_f) <= band_sigma * std_f. If no index qualifies,
    returns len(entropy).
    """
    if isinstance(band_sigma, bool) or not isinstance(band_sigma, (int, float)) or not math.isfinite(band_sigma) or band_sigma <= 0:
        raise ValueError("band_sigma must be a positive finite number")
    if not isinstance(entropy, list):
        raise TypeError("entropy must be a list of floats")
    for x in entropy:
        if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x):
            raise ValueError("entropy entries must be finite numbers")

    if len(entropy) < 4:
        return None

    final_half = entropy[len(entropy) // 2:]
    std_f = statistics.stdev(final_half)
    if std_f == 0.0:
        return None
    mean_f = statistics.mean(final_half)

    threshold = band_sigma * std_f
    last_violating = -1
    for j, val in enumerate(entropy):
        if abs(val - mean_f) > threshold:
            last_violating = j
    return last_violating + 1


def _batches(n: int) -> str:
    return f"{n} batch" + ("" if n == 1 else "es")


def skipped_cycles(k_generation, n_inactive: int) -> dict | None:
    """MCNP's check that enough inactive cycles were skipped (6.3 manual, section 2.8.2.8), on OpenMC's per-batch k.

    For every number of leading batches s skipped (0 to half the run) the standard deviation of the mean of the remaining k values, std(k[s:]) / sqrt(n - s), is formed; the s that
    gives the smallest one is the best skip. The manual: "If this number is larger than Ic, it may indicate that not enough inactive cycles were skipped." Adapted: MCNP uses its combined
    estimator, this uses OpenMC's batch k; MCNP cycles are OpenMC batches. Returns None when the series is too short or has no spread, else
    {"best_skip", "sem_best", "sem_at_inactive", "n_inactive"}. Measured on simulated stationary series (white noise and AR(1) with rho 0.5 and 0.8, 100 to 500 batches) it flagged 0 to 11 %
    (the 11 % for rho 0.8 over 100 batches) and a series decaying into its mean (tau = 30 batches, 20 inactive) 100 %.
    """
    k = [float(x) for x in k_generation]
    n = len(k)
    if n < 20 or n_inactive < 0 or n_inactive >= n - 10:
        return None
    sems = []
    for s in range(0, n // 2 + 1):
        tail = k[s:]
        m = sum(tail) / len(tail)
        var = sum((x - m) ** 2 for x in tail) / (len(tail) - 1)
        sems.append(math.sqrt(var / len(tail)))
    if not all(math.isfinite(x) for x in sems) or max(sems) <= 0:
        return None
    best = min(range(len(sems)), key=lambda i: (sems[i], i))
    at_ic = sems[n_inactive] if n_inactive < len(sems) else None
    return {"best_skip": best, "sem_best": sems[best], "sem_at_inactive": at_ic, "n_inactive": n_inactive}


def check_eigenvalue(summary: dict, lost_particles: int | None = None, thresholds: dict | None = None) -> list[dict]:
    """Check OpenMC eigenvalue run summary against trustworthiness criteria.

    Returns a list of findings in fixed order:
    1. run_mode check (stops early if not 'eigenvalue')
    2. k-estimate
    3. lost-particles
    4. particles-per-batch
    5. batches validation (skips 6 and 7 if batches or inactive missing)
    6. active-batches
    7. entropy-settled
    """
    if not isinstance(summary, dict):
        raise TypeError("summary must be a dict")

    thresh_map = _validate_thresholds(thresholds)

    if lost_particles is not None:
        if isinstance(lost_particles, bool) or not isinstance(lost_particles, int) or lost_particles < 0:
            raise ValueError("lost_particles must be None or a non-negative integer")

    # 1. run_mode check
    if summary.get("run_mode") != "eigenvalue":
        return [{
            "level": "info",
            "code": "not-eigenvalue",
            "message": f"run mode is {summary.get('run_mode')!r}, not 'eigenvalue'",
            "detail": {},
        }]

    findings: list[dict] = []

    # 2. k-estimate check
    keff = summary.get("keff")
    if (isinstance(keff, (list, tuple)) and len(keff) == 2 and
            isinstance(keff[0], (int, float)) and not isinstance(keff[0], bool) and math.isfinite(keff[0]) and
            isinstance(keff[1], (int, float)) and not isinstance(keff[1], bool)):
        try:
            formatted_k = format_k(keff[0], keff[1])
            detail = {"nominal": float(keff[0])}
            if math.isfinite(keff[1]):
                detail["std"] = float(keff[1])
            findings.append({
                "level": "info",
                "code": "k-estimate",
                "message": f"k = {formatted_k} (1 sigma, standard uncertainty)",
                "detail": detail,
            })
        except ValueError:
            findings.append({
                "level": "error",
                "code": "k-missing",
                "message": "the run has no usable keff",
                "detail": {},
            })
    else:
        findings.append({
            "level": "error",
            "code": "k-missing",
            "message": "the run has no usable keff",
            "detail": {},
        })

    # 3. lost-particles check
    if lost_particles is None:
        findings.append({
            "level": "not-compared",
            "code": "lost-particles",
            "message": "lost particle count not available",
            "detail": {},
        })
    elif lost_particles == 0:
        findings.append({
            "level": "info",
            "code": "lost-particles",
            "message": "0 lost particles",
            "detail": {"lost_particles": 0},
        })
    else:
        findings.append({
            "level": "warning",
            "code": "lost-particles",
            "message": f"{lost_particles} lost particles",
            "detail": {"lost_particles": lost_particles},
        })

    # 4. particles-per-batch check
    if "particles" not in summary or isinstance(summary["particles"], bool) or not isinstance(summary["particles"], int):
        findings.append({
            "level": "error",
            "code": "particles-missing",
            "message": "summary has no valid particles per batch",
            "detail": {},
        })
    else:
        particles = summary["particles"]
        bias = thresh_map.get("bias_particles_per_batch")
        recommended = thresh_map.get("recommended_particles_per_batch")
        if bias is not None and particles < bias["value"]:
            findings.append({
                "level": "warning",
                "code": "particles-per-batch",
                "message": f"{particles} particles per batch is below {bias['value']:g}: the power-iteration bias in k is not negligible (limit {bias['value']:g}, source: {bias['source']})",
                "detail": {"particles": particles, "limit": bias["value"], "tier": "bias"},
            })
        elif "min_particles_per_batch" not in thresh_map and recommended is not None:
            if particles < recommended["value"]:
                findings.append({
                    "level": "info",
                    "code": "particles-per-batch",
                    "message": f"{particles} particles per batch is below the {recommended['value']:g} recommended for a final calculation; fine for a trial run (limit {recommended['value']:g}, source: {recommended['source']})",
                    "detail": {"particles": particles, "limit": recommended["value"], "tier": "recommended"},
                })
            else:
                findings.append({
                    "level": "info",
                    "code": "particles-per-batch",
                    "message": f"{particles} particles per batch meets or exceeds the {recommended['value']:g} recommended for a final calculation (limit {recommended['value']:g}, source: {recommended['source']})",
                    "detail": {"particles": particles, "limit": recommended["value"], "tier": "recommended"},
                })
        elif "min_particles_per_batch" not in thresh_map:
            findings.append({
                "level": "not-compared",
                "code": "particles-per-batch",
                "message": "no threshold with a source was supplied for min_particles_per_batch",
                "detail": {"particles": particles},
            })
        else:
            limit = thresh_map["min_particles_per_batch"]["value"]
            source = thresh_map["min_particles_per_batch"]["source"]
            if particles < limit:
                findings.append({
                    "level": "warning",
                    "code": "particles-per-batch",
                    "message": f"{particles} particles per batch is below limit {limit} (limit {limit}, source: {source})",
                    "detail": {"particles": particles, "limit": limit},
                })
            else:
                findings.append({
                    "level": "info",
                    "code": "particles-per-batch",
                    "message": f"{particles} particles per batch meets or exceeds limit {limit} (limit {limit}, source: {source})",
                    "detail": {"particles": particles, "limit": limit},
                })

    # 5. batches validation check
    if "batches" not in summary or isinstance(summary["batches"], bool) or not isinstance(summary["batches"], int):
        findings.append({
            "level": "error",
            "code": "batches-missing",
            "message": "summary has no valid batch count",
            "detail": {},
        })
        return findings

    batches = summary["batches"]

    val = None
    if "n_inactive" in summary:
        val = summary["n_inactive"]
    elif "inactive" in summary:
        val = summary["inactive"]

    if val is None or isinstance(val, bool) or not isinstance(val, int):
        findings.append({
            "level": "error",
            "code": "inactive-missing",
            "message": "summary has no inactive batch count",
            "detail": {},
        })
        return findings

    n_inactive = val

    # 6. active-batches check
    active = batches - n_inactive
    if "min_active_batches" not in thresh_map:
        findings.append({
            "level": "not-compared",
            "code": "active-batches",
            "message": "no threshold with a source was supplied for min_active_batches",
            "detail": {"active_batches": active},
        })
    else:
        limit = thresh_map["min_active_batches"]["value"]
        source = thresh_map["min_active_batches"]["source"]
        if active < limit:
            findings.append({
                "level": "warning",
                "code": "active-batches",
                "message": f"{active} active batches is below limit {limit} (limit {limit}, source: {source})",
                "detail": {"active_batches": active, "limit": limit},
            })
        else:
            findings.append({
                "level": "info",
                "code": "active-batches",
                "message": f"{active} active batches meets or exceeds limit {limit} (limit {limit}, source: {source})",
                "detail": {"active_batches": active, "limit": limit},
            })

    # 7. entropy-settled check
    if "entropy" not in summary or summary["entropy"] is None:
        findings.append({
            "level": "not-compared",
            "code": "entropy-settled",
            "message": "no entropy series (the run had no Shannon entropy mesh)",
            "detail": {},
        })
    elif not isinstance(summary["entropy"], list) or len(summary["entropy"]) != batches:
        findings.append({
            "level": "error",
            "code": "entropy-length",
            "message": f"entropy series length does not match batch count ({batches})",
            "detail": {"entropy_length": len(summary["entropy"]) if isinstance(summary["entropy"], list) else None, "batches": batches} if isinstance(summary["entropy"], list) else {},
        })
    elif "entropy_band_sigma" not in thresh_map:
        findings.append({
            "level": "not-compared",
            "code": "entropy-settled",
            "message": "no threshold with a source was supplied for entropy_band_sigma",
            "detail": {},
        })
    else:
        band_sigma = thresh_map["entropy_band_sigma"]["value"]
        source = thresh_map["entropy_band_sigma"]["source"]
        settling_idx = entropy_settling_batch(summary["entropy"], band_sigma)
        if settling_idx is None:
            findings.append({
                "level": "not-compared",
                "code": "entropy-settled",
                "message": "entropy series too short or constant, settling cannot be judged",
                "detail": {},
            })
        elif settling_idx >= n_inactive:
            findings.append({
                "level": "warning",
                "code": "entropy-settled",
                "message": (
                    f"entropy was still outside its final band at batch {settling_idx + 1}, "
                    f"after the {n_inactive} inactive batches (limit {band_sigma}, source: {source})"
                ),
                "detail": {"index": settling_idx, "n_inactive": n_inactive},
            })
        else:
            findings.append({
                "level": "info",
                "code": "entropy-settled",
                "message": (
                    f"entropy inside its final band from batch {settling_idx + 1}, "
                    f"within the {n_inactive} inactive batches (limit {band_sigma}, source: {source})"
                ),
                "detail": {"index": settling_idx, "n_inactive": n_inactive},
            })

    # 8. skipped-cycles check (MCNP 6.3 manual 2.8.2.8: the number of skipped cycles that gives the smallest standard deviation, compared with the inactive count)
    kgen = summary.get("k_generation")
    result = None
    if isinstance(kgen, list) and len(kgen) == batches and all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) for x in kgen):
        result = skipped_cycles(kgen, n_inactive)
    if result is None:
        findings.append({
            "level": "not-compared",
            "code": "skipped-cycles",
            "message": "no usable per-batch k series (or too few batches) to judge whether enough inactive batches were skipped",
            "detail": {},
        })
    elif result["best_skip"] > n_inactive:
        findings.append({
            "level": "warning",
            "code": "skipped-cycles",
            "message": (
                f"the standard deviation of the mean k is smallest when the first {_batches(result['best_skip'])} are skipped, more than the {_batches(n_inactive)} inactive: "
                f"it may indicate that not enough inactive batches were skipped (the check of the MCNP 6.3 manual, section 2.8.2.8; it can fire by chance in a short, strongly correlated run). "
                f"Look at the entropy and k by batch."
            ),
            "detail": dict(result),
        })
    else:
        findings.append({
            "level": "info",
            "code": "skipped-cycles",
            "message": (
                f"the standard deviation of the mean k is smallest when {_batches(result['best_skip'])} {'is' if result['best_skip'] == 1 else 'are'} skipped, not more than the {_batches(n_inactive)} inactive: "
                f"consistent with enough batches skipped (MCNP 6.3 manual, section 2.8.2.8)"
            ),
            "detail": dict(result),
        })

    return findings
