"""P2, experiment E1 (the oracle): everything the nodal solver needs is tallied in the core run itself.

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


VARIANT = os.environ.get("VARIANT", "")


def adf_of(r, c):
    """(4 faces: -x, +x, -y, +y) x (2 groups: fast, thermal) discontinuity factors of the node at row r, column c."""
    b = block(f_mean, r, c)
    node = b.reshape(-1, 2).mean(axis=0)
    face = [b[:, 0, :].mean(axis=0), b[:, -1, :].mean(axis=0), b[0, :, :].mean(axis=0), b[-1, :, :].mean(axis=0)]
    out = np.array([(f / node)[::-1] for f in face])
    # openndm's row 0 is its lowest-y side, OpenMC's lattice row 0 is the top (+y): its -y face is the physical +y face
    out[[2, 3]] = out[[3, 2]]
    if "noouter" in VARIANT:  # no factor on faces that border the vacuum (openndm's face labels)
        if c == 0:
            out[0] = 1.0
        if c == NC - 1:
            out[1] = 1.0
        if r == 0:
            out[2] = 1.0
        if r == NC - 1:
            out[3] = 1.0
    return out


xs = from_mgxs_library(lib)
dom_index = {u.id: i for i, u in enumerate(lib.domains)}
for r in range(NC):
    for c in range(NC):
        xs.set_adf(dom_index[core.universes[r][c].id], adf_of(r, c), n_axes=2)
xs.finalize(warn=False)
sample = {name: adf_of(r, c).round(3).tolist() for name, (r, c) in {"fuel A (3,3)": (3, 3), "reflector side (3,0)": (3, 0), "fuel next to reflector (3,1)": (3, 1)}.items()}
print("sample ADFs (-x,+x,-y,+y; fast, thermal):", sample)

bc = {f: "vacuum" for f in ("x_min", "x_max", "y_min", "y_max")} | {"z_min": "reflective", "z_max": "reflective"}
for use_adf in (False, True):
    for kernel in ("fdm", "sanm"):
        for sub in (1, 2, 4):
            g = openndm.Geometry.from_openmc(core, dz=[HZ], boundaries=bc, outside="vacuum", subdivide=sub)
            if not use_adf:
                xs0 = from_mgxs_library(lib)
                xs0.finalize(warn=False)
                lib_used = xs0
            else:
                lib_used = xs
            r = openndm.Model(g, lib_used, openndm.Settings(kernel=kernel, verbosity=0)).solve()
            print(f"{'ADF' if use_adf else 'no ADF'} {kernel:4s} x{sub}: k = {r.k_eff:.5f}  {(r.k_eff - k.nominal_value) * 1e5:+7.0f} pcm")
print(f"total {time.time() - t_all:.0f} s")
