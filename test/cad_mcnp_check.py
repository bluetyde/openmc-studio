"""MCNP side of the stage-5 parity gate (test/test_cad_mcnp_parity.cjs).

For each case, the runnable MCNP deck the companion exporter wrote is parsed with
MontePy and every FreeCAD truth point is located in it with the exporter's own
deck locator. MCNP cell n is OpenMC cell n (the exporter keeps OpenMC's ids), so
each point's MCNP cell maps to a source solid through Studio's owner list. Every
point must be in exactly one MCNP cell and that cell must belong to the solid
FreeCAD says contains it - or be the World cell, outside and inside holes.

This compares the deck with the CAD model directly, at points concentrated in
each solid, so a small or tilted component can't escape it the way it could
escape uniform sampling of a large world.

Usage: OPENMC_MCNP_PROJECT=<exporter> python cad_mcnp_check.py CASES.json -> JSON verdict
"""
import json
import os
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(os.environ["OPENMC_MCNP_PROJECT"]) / "src"))
import geometry_check as gc  # noqa: E402
from validate_deck import _read_deck  # noqa: E402


def check(case):
    deck = gc._Deck(_read_deck(case["deck"]))
    P = np.array([t["p_cm"] for t in case["truth"]], dtype=float)
    leaf = deck.locate(P)
    owners = case["owners"]  # OpenMC (= MCNP) cell number -> source key, or "world"
    counts = {"lost": 0, "overlap": 0, "near": 0, "mismatch": 0, "ok": 0}
    examples = []
    for t, n in zip(case["truth"], leaf):
        want = t["key"] if t["key"] is not None else "world"
        if n == gc.NEAR:
            counts["near"] += 1
            continue
        if n in (gc.LOST, gc.OVERLAP):
            counts["lost" if n == gc.LOST else "overlap"] += 1
            bad = {"p": t["p_cm"], "mcnp": "lost" if n == gc.LOST else "overlap", "want": want}
        elif owners.get(str(int(n))) != want:
            counts["mismatch"] += 1
            bad = {"p": t["p_cm"], "mcnp_cell": int(n), "got": owners.get(str(int(n))), "want": want}
        else:
            counts["ok"] += 1
            continue
        if len(examples) < 5:
            examples.append(bad)
    holes = [t for t in case["truth"] if t.get("probe") == "hole"]
    return {**counts, "points": len(P), "solid_points": sum(t["key"] is not None for t in case["truth"]),
            "hole_probes": len(holes), "examples": examples}


def main():
    cases = json.loads(Path(sys.argv[1]).read_text())
    out = {}
    for name, case in cases.items():
        try:
            out[name] = check(case)
        except Exception as exc:  # noqa: BLE001
            out[name] = {"error": f"{type(exc).__name__}: {exc}"}
    print(json.dumps(out))


if __name__ == "__main__":
    main()
