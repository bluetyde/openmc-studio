"""OpenMC side of the stage-3 gate (test/test_cad_csg_gate.cjs). Run with OpenMC's Python.

For each case: build the geometry from the model.py Studio generated (runpy; the
model's own `if __name__ == "__main__"` block, which would run a simulation, is
not entered), then ask OpenMC which cells contain each truth point. Every point
must be in exactly ONE cell - no gaps, no overlaps - and that cell must be:
- a cell of the component made from the solid FreeCAD says contains the point, or
- the World cell, when FreeCAD says no solid does (outside, or inside a hole).

This executes Studio's generated model.py (the product), never GEOUNED output.
Usage: python cad_csg_check.py CASES.json   (written by the gate) -> prints a JSON verdict
"""
import json
import runpy
import sys
import warnings
from pathlib import Path


def check(case):
    import openmc
    warnings.simplefilter("ignore")
    # Studio's owner list follows creation order, which is OpenMC's auto-ID order - but
    # only from a fresh count, so reset it for every model built in this process.
    openmc.reset_auto_ids()
    ns = runpy.run_path(case["model"], run_name="studio_gate")
    cells = sorted(ns["geometry"].get_all_cells().values(), key=lambda c: c.id)
    owners = case["owners"]  # OpenMC cell id -> source key, or "world"
    examples, mismatch, overlaps, gaps = [], 0, 0, 0
    for t in case["truth"]:
        p = tuple(t["p_cm"])
        inside = [c for c in cells if p in c.region]
        want = t["key"] if t["key"] is not None else "world"
        if len(inside) != 1:
            overlaps += len(inside) > 1
            gaps += not inside
            bad = {"p": p, "cells": [c.name for c in inside], "want": want}
        elif owners.get(str(inside[0].id)) != want:
            mismatch += 1
            bad = {"p": p, "cell": inside[0].name, "got": owners.get(str(inside[0].id)), "want": want}
        else:
            continue
        if len(examples) < 5:
            examples.append(bad)
    return {"points": len(case["truth"]), "solid_points": sum(t["key"] is not None for t in case["truth"]),
            "mismatch": mismatch, "overlaps": overlaps, "gaps": gaps, "cells": len(cells), "examples": examples}


def main():
    cases = json.loads(Path(sys.argv[1]).read_text())
    verdict = {}
    for name, case in cases.items():
        try:
            verdict[name] = check(case)
        except Exception as exc:  # noqa: BLE001 - report per case
            verdict[name] = {"error": f"{type(exc).__name__}: {exc}"}
    print(json.dumps(verdict))


if __name__ == "__main__":
    main()
