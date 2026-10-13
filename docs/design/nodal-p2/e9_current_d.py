"""P2, experiment E9: a diffusion coefficient that preserves the Monte Carlo currents, tried with and without discontinuity factors.

E8 found that the Monte Carlo fast-group net current between two neighbouring nodes is 1.25 to 1.35 times what Fick's law gives with the
library's D and the nodes' average fluxes. Here a scale on D is fitted per kind of node (A, B, reflector R) and per group, so that

    J_ab = -(2 a D_a b D_b / (a D_a + b D_b)) (phi_b - phi_a) / h

(the harmonic-mean coupling of the finite-difference solver, a and b the scales of the two nodes' kinds) matches the tallied net current across
every shared face between two nodes (the vacuum faces are left out), by non-linear least squares on residuals relative to the current
(floored at 0.2 of the group's median |J|). The fit is made on each core and on the 11 x 11 zoned core (zoned2) alone and applied to the others, which
asks whether the correction belongs to the library or to one core. Each D (as tallied, fitted on the core itself, fitted on zoned2) is then solved with
no factors, the old factors (face flux over node average), and equivalence factors (true face flux over the parabola with the scaled D): k and assembly power
against OpenMC.

Needs data/<core>.npz from e9a_dump.py (zoned1, zoned2, checker1). Runs in seconds; no Monte Carlo.
    python e9_current_d.py
"""
import os
import sys
from pathlib import Path

import numpy as np
import openmc
import openndm
from scipy.optimize import least_squares

DATA = Path(__file__).resolve().parent / "data"
CORES = ("zoned1", "zoned2", "checker1")
KINDS = ("A", "B", "R")
FIT_ON = "zoned2"


def load(name):
    d = np.load(DATA / f"{name}.npz")
    core = {k: d[k] for k in d.files}
    core["kinds"] = [[str(x) for x in row] for row in d["kinds"]]
    core["NC"] = len(core["kinds"])
    core["name"] = name
    return core


def interfaces(core):
    """Every shared face between two nodes: (a, b, J_ab, dphi_over_h): the net current from a to b and (phi_b - phi_a) / h, per group; vacuum faces are not included."""
    NC, h = core["NC"], float(core["asm"])
    out = []
    for r in range(NC):
        for c in range(NC):
            if c + 1 < NC:    # the +x neighbour
                j = 0.5 * (core["curr"][r, c, 1] + core["curr"][r, c + 1, 0])
                out.append(((r, c), (r, c + 1), j, (core["phi"][r, c + 1] - core["phi"][r, c]) / h))
            if r + 1 < NC:    # the row below, which is lower in y: positive current from a (upper) to b (lower) is minus the net +y current
                j = -0.5 * (core["curr"][r, c, 2] + core["curr"][r + 1, c, 3])
                out.append(((r, c), (r + 1, c), j, (core["phi"][r + 1, c] - core["phi"][r, c]) / h))
    return out


def fit_scales(core):
    """scale[kind][group] by non-linear least squares over the shared faces."""
    ifs = interfaces(core)
    D = core["c_D"]
    scale = {k: np.ones(2) for k in KINDS}
    resid_before, resid_after = np.zeros(2), np.zeros(2)
    for g in range(2):
        J = np.array([i[2][g] for i in ifs])
        floor = 0.2 * np.median(np.abs(J))
        w = np.maximum(np.abs(J), floor)

        def residual(p):
            s = dict(zip(KINDS, p))
            out = []
            for (a, b, j, dphi), wi in zip(ifs, w):
                sa, sb = s[core["kinds"][a[0]][a[1]]], s[core["kinds"][b[0]][b[1]]]
                Da, Db = sa * D[a[0], a[1], g], sb * D[b[0], b[1], g]
                out.append((j[g] - (-(2 * Da * Db / (Da + Db)) * dphi[g])) / wi)
            return np.array(out)

        resid_before[g] = np.sqrt((residual(np.ones(3)) ** 2).mean())
        fit = least_squares(residual, np.ones(3), bounds=(0.3, 10.0))
        resid_after[g] = np.sqrt((residual(fit.x) ** 2).mean())
        for k, v in zip(KINDS, fit.x):
            scale[k][g] = v
    return scale, resid_before, resid_after


def scaled_D(core, scale):
    D = core["c_D"].copy()
    for r in range(core["NC"]):
        for c in range(core["NC"]):
            D[r, c] *= scale[core["kinds"][r][c]]
    return D


def fast_only(scale):
    """The same scales with the thermal group left as tallied (its fit is not reliable)."""
    return {k: np.array([v[0], 1.0]) for k, v in scale.items()}


def hom_faces(core, D):
    """The parabola's face flux (faces -x +x -y +y physical, groups fast first) from the node flux and the net currents with the given D."""
    h = float(core["asm"])
    phi, curr = core["phi"], core["curr"]
    hom = np.zeros_like(core["face"])
    for lo, hi in ((0, 1), (2, 3)):
        jl, jr = curr[:, :, lo], curr[:, :, hi]
        b = -(jl + jr) / (2 * D)
        cc = -(jr - jl) / (2 * D * h)
        hom[:, :, lo] = phi - b * h / 2 + cc * h * h / 6
        hom[:, :, hi] = phi + b * h / 2 + cc * h * h / 6
    return hom


def face_class(core, r, c, f):
    """Class of face f (openndm's order -x, +x, -y, +y, its -y being the physical +y) of node (r, c)."""
    NC, kinds = core["NC"], core["kinds"]
    rr, cc = r + ((0, 0, -1, 1)[f]), c + ((-1, 1, 0, 0)[f])
    if not (0 <= rr < NC and 0 <= cc < NC):
        return "vacuum"
    a, b = kinds[r][c] == "R", kinds[rr][cc] == "R"
    return "reflector/reflector" if (a and b) else ("fuel/reflector" if (a or b) else "fuel/fuel")


def library(core, D):
    NC = core["NC"]
    xs = openndm.XSLibrary(2, NC * NC)
    for r in range(NC):
        for c in range(NC):
            xs.set_composition(r * NC + c, D=D[r, c], absorption=core["c_absorption"][r, c], nu_fission=core["c_nu_fission"][r, c],
                               kappa_fission=core["c_kappa_fission"][r, c], chi=core["c_chi"][r, c], scatter=core["c_scatter"][r, c].reshape(2, 2),
                               inv_velocity=core["c_inv_velocity"][r, c])
    return xs


def geometry(core):
    NC, asm = core["NC"], float(core["asm"])
    openmc.reset_auto_ids()
    lat = openmc.RectLattice()
    lat.pitch, lat.lower_left = (asm, asm), (-NC * asm / 2, -NC * asm / 2)
    unis = [[openmc.Universe(cells=[openmc.Cell()]) for _ in range(NC)] for _ in range(NC)]
    lat.universes = unis
    bc = {f: "vacuum" for f in ("x_min", "x_max", "y_min", "y_max")} | {"z_min": "reflective", "z_max": "reflective"}
    doms = [unis[r][c] for r in range(NC) for c in range(NC)]
    return lambda: openndm.Geometry.from_openmc(lat, domains=doms, dz=[float(core["hz"])], boundaries=bc, outside="vacuum", subdivide=1)


def factors(core, D, mode):
    """(NC, NC, 4, 2) in openndm's face order."""
    NC = core["NC"]
    old = core["face"] / core["phi"][:, :, None, :]
    eq = core["face"] / hom_faces(core, D)
    phys = {"none": np.ones_like(old), "old": old, "equivalence": eq}
    out = np.ones_like(old)
    for r in range(NC):
        for c in range(NC):
            for f in range(4):
                cls = face_class(core, r, c, f)
                fs = {"none": "none", "old": "old", "equivalence": "equivalence",
                      "equivalence, interior": "equivalence" if cls != "vacuum" else "none",
                      "equivalence, interior + old at the vacuum": "equivalence" if cls != "vacuum" else "old"}[mode]
                src = phys[fs][r, c].copy()
                src[[2, 3]] = src[[3, 2]]       # openndm's row 0 is its lowest y: its -y face is the physical +y face
                out[r, c, f] = src[f]
    return out


def solve(core, geom, D, mode):
    NC = core["NC"]
    xs = library(core, D)
    fac = factors(core, D, mode)
    for r in range(NC):
        for c in range(NC):
            xs.set_adf(r * NC + c, fac[r, c], n_axes=2)
    xs.finalize(warn=False)
    fuel = np.array([[core["kinds"][r][c] != "R" for c in range(NC)] for r in range(NC)])
    ref = core["power"] / core["power"][fuel].mean()
    row = []
    for kernel in ("fdm", "sanm"):
        try:
            res = openndm.Model(geom(), xs, openndm.Settings(kernel=kernel, verbosity=0)).solve()
        except Exception:  # noqa: BLE001
            row.append((float("nan"),) * 3)
            continue
        p = res.radial_power()
        p = p / p[fuel].mean()
        err = 100 * (p[fuel] / ref[fuel] - 1)
        row.append(((res.k_eff - core["k"]) * 1e5, np.sqrt((err ** 2).mean()), np.abs(err).max()))
    return row


cores = {n: load(n) for n in CORES if (DATA / f"{n}.npz").is_file()}
fits = {n: fit_scales(c) for n, c in cores.items()}
print("D scales fitted to the Monte Carlo currents (kind: fast, thermal), and the rms relative residual before / after, fast | thermal:")
for n, (scale, rb, ra) in fits.items():
    sd = "  ".join(f"{k}: {scale[k][0]:.2f} {scale[k][1]:.2f}" for k in KINDS)
    print(f"  {n:9s} {sd}    residual {rb[0]:.2f} {rb[1]:.2f} -> {ra[0]:.2f} {ra[1]:.2f}   (OpenMC k {float(cores[n]['k']):.5f} +/- {float(cores[n]['k_sd']) * 1e5:.0f} pcm, "
          f"{int(cores[n]['particles'])} x {int(cores[n]['batches'])})")
if all("c_Dflux" in c for c in cores.values()):
    print("\nflux-averaged D (120-group transport tally) over the library's D (1/(3 <sigma_tr>) in 2 groups): mean over the nodes of each kind, fast | thermal")
    for n, core in cores.items():
        parts = []
        for kd in KINDS:
            sel = np.array([[core["kinds"][r][c] == kd for c in range(core["NC"])] for r in range(core["NC"])])
            q = (core["c_Dflux"] / core["c_D"])[sel].mean(axis=0)
            h = (core["c_Dharm"] / core["c_D"])[sel].mean(axis=0)
            parts.append(f"{kd}: {q[0]:.3f} | {q[1]:.3f} (collapse check {h[0]:.3f} | {h[1]:.3f})")
        print(f"  {n:9s} " + "   ".join(parts))
MODES = ("none", "old", "equivalence", "equivalence, interior", "equivalence, interior + old at the vacuum")
for n, core in cores.items():
    geom = geometry(core)
    print(f"\n{n}: nodal k minus OpenMC k (pcm) and assembly power error (rms / max %), fdm | sanm")
    variants = [("D as tallied", core["c_D"]), ("flux-averaged D (E10)", core["c_Dflux"]),
                ("D fitted on this core", scaled_D(core, fits[n][0])),
                ("fast D fitted on this core", scaled_D(core, fast_only(fits[n][0])))]
    if n != FIT_ON and FIT_ON in fits:
        variants.append((f"D fitted on {FIT_ON}", scaled_D(core, fits[FIT_ON][0])))
        variants.append((f"fast D fitted on {FIT_ON}", scaled_D(core, fast_only(fits[FIT_ON][0]))))
    for vname, D in variants:
        for mode in MODES:
            f, s = solve(core, geom, D, mode)
            print(f"  {vname:24s} {mode:44s} {f[0]:+7.0f} {f[1]:4.1f}/{f[2]:4.1f}  |  {s[0]:+7.0f} {s[1]:4.1f}/{s[2]:4.1f}")
