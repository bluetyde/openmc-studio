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


def run_mc(label, grid, bcs):
    """OpenMC on a grid of nodes (rows listed top first); y and z sides reflective, bcs = (x_min, x_max).
    Returns k, library, {(row, col): ADFs (4 faces -x +x -y +y physical, 2 groups fast first)}."""
    t0 = time.time()
    ny, nx = len(grid), len(grid[0])
    lattice = openmc.RectLattice()
    lattice.universes = grid
    x0, x1, y0, y1 = -ASM / 2, -ASM / 2 + nx * ASM, -ny * ASM / 2, ny * ASM / 2
    px0, px1 = openmc.XPlane(x0, boundary_type=bcs[0]), openmc.XPlane(x1, boundary_type=bcs[1])
    py0, py1 = openmc.YPlane(y0, boundary_type="reflective"), openmc.YPlane(y1, boundary_type="reflective")
    pz0, pz1 = openmc.ZPlane(-HZ / 2, boundary_type="reflective"), openmc.ZPlane(HZ / 2, boundary_type="reflective")
    lattice.lower_left, lattice.pitch = (x0, y0), (ASM, ASM)
    geometry = openmc.Geometry(openmc.Universe(cells=[openmc.Cell(fill=lattice, region=+px0 & -px1 & +py0 & -py1 & +pz0 & -pz1)]))
    settings = openmc.Settings()
    settings.particles, settings.batches, settings.inactive = particles, batches, inactive
    settings.source = openmc.IndependentSource(space=openmc.stats.Box((x0, y0, -HZ / 2), (x0 + ASM, y0 + ASM, HZ / 2)), constraints={"fissionable": True})
    lib = openmc.mgxs.Library(geometry)
    lib.energy_groups = GROUPS
    lib.legendre_order, lib.correction = 0, "P0"
    lib.mgxs_types, lib.domain_type, lib.by_nuclide = TYPES, "universe", False
    lib.domains = lattice_universes(lattice)
    lib.build_library()
    tallies = openmc.Tallies()
    lib.add_to_tallies_file(tallies, merge=True)
    mesh = openmc.RegularMesh()
    mesh.dimension = [nx * K, ny * K, 1]
    mesh.lower_left, mesh.upper_right = [x0, y0, -HZ / 2], [x1, y1, HZ / 2]
    flux = openmc.Tally(name="fine flux")
    flux.filters = [openmc.MeshFilter(mesh), openmc.EnergyFilter(GROUPS.group_edges)]
    flux.scores = ["flux"]
    tallies.append(flux)
    wd = os.path.join(os.getcwd(), label.replace(" ", "_").replace("|", ""))
    os.makedirs(wd, exist_ok=True)
    sp_path = openmc.Model(geometry, materials, settings, tallies).run(output=False, cwd=wd)
    with openmc.StatePoint(sp_path) as sp:
        k = sp.keff
        lib.load_from_statepoint(sp)
        f = sp.get_tally(name="fine flux").mean.reshape(ny * K, nx * K, 2)   # [iy, ix, group], thermal first, iy up
    ms = np.array([1, 2, 4, 8])
    adfs = {}
    for row in range(ny):
        for col in range(nx):
            iy = ny - 1 - row
            b = f[iy * K:(iy + 1) * K, col * K:(col + 1) * K, :]
            node = b.reshape(-1, 2).mean(axis=0)
            cols = [b.mean(axis=0), b.mean(axis=0)[::-1], b.mean(axis=1), b.mean(axis=1)[::-1]]
            face = []
            for p_ in cols:
                slabs = np.array([p_[:m].mean(axis=0) for m in ms])
                face.append(np.polynomial.polynomial.polyfit(ms.astype(float), slabs, 2)[0])
            adfs[(row, col)] = np.array([(x / node)[::-1] for x in face])
    print(f"[{label}] OpenMC k = {k.nominal_value:.5f} +/- {k.std_dev * 1e5:.0f} pcm ({time.time() - t0:.0f} s)")
    return k, lib, adfs


def record(lib, universe):
    xs = from_mgxs_library(lib)
    return xs.composition([u.id for u in lib.domains].index(universe.id))


kA, libA, adfA = run_mc("infinite A", [[A]], ("reflective", "reflective"))
kB, libB, adfB = run_mc("infinite B", [[B]], ("reflective", "reflective"))
kP, libP, adfP = run_mc("pair A B", [[A, B]], ("reflective", "reflective"))
kS, libS, adfS = run_mc("strip B B A R", [[B, B, A, R]], ("reflective", "vacuum"))   # the outer fuel ring next to the reflector, zone B behind it
NC = 9
kinds = [[("R" if (i in (0, NC - 1) or j in (0, NC - 1)) else ("A" if (i in (1, NC - 2) or j in (1, NC - 2)) else "B")) for i in range(NC)] for j in range(NC)]
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
    wd = os.path.join(os.getcwd(), "core_run")
    os.makedirs(wd, exist_ok=True)
    sp_path = openmc.Model(geometry, materials, settings, tallies).run(output=False, cwd=wd)
    with openmc.StatePoint(sp_path) as sp:
        k = sp.keff
        lib.load_from_statepoint(sp)
        f = sp.get_tally(name="fine flux").mean.reshape(NC * K, NC * K, 2)
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


# the core run itself: constants per position (wrapper universes) and per-node factors, as in E1/E3
core_wrap = openmc.RectLattice(name="core run")
core_wrap.pitch, core_wrap.lower_left = (ASM, ASM), (-NC * ASM / 2, -NC * ASM / 2)
core_wrap.universes = [[wrapper(inner[kinds[r][c]], f"{kinds[r][c]} {r},{c}") for c in range(NC)] for r in range(NC)]
kCore, libCore, adfCore = run_mc_core(core_wrap)
doms_w = [core_wrap.universes[r][c] for r in range(NC) for c in range(NC)]
xs_core = from_mgxs_library(libCore)
dom_pos = {u.id: i for i, u in enumerate(libCore.domains)}

G = 2


def mean_arr(a, b):
    return (np.asarray(a, float) + np.asarray(b, float)) / 2


def comp_kwargs(rec):
    return dict(D=rec.D, absorption=rec.absorption, nu_fission=rec.nu_fission, kappa_fission=rec.kappa_fission, chi=rec.chi,
                scatter=np.asarray(rec.scatter, float).reshape(G, G), inv_velocity=rec.inv_velocity)


def reflector_from(rec1, rec2):
    return dict(D=mean_arr(rec1.D, rec2.D), absorption=mean_arr(rec1.absorption, rec2.absorption), nu_fission=np.zeros(G), kappa_fission=np.zeros(G),
                chi=np.asarray(rec1.chi, float), scatter=mean_arr(np.asarray(rec1.scatter).reshape(G, G), np.asarray(rec2.scatter).reshape(G, G)),
                inv_velocity=mean_arr(rec1.inv_velocity, rec2.inv_velocity))


P = dict(fuel={"A": comp_kwargs(record(libA, A)), "B": comp_kwargs(record(libB, B))},
         fuel_ff={("A", "A"): adfA[(0, 0)].mean(axis=0), ("B", "B"): adfB[(0, 0)].mean(axis=0), ("A", "B"): adfP[(0, 0)][1], ("B", "A"): adfP[(0, 1)][0]},
         fuel_to_R={"A": adfS[(0, 2)][1]},
         reflector=reflector_from(record(libS, R), record(libS, R)),
         R_to_fuel=adfS[(0, 3)][0], R_to_vac=adfS[(0, 3)][1])
print("pieces: A|A", P["fuel_ff"][("A", "A")].round(3), "A|B", P["fuel_ff"][("A", "B")].round(3), "B|A", P["fuel_ff"][("B", "A")].round(3), "B|B", P["fuel_ff"][("B", "B")].round(3),
      "A->R", P["fuel_to_R"]["A"].round(3), "R->A", P["R_to_fuel"].round(3), "R->vac", P["R_to_vac"].round(3))


def constants(r, c, source):
    if source == "core" or (source == "strips|corner" and (r, c) in CORNERS):
        return comp_kwargs(xs_core.composition(dom_pos[core_wrap.universes[r][c].id]))
    return P["reflector"] if kinds[r][c] == "R" else P["fuel"][kinds[r][c]]


def factors(r, c, source, only=None):
    """openndm-ordered factors of node (r, c). source 'core': that node's own; 'strips': assembled by neighbour (as V1).
    `only` limits the core's factors to one class of faces: 'fuel-reflector', 'vacuum' or 'fuel-fuel'."""
    mine = adfCore[(r, c)].copy()          # physical -x +x -y +y; row 0 is the top, so openndm's -y is the physical +y
    mine[[2, 3]] = mine[[3, 2]]
    kd = kinds[r][c]
    vals = []
    for f, (dr, dc) in enumerate(((0, -1), (0, 1), (-1, 0), (1, 0))):
        rr, cc = r + dr, c + dc
        nb = kinds[rr][cc] if (0 <= rr < NC and 0 <= cc < NC) else "V"
        if kd == "R":
            strips = P["R_to_fuel"] if nb in ("A", "B") else (P["R_to_vac"] if nb == "V" else np.ones(G))
        else:
            strips = P["fuel_to_R"][kd] if nb == "R" else P["fuel_ff"][(kd, nb)]
        cls = "vacuum" if nb == "V" else ("fuel-fuel" if (kd != "R" and nb != "R") else ("reflector-reflector" if (kd == "R" and nb == "R") else "fuel-reflector"))
        use_core = (source == "core" and (only is None or cls == only)) or (source == "strips|corner" and (r, c) in CORNERS)
        vals.append(mine[f] if use_core else strips)
    return np.array(vals)


def make_library(const_source, factor_source, only=None):
    xs = openndm.XSLibrary(G, NC * NC)
    for idx, (r, c) in enumerate((r, c) for r in range(NC) for c in range(NC)):
        xs.set_composition(idx, **constants(r, c, const_source))
        xs.set_adf(idx, factors(r, c, factor_source, only), n_axes=2)
    xs.finalize(warn=False)
    return xs


bc = {f: "vacuum" for f in ("x_min", "x_max", "y_min", "y_max")} | {"z_min": "reflective", "z_max": "reflective"}
CASES = [("constants core, factors core (the oracle)", "core", "core", None),
         ("constants core, factors strips", "core", "strips", None),
         ("constants strips, factors core", "strips", "core", None),
         ("constants strips, factors strips (two-step)", "strips", "strips", None),
         ("constants strips; core factors on fuel/reflector faces only", "strips", "core", "fuel-reflector"),
         ("constants strips; core factors on vacuum faces only", "strips", "core", "vacuum"),
         ("constants strips; core factors on fuel/fuel faces only", "strips", "core", "fuel-fuel")]
print(f"core run: OpenMC k = {kCore.nominal_value:.5f} +/- {kCore.std_dev * 1e5:.0f} pcm; nodal k minus OpenMC k, pcm (fdm, sanm), one node per assembly:")
for name, cs, fs, only in CASES:
    xs = make_library(cs, fs, only)
    ks = []
    for kernel in ("fdm", "sanm"):
        g = openndm.Geometry.from_openmc(core_wrap, domains=doms_w, dz=[HZ], boundaries=bc, outside="vacuum", subdivide=1)
        ks.append((openndm.Model(g, xs, openndm.Settings(kernel=kernel, verbosity=0)).solve().k_eff - kCore.nominal_value) * 1e5)
    print(f"  {name:62s} {ks[0]:+7.0f} {ks[1]:+7.0f}")
# the constants themselves: how far are the strips' from the core run's, per kind (percent difference of D, absorption, nu-fission)
for kd, positions in (("A", [(1, 4), (1, 1)]), ("B", [(4, 4), (2, 2)]), ("R", [(4, 0), (0, 0)])):
    for (r, c) in positions:
        a, b = constants(r, c, "core"), constants(r, c, "strips")
        diffs = {k: np.round(100 * (np.asarray(b[k], float) / np.asarray(a[k], float) - 1), 1).tolist() for k in ("D", "absorption", "nu_fission") if np.all(np.asarray(a[k], float) != 0)}
        print(f"  strips vs core constants, {kd} at ({r},{c}), % per group (fast, thermal): {diffs}")
print(f"total {time.time() - t_all:.0f} s")
