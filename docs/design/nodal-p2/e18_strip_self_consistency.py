"""P2, experiment E18: does the nodal solve reproduce the strip it was made from?

E17 found that giving the reflector more sets of constants makes the core's k worse, so the remaining reflector error is not a matter of how many sets. The strip is the one place the
whole reflector treatment can be tested against its own Monte Carlo: the row [B B A | R] (reflective at the fuel end, vacuum beyond the reflector, y and z reflective) was run in OpenMC
(E13, data/pieces.npz: k_stripZ) and tallied in CASMO-25 for the constants of each node (stripZ_B, stripZ_A for the fuel nodes, reflZ for the reflector node, all condensed to two groups with
the flux-averaged D). Solving the same four nodes with those constants should give the strip's k if homogenised constants and diffusion were enough. The difference is the method's error at
the fuel/reflector interface, with no core and no choice of fuel source in it. Also tried: the fuel nodes' constants taken from the infinite lattices (E15's corrected fuel) instead.
Both nodal kernels, no factors.

    PYTHONPATH=studio:docs/design/nodal-p2 python docs/design/nodal-p2/e18_strip_self_consistency.py
"""
from pathlib import Path

import numpy as np

from openmc_studio import nodal

DATA = Path(__file__).resolve().parent / "data"
P = np.load(DATA / "pieces.npz")
FINE = np.load(DATA / "fine_inf.npz")
FIELDS = ("D", "absorption", "nu_fission", "kappa_fission", "chi", "scatter", "inv_velocity")
ASM, HZ = 6.3, 1.0


def piece(name):
    return {f: np.asarray(P[f"{name}__{f}"], float).reshape(-1) for f in FIELDS}


def fine(tag):
    return {f: np.asarray(FINE[f"{tag}__{f}"], float) for f in FIELDS + ("flux",)}


def solve(layout, cons, kernel):
    res = nodal.solve_core(layout, cons, ASM, HZ, kernel=kernel, boundaries={"x_min": "reflective", "x_max": "vacuum", "y_min": "reflective", "y_max": "reflective"})
    return res.k_eff


def main():
    k_mc = float(P["k_stripZ"])
    print(f"strip [B B A | R], OpenMC k = {k_mc:.5f} (E13 run, 20,000 x 150, about +/- 60 pcm)")
    layout = [["B", "B", "A", "R"]]
    edges = FINE["edges"]
    cases = {
        "all constants from the strip run itself (stripZ_B, stripZ_A, reflZ)": {"A": piece("stripZ_A"), "B": piece("stripZ_B"), "R": piece("reflZ")},
        "fuel from the infinite lattices, corrected (E15); reflector reflZ": {"A": nodal.critical_buckling_fuel(fine("A"), edges), "B": nodal.critical_buckling_fuel(fine("B"), edges), "R": piece("reflZ")},
        "fuel from the infinite lattices, plain collapse; reflector reflZ": {"A": nodal.critical_buckling_fuel(fine("A"), edges, correct=False), "B": nodal.critical_buckling_fuel(fine("B"), edges, correct=False), "R": piece("reflZ")},
    }
    for label, cons in cases.items():
        row = []
        for kernel in ("sanm", "fdm"):
            row.append((solve(layout, cons, kernel) - k_mc) * 1e5)
        print(f"  {label:72s} sanm {row[0]:+7.0f} pcm | fdm {row[1]:+7.0f} pcm")


if __name__ == "__main__":
    main()
