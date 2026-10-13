"""E11b: is openndm's radial_power() map in the lattice's row order, or flipped?

The assembly-power comparisons of E5 to E10 read `result.radial_power()` and compared it with the Monte Carlo power by array index. Cores symmetric under a vertical flip
(the zoned ones) cannot show a flip; the 8 x 8 checkerboard does, because flipping its rows swaps the A and B positions. The check: build the power of every node from
the node flux (`result.flux`, one row per node in the geometry's node order) and the library's kappa sigma_f, and compare it with `radial_power()` and with its vertical flip.
    python e11b_orientation.py
"""
import numpy as np
import openndm

import e9_current_d as e9

core = e9.load("checker1")
NC = core["NC"]
kinds = np.array(core["kinds"])
fuel = kinds != "R"
D = core["c_Dflux"]
geom = e9.geometry(core)
xs = e9.library(core, D)
xs.finalize(warn=False)
res = openndm.Model(geom(), xs, openndm.Settings(kernel="sanm", verbosity=0)).solve()
g = geom()
flux = np.asarray(res.flux)
print("flux array shape", flux.shape, "; nodes", NC * NC)
kf = core["c_kappa_fission"].reshape(NC * NC, 2)
p_nodes = (flux * kf).sum(axis=1)                    # node order: assumed row-major over the lattice array (row = y index as the array lists it)
as_rows = p_nodes.reshape(NC, NC)
radial = np.asarray(res.radial_power())
ref = core["power"]
print("radial_power() shape", radial.shape)


def corr(a, b):
    m = fuel
    a, b = a[m] / a[m].mean(), b[m] / b[m].mean()
    return np.corrcoef(a, b)[0, 1], np.sqrt(((a / b - 1) ** 2).mean()) * 100


for name, arr in (("power from the node flux, row-major", as_rows), ("radial_power() as returned", radial), ("radial_power(), rows flipped", radial[::-1]),
                  ("radial_power(), columns flipped", radial[:, ::-1]), ("radial_power(), transposed", radial.T)):
    cc, rms = corr(arr, ref)
    print(f"  {name:40s} against the Monte Carlo power: correlation {cc:+.3f}, rms difference {rms:5.1f} %")
print("the node-flux power and radial_power() should agree if radial_power() is in the lattice's row order:")
for name, arr in (("as returned", radial), ("rows flipped", radial[::-1])):
    cc, rms = corr(arr, as_rows)
    print(f"  radial_power(), {name:14s} against the node-flux power: correlation {cc:+.3f}, rms difference {rms:5.1f} %")

# the node vector `result.power` against kappa sigma_f x flux, node by node (same order as `result.flux`)
pv = np.asarray(res.power)
print("result.power shape", pv.shape)
a, b = pv / pv.mean(), p_nodes / p_nodes.mean()
print(f"  result.power against kappa sigma_f x flux, node by node: correlation {np.corrcoef(a, b)[0, 1]:+.4f}, rms difference {np.sqrt(((a / b - 1) ** 2).mean()) * 100:.2f} %, largest {np.abs(a / b - 1).max() * 100:.2f} %")
nu = (flux * core["c_nu_fission"].reshape(NC * NC, 2)).sum(axis=1)
c_ = nu / nu.mean()
print(f"  result.power against nu sigma_f x flux:                  correlation {np.corrcoef(a, c_)[0, 1]:+.4f}, rms difference {np.sqrt(((a / c_ - 1) ** 2).mean()) * 100:.2f} %")
# which way is result.power ordered: row-major over the lattice array, as the flux?
pm = pv.reshape(NC, NC)
for name, arr in (("result.power row-major", pm), ("result.power, rows flipped", pm[::-1]), ("radial_power() rows flipped", radial[::-1]), ("radial_power() as returned", radial)):
    cc, rms = corr(arr, ref)
    print(f"  {name:32s} against the Monte Carlo power: correlation {cc:+.3f}, rms {rms:5.1f} %")

# which index order does result.flux use? compare each group's flux, as listed and with the rows flipped, with the Monte Carlo node-average flux
phi = core["phi"]
for g, gn in enumerate(("fast", "thermal")):
    f = flux[:, g].reshape(NC, NC)
    for name, arr in (("as listed (row-major)", f), ("rows flipped", f[::-1])):
        cc, rms = corr(arr, phi[:, :, g])
        print(f"  result.flux {gn:7s} {name:22s} against the Monte Carlo node flux: correlation {cc:+.3f}, rms difference {rms:5.1f} %")
for name, arr in (("kappa sigma_f x flux, as listed", as_rows), ("kappa sigma_f x flux, rows flipped", as_rows[::-1])):
    cc, rms = corr(arr, np.asarray(res.power).reshape(NC, NC))
    print(f"  {name:36s} against result.power as listed: correlation {cc:+.3f}")
