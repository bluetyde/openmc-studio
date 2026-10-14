"""P2, experiment E14: which constants make the two-step k high?

E13 left the two-step k +1.1k to +1.7k above OpenMC's, against +0.2k to +0.7k with the core run's own constants by kind (same flux-averaged D, no factors). The pieces
(data/pieces.npz, from e13_two_step_library.py) and the core runs (data/<core>.npz) differ in many numbers. Here the two-step constants are taken as the base and ONE field
at a time is replaced by the core run's value for the same kind of node (the mean over the nodes of that kind), then the core is solved again, no new Monte Carlo:
the change in k says how much of the gap that field carries. Also printed: the pieces' fields against the core run's, in percent.
Fields: D, absorption, nu_fission, and the 2 x 2 scattering matrix (row = from-group, column = to-group, fast first), for the fuel kinds (A and B together) and the reflector,
each group on its own and both together; kappa_fission, chi and inverse_velocity do not enter k.
Throwaway script for the sandbox.

    python e14_swap_fields.py
"""
import numpy as np
import openndm

import e9_current_d as e9
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data"
P = np.load(DATA / "pieces.npz")
FIELDS = ("D", "absorption", "nu_fission", "kappa_fission", "chi", "scatter", "inv_velocity")


def piece(name):
    return {f: np.asarray(P[f"{name}__{f}"], float).reshape(-1) for f in FIELDS}


def core_by_kind(core):
    out = {}
    for kd in ("A", "B", "R"):
        sel = np.array([[core["kinds"][r][c] == kd for c in range(core["NC"])] for r in range(core["NC"])])
        out[kd] = dict(D=core["c_Dflux"][sel].mean(axis=0), absorption=core["c_absorption"][sel].mean(axis=0), nu_fission=core["c_nu_fission"][sel].mean(axis=0),
                       kappa_fission=core["c_kappa_fission"][sel].mean(axis=0), chi=core["c_chi"][sel].mean(axis=0), scatter=core["c_scatter"][sel].mean(axis=0),
                       inv_velocity=core["c_inv_velocity"][sel].mean(axis=0))
    return out


def two_step(name):
    z = name != "checker1"
    return {"A": piece("stripZ_A" if z else "stripC_A"), "B": piece("stripZ_B" if z else "stripC_B"), "R": piece("reflZ" if z else "reflC")}


def solve_k(core, geom, per_kind):
    NC = core["NC"]
    xs = openndm.XSLibrary(2, NC * NC)
    for r in range(NC):
        for c in range(NC):
            d = per_kind[core["kinds"][r][c]]
            xs.set_composition(r * NC + c, D=d["D"], absorption=d["absorption"], nu_fission=d["nu_fission"], kappa_fission=d["kappa_fission"], chi=d["chi"],
                               scatter=d["scatter"].reshape(2, 2), inv_velocity=d["inv_velocity"])
            xs.set_adf(r * NC + c, np.ones((4, 2)), n_axes=2)
    xs.finalize(warn=False)
    return (openndm.Model(geom(), xs, openndm.Settings(kernel="sanm", verbosity=0)).solve().k_eff - float(core["k"])) * 1e5


def replaced(base, ref, kinds, field, idx):
    out = {k: {f: v.copy() for f, v in d.items()} for k, d in base.items()}
    for kd in kinds:
        if idx is None:
            out[kd][field] = ref[kd][field].copy()
        else:
            out[kd][field][idx] = ref[kd][field][idx]
    return out


def main():
    for name in ("zoned1", "zoned2", "checker1"):
        core = e9.load(name)
        geom = e9.geometry(core)
        base, ref = two_step(name), core_by_kind(core)
        k_base, k_ref = solve_k(core, geom, base), solve_k(core, geom, ref)
        print(f"\n===== {name}: two-step {k_base:+.0f} pcm, the core run's own constants by kind {k_ref:+.0f} pcm (SANM, no factors)")
        print("  the pieces against the core run, % difference of the kind's value (pieces / core - 1); fast | thermal (scatter: the four entries from-to)")
        for kd, label in (("A", "fuel A"), ("B", "fuel B"), ("R", "reflector")):
            row = []
            for f in ("D", "absorption", "nu_fission"):
                a, b = base[kd][f], ref[kd][f]
                with np.errstate(divide="ignore", invalid="ignore"):
                    q = np.where(np.abs(b) > 0, 100 * (a / b - 1), np.nan)
                row.append(f"{f} {q[0]:+6.1f} {q[1]:+6.1f}")
            sa, sb = base[kd]["scatter"], ref[kd]["scatter"]
            with np.errstate(divide="ignore", invalid="ignore"):
                sq = np.where(np.abs(sb) > 0, 100 * (sa / sb - 1), np.nan)
            row.append("scatter " + " ".join(f"{v:+6.1f}" for v in sq))
            print(f"    {label:9s} " + "   ".join(row))
        print("  replacing ONE field of the two-step constants by the core run's: change of k (pcm)")
        rows = []
        for group, kinds in (("fuel", ("A", "B")), ("reflector", ("R",))):
            for f, n in (("D", 2), ("absorption", 2), ("nu_fission", 2), ("scatter", 4)):
                for idx in [None] + list(range(n)):
                    if n == 2 and idx is not None:
                        lab = f"{group} {f} {('fast', 'thermal')[idx]}"
                    elif n == 4 and idx is not None:
                        lab = f"{group} scatter [{idx // 2}->{idx % 2}]"
                    else:
                        lab = f"{group} {f} (all)"
                    rows.append((lab, solve_k(core, geom, replaced(base, ref, kinds, f, idx)) - k_base))
        allfuel = {k: {f: v.copy() for f, v in d.items()} for k, d in base.items()}
        for kd in ("A", "B"):
            allfuel[kd] = {f: v.copy() for f, v in ref[kd].items()}
        allrefl = {k: {f: v.copy() for f, v in d.items()} for k, d in base.items()}
        allrefl["R"] = {f: v.copy() for f, v in ref["R"].items()}
        rows.append(("ALL fuel constants", solve_k(core, geom, allfuel) - k_base))
        rows.append(("ALL reflector constants", solve_k(core, geom, allrefl) - k_base))
        for lab, dk in sorted(rows, key=lambda r: -abs(r[1]))[:10]:
            print(f"    {lab:34s} {dk:+7.0f}")


if __name__ == "__main__":
    main()
