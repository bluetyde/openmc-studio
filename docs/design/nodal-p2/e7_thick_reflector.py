"""P2, experiment E6: a second core, to see whether the first core's cancellation of errors is luck.

9 x 9 positions: a ring of water around a 7 x 7 fuel region zoned radially (an outer fuel ring of A, 2.4 %, around a 5 x 5 interior of B, 3.1 %).
Two-step input, assembled by neighbour kind: fuel constants from infinite A and B; fuel/fuel factors from the infinite lattices
(A|A, B|B) and from a one-row pair [A B] with all faces reflective (A|B); the reflector's constants, the fuel-to-reflector factor and the reflector's
factors from the strip [B B A | R] (the outer fuel ring has the zone B behind it). Compared with the core run itself (E5's pieces swapped).
Throwaway script for the sandbox.

    OMP_NUM_THREADS=8 python e6_zoned_core.py [particles] [batches] [inactive] [K]
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


REFL = int(os.environ.get("REFL", "1"))
NC = 7 + 2 * REFL
kinds = [[("R" if (min(i, j, NC - 1 - i, NC - 1 - j) < REFL) else ("A" if min(i, j, NC - 1 - i, NC - 1 - j) == REFL else "B")) for i in range(NC)] for j in range(NC)]
inner = {"A": A, "B": B, "R": R}


def run_mc_core(lattice):
    """The core run: constants on every position's wrapper universe, per-node factors from the fine mesh."""
    t0 = time.time()
    box = openmc.model.RectangularPrism(NC * ASM, NC * ASM, boundary_type="vacuum")
    z0, z1 = openmc.ZPlane(-HZ / 2, boundary_type="reflective"), openmc.ZPlane(HZ / 2, boundary_type="reflective")
    geometry = openmc.Geometry(openmc.Universe(cells=[openmc.Cell(fill=lattice, region=-box & +z0 & -z1)]))
    settings = openmc.Settings()
    settings.particles, settings.batches, settings.inactive = particles, batches, inactive
    settings.source = openmc.IndependentSource(space=openmc.stats.Box((-ASM, -ASM, -HZ / 2), (ASM, ASM, HZ / 2)), constraints={"fissionable": True})
    lib = openmc.mgxs.Library(geometry)
    lib.energy_groups = GROUPS
    lib.legendre_order, lib.correction = 0, "P0"
    lib.mgxs_types, lib.domain_type, lib.by_nuclide = TYPES, "universe", False
    lib.domains = lattice_universes(lattice)
    lib.build_library()
    tallies = openmc.Tallies()
    lib.add_to_tallies_file(tallies, merge=True)
    mesh = openmc.RegularMesh()
    mesh.dimension = [NC * K, NC * K, 1]
    mesh.lower_left, mesh.upper_right = [-NC * ASM / 2, -NC * ASM / 2, -HZ / 2], [NC * ASM / 2, NC * ASM / 2, HZ / 2]
    flux = openmc.Tally(name="fine flux")
    flux.filters = [openmc.MeshFilter(mesh), openmc.EnergyFilter(GROUPS.group_edges)]
    flux.scores = ["flux"]
    tallies.append(flux)
    pmesh = openmc.RegularMesh()
    pmesh.dimension = [NC, NC, 1]
    pmesh.lower_left, pmesh.upper_right = [-NC * ASM / 2, -NC * ASM / 2, -HZ / 2], [NC * ASM / 2, NC * ASM / 2, HZ / 2]
    pw = openmc.Tally(name="assembly power")
    pw.filters = [openmc.MeshFilter(pmesh)]
    pw.scores = ["kappa-fission"]
    tallies.append(pw)
    wd = os.path.join(os.getcwd(), "core_run")
    os.makedirs(wd, exist_ok=True)
    sp_path = openmc.Model(geometry, materials, settings, tallies).run(output=False, cwd=wd)
    with openmc.StatePoint(sp_path) as sp:
        k = sp.keff
        lib.load_from_statepoint(sp)
        f = sp.get_tally(name="fine flux").mean.reshape(NC * K, NC * K, 2)
        tp = sp.get_tally(name="assembly power")
        global POWER
        POWER = (tp.mean.reshape(NC, NC)[::-1], tp.std_dev.reshape(NC, NC)[::-1])   # [row (0 = top), column]
        global FLUXN
        FLUXN = np.array([[f[(NC - 1 - r) * K:(NC - r) * K, c * K:(c + 1) * K, :].reshape(-1, 2).mean(axis=0)[::-1] for c in range(NC)] for r in range(NC)])   # [row, col, group fast first]
    ms = np.array([1, 2, 4, 8])
    adfs = {}
    for row in range(NC):
        for col in range(NC):
            iy = NC - 1 - row
            b = f[iy * K:(iy + 1) * K, col * K:(col + 1) * K, :]
            node = b.reshape(-1, 2).mean(axis=0)
            cols = [b.mean(axis=0), b.mean(axis=0)[::-1], b.mean(axis=1), b.mean(axis=1)[::-1]]
            face = [np.polynomial.polynomial.polyfit(ms.astype(float), np.array([p_[:m].mean(axis=0) for m in ms]), 2)[0] for p_ in cols]
            adfs[(row, col)] = np.array([(x / node)[::-1] for x in face])
    print(f"[core run] OpenMC k = {k.nominal_value:.5f} +/- {k.std_dev * 1e5:.0f} pcm ({time.time() - t0:.0f} s)")
    return k, lib, adfs


core_wrap = openmc.RectLattice(name="core run")
core_wrap.pitch, core_wrap.lower_left = (ASM, ASM), (-NC * ASM / 2, -NC * ASM / 2)
core_wrap.universes = [[wrapper(inner[kinds[r][c]], f"{kinds[r][c]} {r},{c}") for c in range(NC)] for r in range(NC)]
kCore, libCore, adfCore = run_mc_core(core_wrap)
doms_w = [core_wrap.universes[r][c] for r in range(NC) for c in range(NC)]
bc = {f: "vacuum" for f in ("x_min", "x_max", "y_min", "y_max")} | {"z_min": "reflective", "z_max": "reflective"}
fuel = np.array([[kinds[r][c] != "R" for c in range(NC)] for r in range(NC)])
ref_p = POWER[0] / POWER[0][fuel].mean()
print(f"REFL = {REFL} layers, {NC} x {NC}: OpenMC k = {kCore.nominal_value:.5f} +/- {kCore.std_dev * 1e5:.0f} pcm; power statistical error rms "
      f"{100 * np.sqrt(((POWER[1] / POWER[0])[fuel] ** 2).mean()):.2f} %")
dom_pos = {u.id: i for i, u in enumerate(libCore.domains)}


def face_class(r, c, f):
    """Class of face f (openndm order -x, +x, -y, +y) of node (r, c): what is on the other side."""
    rr, cc = r + ((0, 0, -1, 1)[f]), c + ((-1, 1, 0, 0)[f])
    if not (0 <= rr < NC and 0 <= cc < NC):
        return "vacuum"
    a, b = kinds[r][c] == "R", kinds[rr][cc] == "R"
    return "reflector/reflector" if (a and b) else ("fuel/reflector" if (a or b) else "fuel/fuel")


MODES = [("no factors", set()), ("all faces (the oracle)", {"vacuum", "reflector/reflector", "fuel/reflector", "fuel/fuel"}),
         ("fuel/reflector faces only", {"fuel/reflector"}), ("fuel/fuel faces only", {"fuel/fuel"}), ("vacuum faces only", {"vacuum"}),
         ("fuel/reflector and vacuum faces", {"fuel/reflector", "vacuum"}), ("all but fuel/fuel", {"vacuum", "reflector/reflector", "fuel/reflector"})]
mid = NC // 2
for name, classes in MODES:
    xs = from_mgxs_library(libCore)
    for r in range(NC):
        for c in range(NC):
            mine = adfCore[(r, c)].copy()
            mine[[2, 3]] = mine[[3, 2]]            # openndm's row 0 is its lowest y
            for f in range(4):
                if face_class(r, c, f) not in classes:
                    mine[f] = 1.0
            xs.set_adf(dom_pos[core_wrap.universes[r][c].id], mine, n_axes=2)
    xs.finalize(warn=False)
    row = []
    for kernel in ("fdm", "sanm"):
        g = openndm.Geometry.from_openmc(core_wrap, dz=[HZ], boundaries=bc, outside="vacuum", subdivide=1)
        res = openndm.Model(g, xs, openndm.Settings(kernel=kernel, verbosity=0)).solve()
        nodal = res.radial_power()
        nodal = nodal / nodal[fuel].mean()
        err = 100 * (nodal[fuel] / ref_p[fuel] - 1)
        row.append(((res.k_eff - kCore.nominal_value) * 1e5, np.sqrt((err ** 2).mean()), np.abs(err).max()))
    print(f"  {name:34s} fdm: {row[0][0]:+6.0f} pcm, power rms/max {row[0][1]:4.1f}/{row[0][2]:4.1f} %;  sanm: {row[1][0]:+6.0f} pcm, power rms/max {row[1][1]:4.1f}/{row[1][2]:4.1f} %")
print(f"total {time.time() - t_all:.0f} s")
