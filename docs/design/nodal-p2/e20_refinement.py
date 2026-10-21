"""P2, experiment E20: is the strip's remaining error the nodal discretisation or the homogenised constants?

E18/E19: the strip [B B A | R] solved with one node per assembly is 369 to 502 pcm above OpenMC's with SANM and 46 to 175 pcm below it with FDM; the fuel-only periodic row is right (+27 pcm).
The same node constants are used here on a refined mesh (each node split into 2 x 2 and 4 x 4 equal sub-nodes, all with that node's constants, no factors). Refining removes the discretisation error
and keeps the homogenisation error: the value the refined solution converges to, minus OpenMC's k, is what the constants and diffusion theory alone cost; the step from one node per assembly to
that value is what the coarse mesh costs. Data: data/strips_e19.npz (the three rows of E19, per-node constants) and data/pieces.npz + fine_inf.npz (E13/E15 constants for the same strip).

    PYTHONPATH=studio:docs/design/nodal-p2 python docs/design/nodal-p2/e20_refinement.py
"""
from pathlib import Path

import numpy as np
import openndm

from openmc_studio import nodal

DATA = Path(__file__).resolve().parent / "data"
E19 = np.load(DATA / "strips_e19.npz")
P = np.load(DATA / "pieces.npz")
FINE = np.load(DATA / "fine_inf.npz")
FIELDS = ("D", "absorption", "nu_fission", "kappa_fission", "chi", "scatter", "inv_velocity")
ASM, HZ = 6.3, 1.0


def solve(order, consts, x_max, kernel, sub):
    """A row of nodes (left to right), reflective at the left and in y, `x_max` at the right, each node split sub x sub (in x and y)."""
    kinds = sorted(set(order))
    comp = np.array([[kinds.index(k) for k in order]], dtype=int)
    bc = {"x_min": "reflective", "x_max": x_max, "y_min": "reflective", "y_max": "reflective", "z_min": "reflective", "z_max": "reflective"}
    geom = openndm.Geometry.from_lattice(comp, pitch=ASM, dz=[HZ], boundaries=bc, outside="vacuum", subdivide=(sub, sub, 1))
    xs = openndm.XSLibrary(2, len(kinds))
    for i, k in enumerate(kinds):
        c = nodal.check_constants(k, consts[k])
        xs.set_composition(i, D=c["D"], absorption=c["absorption"], nu_fission=c["nu_fission"], kappa_fission=c["kappa_fission"], chi=c["chi"], scatter=c["scatter"], inv_velocity=c["inv_velocity"])
        xs.set_adf(i, np.ones((4, 2)), n_axes=2)
    xs.finalize(warn=False)
    return openndm.Model(geom, xs, openndm.Settings(kernel=kernel, verbosity=0)).solve().k_eff


def e19_consts(tag, names):
    return {n: {f: np.asarray(E19[f"{tag}__{n}__{f}"], float) for f in FIELDS} for n in names}


def main():
    cases = (("periodic [B B A], E19 node constants", "periodic", ["B0", "B1", "A2"], "reflective"),
             ("vacuum   [B B A], E19 node constants", "vacuum", ["B0", "B1", "A2"], "vacuum"),
             ("reflector [B B A | R], E19 node constants", "reflector", ["B0", "B1", "A2", "R3"], "vacuum"))
    print("nodal minus OpenMC (pcm); node split into sub x sub, no factors")
    for label, tag, names, xmax in cases:
        k_mc = float(E19[f"{tag}__k"])
        cons = e19_consts(tag, names)
        row = []
        for kernel in ("sanm", "fdm"):
            row.append("  ".join(f"{(solve(names, cons, xmax, kernel, s) - k_mc) * 1e5:+7.0f}" for s in (1, 2, 4)))
        print(f"{label:48s} sanm (1, 2, 4): {row[0]} | fdm (1, 2, 4): {row[1]}")
    # E13/E15 recipe constants for the same strip (fuel from the infinite lattices, corrected; reflector reflZ), against E13's strip run
    k_mc = float(P["k_stripZ"])
    edges = FINE["edges"]

    def fine(tag):
        return {f: np.asarray(FINE[f"{tag}__{f}"], float) for f in FIELDS + ("flux",)}
    cons = {"A": nodal.critical_buckling_fuel(fine("A"), edges), "B": nodal.critical_buckling_fuel(fine("B"), edges), "R": {f: np.asarray(P[f"reflZ__{f}"], float).reshape(-1) for f in FIELDS}}
    row = []
    for kernel in ("sanm", "fdm"):
        row.append("  ".join(f"{(solve(['B', 'B', 'A', 'R'], cons, 'vacuum', kernel, s) - k_mc) * 1e5:+7.0f}" for s in (1, 2, 4)))
    print(f"{'reflector [B B A | R], recipe constants vs E13 run':48s} sanm (1, 2, 4): {row[0]} | fdm (1, 2, 4): {row[1]}")


if __name__ == "__main__":
    main()
