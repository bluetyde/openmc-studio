"""P2, experiment E15: a critical-buckling spectrum correction of the fuel constants, against E14's finding.

E14: the two-step k is high mainly because the fuel's fast-to-thermal scattering is 3 to 6 % larger in the pieces than in the core run's fuel (and the thermal nu-sigma_f
and absorption differ a little the other way): fuel inside a leaking core has a harder flux spectrum than fuel in an infinite lattice. The standard remedy is a B1-type
correction: collapse the fine-group constants with the spectrum of the same homogeneous medium *with leakage* (a buckling B^2 chosen so that k = 1) instead of without.
Here, for the infinite lattices of A and B (CASMO-25, homogenised by the Monte Carlo flux), the homogeneous fine-group balance
    (Sigma_a,g + sum_{h != g} Sigma_s(g->h) + D_g B^2) phi_g - sum_{h != g} Sigma_s(h->g) phi_h = (chi_g / k) sum_h nuSigma_f,h phi_h
is solved at B^2 = 0 and at the B^2 for which k = 1, and the Monte Carlo flux of each fine group is multiplied by the ratio of the two spectra, so that the
spatial self-shielding the Monte Carlo flux carries is kept; the constants (D flux-averaged, absorption, nu-fission, kappa, scattering matrix) are then collapsed to the two groups
with the corrected weights. The core is assembled and solved as in E13 (no factors; reflector from the strip); k against OpenMC's and against the uncorrected infinite-lattice fuel,
the strips' fuel and the core run's own constants by kind.
Throwaway script for the sandbox.

    OMP_NUM_THREADS=8 python e15_critical_spectrum.py [particles] [batches] [inactive]       (REBUILD=1 reruns the Monte Carlo; otherwise data/fine_inf.npz is used)
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
    return cond, k, domains, lib


def record(cond, domains, universe):
    xs = from_mgxs_library(cond, d_tolerance=10.0)
    return xs.composition([d.id for d in domains].index(universe.id))


def consts(rec):
    return dict(D=np.asarray(rec.D, float), absorption=np.asarray(rec.absorption, float), nu_fission=np.asarray(rec.nu_fission, float),
                kappa_fission=np.asarray(rec.kappa_fission, float), chi=np.asarray(rec.chi, float), scatter=np.asarray(rec.scatter, float).reshape(2, 2),
                inv_velocity=np.asarray(rec.inv_velocity, float))


def mean_consts(a, b):
    return {k: (a[k] + b[k]) / 2 for k in a}


import e9_current_d as e9

FINE = Path(__file__).resolve().parent / "data" / "fine_inf.npz"
G = 25


def fine_arrays(lib, domain):
    """Fine-group arrays of one domain (fast group first): D (flux-averaged within nothing: the fine-group 1/(3 sigma_tr)), absorption, nu-fission, kappa-fission, chi, scattering
    matrix [from, to], inverse velocity, and the Monte Carlo flux."""
    xs = from_mgxs_library(lib, d_tolerance=10.0)
    rec = xs.composition([d.id for d in lib.domains].index(domain.id))
    mg = lib.get_mgxs(domain, "transport")
    flux = np.asarray(mg.tallies["flux (tracklength)"].get_values()).reshape(-1)[::-1]
    S = np.asarray(rec.scatter, float).reshape(G, G)
    if np.tril(S, -1).sum() > np.triu(S, 1).sum():      # down-scattering must be above the diagonal in [from, to] with the fast group first
        S = S.T
        print("scattering matrix transposed to [from, to]")
    return dict(D=np.asarray(rec.D, float), absorption=np.asarray(rec.absorption, float), nu_fission=np.asarray(rec.nu_fission, float),
                kappa_fission=np.asarray(rec.kappa_fission, float), chi=np.asarray(rec.chi, float), scatter=S,
                inv_velocity=np.asarray(rec.inv_velocity, float), flux=flux)


if os.environ.get("REBUILD") or not FINE.is_file():
    cA, kA, dA, libA = run_piece("infinite A", [[A_]], ("reflective", "reflective"))
    cB, kB, dB, libB = run_piece("infinite B", [[B_]], ("reflective", "reflective"))
    cS, kS, dS, libS = run_piece("strip B B A R", [[B_, B_, A_, R_]], ("reflective", "vacuum"))
    out = {}
    for tag, lib, dom in (("A", libA, A_), ("B", libB, B_)):
        for f, v in fine_arrays(lib, dom).items():
            out[f"{tag}__{f}"] = v
    out["edges"] = np.asarray(openmc.mgxs.GROUP_STRUCTURES["CASMO-25"], float)
    for f, v in consts(record(cS, dS, R_)).items():
        out[f"reflZ__{f}"] = v
    np.savez_compressed(FINE, **out)
    print("fine data saved", FINE)
F = np.load(FINE)
edges = F["edges"]
fast_fine = (edges[:-1][::-1] >= 0.625 - 1e-9)           # fast first: True for the groups collapsed into the fast group


def spectrum(a, b2):
    """Fine-group spectrum and k of the homogeneous medium with buckling b2 (the balance in the module doc)."""
    S = a["scatter"].copy()
    np.fill_diagonal(S, 0.0)
    M = np.diag(a["absorption"] + S.sum(axis=1) + a["D"] * b2) - S.T
    Fm = np.outer(a["chi"], a["nu_fission"])
    w, v = np.linalg.eig(np.linalg.solve(M, Fm))
    j = np.argmax(w.real)
    phi = np.abs(v[:, j].real)
    return phi / phi.sum(), float(w[j].real)


def critical_b2(a, target=1.0):
    """The buckling at which the homogeneous fine-group medium has k = target (1: critical)."""
    lo, hi = 0.0, 0.05
    k0 = spectrum(a, 0.0)[1]
    if k0 <= target:
        return 0.0
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        if spectrum(a, mid)[1] > target:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def collapse(a, weight, fast=fast_fine):
    """Two-group constants from the fine groups with the given weights (flux-averaged D, flux-weighted others, scattering from the flux of the group it leaves)."""
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
    # chi: the fission-source weighted fraction born in each group
    src = a["nu_fission"] * weight
    chi_f = np.array([(a["chi"][g] * 1.0).sum() for g in groups])
    out["chi"] = chi_f / chi_f.sum()
    return out


FINE_A = {tag: {f: F[f"{tag}__{f}"] for f in ("D", "absorption", "nu_fission", "kappa_fission", "chi", "scatter", "inv_velocity", "flux")} for tag in ("A", "B")}


def corrected_fuel(target):
    out = {}
    for tag in ("A", "B"):
        a = FINE_A[tag]
        phi0, _ = spectrum(a, 0.0)
        phic, _ = spectrum(a, critical_b2(a, target))
        out[tag] = collapse(a, a["flux"] / a["flux"].sum() * (phic / np.maximum(phi0, 1e-300)))
    return out


fuel_plain, fuel_corr = {}, {}
for tag in ("A", "B"):
    a = FINE_A[tag]
    phi0, k0 = spectrum(a, 0.0)
    b2 = critical_b2(a)
    phic, kc = spectrum(a, b2)
    ratio = phic / np.maximum(phi0, 1e-300)
    w_mc = a["flux"] / a["flux"].sum()
    fuel_plain[tag] = collapse(a, w_mc)
    fuel_corr[tag] = collapse(a, w_mc * ratio)
    hard = float((phic * (np.arange(G) < 8)).sum() / (phi0 * (np.arange(G) < 8)).sum())
    print(f"fuel {tag}: k_inf of the homogeneous medium {k0:.4f}; critical B^2 = {b2:.5f} /cm^2 (k = {kc:.4f}); the 8 hardest groups hold {100 * hard:.1f} % as much flux as without leakage")
    print(f"   plain    : D {fuel_plain[tag]['D'].round(4).tolist()} absorption {fuel_plain[tag]['absorption'].round(5).tolist()} nu-fission {fuel_plain[tag]['nu_fission'].round(5).tolist()} scatter {fuel_plain[tag]['scatter'].round(5).reshape(-1).tolist()}")
    print(f"   corrected: D {fuel_corr[tag]['D'].round(4).tolist()} absorption {fuel_corr[tag]['absorption'].round(5).tolist()} nu-fission {fuel_corr[tag]['nu_fission'].round(5).tolist()} scatter {fuel_corr[tag]['scatter'].round(5).reshape(-1).tolist()}")

R_Z = {f.split("__")[1]: np.asarray(F[f], float) for f in F.files if f.startswith("reflZ__")}


def solve_k(core, geom, per_kind):
    NC = core["NC"]
    xs = openndm.XSLibrary(2, NC * NC)
    for r in range(NC):
        for c in range(NC):
            d = per_kind[core["kinds"][r][c]]
            xs.set_composition(r * NC + c, D=d["D"], absorption=d["absorption"], nu_fission=d["nu_fission"], kappa_fission=d["kappa_fission"], chi=d["chi"],
                               scatter=np.asarray(d["scatter"], float).reshape(2, 2), inv_velocity=d["inv_velocity"])
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
        row.append(((res.k_eff - float(core["k"])) * 1e5, np.sqrt((err ** 2).mean())))
    return row


def core_consts(core):
    out = {}
    for kd in ("A", "B", "R"):
        sel = np.array([[core["kinds"][r][c] == kd for c in range(core["NC"])] for r in range(core["NC"])])
        out[kd] = dict(D=core["c_Dflux"][sel].mean(axis=0), absorption=core["c_absorption"][sel].mean(axis=0), nu_fission=core["c_nu_fission"][sel].mean(axis=0),
                       kappa_fission=core["c_kappa_fission"][sel].mean(axis=0), chi=core["c_chi"][sel].mean(axis=0), scatter=core["c_scatter"][sel].mean(axis=0),
                       inv_velocity=core["c_inv_velocity"][sel].mean(axis=0))
    return out


PIECES = np.load(Path(__file__).resolve().parent / "data" / "pieces.npz") if (Path(__file__).resolve().parent / "data" / "pieces.npz").is_file() else None


def strip_fuel(tag, zoned):
    pre = "stripZ_" if zoned else "stripC_"
    return {f: np.asarray(PIECES[f"{pre}{tag}__{f}"], float).reshape(-1) for f in ("D", "absorption", "nu_fission", "kappa_fission", "chi", "scatter", "inv_velocity")}


for name in ("zoned1", "zoned2", "checker1"):
    core = e9.load(name)
    geom = e9.geometry(core)
    zoned = name != "checker1"
    refl = R_Z if zoned else {f: np.asarray(PIECES[f"reflC__{f}"], float).reshape(-1) for f in R_Z}
    own = corrected_fuel(float(core["k"]))
    cases = [("fuel: infinite lattice, plain collapse", {"A": fuel_plain["A"], "B": fuel_plain["B"], "R": refl}),
             ("fuel: infinite lattice, critical-buckling spectrum (k = 1)", {"A": fuel_corr["A"], "B": fuel_corr["B"], "R": refl}),
             (f"fuel: infinite lattice, buckling for the core's own k ({float(core['k']):.3f})", {"A": own["A"], "B": own["B"], "R": refl})]
    if PIECES is not None:
        cases.append(("fuel: the strips' fuel nodes (E13)", {"A": strip_fuel("A", zoned), "B": strip_fuel("B", zoned), "R": refl}))
    cases.append(("the core run's own constants by kind", core_consts(core)))
    print(f"\n{name}: OpenMC k {float(core['k']):.5f}; nodal k minus OpenMC k (pcm) and power rms %, fdm | sanm, no factors")
    for label, pk in cases:
        f, s_ = solve_k(core, geom, pk)
        print(f"  {label:54s} {f[0]:+7.0f} {f[1]:4.1f}  |  {s_[0]:+7.0f} {s_[1]:4.1f}")
print(f"total {time.time() - t_all:.0f} s")
