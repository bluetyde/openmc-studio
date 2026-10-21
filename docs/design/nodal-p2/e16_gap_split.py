"""P2, experiment E16: how much of the two-step k's remaining gap is the fuel and how much the reflector?

E15 left the two-step k (infinite-lattice fuel with the critical-buckling correction, reflector from the strips) +539, +1,150 and +1,018 pcm above OpenMC's, against +185,
+702 and +381 pcm with the core run's own constants by kind (SANM, no factors). Here the two sources of each kind are crossed, no new Monte Carlo (data/*.npz):

    fuel      F1 = infinite lattice with the critical-buckling correction (nodal.critical_buckling_fuel)     F0 = the core run's own constants by kind
    reflector R1 = the strip(s) of E13 (reflZ, reflC)                                                        R0 = the core run's own constants by kind

so F1/R1 is the two-step, F0/R0 the best the node-level constants can do, and the two mixed cases say which kind carries the difference. Also printed: the reflector's fields,
R1 against R0 in percent, and the same for the mean D of E10 (flux average) so the reflector's remaining D difference is visible.

    PYTHONPATH=studio:docs/design/nodal-p2 python docs/design/nodal-p2/e16_gap_split.py
"""
from pathlib import Path

import numpy as np

import e9_current_d as e9
from openmc_studio import nodal

DATA = Path(__file__).resolve().parent / "data"
FINE = np.load(DATA / "fine_inf.npz")
PIECES = np.load(DATA / "pieces.npz")
FIELDS = ("D", "absorption", "nu_fission", "kappa_fission", "chi", "scatter", "inv_velocity")


def fine(tag):
    return {f: np.asarray(FINE[f"{tag}__{f}"], float) for f in FIELDS + ("flux",)}


def refl_strip(name):
    if name == "checker1":
        return {f: np.asarray(PIECES[f"reflC__{f}"], float).reshape(-1) for f in FIELDS}
    return {f: np.asarray(FINE[f"reflZ__{f}"], float).reshape(-1) for f in FIELDS}


def core_by_kind(core):
    out = {}
    for kd in ("A", "B", "R"):
        sel = np.array([[core["kinds"][r][c] == kd for c in range(core["NC"])] for r in range(core["NC"])])
        out[kd] = {f: core["c_" + f][sel].mean(axis=0) for f in ("D", "absorption", "nu_fission", "kappa_fission", "chi", "scatter", "inv_velocity")}
        out[kd]["D"] = core["c_Dflux"][sel].mean(axis=0)
    return out


def main():
    edges = FINE["edges"]
    for name in ("zoned1", "zoned2", "checker1"):
        core = e9.load(name)
        own = core_by_kind(core)
        F1 = {"A": nodal.critical_buckling_fuel(fine("A"), edges), "B": nodal.critical_buckling_fuel(fine("B"), edges)}
        R1 = refl_strip(name)

        def k(fuel, refl):
            cons = {"A": fuel["A"], "B": fuel["B"], "R": refl}
            res = nodal.solve_core(core["kinds"], cons, float(core["asm"]), float(core["hz"]))
            fm = np.array([[kd != "R" for kd in row] for row in core["kinds"]])
            ref = core["power"] / core["power"][fm].mean()
            p = res.power / res.power[fm].mean()
            return (res.k_eff - float(core["k"])) * 1e5, 100 * np.sqrt(((p[fm] / ref[fm] - 1) ** 2).mean())

        print(f"\n===== {name}: OpenMC k {float(core['k']):.5f}; nodal minus OpenMC (pcm) and assembly power rms %, SANM, no factors")
        for lab, fuel, refl in (("fuel F1 (infinite, corrected) + reflector R1 (strips)  = the two-step", F1, R1),
                                ("fuel F1 + reflector R0 (core run's own)", F1, own["R"]),
                                ("fuel F0 (core run's own)   + reflector R1", own, R1),
                                ("fuel F0 + reflector R0                              = the node-level best", own, own["R"])):
            d, rms = k(fuel, refl)
            print(f"  {lab:72s} {d:+7.0f}  {rms:4.1f}")
        print("  reflector R1 (strips) against R0 (core run's own), percent (fast | thermal; scatter 4 entries from-to):")
        for f in ("D", "absorption"):
            q = 100 * (R1[f] / own["R"][f] - 1)
            print(f"    {f:11s} {q[0]:+7.1f} {q[1]:+7.1f}")
        q = 100 * (R1["scatter"].reshape(-1) / own["R"]["scatter"].reshape(-1) - 1)
        print("    scatter     " + " ".join(f"{v:+7.1f}" for v in q))
        print(f"    absolute R1: D {R1['D'].round(4).tolist()} absorption {R1['absorption'].round(5).tolist()}; R0: D {own['R']['D'].round(4).tolist()} absorption {own['R']['absorption'].round(5).tolist()}")


if __name__ == "__main__":
    main()
