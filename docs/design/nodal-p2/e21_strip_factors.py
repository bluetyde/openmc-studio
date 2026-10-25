"""P2, experiment E21: discontinuity factors made from the strip, on the fuel/reflector and vacuum faces.

The plan's reading for the next step: the standard remedy for an interface homogenisation error is a discontinuity factor on the fuel/reflector face and on the vacuum face,
made from the strip itself. With the core run's own tallies it did not help (E8, E9); with strip data it has not been tried. The most it can remove is bounded by the gap between the
two-step k and the k with the core run's own constants (+185 to +702 pcm).

Here the three strips [B B A | R] (zoned cores), [B A B | R] and [A B A | R] (checkerboard) are run with a fine flux mesh (K sub-cells per node along x) and a surface-current tally on the
node mesh, each node with its own wrapper universe (its own constants from the same run, as in E19). For every x face of every node the factor is the generalised-equivalence one of E8:
the true face flux (the fine-mesh flux extrapolated to zero sub-cell width, as E3) over the face flux of the homogeneous parabola built from the node's Monte Carlo average flux and the
Monte Carlo net currents on its two faces (Fick's law with the node's own flux-averaged D). Classes taken from the strips:
    fuel -> reflector face of the last fuel node        ("fuel_R", per kind A or B)
    reflector -> fuel face of the reflector node        ("R_fuel", per kind of its fuel neighbour)
    reflector -> vacuum face of the reflector node      ("R_vac")
Every other face keeps 1 (fuel/fuel from the infinite lattices is about 1; reflector/reflector and the y faces of the reflector are not in a strip).
The factors are then put on the matching faces of the three cores of data/<core>.npz and the cores are solved as in E15 (corrected fuel from the infinite lattices, reflector from the strip,
no factors) against OpenMC's k and assembly power, with each class of face switched on in turn.

    OMP_NUM_THREADS=8 PYTHONPATH=studio:docs/design/nodal-p2 python docs/design/nodal-p2/e21_strip_factors.py [particles batches inactive]    (REUSE=1 reads data/strips_e21.npz instead of running the strips)
"""
import os
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
import openmc
import openmc.mgxs
import openndm
from openndm.gc import lattice_universes
from openndm.gc.mgxs import from_mgxs_library

particles = int(sys.argv[1]) if len(sys.argv) > 1 else 20000
batches = int(sys.argv[2]) if len(sys.argv) > 2 else 150
inactive = int(sys.argv[3]) if len(sys.argv) > 3 else 30
K = int(os.environ.get("K", "80"))     # fine sub-cells per node along x (E3: the face flux needs K = 80; with K = 8 the two sides of an interface differ by 6 % fast and 16 % thermal)
DATA = Path(__file__).resolve().parent / "data"
STRIPS = DATA / "strips_e21.npz"
t_all = time.time()
PITCH, N = 1.26, 5
ASM = N * PITCH
HZ = 1.0
GROUPS = openmc.mgxs.EnergyGroups([0.0, 0.625, 20.0e6])
INTERMEDIATE = openmc.mgxs.EnergyGroups(openmc.mgxs.GROUP_STRUCTURES["CASMO-25"])
FULL_TYPES = ["absorption", "transport", "diffusion-coefficient", "nu-fission", "kappa-fission", "chi", "inverse-velocity", "consistent nu-scatter matrix", "consistent scatter matrix"]
STRIP_ORDERS = {"BBA": ["B", "B", "A", "R"], "BAB": ["B", "A", "B", "R"], "ABA": ["A", "B", "A", "R"], "BBARR": ["B", "B", "A", "R", "R"]}   # the last one: a two-layer reflector, for the 11 x 11 core


def build():
    openmc.reset_auto_ids()

    def uo2(name, enr):
        m = openmc.Material(name=name)
        m.add_nuclide("U235", enr / 100); m.add_nuclide("U238", 1 - enr / 100); m.add_nuclide("O16", 2.0)
        m.set_density("g/cm3", 10.4)
        return m
    fa, fb = uo2("fuel 2.4%", 2.4), uo2("fuel 3.1%", 3.1)
    clad = openmc.Material(name="clad"); clad.add_element("Zr", 1.0); clad.set_density("g/cm3", 6.55)
    water = openmc.Material(name="water")
    water.add_nuclide("H1", 2.0); water.add_nuclide("O16", 1.0); water.set_density("g/cm3", 0.74); water.add_s_alpha_beta("c_H_in_H2O")

    def assembly(fuel, name):
        f, c = openmc.ZCylinder(r=0.4096), openmc.ZCylinder(r=0.475)
        pin = openmc.Universe(cells=[openmc.Cell(fill=fuel, region=-f), openmc.Cell(fill=clad, region=+f & -c), openmc.Cell(fill=water, region=+c)])
        a, b = openmc.ZCylinder(r=0.56), openmc.ZCylinder(r=0.60)
        tube = openmc.Universe(cells=[openmc.Cell(fill=water, region=-a), openmc.Cell(fill=clad, region=+a & -b), openmc.Cell(fill=water, region=+b)])
        lat = openmc.RectLattice()
        lat.pitch, lat.lower_left = (PITCH, PITCH), (-ASM / 2, -ASM / 2)
        lat.universes = [[tube if (i == N // 2 and j == N // 2) else pin for i in range(N)] for j in range(N)]
        return openmc.Universe(cells=[openmc.Cell(fill=lat, region=-openmc.model.RectangularPrism(ASM, ASM))], name=name)
    return {"A": assembly(fa, "A"), "B": assembly(fb, "B"), "R": openmc.Universe(cells=[openmc.Cell(fill=water)], name="R")}, openmc.Materials([fa, fb, clad, water])


def run_strip(label, order, base, materials):
    """One row [order ...] (reflective at the far end, vacuum beyond the last node), a wrapper universe per position. Returns k and, per node: D, flux, face flux, net current."""
    t0 = time.time()
    n = len(order)
    wrappers = [openmc.Universe(cells=[openmc.Cell(fill=base[kd])], name=f"{kd}{i}") for i, kd in enumerate(order)]
    lattice = openmc.RectLattice()
    lattice.universes = [wrappers]
    x0, x1, y0, y1 = -ASM / 2, -ASM / 2 + n * ASM, -ASM / 2, ASM / 2
    px0, px1 = openmc.XPlane(x0, boundary_type="reflective"), openmc.XPlane(x1, boundary_type="vacuum")
    py0, py1 = openmc.YPlane(y0, boundary_type="reflective"), openmc.YPlane(y1, boundary_type="reflective")
    pz0, pz1 = openmc.ZPlane(-HZ / 2, boundary_type="reflective"), openmc.ZPlane(HZ / 2, boundary_type="reflective")
    lattice.lower_left, lattice.pitch = (x0, y0), (ASM, ASM)
    geometry = openmc.Geometry(openmc.Universe(cells=[openmc.Cell(fill=lattice, region=+px0 & -px1 & +py0 & -py1 & +pz0 & -pz1)]))
    settings = openmc.Settings()
    settings.particles, settings.batches, settings.inactive, settings.seed = particles, batches, inactive, 21
    settings.source = openmc.IndependentSource(space=openmc.stats.Box((x0, y0, -HZ / 2), (x0 + ASM, y0 + ASM, HZ / 2)), constraints={"fissionable": True})
    lib = openmc.mgxs.Library(geometry)
    lib.energy_groups = INTERMEDIATE
    lib.legendre_order, lib.correction = 0, "P0"
    lib.mgxs_types, lib.domain_type, lib.by_nuclide = FULL_TYPES, "universe", False
    domains = lattice_universes(lattice)
    lib.domains = domains
    lib.build_library()
    tallies = openmc.Tallies()
    lib.add_to_tallies_file(tallies, merge=True)
    fine = openmc.RegularMesh()
    fine.dimension = [n * K, 1, 1]
    fine.lower_left, fine.upper_right = [x0, y0, -HZ / 2], [x1, y1, HZ / 2]
    flux = openmc.Tally(name="fine flux")
    flux.filters = [openmc.MeshFilter(fine), openmc.EnergyFilter(GROUPS.group_edges)]
    flux.scores = ["flux"]
    tallies.append(flux)
    nodes = openmc.RegularMesh()
    nodes.dimension = [n, 1, 1]
    nodes.lower_left, nodes.upper_right = [x0, y0, -HZ / 2], [x1, y1, HZ / 2]
    cur = openmc.Tally(name="node surface current")
    cur.filters = [openmc.MeshSurfaceFilter(nodes), openmc.EnergyFilter(GROUPS.group_edges)]
    cur.scores = ["current"]
    tallies.append(cur)
    wd = Path(tempfile.mkdtemp(prefix="e21_" + label + "_"))
    sp_path = openmc.Model(geometry, materials, settings, tallies).run(output=False, cwd=str(wd))
    with openmc.StatePoint(sp_path) as sp:
        k = sp.keff
        lib.load_from_statepoint(sp)
        f = sp.get_tally(name="fine flux").mean.reshape(n * K, 2)                      # [sub-cell along x, group thermal first]
        c = sp.get_tally(name="node surface current").mean.reshape(n, 12, 2)           # [node, surface, group thermal first]
    cond = lib.get_condensed_library(GROUPS)
    xs = from_mgxs_library(cond, d_tolerance=10.0)
    ids = [d.id for d in domains]
    D = np.array([np.asarray(xs.composition(ids.index(w.id)).D, float) for w in wrappers])        # [node, group fast first]
    vcell = (ASM / K) * ASM * HZ
    ms = np.array([1, 2, 4, 8])
    phi = np.zeros((n, 2)); face = np.zeros((n, 2, 2)); curr = np.zeros((n, 2, 2))
    for i in range(n):
        b = f[i * K:(i + 1) * K, :][:, ::-1]                                           # [sub-cell, group fast first]
        phi[i] = b.mean(axis=0) / vcell
        for side, cols in enumerate((b, b[::-1])):                                     # -x face: from the -x side; +x face: from the +x side
            face[i, side] = np.polynomial.polynomial.polyfit(ms.astype(float), np.array([cols[:m].mean(axis=0) for m in ms]), 2)[0] / vcell
        cc = c[i][:, ::-1]                                                             # group fast first
        curr[i, 0] = (cc[1] - cc[0]) / (ASM * HZ)                                      # -x face: entering minus leaving = net +x current
        curr[i, 1] = (cc[2] - cc[3]) / (ASM * HZ)                                      # +x face: leaving minus entering
    print(f"[strip {label}] OpenMC k = {k.nominal_value:.5f} +/- {k.std_dev * 1e5:.0f} pcm ({time.time() - t0:.0f} s)", flush=True)
    return dict(k=k.nominal_value, k_std=k.std_dev, D=D, phi=phi, face=face, curr=curr)


def equivalence(strip, i):
    """(2 faces -x +x, 2 groups fast first): true face flux over the parabola's face flux, node i of a strip."""
    D, h = strip["D"][i], ASM
    jl, jr, phi = strip["curr"][i, 0], strip["curr"][i, 1], strip["phi"][i]
    b = -(jl + jr) / (2 * D)
    c = -(jr - jl) / (2 * D * h)
    hom = np.stack([phi - b * h / 2 + c * h * h / 6, phi + b * h / 2 + c * h * h / 6])
    return strip["face"][i] / hom


def old_definition(strip, i):
    return strip["face"][i] / strip["phi"][i]


if os.environ.get("REUSE") and STRIPS.is_file():
    S = np.load(STRIPS)
    strips = {tag: {f: S[f"{tag}__{f}"] for f in ("k", "k_std", "D", "phi", "face", "curr")} for tag in STRIP_ORDERS}
else:
    base, materials = build()
    strips = {tag: run_strip(tag, order, base, materials) for tag, order in STRIP_ORDERS.items()}
    np.savez_compressed(STRIPS, **{f"{tag}__{f}": np.asarray(v) for tag, d in strips.items() for f, v in d.items()})
    print("saved", STRIPS)

# the factors by class; nR = the number of reflector layers behind the fuel in the strip (and in the core they are applied to)
TABLE = {}
for tag, order in STRIP_ORDERS.items():
    n = len(order)
    nR = n - max(i for i, kd in enumerate(order) if kd != "R") - 1
    last = n - nR - 1                                                                # the last fuel node
    kd = order[last]
    TABLE.setdefault(("fuel_R", kd, nR), []).append(equivalence(strips[tag], last)[1])
    TABLE.setdefault(("R_fuel", kd, nR), []).append(equivalence(strips[tag], last + 1)[0])
    for j in range(last + 1, n - 1):                                                 # between two reflector nodes
        TABLE.setdefault(("R_Rout", None, nR), []).append(equivalence(strips[tag], j)[1])
        TABLE.setdefault(("R_Rin", None, nR), []).append(equivalence(strips[tag], j + 1)[0])
    TABLE.setdefault(("R_vac", None, nR), []).append(equivalence(strips[tag], n - 1)[1])
FACTORS = {key: np.mean(v, axis=0) for key, v in TABLE.items()}
print("\nstrip factors (generalised equivalence; fast | thermal):")
for key, v in FACTORS.items():
    print(f"  {str(key):22s} {v.round(3).tolist()}   (strips: {[np.round(x, 3).tolist() for x in TABLE[key]]})")
print("the old definition (face over node average) on the same faces, for comparison:")
for tag, order in STRIP_ORDERS.items():
    n = len(order)
    nR = n - max(i for i, kd in enumerate(order) if kd != "R") - 1
    print(f"  [{tag} | R]  fuel->R {old_definition(strips[tag], n - nR - 1)[1].round(3).tolist()}  R->fuel {old_definition(strips[tag], n - nR)[0].round(3).tolist()}  R->vac {old_definition(strips[tag], n - 1)[1].round(3).tolist()}")
print("continuity at the fuel/reflector interface, face flux of the fuel side over the reflector side (should be 1 within the statistical error):",
      {tag: (strips[tag]["face"][max(i for i, kd in enumerate(o) if kd != "R"), 1] / strips[tag]["face"][max(i for i, kd in enumerate(o) if kd != "R") + 1, 0]).round(3).tolist() for tag, o in STRIP_ORDERS.items()})

# ---- the cores ----
import e9_current_d as e9     # noqa: E402

FINE = DATA / "fine_inf.npz"
F = np.load(FINE)
edges = F["edges"]
G = 25
fast_fine = (edges[:-1][::-1] >= 0.625 - 1e-9)


def spectrum(a, b2):
    S_ = a["scatter"].copy()
    np.fill_diagonal(S_, 0.0)
    M = np.diag(a["absorption"] + S_.sum(axis=1) + a["D"] * b2) - S_.T
    Fm = np.outer(a["chi"], a["nu_fission"])
    w, v = np.linalg.eig(np.linalg.solve(M, Fm))
    j = np.argmax(w.real)
    phi = np.abs(v[:, j].real)
    return phi / phi.sum(), float(w[j].real)


def critical_b2(a, target=1.0):
    lo, hi = 0.0, 0.05
    if spectrum(a, 0.0)[1] <= target:
        return 0.0
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        if spectrum(a, mid)[1] > target:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def collapse(a, weight, fast=fast_fine):
    groups = (fast, ~fast)
    out = {}
    w = [weight[g] / weight[g].sum() for g in groups]
    out["D"] = np.array([(w[i] * a["D"][g]).sum() for i, g in enumerate(groups)])
    for f in ("absorption", "nu_fission", "kappa_fission", "inv_velocity"):
        out[f] = np.array([(w[i] * a[f][g]).sum() for i, g in enumerate(groups)])
    sc = np.zeros((2, 2))
    for i, gi in enumerate(groups):
        for j, gj in enumerate(groups):
            sc[i, j] = (w[i][:, None] * a["scatter"][np.ix_(gi, gj)]).sum()
    out["scatter"] = sc
    chi_f = np.array([(a["chi"][g] * 1.0).sum() for g in groups])
    out["chi"] = chi_f / chi_f.sum()
    return out


FINE_A = {tag: {f: F[f"{tag}__{f}"] for f in ("D", "absorption", "nu_fission", "kappa_fission", "chi", "scatter", "inv_velocity", "flux")} for tag in ("A", "B")}
fuel_corr = {}
for tag in ("A", "B"):
    a = FINE_A[tag]
    phi0, _ = spectrum(a, 0.0)
    phic, _ = spectrum(a, critical_b2(a))
    fuel_corr[tag] = collapse(a, a["flux"] / a["flux"].sum() * (phic / np.maximum(phi0, 1e-300)))
PIECES = np.load(DATA / "pieces.npz")
FIELDS = ("D", "absorption", "nu_fission", "kappa_fission", "chi", "scatter", "inv_velocity")
R_Z = {f: np.asarray(PIECES[f"reflZ__{f}"], float).reshape(-1) for f in FIELDS}
R_C = {f: np.asarray(PIECES[f"reflC__{f}"], float).reshape(-1) for f in FIELDS}
OFFSETS = ((0, -1), (0, 1), (-1, 0), (1, 0))      # openndm's face order: -x, +x, -y, +y (its -y is the physical +y, the row above)


def layer(core, r, c):
    """0 = the outermost ring of nodes, 1 = the next, ..."""
    NC = core["NC"]
    return min(r, c, NC - 1 - r, NC - 1 - c)


def classes_of(core, r, c, f):
    """The key of FACTORS for face f (openndm order) of node (r, c), or None. Reflector faces along a strip's direction only: toward the fuel, toward another reflector node
    one layer further in or out, and out to the vacuum. Faces along a ring (between two nodes of the same layer) and corner nodes' ring faces keep 1."""
    NC, kd = core["NC"], core["kinds"][r][c]
    nR = max(layer(core, r, c) for r in range(NC) for c in range(NC) if core["kinds"][r][c] == "R") + 1
    dr, dc = OFFSETS[f]
    rr, cc = r + dr, c + dc
    inside = 0 <= rr < NC and 0 <= cc < NC
    nb = core["kinds"][rr][cc] if inside else None
    if kd == "R":
        if not inside:
            return ("R_vac", None, nR)
        if nb != "R":
            return ("R_fuel", nb, nR)
        dl = layer(core, rr, cc) - layer(core, r, c)
        return ("R_Rout", None, nR) if dl > 0 else (("R_Rin", None, nR) if dl < 0 else None)      # a neighbour one layer further in: this node's inward face
    return ("fuel_R", kd, nR) if nb == "R" else None


def solve(core, geom, per_kind, enabled, scale_vac=True):
    NC = core["NC"]
    xs = openndm.XSLibrary(2, NC * NC)
    for r in range(NC):
        for c in range(NC):
            d = per_kind[core["kinds"][r][c]]
            xs.set_composition(r * NC + c, D=d["D"], absorption=d["absorption"], nu_fission=d["nu_fission"], kappa_fission=d["kappa_fission"], chi=d["chi"],
                               scatter=np.asarray(d["scatter"], float).reshape(2, 2), inv_velocity=d["inv_velocity"])
            a = np.ones((4, 2))
            for f in range(4):
                key = classes_of(core, r, c, f)
                if key is not None and key[0] in enabled and key in FACTORS:
                    a[f] = FACTORS[key]
            xs.set_adf(r * NC + c, a, n_axes=2)
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


MODES = [("no factors", ()),
         ("fuel -> R and R -> fuel faces", ("fuel_R", "R_fuel")),
         ("fuel -> R face only", ("fuel_R",)),
         ("R -> fuel face only", ("R_fuel",)),
         ("R -> vacuum face only", ("R_vac",)),
         ("fuel/R faces and R/R faces", ("fuel_R", "R_fuel", "R_Rout", "R_Rin")),
         ("all classes", ("fuel_R", "R_fuel", "R_Rout", "R_Rin", "R_vac"))]
for name in ("zoned1", "zoned2", "checker1"):
    core = e9.load(name)
    geom = e9.geometry(core)
    refl = R_Z if name != "checker1" else R_C
    per_kind = {"A": fuel_corr["A"], "B": fuel_corr["B"], "R": refl}
    print(f"\n{name}: OpenMC k {float(core['k']):.5f}; two-step (corrected fuel, strip reflector); nodal k minus OpenMC k (pcm), power rms/max %: fdm | sanm")
    for label, enabled in MODES:
        f, s_ = solve(core, geom, per_kind, enabled)
        print(f"  {label:34s} {f[0]:+7.0f} {f[1]:4.1f}/{f[2]:4.1f}  |  {s_[0]:+7.0f} {s_[1]:4.1f}/{s_[2]:4.1f}")
print(f"total {time.time() - t_all:.0f} s")
