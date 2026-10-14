"""P2, experiment E13: the two-step inputs, built through the library path of E12.

Every piece is a small Monte Carlo run tallied in the CASMO-25 structure (all types, `diffusion-coefficient` among them) and condensed to [0, 0.625 eV, 20 MeV], so each
piece's D is the flux average of E10/E12:
  infinite A, infinite B        one assembly, all faces reflective: the fuel constants of A and B
  strip [B B A | R]             the outer fuel ring next to the reflector with the zone B behind it (reflective far end, vacuum beyond the reflector): the reflector's constants
                                (the zoned cores)
  strips [B A B | R], [A B A | R]   the same with the checkerboard behind (the checkerboard core); the reflector's constants are the mean of the two
The core is assembled by kind (A, B, R) from those pieces alone, no number from the core run, solved by openndm without discontinuity factors, and compared with the core run
saved in data/<core>.npz (k and assembly power; power read in lattice order, E11b). For reference, the same solve with the core run's own constants and the core run's
flux-averaged D (E10: the best the node-level constants can do) and with the old 2-group library (D = 1/(3 <sigma_tr>)).
Throwaway script for the sandbox.

    OMP_NUM_THREADS=8 python e13_two_step_library.py [particles] [batches] [inactive]
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


FULL_TYPES = ["absorption", "transport", "diffusion-coefficient", "nu-fission", "kappa-fission", "chi", "inverse-velocity", "consistent nu-scatter matrix", "consistent scatter matrix"]
INTERMEDIATE = openmc.mgxs.EnergyGroups(openmc.mgxs.GROUP_STRUCTURES["CASMO-25"])
A_, B_ = assembly(fuel_a, "asm A"), assembly(fuel_b, "asm B")
R_ = openmc.Universe(cells=[openmc.Cell(fill=water)], name="reflector")


def run_piece(label, grid, x_bcs, structure=INTERMEDIATE, d_only=False):
    """A row of nodes (grid = [[universes ...]]), y and z reflective; returns the 2-group library (condensed from `structure`), k and the domain list."""
    t0 = time.time()
    ny, nx = len(grid), len(grid[0])
    lattice = openmc.RectLattice()
    lattice.universes = grid
    x0, x1, y0, y1 = -ASM / 2, -ASM / 2 + nx * ASM, -ny * ASM / 2, ny * ASM / 2
    px0, px1 = openmc.XPlane(x0, boundary_type=x_bcs[0]), openmc.XPlane(x1, boundary_type=x_bcs[1])
    py0, py1 = openmc.YPlane(y0, boundary_type="reflective"), openmc.YPlane(y1, boundary_type="reflective")
    pz0, pz1 = openmc.ZPlane(-HZ / 2, boundary_type="reflective"), openmc.ZPlane(HZ / 2, boundary_type="reflective")
    lattice.lower_left, lattice.pitch = (x0, y0), (ASM, ASM)
    geometry = openmc.Geometry(openmc.Universe(cells=[openmc.Cell(fill=lattice, region=+px0 & -px1 & +py0 & -py1 & +pz0 & -pz1)]))
    settings = openmc.Settings()
    settings.particles, settings.batches, settings.inactive = particles, batches, inactive
    settings.source = openmc.IndependentSource(space=openmc.stats.Box((x0, y0, -HZ / 2), (x0 + ASM, y0 + ASM, HZ / 2)), constraints={"fissionable": True})
    lib = openmc.mgxs.Library(geometry)
    lib.energy_groups = structure
    lib.legendre_order, lib.correction = 0, "P0"
    lib.mgxs_types, lib.domain_type, lib.by_nuclide = FULL_TYPES, "universe", False
    domains = lattice_universes(lattice)
    lib.domains = domains
    lib.build_library()
    tallies = openmc.Tallies()
    lib.add_to_tallies_file(tallies, merge=True)
    wd = Path.cwd() / ("piece_" + label.replace(" ", "_").replace("|", ""))
    wd.mkdir(exist_ok=True)
    sp_path = openmc.Model(geometry, materials, settings, tallies).run(output=False, cwd=str(wd))
    with openmc.StatePoint(sp_path) as sp:
        k = sp.keff
        lib.load_from_statepoint(sp)
    cond = lib.get_condensed_library(GROUPS)
    print(f"[{label}] OpenMC k = {k.nominal_value:.5f} +/- {k.std_dev * 1e5:.0f} pcm ({time.time() - t0:.0f} s)")
    return cond, k, domains


def record(cond, domains, universe):
    xs = from_mgxs_library(cond, d_tolerance=10.0)
    return xs.composition([d.id for d in domains].index(universe.id))


def consts(rec):
    return dict(D=np.asarray(rec.D, float), absorption=np.asarray(rec.absorption, float), nu_fission=np.asarray(rec.nu_fission, float),
                kappa_fission=np.asarray(rec.kappa_fission, float), chi=np.asarray(rec.chi, float), scatter=np.asarray(rec.scatter, float).reshape(2, 2),
                inv_velocity=np.asarray(rec.inv_velocity, float))


def mean_consts(a, b):
    return {k: (a[k] + b[k]) / 2 for k in a}


cA, kA, dA = run_piece("infinite A", [[A_]], ("reflective", "reflective"))
cB, kB, dB = run_piece("infinite B", [[B_]], ("reflective", "reflective"))
cS, kS, dS = run_piece("strip B B A R", [[B_, B_, A_, R_]], ("reflective", "vacuum"))
cC1, kC1, dC1 = run_piece("strip B A B R", [[B_, A_, B_, R_]], ("reflective", "vacuum"))
cC2, kC2, dC2 = run_piece("strip A B A R", [[A_, B_, A_, R_]], ("reflective", "vacuum"))
FUEL = {"A": consts(record(cA, dA, A_)), "B": consts(record(cB, dB, B_))}
R_ZONED = consts(record(cS, dS, R_))
# fuel constants from the fuel nodes of the strips, which leak toward the reflector (a harder spectrum than the infinite lattice's)
FUEL_STRIP_Z = {"A": consts(record(cS, dS, A_)), "B": consts(record(cS, dS, B_))}
FUEL_STRIP_C = {"A": mean_consts(consts(record(cC1, dC1, A_)), consts(record(cC2, dC2, A_))), "B": mean_consts(consts(record(cC1, dC1, B_)), consts(record(cC2, dC2, B_)))}
R_CHECK = mean_consts(consts(record(cC1, dC1, R_)), consts(record(cC2, dC2, R_)))
for kd in ("A", "B"):
    print(f"fuel {kd}: D {FUEL[kd]['D'].round(4).tolist()}  absorption {FUEL[kd]['absorption'].round(5).tolist()}  nu-fission {FUEL[kd]['nu_fission'].round(5).tolist()}")
print(f"fuel from the zoned strip: A D {FUEL_STRIP_Z['A']['D'].round(4).tolist()} absorption {FUEL_STRIP_Z['A']['absorption'].round(5).tolist()};  B D {FUEL_STRIP_Z['B']['D'].round(4).tolist()} absorption {FUEL_STRIP_Z['B']['absorption'].round(5).tolist()}")
print(f"reflector (zoned strip): D {R_ZONED['D'].round(4).tolist()} absorption {R_ZONED['absorption'].round(5).tolist()};  (checkerboard strips): D {R_CHECK['D'].round(4).tolist()} absorption {R_CHECK['absorption'].round(5).tolist()}")

# E14: keep the pieces' constants (2 groups, fast first) so that they can be swapped against the core run's without another Monte Carlo run
_pieces = {"infA": FUEL["A"], "infB": FUEL["B"], "stripZ_A": FUEL_STRIP_Z["A"], "stripZ_B": FUEL_STRIP_Z["B"], "stripC_A": FUEL_STRIP_C["A"], "stripC_B": FUEL_STRIP_C["B"],
           "reflZ": R_ZONED, "reflC": R_CHECK}
_out = {f"{pn}__{fld}": np.asarray(v, float) for pn, d in _pieces.items() for fld, v in d.items()}
_out.update({"k_infA": kA.nominal_value, "k_infB": kB.nominal_value, "k_stripZ": kS.nominal_value, "k_stripC1": kC1.nominal_value, "k_stripC2": kC2.nominal_value,
             "particles": particles, "batches": batches})
np.savez_compressed(Path(__file__).resolve().parent / "data" / "pieces.npz", **_out)
print("pieces saved to data/pieces.npz")

import e9_current_d as e9


def solve_with(core, geom, per_kind):
    NC = core["NC"]
    xs = openndm.XSLibrary(2, NC * NC)
    for r in range(NC):
        for c in range(NC):
            xs.set_composition(r * NC + c, **per_kind[core["kinds"][r][c]])
            xs.set_adf(r * NC + c, np.ones((4, 2)), n_axes=2)
    xs.finalize(warn=False)
    fuelmask = np.array([[core["kinds"][r][c] != "R" for c in range(NC)] for r in range(NC)])
    ref = core["power"] / core["power"][fuelmask].mean()
    row = []
    for kernel in ("fdm", "sanm"):
        res = openndm.Model(geom(), xs, openndm.Settings(kernel=kernel, verbosity=0)).solve()
        p = res.radial_power()[::-1]
        p = p / p[fuelmask].mean()
        err = 100 * (p[fuelmask] / ref[fuelmask] - 1)
        row.append(((res.k_eff - float(core["k"])) * 1e5, np.sqrt((err ** 2).mean()), np.abs(err).max()))
    return row


def core_consts(core):
    """The core run's own constants by kind (the mean over the nodes of each kind) with its flux-averaged D (E10), for the comparison row."""
    out = {}
    for kd in ("A", "B", "R"):
        sel = np.array([[core["kinds"][r][c] == kd for c in range(core["NC"])] for r in range(core["NC"])])
        out[kd] = dict(D=core["c_Dflux"][sel].mean(axis=0), absorption=core["c_absorption"][sel].mean(axis=0), nu_fission=core["c_nu_fission"][sel].mean(axis=0),
                       kappa_fission=core["c_kappa_fission"][sel].mean(axis=0), chi=core["c_chi"][sel].mean(axis=0), scatter=core["c_scatter"][sel].mean(axis=0).reshape(2, 2),
                       inv_velocity=core["c_inv_velocity"][sel].mean(axis=0))
    return out


for name, refl, fuel_strip in (("zoned1", R_ZONED, FUEL_STRIP_Z), ("zoned2", R_ZONED, FUEL_STRIP_Z), ("checker1", R_CHECK, FUEL_STRIP_C)):
    core = e9.load(name)
    geom = e9.geometry(core)
    print(f"\n{name}: OpenMC k {float(core['k']):.5f}; nodal k minus OpenMC k (pcm) and assembly power rms/max %, fdm | sanm, no factors")
    cases = [("two-step: fuel from infinite lattices", {"A": FUEL["A"], "B": FUEL["B"], "R": refl}),
             ("two-step: fuel from the strips' fuel nodes", {"A": fuel_strip["A"], "B": fuel_strip["B"], "R": refl}),
             ("core run's constants by kind, E10 D", core_consts(core))]
    for label, per_kind in cases:
        f, s_ = solve_with(core, geom, per_kind)
        print(f"  {label:36s} {f[0]:+7.0f} {f[1]:4.1f}/{f[2]:4.1f}  |  {s_[0]:+7.0f} {s_[1]:4.1f}/{s_[2]:4.1f}")
    f, s_ = e9.solve(core, geom, core["c_Dflux"], "none")
    print(f"  {'core run, every position, E10 D':36s} {f[0]:+7.0f} {f[1]:4.1f}/{f[2]:4.1f}  |  {s_[0]:+7.0f} {s_[1]:4.1f}/{s_[2]:4.1f}")
    f, s_ = e9.solve(core, geom, core["c_D"], "none")
    print(f"  {'core run, every position, old D':36s} {f[0]:+7.0f} {f[1]:4.1f}/{f[2]:4.1f}  |  {s_[0]:+7.0f} {s_[1]:4.1f}/{s_[2]:4.1f}")
print(f"total {time.time() - t_all:.0f} s")
