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
bc = {f: "vacuum" for f in ("x_min", "x_max", "y_min", "y_max")} | {"z_min": "reflective", "z_max": "reflective"}
fuel = np.array([[kinds[r][c] != "R" for c in range(NC)] for r in range(NC)])
ref_p = POWER[0] / POWER[0][fuel].mean()
print(f"REFL = {REFL} layers, {NC} x {NC}: OpenMC k = {kCore.nominal_value:.5f} +/- {kCore.std_dev * 1e5:.0f} pcm; power statistical error rms "
      f"{100 * np.sqrt(((POWER[1] / POWER[0])[fuel] ** 2).mean()):.2f} %")


def equivalence_adf(r, c):
    """(4 faces -x +x -y +y physical, 2 groups fast first): true face flux / the parabola's face flux."""
    D = np.asarray(xs0.composition(dom_pos[core_wrap.universes[r][c].id]).D, float)
    h = ASM
    phi = PHI[(r, c)]
    hom = np.zeros((4, 2))
    for axis, (lo, hi) in enumerate(((0, 1), (2, 3))):
        jl, jr = CURR[r, c, lo], CURR[r, c, hi]
        b = -(jl + jr) / (2 * D)
        cc = -(jr - jl) / (2 * D * h)
        hom[lo] = phi - b * h / 2 + cc * h * h / 6
        hom[hi] = phi + b * h / 2 + cc * h * h / 6
    return FACE[(r, c)] / hom, hom


def old_adf(r, c):
    return FACE[(r, c)] / PHI[(r, c)]


def face_class(r, c, f):
    rr, cc = r + ((0, 0, -1, 1)[f]), c + ((-1, 1, 0, 0)[f])
    if not (0 <= rr < NC and 0 <= cc < NC):
        return "vacuum"
    a, b = kinds[r][c] == "R", kinds[rr][cc] == "R"
    return "reflector/reflector" if (a and b) else ("fuel/reflector" if (a or b) else "fuel/fuel")


# what the factors look like, by class of face (openndm's order: its -y is the physical +y)
for name, fn in (("face / node average (E1)", old_adf), ("equivalence (parabola)", lambda r, c: equivalence_adf(r, c)[0])):
    stats = {}
    for r in range(NC):
        for c in range(NC):
            a = fn(r, c).copy()
            a[[2, 3]] = a[[3, 2]]
            for f in range(4):
                stats.setdefault(face_class(r, c, f), []).append(a[f])
    print(f"{name}: mean and range of the factor by face class (fast | thermal)")
    for cls, v in stats.items():
        v = np.array(v)
        print(f"    {cls:20s} fast {v[:, 0].mean():.3f} [{v[:, 0].min():.3f}, {v[:, 0].max():.3f}]   thermal {v[:, 1].mean():.3f} [{v[:, 1].min():.3f}, {v[:, 1].max():.3f}]")
eq0, hom0 = equivalence_adf(NC // 2, NC // 2)
print("centre node: true face flux / node average (E1):", old_adf(NC // 2, NC // 2).round(3).tolist(), " equivalence:", eq0.round(3).tolist())

# Does Fick's law with the node's own D reproduce the Monte Carlo net current between two neighbouring nodes?
# J_fd = -(2 D_a D_b / (D_a + D_b)) (phi_b - phi_a) / h across the shared x face, from the node-average fluxes (E8 data); J_mc is the tallied net current there.
mid = NC // 2
print(f"current through the shared x face between neighbours, middle row {mid} (J_mc / J_fd; fast | thermal):")
for c in range(NC - 1):
    a_, b_ = (mid, c), (mid, c + 1)
    Da = np.asarray(xs0.composition(dom_pos[core_wrap.universes[mid][c].id]).D, float)
    Db = np.asarray(xs0.composition(dom_pos[core_wrap.universes[mid][c + 1].id]).D, float)
    jfd = -(2 * Da * Db / (Da + Db)) * (PHI[b_] - PHI[a_]) / ASM
    jmc = 0.5 * (CURR[mid, c, 1] + CURR[mid, c + 1, 0])
    print(f"    {kinds[mid][c]}-{kinds[mid][c + 1]} (col {c}|{c + 1}): J_mc {jmc[0]:+.3e} {jmc[1]:+.3e}   ratio {jmc[0] / jfd[0]:6.2f} {jmc[1] / jfd[1]:6.2f}")
# a global per-group factor on D that makes Fick's law reproduce the Monte Carlo currents (least squares over every shared face between two nodes, vacuum faces excluded)
num, den = np.zeros(2), np.zeros(2)
for r in range(NC):
    for c in range(NC):
        for dr, dc, lo, hi in ((0, 1, 1, 0), (1, 0, 2, 3)):     # the +x neighbour (its -x face); the row below, which is lower in y (its +y face)
            rr, cc = r + dr, c + dc
            if rr >= NC or cc >= NC:
                continue
            Da = np.asarray(xs0.composition(dom_pos[core_wrap.universes[r][c].id]).D, float)
            Db = np.asarray(xs0.composition(dom_pos[core_wrap.universes[rr][cc].id]).D, float)
            if dc:
                jfd = -(2 * Da * Db / (Da + Db)) * (PHI[(rr, cc)] - PHI[(r, c)]) / ASM
                jmc = 0.5 * (CURR[r, c, 1] + CURR[rr, cc, 0])
            else:
                jfd = -(2 * Da * Db / (Da + Db)) * (PHI[(r, c)] - PHI[(rr, cc)]) / ASM      # row rr is below row r: the +y current is -D (phi_upper - phi_lower) / h
                jmc = 0.5 * (CURR[r, c, 2] + CURR[rr, cc, 3])     # net +y current through the face between them: node r's lower face, node rr's upper face
            num += jmc * jfd
            den += jfd * jfd
D_SCALE = num / den
print(f"D scale that makes Fick's law match the Monte Carlo currents (fast, thermal): {D_SCALE.round(3).tolist()}")


def library(scaled):
    xs = from_mgxs_library(libCore)
    if scaled:
        for idx in range(xs.n_compositions):
            rec = xs.composition(idx)
            xs.set_composition(idx, D=np.asarray(rec.D, float) * D_SCALE, absorption=rec.absorption, nu_fission=rec.nu_fission, kappa_fission=rec.kappa_fission,
                               chi=rec.chi, scatter=np.asarray(rec.scatter, float).reshape(2, 2), inv_velocity=rec.inv_velocity)
    return xs


EQ = lambda r, c: equivalence_adf(r, c)[0]
ONE = lambda r, c: np.ones((4, 2))
INTERIOR = ("fuel/fuel", "fuel/reflector", "reflector/reflector")
# each mode: which factor function is used on each class of face
MODES = [("no factors", {}),
         ("face / node average, all faces (E1)", {k: old_adf for k in INTERIOR + ("vacuum",)}),
         ("equivalence, all faces", {k: EQ for k in INTERIOR + ("vacuum",)}),
         ("equivalence, interior faces only", {k: EQ for k in INTERIOR}),
         ("equivalence, fuel/fuel only", {"fuel/fuel": EQ}),
         ("equivalence, fuel/reflector only", {"fuel/reflector": EQ}),
         ("equivalence interior + old definition at the vacuum", dict({k: EQ for k in INTERIOR}, vacuum=old_adf)),
         ("old definition on fuel/reflector and vacuum, equivalence fuel/fuel", {"fuel/fuel": EQ, "fuel/reflector": old_adf, "vacuum": old_adf, "reflector/reflector": EQ})]
for scaled, name, by_class in [(sc, nm, bc_) for sc in (False, True) for nm, bc_ in MODES]:
    xs = library(scaled)
    for r in range(NC):
        for c in range(NC):
            mine = {k: fn(r, c) for k, fn in by_class.items()}
            a = np.ones((4, 2))
            # openndm's face order: -x, +x, -y, +y with its -y the physical +y; classes are in openndm's labels, so look the class up there
            phys = {}
            for k, v in mine.items():
                phys[k] = v.copy()
                phys[k][[2, 3]] = phys[k][[3, 2]]
            for f in range(4):
                cls = face_class(r, c, f)
                if cls in phys:
                    a[f] = phys[cls][f]
            xs.set_adf(dom_pos[core_wrap.universes[r][c].id], a, n_axes=2)
    xs.finalize(warn=False)
    row = []
    for kernel in ("fdm", "sanm"):
        g = openndm.Geometry.from_openmc(core_wrap, dz=[HZ], boundaries=bc, outside="vacuum", subdivide=1)
        try:
            res = openndm.Model(g, xs, openndm.Settings(kernel=kernel, verbosity=0)).solve()
        except Exception as e:  # noqa: BLE001
            row.append((float("nan"), float("nan"), float("nan")))
            continue
        nodal = res.radial_power()
        nodal = nodal / nodal[fuel].mean()
        err = 100 * (nodal[fuel] / ref_p[fuel] - 1)
        row.append(((res.k_eff - kCore.nominal_value) * 1e5, np.sqrt((err ** 2).mean()), np.abs(err).max()))
    print(f"  {'D x scale: ' if scaled else 'D as tallied: '}{name:70s} fdm: {row[0][0]:+6.0f} pcm, power rms/max {row[0][1]:4.1f}/{row[0][2]:4.1f} %;  sanm: {row[1][0]:+6.0f} pcm, power rms/max {row[1][1]:4.1f}/{row[1][2]:4.1f} %")
print(f"total {time.time() - t_all:.0f} s")
