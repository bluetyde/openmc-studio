"""P2, experiment E3 (the face-flux estimate), built on E1 (the oracle): everything the nodal solver needs is tallied in the core run itself.

P0 left a +5,470 pcm error on an 8 x 8 core with a water reflector ring (vacuum outside) even though the reflector's
group constants were already tallied in that same core run. E1 asks whether the rest of the error is in how constants
are *generated* (two-step methods) or in the nodal solve itself, by giving the solver, for every position of the core:
  - its own group constants (each position is its own universe, tallied in the core run), and
  - its own discontinuity factors on all four faces, from a fine flux mesh over the core (slab next to the face / node average).
If k is still far off, no two-step method can fix it with these factors; if k comes close, the two-step methods (E2) have
a target. Throwaway script for the sandbox: it is not part of the app.

    OMP_NUM_THREADS=8 python e1_core_tallied.py [particles] [batches] [inactive] [K]
K = flux-mesh cells per assembly side (the face slab is 1/K of the pitch wide).
"""
import glob
import os
import sys
import time

import numpy as np
import openmc
import openmc.mgxs
import openndm
from openndm.gc import lattice_universes
from openndm.gc.mgxs import from_mgxs_library

particles = int(sys.argv[1]) if len(sys.argv) > 1 else 20000
batches = int(sys.argv[2]) if len(sys.argv) > 2 else 150
inactive = int(sys.argv[3]) if len(sys.argv) > 3 else 30
K = int(sys.argv[4]) if len(sys.argv) > 4 else 20
t_all = time.time()
openmc.reset_auto_ids()


def uo2(name, enr):
    m = openmc.Material(name=name)
    m.add_nuclide("U235", enr / 100)
    m.add_nuclide("U238", 1 - enr / 100)
    m.add_nuclide("O16", 2.0)
    m.set_density("g/cm3", 10.4)
    return m


fuel_a, fuel_b = uo2("fuel 2.4%", 2.4), uo2("fuel 3.1%", 3.1)
clad = openmc.Material(name="clad")
clad.add_element("Zr", 1.0)
clad.set_density("g/cm3", 6.55)
water = openmc.Material(name="water")
water.add_nuclide("H1", 2.0)
water.add_nuclide("O16", 1.0)
water.set_density("g/cm3", 0.74)
water.add_s_alpha_beta("c_H_in_H2O")
materials = openmc.Materials([fuel_a, fuel_b, clad, water])

PITCH, N = 1.26, 5
ASM = N * PITCH
HZ = 1.0


def pin(fuel):
    f, c = openmc.ZCylinder(r=0.4096), openmc.ZCylinder(r=0.475)
    return openmc.Universe(cells=[openmc.Cell(fill=fuel, region=-f), openmc.Cell(fill=clad, region=+f & -c), openmc.Cell(fill=water, region=+c)])


def tube():
    a, b = openmc.ZCylinder(r=0.56), openmc.ZCylinder(r=0.60)
    return openmc.Universe(cells=[openmc.Cell(fill=water, region=-a), openmc.Cell(fill=clad, region=+a & -b), openmc.Cell(fill=water, region=+b)])


def assembly(fuel, name):
    lat = openmc.RectLattice()
    lat.pitch, lat.lower_left = (PITCH, PITCH), (-ASM / 2, -ASM / 2)
    p, g = pin(fuel), tube()
    lat.universes = [[g if (i == N // 2 and j == N // 2) else p for i in range(N)] for j in range(N)]
    box = openmc.model.RectangularPrism(ASM, ASM)
    return openmc.Universe(cells=[openmc.Cell(fill=lat, region=-box)], name=name)


def wrapper(inner, name):
    """A new universe holding `inner`, so that one assembly design can sit at many positions, each its own tally domain."""
    return openmc.Universe(cells=[openmc.Cell(fill=inner)], name=name)


A, B = assembly(fuel_a, "asm A"), assembly(fuel_b, "asm B")
R = openmc.Universe(cells=[openmc.Cell(fill=water)], name="reflector")
NC = 8
kinds = [[("R" if (i in (0, NC - 1) or j in (0, NC - 1)) else ("A" if (i + j) % 2 == 0 else "B")) for i in range(NC)] for j in range(NC)]
inner = {"A": A, "B": B, "R": R}
core = openmc.RectLattice(name="core")
core.pitch, core.lower_left = (ASM, ASM), (-NC * ASM / 2, -NC * ASM / 2)
core.universes = [[wrapper(inner[kinds[r][c]], f"{kinds[r][c]} at row {r} col {c}") for c in range(NC)] for r in range(NC)]

box = openmc.model.RectangularPrism(NC * ASM, NC * ASM, boundary_type="vacuum")
z0, z1 = openmc.ZPlane(-HZ / 2, boundary_type="reflective"), openmc.ZPlane(HZ / 2, boundary_type="reflective")
geometry = openmc.Geometry(openmc.Universe(cells=[openmc.Cell(fill=core, region=-box & +z0 & -z1)]))
settings = openmc.Settings()
settings.particles, settings.batches, settings.inactive = particles, batches, inactive
settings.source = openmc.IndependentSource(space=openmc.stats.Box((-ASM, -ASM, -HZ / 2), (ASM, ASM, HZ / 2)), constraints={"fissionable": True})

TYPES = ["absorption", "transport", "nu-fission", "kappa-fission", "chi", "inverse-velocity", "consistent nu-scatter matrix", "consistent scatter matrix"]
groups = openmc.mgxs.EnergyGroups([0.0, 0.625, 20.0e6])
lib = openmc.mgxs.Library(geometry)
lib.energy_groups = groups
lib.legendre_order, lib.correction = 0, "P0"
lib.mgxs_types, lib.domain_type, lib.by_nuclide = TYPES, "universe", False
lib.domains = lattice_universes(core)
lib.build_library()
tallies = openmc.Tallies()
lib.add_to_tallies_file(tallies, merge=True)

mesh = openmc.RegularMesh()
mesh.dimension = [NC * K, NC * K, 1]
mesh.lower_left = [-NC * ASM / 2, -NC * ASM / 2, -HZ / 2]
mesh.upper_right = [NC * ASM / 2, NC * ASM / 2, HZ / 2]
flux = openmc.Tally(name="fine flux")
flux.filters = [openmc.MeshFilter(mesh), openmc.EnergyFilter(groups.group_edges)]
flux.scores = ["flux"]
tallies.append(flux)

model = openmc.Model(geometry, materials, settings, tallies)
existing = sorted(glob.glob('statepoint.*.h5'))
sp_path = max(existing, key=os.path.getmtime) if (existing and os.environ.get('REUSE')) else model.run(output=False)
with openmc.StatePoint(sp_path) as sp:
    k = sp.keff
    lib.load_from_statepoint(sp)
    t = sp.get_tally(name="fine flux")
    f_mean = t.mean.reshape(NC * K, NC * K, 2)       # [iy, ix, group], groups ascending in energy (thermal first)
    f_sd = t.std_dev.reshape(NC * K, NC * K, 2)
print(f"OpenMC k = {k.nominal_value:.5f} +/- {k.std_dev * 1e5:.0f} pcm  (run + tallies {time.time() - t_all:.0f} s)")


def block(arr, r, c):
    """The K x K cells of row r (0 = top = +y) and column c of the core."""
    iy = NC - 1 - r
    return arr[iy * K:(iy + 1) * K, c * K:(c + 1) * K, :]


FACES = ("-x", "+x", "-y", "+y")   # physical faces


def inward(arr, r, c):
    """Per physical face, the K columns from the face inward, each the mean over the face's length: 4 arrays (K, 2 groups, fast first)."""
    b = block(arr, r, c)
    cols = [b.mean(axis=0), b.mean(axis=0)[::-1], b.mean(axis=1), b.mean(axis=1)[::-1]]
    return [x[:, ::-1] for x in cols]


def node_mean(r, c):
    return block(f_mean, r, c).reshape(-1, 2).mean(axis=0)[::-1]


def face_flux(r, c, how):
    """(4 faces, 2 groups) flux at the face, absolute (not divided by the node average). how: ('slab', m columns) or 'extrap'."""
    prof = inward(f_mean, r, c)
    if how == "extrap":
        ms = np.array([1, 2, 4, 8])
        out = []
        for p in prof:
            slabs = np.array([p[:m].mean(axis=0) for m in ms])          # (4, 2)
            coef = np.polynomial.polynomial.polyfit(ms.astype(float), slabs, 2)   # value at m -> 0
            out.append(coef[0])
        return np.array(out)
    return np.array([p[:how[1]].mean(axis=0) for p in prof])


def kind(r, c):
    return kinds[r][c]


def continuity(how):
    """Relative difference of the face flux read from the two sides of every interface, split fuel/fuel and fuel/reflector, per group."""
    res = {"fuel/fuel": [], "fuel/reflector": [], "reflector/reflector": []}
    for r in range(NC):
        for c in range(NC):
            fl = face_flux(r, c, how)
            for (dr, dc), mine, theirs in (((0, 1), 1, 0), ((1, 0), 2, 3)):   # +x neighbour: its -x face; row below: its +y face
                rr, cc = r + dr, c + dc
                if rr >= NC or cc >= NC:
                    continue
                fr = face_flux(rr, cc, how)
                d = np.abs(fl[mine] - fr[theirs]) / (0.5 * (fl[mine] + fr[theirs]))
                a, b = kind(r, c), kind(rr, cc)
                key = "fuel/fuel" if (a != "R" and b != "R") else ("reflector/reflector" if (a == "R" and b == "R") else "fuel/reflector")
                res[key].append(d)
    return {k: (np.sqrt((np.array(v) ** 2).mean(axis=0)) if v else None) for k, v in res.items()}


def adf_of(r, c, how):
    """(4 faces in openndm's order -x, +x, -y, +y; 2 groups fast, thermal). openndm's row 0 is its lowest-y side, so the y faces are swapped."""
    out = face_flux(r, c, how) / node_mean(r, c)
    out[[2, 3]] = out[[3, 2]]
    return out


ESTIMATORS = [("slab 16/K", ("slab", 16)), ("slab 8/K", ("slab", 8)), ("slab 4/K", ("slab", 4)), ("slab 2/K", ("slab", 2)), ("slab 1/K", ("slab", 1)), ("extrapolated", "extrap")]
bc = {f: "vacuum" for f in ("x_min", "x_max", "y_min", "y_max")} | {"z_min": "reflective", "z_max": "reflective"}
dom_index = {u.id: i for i, u in enumerate(lib.domains)}
print(f"K = {K} columns per assembly side; slab m/K is m columns = {100.0 * 1 / K:.2f} % of the pitch each")
print(f"{'estimator':14s} {'fuel/fuel rms %':>16s} {'fuel/refl rms %':>16s}   (fast, thermal)   k - k_OpenMC, pcm (fdm, sanm)")
for name, how in ESTIMATORS:
    cont = continuity(how)
    xs = from_mgxs_library(lib)
    for r in range(NC):
        for c in range(NC):
            xs.set_adf(dom_index[core.universes[r][c].id], adf_of(r, c, how), n_axes=2)
    xs.finalize(warn=False)
    ks = []
    for kernel in ("fdm", "sanm"):
        g = openndm.Geometry.from_openmc(core, dz=[HZ], boundaries=bc, outside="vacuum", subdivide=1)
        ks.append((openndm.Model(g, xs, openndm.Settings(kernel=kernel, verbosity=0)).solve().k_eff - k.nominal_value) * 1e5)
    ff = ", ".join(f"{100 * v:5.1f}" for v in cont["fuel/fuel"])
    fr = ", ".join(f"{100 * v:5.1f}" for v in cont["fuel/reflector"])
    print(f"{name:14s} {ff:>16s} {fr:>16s}   {ks[0]:+7.0f} {ks[1]:+7.0f}")
print(f"total {time.time() - t_all:.0f} s")
