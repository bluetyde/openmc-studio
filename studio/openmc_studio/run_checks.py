"""What the server adds to a finished run: result checks, a figure of merit, a record check and the one-page report.

Glue between a run folder and four modules that know nothing about folders: mc_result_checks (findings), variance_stats
(figure of merit), rerun_check (the stored provenance against today) and run_report (the page). Limits come with a named
source or are not applied: a check whose limit has no source says "not compared".
"""
import json
import re
from pathlib import Path

from . import mc_result_checks, rerun_check, run_report, variance_stats

# Only limits with a source in hand are set. The MCNP manual gives a number for histories per cycle; neither it nor OpenMC's
# documentation (not available offline when this was written) gives one for active batches or the entropy plateau, so those two
# stay "not compared" until a source is found.
THRESHOLDS = {
    "min_particles_per_batch": {
        "value": 5000,
        "source": "MCNP 6.3 manual (LA-UR-22-30006 Rev. 1), section 2.8.1: a final calculation uses histories per cycle \"of 5000 or more\"",
    },
}

# OpenMC's lost-particle lines in a run log; the same patterns as the geometry check uses.
LOST_RE = re.compile(r"(could not be located|was lost|lost particle)", re.I)


def lost_particles(run_dir):
    """Number of lost-particle lines in the run's log, or None when there is no log to read."""
    log = Path(run_dir) / "run.log"
    try:
        text = log.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    return sum(1 for line in text.splitlines() if LOST_RE.search(line))


def run_seconds(run_dir, summary=None):
    """The run's transport time in seconds: OpenMC's own total from the statepoint, else the wall time the record kept."""
    t = (summary or {}).get("runtime_s")
    if isinstance(t, (int, float)) and t > 0:
        return float(t)
    try:
        rec = json.loads((Path(run_dir) / "provenance.json").read_text(encoding="utf-8"))
        t = (rec.get("outcome") or {}).get("seconds")
    except (OSError, ValueError):
        return None
    return float(t) if isinstance(t, (int, float)) and t > 0 else None


def add_fom(results, seconds):
    """Put `fom` (1 / (R^2 T)) on every table row with a relative error, in place. No time, no figure."""
    if seconds is None:
        return
    for t in results.get("tallies") or []:
        for row in t.get("rows") or []:
            r = row.get("rel_err")
            if isinstance(r, (int, float)) and r > 0:
                try:
                    row["fom"] = variance_stats.figure_of_merit(r, seconds)
                except variance_stats.VarianceError:
                    pass


def findings(run_dir, summary):
    """The result checks for a run's summary (eigenvalue runs only; a fixed-source run answers with one info line)."""
    if not summary:
        return []
    return mc_result_checks.check_eigenvalue(summary, lost_particles(run_dir), THRESHOLDS)


def augment(run_dir, results):
    """Add `findings` and the figure of merit to the dict results.load returned."""
    summary = results.get("summary")
    results["findings"] = findings(run_dir, summary)
    add_fom(results, run_seconds(run_dir, summary))
    return results


def record_check(run_dir):
    """rerun_check against today's environment, as a dict."""
    return rerun_check.check(run_dir)


def report_html(run_dir, results):
    """The one-page report for a run: its provenance record, its summary and its findings."""
    try:
        record = json.loads((Path(run_dir) / "provenance.json").read_text(encoding="utf-8"))
        if not isinstance(record, dict):
            record = {"error": "provenance.json is not an object"}
    except (OSError, ValueError) as exc:
        record = {"error": f"no usable provenance.json: {exc}"}
    rep = run_report.build_report(record, results.get("summary"), results.get("findings"))
    return run_report.render_html(rep)
