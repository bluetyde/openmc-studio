"""P2, experiment E12: the flux-averaged D through the normal library path.

OpenMC 0.15.3's `DiffusionCoefficient.get_condensed_xs` multiplies each fine group's D = 1/(3 sigma_tr) by the fine flux, sums and divides by the coarse flux: the flux
average of D that E10 found the solver needs. So the path needs no hand-made D: tally the library in an intermediate group structure with the `diffusion-coefficient`
type among the others, condense it to the two groups with `Library.get_condensed_library`, and let openndm read D from that type (`from_mgxs_library`, which prefers it).
Here, on the 9 x 9 zoned core (one run, the same seeds as E9/E10, so the saved Monte Carlo data of data/zoned1.npz is the reference), for each standard structure
(CASMO-8, 16, 25, 40, 70, MPACT-51, 69; D only for SCALE-252):
  - D of the condensed library over the library's 2-group D (1/(3 <sigma_tr>)), per kind of node, against the 120-group value of E10;
  - the nodal solve of the condensed library as it comes out of `from_mgxs_library` (no hand-injected D): k and assembly power against the Monte Carlo run;
and the time to condense. openndm's check of the diffusion-coefficient estimator against the transport one is a warning (tolerance raised here, because the
two legitimately differ by 20 to 30 %).
Throwaway script for the sandbox.

    OMP_NUM_THREADS=8 python e12_library_path.py [particles] [batches] [inactive]
"""
import os
from pathlib import Path
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
K = 8
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


CORE = os.environ.get("CORE", "zoned1")
if CORE.startswith("zoned"):
    REFL = int(CORE[5:])
    NC = 7 + 2 * REFL
    kinds = [[("R" if (min(i, j, NC - 1 - i, NC - 1 - j) < REFL) else ("A" if min(i, j, NC - 1 - i, NC - 1 - j) == REFL else "B")) for i in range(NC)] for j in range(NC)]
else:
    NC = 8
    kinds = [[("R" if (i in (0, NC - 1) or j in (0, NC - 1)) else ("A" if (i + j) % 2 == 0 else "B")) for i in range(NC)] for j in range(NC)]
inner = {"A": A, "B": B, "R": R}
core = openmc.RectLattice(name="core run")
core.pitch, core.lower_left = (ASM, ASM), (-NC * ASM / 2, -NC * ASM / 2)
core.universes = [[wrapper(inner[kinds[r][c]], f"{kinds[r][c]} {r},{c}") for c in range(NC)] for r in range(NC)]
box = openmc.model.RectangularPrism(NC * ASM, NC * ASM, boundary_type="vacuum")
z0, z1 = openmc.ZPlane(-HZ / 2, boundary_type="reflective"), openmc.ZPlane(HZ / 2, boundary_type="reflective")
geometry = openmc.Geometry(openmc.Universe(cells=[openmc.Cell(fill=core, region=-box & +z0 & -z1)]))
settings = openmc.Settings()
settings.particles, settings.batches, settings.inactive = particles, batches, inactive
settings.source = openmc.IndependentSource(space=openmc.stats.Box((-ASM, -ASM, -HZ / 2), (ASM, ASM, HZ / 2)), constraints={"fissionable": True})
STRUCTS = [x for x in os.environ.get("STRUCTS", "CASMO-8,CASMO-16,CASMO-25,CASMO-40,CASMO-70,MPACT-51,MPACT-69").split(",") if x]
D_ONLY = [x for x in os.environ.get("D_ONLY", "SCALE-252").split(",") if x]
FULL_TYPES = ["absorption", "transport", "diffusion-coefficient", "nu-fission", "kappa-fission", "chi", "inverse-velocity", "consistent nu-scatter matrix", "consistent scatter matrix"]
domains = lattice_universes(core)
libs = {}
for name in STRUCTS + D_ONLY:
    lib = openmc.mgxs.Library(geometry)
    lib.energy_groups = openmc.mgxs.EnergyGroups(openmc.mgxs.GROUP_STRUCTURES[name])
    lib.legendre_order, lib.correction = 0, "P0"
    lib.mgxs_types = FULL_TYPES if name in STRUCTS else ["transport", "diffusion-coefficient"]
    lib.domain_type, lib.domains, lib.by_nuclide = "universe", domains, False
    lib.build_library()
    libs[name] = lib
base = openmc.mgxs.Library(geometry)
base.energy_groups = GROUPS
base.legendre_order, base.correction = 0, "P0"
base.mgxs_types = FULL_TYPES
base.domain_type, base.domains, base.by_nuclide = "universe", domains, False
base.build_library()
tallies = openmc.Tallies()
for lib in list(libs.values()) + [base]:
    lib.add_to_tallies_file(tallies, merge=True)
wd = Path.cwd() / "library_path"
wd.mkdir(exist_ok=True)
t_run = time.time()
import resource
cpu0 = resource.getrusage(resource.RUSAGE_CHILDREN)
sp_path = openmc.Model(geometry, materials, settings, tallies).run(output=False, cwd=str(wd))
t_run = time.time() - t_run
cpu1 = resource.getrusage(resource.RUSAGE_CHILDREN)
print(f"CPU time of the transport run (all threads): {cpu1.ru_utime - cpu0.ru_utime:.0f} s user, {cpu1.ru_stime - cpu0.ru_stime:.0f} s system; wall {t_run:.0f} s; libraries tallied: {len(libs) + 1}")
with openmc.StatePoint(sp_path) as sp:
    k = sp.keff
    for lib in list(libs.values()) + [base]:
        lib.load_from_statepoint(sp)
print(f"{CORE} core {NC} x {NC}: OpenMC k = {k.nominal_value:.5f} +/- {k.std_dev * 1e5:.0f} pcm; run with {len(libs) + 1} libraries {t_run:.0f} s")
ref = np.load(Path(__file__).resolve().parent / "data" / f"{CORE}.npz")
assert abs(float(ref["k"]) - k.nominal_value) < 1e-9, "the saved data is not from this run"
fuel = np.array([[kinds[r][c] != "R" for c in range(NC)] for r in range(NC)])
mc_power = ref["power"] / ref["power"][fuel].mean()
dom_index = {d.id: n for n, d in enumerate(domains)}


def d_by_position(lib):
    out = np.zeros((NC, NC, 2))
    for r in range(NC):
        for c in range(NC):
            m = lib.get_mgxs(core.universes[r][c], "diffusion-coefficient")
            out[r, c] = np.asarray(m.get_xs(xs_type="macro")).reshape(-1)
    return out


def summarise(label, D2, t_cond):
    parts = []
    for kd in ("A", "B", "R"):
        sel = np.array([[kinds[r][c] == kd for c in range(NC)] for r in range(NC)])
        a = (D2 / ref["c_D"])[sel].mean(axis=0)
        b = (D2 / ref["c_Dflux"])[sel].mean(axis=0)
        parts.append(f"{kd}: {a[0]:.3f}|{a[1]:.3f} ({b[0]:.3f}|{b[1]:.3f})")
    print(f"  {label:10s} D / D_library  (and / D_flux of the 120-group tally), fast|thermal:  " + "   ".join(parts) + f"   condense {t_cond:.1f} s")


def solve(lib2, label):
    xs = from_mgxs_library(lib2, d_tolerance=10.0)
    xs.finalize(warn=False)
    out = []
    for kernel in ("fdm", "sanm"):
        g = openndm.Geometry.from_openmc(core, dz=[HZ], boundaries={f: "vacuum" for f in ("x_min", "x_max", "y_min", "y_max")} | {"z_min": "reflective", "z_max": "reflective"},
                                         outside="vacuum", subdivide=1)
        res = openndm.Model(g, xs, openndm.Settings(kernel=kernel, verbosity=0)).solve()
        p = res.radial_power()[::-1]
        p = p / p[fuel].mean()
        err = 100 * (p[fuel] / mc_power[fuel] - 1)
        out.append(((res.k_eff - k.nominal_value) * 1e5, np.sqrt((err ** 2).mean()), np.abs(err).max()))
    print(f"  {label:10s} solve: fdm {out[0][0]:+6.0f} pcm, power {out[0][1]:4.1f}/{out[0][2]:4.1f} %;  sanm {out[1][0]:+6.0f} pcm, power {out[1][1]:4.1f}/{out[1][2]:4.1f} %")


print("the 2-group library as the old path built it (D = 1/(3 <sigma_tr>) at 2 groups; the diffusion-coefficient type there is the same):")
summarise("2 groups", d_by_position(base), 0.0)
solve(base, "2 groups")
print("through an intermediate structure, condensed with get_condensed_library:")
for name in STRUCTS + D_ONLY:
    t0 = time.time()
    cond = libs[name].get_condensed_library(GROUPS)
    t_cond = time.time() - t0
    summarise(name, d_by_position(cond), t_cond)
    if name in STRUCTS:
        solve(cond, name)
print(f"total {time.time() - t_all:.0f} s")
