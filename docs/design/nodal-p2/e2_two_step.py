"""P2, experiment E2: a two-step recipe for the reflector, against the same 8 x 8 core as P0 and E1.

Step 1 (small Monte Carlo runs, none of them the core):
  - an infinite lattice of each fuel assembly (A, B): group constants and discontinuity factors (ADFs);
  - a one-row strip [fuel | water reflector] with a reflective far side of the fuel and vacuum beyond the reflector,
    for each fuel: the reflector's group constants and the ADFs on both sides of the fuel/reflector face and on the
    reflector's vacuum face. The reflector constants used in the core are the mean of the two strips.
Step 2: the core's solver input is assembled from those pieces by *neighbour*: a fuel node's face toward a reflector
node takes the strip's fuel-side factor, toward fuel the infinite-lattice factor (mean of its four faces); a reflector
node's face toward fuel takes the strip's reflector-side factor, toward the vacuum the strip's vacuum-face factor,
toward another reflector node 1.
The reference is the P0/E1 core run (OpenMC k = 0.94469 +/- 58 pcm, 20,000 x 150, same seed); E1 (everything tallied in the
core run itself) gave -0.7k to -2.5k pcm depending on the width of the face slab, without factors +5.3k.
Throwaway script for the sandbox.

    OMP_NUM_THREADS=8 python e2_two_step.py [particles] [batches] [inactive] [K]
"""
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
REF_K = 0.94469
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
TYPES = ["absorption", "transport", "nu-fission", "kappa-fission", "chi", "inverse-velocity", "consistent nu-scatter matrix", "consistent scatter matrix"]
GROUPS = openmc.mgxs.EnergyGroups([0.0, 0.625, 20.0e6])


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
    return openmc.Universe(cells=[openmc.Cell(fill=lat, region=-openmc.model.RectangularPrism(ASM, ASM))], name=name)


def wrapper(inner, name):
    return openmc.Universe(cells=[openmc.Cell(fill=inner)], name=name)


A, B = assembly(fuel_a, "asm A"), assembly(fuel_b, "asm B")
R = openmc.Universe(cells=[openmc.Cell(fill=water)], name="reflector")


def run_mc(label, lattice, nx, bcs):
    """OpenMC on a 1 x nx row (or 1 x 1) of nodes; constants on the lattice's universes and a fine flux mesh for the ADFs.
    bcs = (x_min, x_max): the y and z sides are reflective. Returns k, library, per-node ADFs (4 faces x 2 groups, fast first)."""
    t0 = time.time()
    x0, x1 = -ASM / 2, -ASM / 2 + nx * ASM
    px0, px1 = openmc.XPlane(x0, boundary_type=bcs[0]), openmc.XPlane(x1, boundary_type=bcs[1])
    py0, py1 = openmc.YPlane(-ASM / 2, boundary_type="reflective"), openmc.YPlane(ASM / 2, boundary_type="reflective")
    pz0, pz1 = openmc.ZPlane(-HZ / 2, boundary_type="reflective"), openmc.ZPlane(HZ / 2, boundary_type="reflective")
    lattice.lower_left, lattice.pitch = (x0, -ASM / 2), (ASM, ASM)
    geometry = openmc.Geometry(openmc.Universe(cells=[openmc.Cell(fill=lattice, region=+px0 & -px1 & +py0 & -py1 & +pz0 & -pz1)]))
    settings = openmc.Settings()
    settings.particles, settings.batches, settings.inactive = particles, batches, inactive
    settings.source = openmc.IndependentSource(space=openmc.stats.Box((-ASM / 2, -ASM / 2, -HZ / 2), (ASM / 2, ASM / 2, HZ / 2)), constraints={"fissionable": True})
    lib = openmc.mgxs.Library(geometry)
    lib.energy_groups = GROUPS
    lib.legendre_order, lib.correction = 0, "P0"
    lib.mgxs_types, lib.domain_type, lib.by_nuclide = TYPES, "universe", False
    lib.domains = lattice_universes(lattice)
    lib.build_library()
    tallies = openmc.Tallies()
    lib.add_to_tallies_file(tallies, merge=True)
    mesh = openmc.RegularMesh()
    mesh.dimension = [nx * K, K, 1]
    mesh.lower_left, mesh.upper_right = [x0, -ASM / 2, -HZ / 2], [x1, ASM / 2, HZ / 2]
    flux = openmc.Tally(name="fine flux")
    flux.filters = [openmc.MeshFilter(mesh), openmc.EnergyFilter(GROUPS.group_edges)]
    flux.scores = ["flux"]
    tallies.append(flux)
    wd = os.path.join(os.getcwd(), label.replace(" ", "_"))
    os.makedirs(wd, exist_ok=True)
    sp_path = openmc.Model(geometry, materials, settings, tallies).run(output=False, cwd=wd)
    with openmc.StatePoint(sp_path) as sp:
        k = sp.keff
        lib.load_from_statepoint(sp)
        f = sp.get_tally(name="fine flux").mean.reshape(K, nx * K, 2)   # [iy, ix, group], thermal first
    adfs = []
    for n in range(nx):
        b = f[:, n * K:(n + 1) * K, :]
        node = b.reshape(-1, 2).mean(axis=0)
        face = [b[:, 0, :].mean(axis=0), b[:, -1, :].mean(axis=0), b[0, :, :].mean(axis=0), b[-1, :, :].mean(axis=0)]
        adfs.append(np.array([(x / node)[::-1] for x in face]))   # -x, +x, -y, +y (physical); fast, thermal
    print(f"[{label}] OpenMC k = {k.nominal_value:.5f} +/- {k.std_dev * 1e5:.0f} pcm ({time.time() - t0:.0f} s)")
    return k, lib, adfs


def single(inner, label):
    lat = openmc.RectLattice()
    lat.universes = [[inner]]
    return run_mc(label, lat, 1, ("reflective", "reflective"))


def strip(inner, label):
    lat = openmc.RectLattice()
    lat.universes = [[inner, R]]
    return run_mc(label, lat, 2, ("reflective", "vacuum"))


def record(lib, universe):
    xs = from_mgxs_library(lib)
    return xs.composition([u.id for u in lib.domains].index(universe.id))


kA, libA, adfA = single(A, "infinite A")
kB, libB, adfB = single(B, "infinite B")
kSA, libSA, adfSA = strip(A, "strip A R")
kSB, libSB, adfSB = strip(B, "strip B R")

# ADF pieces (openndm's face order -x, +x, -y, +y, with openndm's y axis flipped against the lattice rows, so these are used by neighbour, below)
fuel_inf = {"A": adfA[0].mean(axis=0), "B": adfB[0].mean(axis=0)}          # mean of the four faces: (2 groups)
fuel_to_R = {"A": adfSA[0][1], "B": adfSB[0][1]}                          # the fuel node's +x face, toward the reflector
R_to_fuel = (adfSA[1][0] + adfSB[1][0]) / 2                                # the reflector node's -x face
R_to_vac = (adfSA[1][1] + adfSB[1][1]) / 2                                 # the reflector node's +x face (vacuum)
print("fuel infinite ADF (fast, thermal): A", fuel_inf["A"].round(3), " B", fuel_inf["B"].round(3))
print("fuel -> reflector: A", fuel_to_R["A"].round(3), " B", fuel_to_R["B"].round(3))
print("reflector -> fuel", R_to_fuel.round(3), "  reflector -> vacuum", R_to_vac.round(3))

# the core, as in P0/E1: one wrapper universe per position so each position is its own composition
NC = 8
kinds = [[("R" if (i in (0, NC - 1) or j in (0, NC - 1)) else ("A" if (i + j) % 2 == 0 else "B")) for i in range(NC)] for j in range(NC)]
inner = {"A": A, "B": B, "R": R}
core = openmc.RectLattice(name="core")
core.pitch, core.lower_left = (ASM, ASM), (-NC * ASM / 2, -NC * ASM / 2)
core.universes = [[wrapper(inner[kinds[r][c]], f"{kinds[r][c]} {r},{c}") for c in range(NC)] for r in range(NC)]
doms = [core.universes[r][c] for r in range(NC) for c in range(NC)]

# constants by kind: fuel from the infinite lattices, reflector as the mean of the two strips
rA, rB = record(libA, A), record(libB, B)
rR1, rR2 = record(libSA, R), record(libSB, R)
G = 2


def mean_arr(a, b):
    return (np.asarray(a, float) + np.asarray(b, float)) / 2


reflector = dict(D=mean_arr(rR1.D, rR2.D), absorption=mean_arr(rR1.absorption, rR2.absorption), nu_fission=np.zeros(G), kappa_fission=np.zeros(G),
                 chi=np.asarray(rR1.chi, float), scatter=mean_arr(np.asarray(rR1.scatter).reshape(G, G), np.asarray(rR2.scatter).reshape(G, G)),
                 inv_velocity=mean_arr(rR1.inv_velocity, rR2.inv_velocity))
by_kind = {"A": rA, "B": rB}


def make_library(use_adf, same_constants_as_core=False):
    xs = openndm.XSLibrary(G, NC * NC)
    for idx, (r, c) in enumerate((r, c) for r in range(NC) for c in range(NC)):
        kd = kinds[r][c]
        if kd == "R":
            xs.set_composition(idx, **reflector)
        else:
            rec = by_kind[kd]
            xs.set_composition(idx, D=rec.D, absorption=rec.absorption, nu_fission=rec.nu_fission, kappa_fission=rec.kappa_fission, chi=rec.chi,
                               scatter=np.asarray(rec.scatter, float).reshape(G, G), inv_velocity=rec.inv_velocity)
        if use_adf:
            # openndm's faces: -x (column c-1), +x (c+1), -y (row r-1), +y (row r+1); outside the core is vacuum
            vals = []
            for dr, dc in ((0, -1), (0, 1), (-1, 0), (1, 0)):
                rr, cc = r + dr, c + dc
                nb = kinds[rr][cc] if (0 <= rr < NC and 0 <= cc < NC) else "V"
                if kd == "R":
                    vals.append(R_to_fuel if nb in ("A", "B") else (R_to_vac if nb == "V" else np.ones(G)))
                else:
                    vals.append(fuel_to_R[kd] if nb == "R" else fuel_inf[kd])
            xs.set_adf(idx, np.array(vals), n_axes=2)
    xs.finalize(warn=False)
    return xs


bc = {f: "vacuum" for f in ("x_min", "x_max", "y_min", "y_max")} | {"z_min": "reflective", "z_max": "reflective"}
print(f"core (OpenMC reference k = {REF_K}):")
for use_adf in (False, True):
    xs = make_library(use_adf)
    for kernel in ("fdm", "sanm"):
        g = openndm.Geometry.from_openmc(core, domains=doms, dz=[HZ], boundaries=bc, outside="vacuum", subdivide=1)
        r = openndm.Model(g, xs, openndm.Settings(kernel=kernel, verbosity=0)).solve()
        print(f"  {'ADF' if use_adf else 'no ADF'} {kernel:4s}: k = {r.k_eff:.5f}  {(r.k_eff - REF_K) * 1e5:+7.0f} pcm")
print(f"total {time.time() - t_all:.0f} s")
