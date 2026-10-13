"""P2, experiment E9a: the Monte Carlo data for the current-preserving D study, written to disk.

One core run (20,000 x 150 by default) of one of three cores, then everything the analysis needs is saved to data/<core>.npz so that
e9_current_d.py can try D estimators, factors and solves in seconds without another run:
  zoned1, zoned2   9 x 9 and 11 x 11 positions, a 7 x 7 fuel region zoned radially (an outer fuel ring of A around an interior of B),
                   with 1 and 2 layers of water reflector (the E6 / E7 cores); vacuum outside
  checker1         8 x 8, a 6 x 6 checkerboard of A and B in one water ring (the P0 / E5 core)
Saved: the kinds map, k, the assembly power (kappa-fission per assembly) and its error, the node-average flux density, the extrapolated face flux
density, the net currents through the node faces (surface-current tally), and the group constants of every position.
Throwaway script for the sandbox.

    CORE=zoned2 OMP_NUM_THREADS=8 python e9a_dump.py [particles] [batches] [inactive] [K]
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


CORE = os.environ.get("CORE", "zoned2")
if CORE.startswith("zoned"):
    REFL = int(CORE[5:])
    NC = 7 + 2 * REFL
    kinds = [[("R" if (min(i, j, NC - 1 - i, NC - 1 - j) < REFL) else ("A" if min(i, j, NC - 1 - i, NC - 1 - j) == REFL else "B")) for i in range(NC)] for j in range(NC)]
elif CORE == "checker1":
    NC = 8
    kinds = [[("R" if (i in (0, NC - 1) or j in (0, NC - 1)) else ("A" if (i + j) % 2 == 0 else "B")) for i in range(NC)] for j in range(NC)]
else:
    raise SystemExit("CORE must be zoned1, zoned2 or checker1")
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
    # E10: the transport cross-section in 120 groups (30 below 0.625 eV, 90 above) in every position, for the flux-averaged D
    fine_edges = np.unique(np.concatenate([np.logspace(-5, np.log10(0.625), 31), np.logspace(np.log10(0.625), np.log10(2.0e7), 91)]))
    libF = openmc.mgxs.Library(geometry)
    libF.energy_groups = openmc.mgxs.EnergyGroups(fine_edges)
    libF.legendre_order, libF.correction = 0, "P0"
    libF.mgxs_types, libF.domain_type, libF.by_nuclide = ["transport"], "universe", False
    libF.domains = lattice_universes(lattice)
    libF.build_library()
    libF.add_to_tallies_file(tallies, merge=True)
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
    smesh = openmc.RegularMesh()
    smesh.dimension = [NC, NC, 1]
    smesh.lower_left, smesh.upper_right = [-NC * ASM / 2, -NC * ASM / 2, -HZ / 2], [NC * ASM / 2, NC * ASM / 2, HZ / 2]
    cur = openmc.Tally(name="node surface current")
    cur.filters = [openmc.MeshSurfaceFilter(smesh), openmc.EnergyFilter(GROUPS.group_edges)]
    cur.scores = ["current"]
    tallies.append(cur)
    wd = os.path.join(os.getcwd(), "core_run")
    os.makedirs(wd, exist_ok=True)
    sp_path = openmc.Model(geometry, materials, settings, tallies).run(output=False, cwd=wd)
    with openmc.StatePoint(sp_path) as sp:
        k = sp.keff
        lib.load_from_statepoint(sp)
        libF.load_from_statepoint(sp)
        n_th = 30
        global DFLUX, DHARM
        DFLUX, DHARM = {}, {}
        for dom in libF.domains:
            mf = libF.get_mgxs(dom, "transport")
            sigf = np.nan_to_num(np.asarray(mf.get_xs(xs_type="macro")).reshape(-1))
            ph = np.nan_to_num(np.asarray(mf.tallies["flux (tracklength)"].get_values()).reshape(-1)[::-1])
            nf = len(sigf)
            dflux, dharm = np.zeros(2), np.zeros(2)
            for gi, idx in enumerate((np.arange(nf - n_th), np.arange(nf - n_th, nf))):     # fast first: the last 30 fine groups are thermal
                w, sg = ph[idx], sigf[idx]
                ok = (sg > 0) & (w > 0)
                dflux[gi] = (w[ok] / (3.0 * sg[ok])).sum() / w[ok].sum()
                dharm[gi] = 1.0 / (3.0 * (w * sg).sum() / w.sum())
            DFLUX[dom.id], DHARM[dom.id] = dflux, dharm
        f = sp.get_tally(name="fine flux").mean.reshape(NC * K, NC * K, 2)
        tp = sp.get_tally(name="assembly power")
        global POWER
        POWER = (tp.mean.reshape(NC, NC)[::-1], tp.std_dev.reshape(NC, NC)[::-1])   # [row (0 = top), column]
        c = sp.get_tally(name="node surface current").mean.reshape(NC * NC, 12, 2)   # [cell (x fastest, y up), surface, group thermal first]
        global CURR
        CURR = np.zeros((NC, NC, 4, 2))   # [row (0 = top), column, face (-x, +x, -y, +y), group fast first]: net current in the +x / +y direction through that face
        for row in range(NC):
            for col in range(NC):
                cc = c[(NC - 1 - row) * NC + col][:, ::-1]
                CURR[row, col, 0] = cc[1] - cc[0]    # x-min: entering minus leaving
                CURR[row, col, 1] = cc[2] - cc[3]    # x-max: leaving minus entering
                CURR[row, col, 2] = cc[5] - cc[4]
                CURR[row, col, 3] = cc[6] - cc[7]
        CURR /= (ASM * HZ)    # crossings per source particle -> current density (per cm^2), the units of the flux density
        global FLUXN
        FLUXN = np.array([[f[(NC - 1 - r) * K:(NC - r) * K, c * K:(c + 1) * K, :].reshape(-1, 2).mean(axis=0)[::-1] for c in range(NC)] for r in range(NC)])   # [row, col, group fast first]
    ms = np.array([1, 2, 4, 8])
    adfs = {}
    global FACE, PHI
    FACE, PHI = {}, {}
    for row in range(NC):
        for col in range(NC):
            iy = NC - 1 - row
            b = f[iy * K:(iy + 1) * K, col * K:(col + 1) * K, :]
            node = b.reshape(-1, 2).mean(axis=0)
            cols = [b.mean(axis=0), b.mean(axis=0)[::-1], b.mean(axis=1), b.mean(axis=1)[::-1]]
            face = [np.polynomial.polynomial.polyfit(ms.astype(float), np.array([p_[:m].mean(axis=0) for m in ms]), 2)[0] for p_ in cols]
            vcell = (ASM / K) ** 2 * HZ
            FACE[(row, col)] = np.array([x[::-1] for x in face]) / vcell     # true face flux density, faces -x +x -y +y, fast first
            PHI[(row, col)] = node[::-1] / vcell                              # node-average flux density, fast first
            adfs[(row, col)] = np.array([(x / node)[::-1] for x in face])
    print(f"[core run] OpenMC k = {k.nominal_value:.5f} +/- {k.std_dev * 1e5:.0f} pcm ({time.time() - t0:.0f} s)")
    return k, lib, adfs


core_wrap = openmc.RectLattice(name="core run")
core_wrap.pitch, core_wrap.lower_left = (ASM, ASM), (-NC * ASM / 2, -NC * ASM / 2)
core_wrap.universes = [[wrapper(inner[kinds[r][c]], f"{kinds[r][c]} {r},{c}") for c in range(NC)] for r in range(NC)]
kCore, libCore, adfCore = run_mc_core(core_wrap)
dom_pos = {u.id: i for i, u in enumerate(libCore.domains)}
xs0 = from_mgxs_library(libCore)
names = ("D", "absorption", "nu_fission", "kappa_fission", "chi", "scatter", "inv_velocity")
consts = {n: np.zeros((NC, NC, 4 if n == "scatter" else 2)) for n in names}
consts["Dflux"] = np.zeros((NC, NC, 2))      # E10: flux-averaged D from the 120-group transport tally
consts["Dharm"] = np.zeros((NC, NC, 2))      # the same tally collapsed the library's way (1 / (3 <sigma_tr>))
for r in range(NC):
    for c in range(NC):
        rec = xs0.composition(dom_pos[core_wrap.universes[r][c].id])
        for n in names:
            consts[n][r, c] = np.asarray(getattr(rec, n), float).reshape(-1)
        consts["Dflux"][r, c] = DFLUX[core_wrap.universes[r][c].id]
        consts["Dharm"][r, c] = DHARM[core_wrap.universes[r][c].id]
face = np.array([[FACE[(r, c)] for c in range(NC)] for r in range(NC)])     # [row, col, face (-x +x -y +y physical), group fast first]
phi = np.array([[PHI[(r, c)] for c in range(NC)] for r in range(NC)])       # [row, col, group]
from pathlib import Path
out = Path(__file__).resolve().parent / "data"
out.mkdir(exist_ok=True)
np.savez_compressed(out / f"{CORE}.npz", kinds=np.array(kinds), k=kCore.nominal_value, k_sd=kCore.std_dev, power=POWER[0], power_sd=POWER[1],
                    curr=CURR, phi=phi, face=face, asm=ASM, hz=HZ, particles=particles, batches=batches, K=K,
                    **{"c_" + n: v for n, v in consts.items()})
print(f"{CORE}: {NC} x {NC}, OpenMC k = {kCore.nominal_value:.5f} +/- {kCore.std_dev * 1e5:.0f} pcm; saved {out / (CORE + '.npz')} ({(out / (CORE + '.npz')).stat().st_size // 1024} kB); total {time.time() - t_all:.0f} s")
