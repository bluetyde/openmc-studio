"""P0 of the nodal package plan: can an OpenMC lattice model give openndm its group constants with no extra user steps?

A 4 x 4 mini core of 5 x 5 pin assemblies (two enrichments, water reflector ring), 2D (z reflective), vacuum outside.
OpenMC runs the core and tallies a 2-group openmc.mgxs.Library on the assembly universes; openndm reads that library and solves
the same lattice; k is compared. Throwaway script, not a repo file.

    OMP_NUM_THREADS=4 python p0.py [particles] [batches] [inactive]
"""
import sys
import time
import warnings

import numpy as np
import openmc
import openmc.mgxs
import openndm
from openndm.gc import lattice_universes
from openndm.gc.mgxs import from_mgxs_library

particles = int(sys.argv[1]) if len(sys.argv) > 1 else 20000
batches = int(sys.argv[2]) if len(sys.argv) > 2 else 120
inactive = int(sys.argv[3]) if len(sys.argv) > 3 else 30

t_all = time.time()
openmc.reset_auto_ids()


def uo2_fraction(name, enr):
    m = openmc.Material(name=name)
    m.add_nuclide("U235", enr / 100)
    m.add_nuclide("U238", 1 - enr / 100)
    m.add_nuclide("O16", 2.0)
    m.set_density("g/cm3", 10.4)
    return m


fuel_a = uo2_fraction("fuel 2.4%", 2.4)
fuel_b = uo2_fraction("fuel 3.1%", 3.1)
clad = openmc.Material(name="clad")
clad.add_element("Zr", 1.0)
clad.set_density("g/cm3", 6.55)
water = openmc.Material(name="water")
water.add_nuclide("H1", 2.0)
water.add_nuclide("O16", 1.0)
water.set_density("g/cm3", 0.74)
water.add_s_alpha_beta("c_H_in_H2O")
materials = openmc.Materials([fuel_a, fuel_b, clad, water])

PITCH = 1.26
N = 5
ASM = N * PITCH


def pin(fuel):
    f = openmc.ZCylinder(r=0.4096)
    c = openmc.ZCylinder(r=0.475)
    return openmc.Universe(cells=[openmc.Cell(fill=fuel, region=-f), openmc.Cell(fill=clad, region=+f & -c),
                                  openmc.Cell(fill=water, region=+c)])


def tube():
    a = openmc.ZCylinder(r=0.56)
    b = openmc.ZCylinder(r=0.60)
    return openmc.Universe(cells=[openmc.Cell(fill=water, region=-a), openmc.Cell(fill=clad, region=+a & -b),
                                  openmc.Cell(fill=water, region=+b)])


def assembly(fuel, name):
    lat = openmc.RectLattice()
    lat.pitch = (PITCH, PITCH)
    lat.lower_left = (-ASM / 2, -ASM / 2)
    p, g = pin(fuel), tube()
    lat.universes = [[g if (i == N // 2 and j == N // 2) else p for i in range(N)] for j in range(N)]
    box = openmc.model.RectangularPrism(ASM, ASM)  # the lattice fills a box; outside it never happens
    cell = openmc.Cell(fill=lat, region=-box)
    return openmc.Universe(cells=[cell], name=name)


def reflector():
    return openmc.Universe(cells=[openmc.Cell(fill=water)], name="reflector")


A, B, R = assembly(fuel_a, "asm A"), assembly(fuel_b, "asm B"), reflector()
HZ = 1.0
TYPES = ["absorption", "transport", "nu-fission", "kappa-fission", "chi", "inverse-velocity",
         "consistent nu-scatter matrix", "consistent scatter matrix"]


def case(label, lattice, side, n_nodes, outside_bc, subdiv=(1, 2, 4)):
    """Run OpenMC on `lattice` (n x n positions of width ASM), tally 2-group constants on its universes, solve with openndm."""
    t0 = time.time()
    box = openmc.model.RectangularPrism(n_nodes * ASM, n_nodes * ASM, boundary_type=outside_bc)
    z0, z1 = openmc.ZPlane(-HZ / 2, boundary_type="reflective"), openmc.ZPlane(HZ / 2, boundary_type="reflective")
    root = openmc.Universe(cells=[openmc.Cell(fill=lattice, region=-box & +z0 & -z1)])
    geometry = openmc.Geometry(root)
    settings = openmc.Settings()
    settings.particles, settings.batches, settings.inactive = particles, batches, inactive
    settings.source = openmc.IndependentSource(
        space=openmc.stats.Box((-ASM, -ASM, -HZ / 2), (ASM, ASM, HZ / 2)), constraints={"fissionable": True})
    lib = openmc.mgxs.Library(geometry)
    lib.energy_groups = openmc.mgxs.EnergyGroups([0.0, 0.625, 20.0e6])
    lib.legendre_order = 0
    lib.correction = "P0"
    lib.mgxs_types = TYPES
    lib.domain_type = "universe"
    lib.domains = lattice_universes(lattice)
    lib.by_nuclide = False
    lib.build_library()
    tallies = openmc.Tallies()
    lib.add_to_tallies_file(tallies, merge=True)
    model = openmc.Model(geometry, materials, settings, tallies)
    sp_path = model.run(output=False)
    with openmc.StatePoint(sp_path) as sp:
        k = sp.keff
        lib.load_from_statepoint(sp)
    print(f"[{label}] OpenMC k = {k.nominal_value:.5f} +/- {k.std_dev * 1e5:.0f} pcm  ({time.time() - t0:.0f} s)")
    xs = from_mgxs_library(lib)
    xs.finalize(warn=False)
    bc = {f: outside_bc for f in ("x_min", "x_max", "y_min", "y_max")} | {"z_min": "reflective", "z_max": "reflective"}
    for kernel in ("fdm", "sanm"):
        for sub in subdiv:
            g = openndm.Geometry.from_openmc(lattice, dz=[HZ], boundaries=bc, outside=side, subdivide=sub)
            r = openndm.Model(g, xs, openndm.Settings(kernel=kernel, verbosity=0)).solve()
            print(f"    nodal {kernel:4s} x{sub}: k = {r.k_eff:.5f}  {(r.k_eff - k.nominal_value) * 1e5:+7.0f} pcm   {r.runtime * 1000:.0f} ms")
    return k, xs


# 1. infinite lattice of one assembly: isolates the group-constant path (no leakage, no reflector)
for name, asm in (("A", A), ("B", B)):
    lat = openmc.RectLattice()
    lat.pitch = (ASM, ASM)
    lat.lower_left = (-ASM / 2, -ASM / 2)
    lat.universes = [[asm]]
    case(f"infinite {name}", lat, "reflective", 1, "reflective", subdiv=(1,))

# 2. a small core: 8 x 8 positions, 6 x 6 fuel in a checkerboard, a one-assembly water reflector ring, vacuum outside
NC = 8
core = openmc.RectLattice(name="core")
core.pitch = (ASM, ASM)
core.lower_left = (-NC * ASM / 2, -NC * ASM / 2)
core.universes = [[R if (i in (0, NC - 1) or j in (0, NC - 1)) else (A if (i + j) % 2 == 0 else B) for i in range(NC)] for j in range(NC)]
core.outer = R
case("core 8x8", core, "vacuum", NC, "vacuum")
print(f"total {time.time() - t_all:.0f} s")
