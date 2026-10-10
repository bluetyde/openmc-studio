"""P2, experiment E4: reflector and fuel constants that see the checkerboard, against the same 8 x 8 core.

V0  (as E2)  fuel constants and factors from infinite lattices of A and B; reflector from a one-fuel strip [fuel | R].
V1           the reflector's constants, the fuel-to-reflector factors and the reflector's factors from strips with the
             checkerboard behind the reflector: [A B A | R] and [B A B | R] (reflective far end, vacuum beyond R).
V2           V1, and the fuel constants and fuel/fuel factors from a 2 x 2 checkerboard color set [[A B] [B A]] (all faces
             reflective) instead of single-assembly infinite lattices.
Face flux: extrapolated to zero slab width (E3). Reference: OpenMC k = 0.94469 +/- 58 pcm (the P0/E1/E2 core run).
Throwaway script for the sandbox.

    OMP_NUM_THREADS=8 python e4_checkerboard.py [particles] [batches] [inactive] [K]
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


# V0 pieces
kA, libA, adfA = run_mc("infinite A", [[A]], ("reflective", "reflective"))
kB, libB, adfB = run_mc("infinite B", [[B]], ("reflective", "reflective"))
kSA, libSA, adfSA = run_mc("strip A R", [[A, R]], ("reflective", "vacuum"))
kSB, libSB, adfSB = run_mc("strip B R", [[B, R]], ("reflective", "vacuum"))
# V1 pieces: three fuel nodes in a checkerboard behind the reflector
kCA, libCA, adfCA = run_mc("strip B A B R", [[B, A, B, R]], ("reflective", "vacuum"))   # B next to the reflector
kCB, libCB, adfCB = run_mc("strip A B A R", [[A, B, A, R]], ("reflective", "vacuum"))   # A next to the reflector
# V2 piece: color set
kCS, libCS, adfCS = run_mc("color set", [[A, B], [B, A]], ("reflective", "reflective"))

# the core, as in P0/E1: one wrapper universe per position so each position is its own composition
NC = 8
kinds = [[("R" if (i in (0, NC - 1) or j in (0, NC - 1)) else ("A" if (i + j) % 2 == 0 else "B")) for i in range(NC)] for j in range(NC)]
inner = {"A": A, "B": B, "R": R}
core = openmc.RectLattice(name="core")
core.pitch, core.lower_left = (ASM, ASM), (-NC * ASM / 2, -NC * ASM / 2)
core.universes = [[wrapper(inner[kinds[r][c]], f"{kinds[r][c]} {r},{c}") for c in range(NC)] for r in range(NC)]
doms = [core.universes[r][c] for r in range(NC) for c in range(NC)]

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


rec_infA, rec_infB = record(libA, A), record(libB, B)
rec_csA, rec_csB = record(libCS, A), record(libCS, B)
PIECES = {
    "V0 one-fuel strips, infinite fuel": dict(
        fuel={"A": comp_kwargs(rec_infA), "B": comp_kwargs(rec_infB)},
        fuel_ff={"A": adfA[(0, 0)].mean(axis=0), "B": adfB[(0, 0)].mean(axis=0)},
        fuel_to_R={"A": adfSA[(0, 0)][1], "B": adfSB[(0, 0)][1]},
        reflector=reflector_from(record(libSA, R), record(libSB, R)),
        R_to_fuel=(adfSA[(0, 1)][0] + adfSB[(0, 1)][0]) / 2, R_to_vac=(adfSA[(0, 1)][1] + adfSB[(0, 1)][1]) / 2),
    "V1 checkerboard strips": dict(
        fuel={"A": comp_kwargs(rec_infA), "B": comp_kwargs(rec_infB)},
        fuel_ff={"A": adfA[(0, 0)].mean(axis=0), "B": adfB[(0, 0)].mean(axis=0)},
        fuel_to_R={"A": adfCB[(0, 2)][1], "B": adfCA[(0, 2)][1]},
        reflector=reflector_from(record(libCA, R), record(libCB, R)),
        R_to_fuel=(adfCA[(0, 3)][0] + adfCB[(0, 3)][0]) / 2, R_to_vac=(adfCA[(0, 3)][1] + adfCB[(0, 3)][1]) / 2),
}
PIECES["V2 checkerboard strips + color set"] = dict(
    PIECES["V1 checkerboard strips"],
    fuel={"A": comp_kwargs(rec_csA), "B": comp_kwargs(rec_csB)},
    fuel_ff={"A": adfCS[(0, 0)].mean(axis=0), "B": adfCS[(0, 1)].mean(axis=0)})
for name, p in PIECES.items():
    print(f"{name}: fuel->R A {p['fuel_to_R']['A'].round(3)} B {p['fuel_to_R']['B'].round(3)}; R->fuel {p['R_to_fuel'].round(3)}; R->vacuum {p['R_to_vac'].round(3)}; "
          f"R D {np.round(p['reflector']['D'], 4)} absorption {np.round(p['reflector']['absorption'], 5)}")


def make_library(p, use_adf):
    xs = openndm.XSLibrary(G, NC * NC)
    for idx, (r, c) in enumerate((r, c) for r in range(NC) for c in range(NC)):
        kd = kinds[r][c]
        xs.set_composition(idx, **(p["reflector"] if kd == "R" else p["fuel"][kd]))
        if use_adf:
            # openndm's faces: -x (column c-1), +x (c+1), -y (row r-1), +y (row r+1); outside the core is vacuum
            vals = []
            for dr, dc in ((0, -1), (0, 1), (-1, 0), (1, 0)):
                rr, cc = r + dr, c + dc
                nb = kinds[rr][cc] if (0 <= rr < NC and 0 <= cc < NC) else "V"
                if kd == "R":
                    vals.append(p["R_to_fuel"] if nb in ("A", "B") else (p["R_to_vac"] if nb == "V" else np.ones(G)))
                else:
                    vals.append(p["fuel_to_R"][kd] if nb == "R" else p["fuel_ff"][kd])
            xs.set_adf(idx, np.array(vals), n_axes=2)
    xs.finalize(warn=False)
    return xs


bc = {f: "vacuum" for f in ("x_min", "x_max", "y_min", "y_max")} | {"z_min": "reflective", "z_max": "reflective"}
print(f"core (OpenMC reference k = {REF_K}), nodal k minus OpenMC k, pcm:")
for name, p in PIECES.items():
    row = []
    for use_adf in (False, True):
        xs = make_library(p, use_adf)
        for kernel in ("fdm", "sanm"):
            g = openndm.Geometry.from_openmc(core, domains=doms, dz=[HZ], boundaries=bc, outside="vacuum", subdivide=1)
            row.append((openndm.Model(g, xs, openndm.Settings(kernel=kernel, verbosity=0)).solve().k_eff - REF_K) * 1e5)
    print(f"  {name:40s} no factors {row[0]:+7.0f} {row[1]:+7.0f}   with factors {row[2]:+7.0f} {row[3]:+7.0f}   (fdm, sanm)")
print(f"total {time.time() - t_all:.0f} s")
