"""P2, experiment E11: where does the 8 x 8 checkerboard's assembly-power error come from?

With the flux-averaged D (E10) the zoned cores' power is 2 to 4 % rms and k is within 1k, but the checkerboard (6 x 6 fuel nodes, A and B alternating, one water ring) has
16 to 17 % rms whatever the factors. Questions, answered from the saved Monte Carlo data (no new run):
  1. Is the error systematic by kind (all A too low, all B too high), or scattered?
  2. Is it in the flux (which group?) or in the constants (nodal power = kappa sigma_f phi x volume must equal the Monte Carlo power if the flux is right)?
  3. Does Fick's law with the flux-averaged D fail at the A/B interfaces (net current from Monte Carlo over the current from the node-average fluxes, by pair of kinds)?
  4. Does the equivalence-factor definition give sensible values there (A|B faces)?
Needs data/checker1.npz (and zoned1.npz for comparison). Runs in seconds.
    python e11_checker_diag.py
"""
import numpy as np

import e9_current_d as e9

np.set_printoptions(linewidth=200, precision=3, suppress=True)


def nodal(core, D, mode, kernel="sanm"):
    """The nodal solution: power map (rows top first), flux (NC, NC, 2 groups fast first), k error in pcm."""
    import openndm
    NC = core["NC"]
    geom = e9.geometry(core)
    xs = e9.library(core, D)
    fac = e9.factors(core, D, mode)
    for r in range(NC):
        for c in range(NC):
            xs.set_adf(r * NC + c, fac[r, c], n_axes=2)
    xs.finalize(warn=False)
    res = openndm.Model(geom(), xs, openndm.Settings(kernel=kernel, verbosity=0)).solve()
    flux = np.asarray(res.flux).reshape(NC, NC, -1)[::-1]      # openndm lists results bottom-up; flip to the lattice array's order (E11b)
    return res.radial_power()[::-1], flux, (res.k_eff - float(core["k"])) * 1e5


def report(name):
    core = e9.load(name)
    NC, kinds = core["NC"], np.array(core["kinds"])
    fuel = kinds != "R"
    D = core["c_Dflux"]
    ref = core["power"] / core["power"][fuel].mean()
    print(f"\n===== {name}: flux-averaged D, no factors, SANM")
    p, flux, dk = nodal(core, D, "none")
    p = p / p[fuel].mean()
    err = 100 * (p / np.where(ref > 0, ref, np.nan) - 1)
    print(f"k error {dk:+.0f} pcm; power error rms {np.sqrt((err[fuel] ** 2).mean()):.1f} %")
    for kd in ("A", "B"):
        e = err[kinds == kd]
        print(f"  kind {kd}: nodal / Monte Carlo power - 1: mean {e.mean():+.1f} %, spread (sd) {e.std():.1f} %, range [{e.min():+.1f}, {e.max():+.1f}] %  ({len(e)} nodes; the power of {kd} in the Monte Carlo: mean {ref[kinds == kd].mean():.3f})")
    print("power error map, % (nodal over Monte Carlo minus 1; the water ring blank):")
    for r in range(NC):
        print("   " + " ".join(f"{err[r, c]:+6.1f}" if fuel[r, c] else "     ." for c in range(NC)))
    # flux: the node-average flux in each group, nodal against Monte Carlo, both normalised to the mean over the fuel nodes
    phi_mc = core["phi"]
    for g, gn in enumerate(("fast", "thermal")):
        a = flux[:, :, g] / flux[:, :, g][fuel].mean()
        b = phi_mc[:, :, g] / phi_mc[:, :, g][fuel].mean()
        e = 100 * (a / b - 1)
        print(f"  {gn:7s} flux nodal / Monte Carlo - 1 (%): A mean {e[kinds == 'A'].mean():+.1f} (sd {e[kinds == 'A'].std():.1f}), B mean {e[kinds == 'B'].mean():+.1f} (sd {e[kinds == 'B'].std():.1f}), R mean {e[kinds == 'R'].mean():+.1f}")
    # the constants: Monte Carlo power from the node-average flux and the library's kappa sigma_f, against the tallied power
    kf = core["c_kappa_fission"]
    p_from_flux = (kf * core["phi"]).sum(axis=2)
    pf = p_from_flux / p_from_flux[fuel].mean()
    e = 100 * (pf / np.where(ref > 0, ref, np.nan) - 1)
    print(f"  Monte Carlo node flux x library kappa sigma_f against the tallied power: rms {np.sqrt((e[fuel] ** 2).mean()):.2f} % (the constants and the flux are consistent if this is near 0)")
    # Fick's law at the interfaces, by pair of kinds
    ifs = e9.interfaces(core)
    byk = {}
    for a, b, j, dphi in ifs:
        ka, kb = kinds[a], kinds[b]
        key = "-".join(sorted((ka, kb)))
        Da, Db = D[a[0], a[1]], D[b[0], b[1]]
        jfd = -(2 * Da * Db / (Da + Db)) * dphi
        byk.setdefault(key, []).append(j / jfd)
    print("  net current from Monte Carlo over Fick's law with the flux-averaged D, by pair of kinds (fast | thermal): median [10th, 90th percentile]")
    for key, v in sorted(byk.items()):
        v = np.array(v)
        q = np.percentile(v, [10, 50, 90], axis=0)
        print(f"    {key:4s} ({len(v):3d} faces): fast {q[1][0]:6.2f} [{q[0][0]:6.2f}, {q[2][0]:6.2f}]   thermal {q[1][1]:6.2f} [{q[0][1]:6.2f}, {q[2][1]:6.2f}]")
    # the equivalence factors on the A|B faces
    eq = core["face"] / e9.hom_faces(core, D)
    old = core["face"] / core["phi"][:, :, None, :]
    rows = {"equivalence": eq, "face / node average": old}
    for label, arr in rows.items():
        vals = {"A": [], "B": []}
        for r in range(NC):
            for c in range(NC):
                if kinds[r, c] == "R":
                    continue
                for f in range(4):
                    rr, cc = r + ((0, 0, 1, -1)[f]), c + ((-1, 1, 0, 0)[f])      # physical faces -x +x -y(row below) +y(row above)
                    if 0 <= rr < NC and 0 <= cc < NC and kinds[rr, cc] != "R" and kinds[rr, cc] != kinds[r, c]:
                        vals[kinds[r, c]].append(arr[r, c, f])
        for kd in ("A", "B"):
            v = np.array(vals[kd])
            if len(v):
                print(f"  {label:20s} on the faces of {kd} that touch the other fuel kind: fast {v[:, 0].mean():.3f} (sd {v[:, 0].std():.3f}), thermal {v[:, 1].mean():.3f} (sd {v[:, 1].std():.3f}) ({len(v)} faces)")


for n in ("checker1", "zoned1"):
    report(n)
