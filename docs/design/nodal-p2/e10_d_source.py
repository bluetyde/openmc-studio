"""P2, experiment E10: where the library's diffusion coefficient falls short of the Monte Carlo currents.

E9 found that the fast-group D (D = 1/(3 sigma_tr) with sigma_tr = <sigma_t phi> - <sigma_s1 phi>, flux-weighted over the whole group, OpenMC's TransportXS)
is 25 % (fuel) to 55 % (reflector) too small to carry the Monte Carlo currents. Hypothesis: 1/<sigma_tr> is not <1/sigma_tr>. The group D that follows from
the energy-dependent diffusion equation is the flux average of D(E) = 1/(3 sigma_tr(E)), and that is never smaller than 1/(3 <sigma_tr>) (Jensen); the fast group spans
more than seven decades of energy with resonance dips, so the gap can be large.
Test: on the 9 x 9 zoned core, one run tallies the transport cross-section and the flux in 2 groups (the library's) and in ~300 fine groups (one edge at 0.625 eV)
in three positions (an interior B, an outer-ring A, an edge reflector node). Per coarse group it prints
    D_lib      = 1/(3 sigma_tr) from the 2-group library
    D_harmonic = 1/(3 sum(phi sigma_tr)/sum(phi)) from the fine groups (should agree with D_lib: a check of the collapse)
    D_flux     = sum(phi D)/sum(phi) with D = 1/(3 sigma_tr) per fine group
and D_flux / D_lib against the scales E9 fitted to the currents (fuel 1.24 to 1.30, reflector 1.52 to 1.59 in the fast group).
Throwaway script for the sandbox.

    OMP_NUM_THREADS=8 python e10_d_source.py [particles] [batches] [inactive]
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


REFL = 1
NC = 7 + 2 * REFL
kinds = [[("R" if (min(i, j, NC - 1 - i, NC - 1 - j) < REFL) else ("A" if min(i, j, NC - 1 - i, NC - 1 - j) == REFL else "B")) for i in range(NC)] for j in range(NC)]
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
positions = {"B interior": (4, 4), "A outer ring": (1, 4), "R edge": (4, 0)}
domains = [core.universes[r][c] for (r, c) in positions.values()]
edges = np.unique(np.concatenate([np.logspace(-5, np.log10(0.625), 61), np.logspace(np.log10(0.625), np.log10(2.0e7), 241)]))
fine_groups = openmc.mgxs.EnergyGroups(edges)
libs = {}
for name, g in (("coarse", GROUPS), ("fine", fine_groups)):
    lib = openmc.mgxs.Library(geometry)
    lib.energy_groups = g
    lib.legendre_order, lib.correction = 0, "P0"
    lib.mgxs_types = ["transport"]
    lib.domain_type, lib.domains, lib.by_nuclide = "universe", domains, False
    lib.build_library()
    libs[name] = lib
tallies = openmc.Tallies()
for lib in libs.values():
    lib.add_to_tallies_file(tallies, merge=True)
wd = Path.cwd() / "d_source"
wd.mkdir(exist_ok=True)
sp_path = openmc.Model(geometry, materials, settings, tallies).run(output=False, cwd=str(wd))
with openmc.StatePoint(sp_path) as sp:
    k = sp.keff
    for lib in libs.values():
        lib.load_from_statepoint(sp)
print(f"zoned core {NC} x {NC}: OpenMC k = {k.nominal_value:.5f} +/- {k.std_dev * 1e5:.0f} pcm; {len(edges) - 1} fine groups; {time.time() - t_all:.0f} s")
n_fine = len(edges) - 1
thermal_fine = np.arange(n_fine)[::-1][: 60]          # fast-first indexing: the last 60 fine groups are below 0.625 eV
fast_fine = np.arange(n_fine - 60)
for pname, (r, c) in positions.items():
    dom = core.universes[r][c]
    mc = libs["coarse"].get_mgxs(dom, "transport")
    mf = libs["fine"].get_mgxs(dom, "transport")
    sig2 = np.asarray(mc.get_xs(xs_type="macro")).reshape(-1)             # fast first
    sigf = np.asarray(mf.get_xs(xs_type="macro")).reshape(-1)
    phi_f = np.asarray(mf.tallies["flux (tracklength)"].get_values()).reshape(-1)[::-1]    # the energy filter is ascending; fast first here
    Dl = 1.0 / (3.0 * sig2)
    with np.errstate(divide="ignore", invalid="ignore"):
        Df = 1.0 / (3.0 * sigf)
    out = []
    for gname, idx, gi in (("fast", fast_fine, 0), ("thermal", thermal_fine, 1)):
        w = np.nan_to_num(phi_f[idx])
        ok = np.isfinite(sigf[idx]) & (sigf[idx] > 0) & (w > 0)       # a fine group with no flux or a non-positive (noisy) sigma_tr is left out of the average
        harm = 1.0 / (3.0 * (w * np.nan_to_num(sigf[idx])).sum() / w.sum())
        flux = (w[ok] * Df[idx][ok]).sum() / w[ok].sum()
        out.append((gname, Dl[gi], harm, flux, flux / Dl[gi], float(w[~ok].sum() / w.sum())))
    print(f"{pname:13s}" + "".join(f"  | {g}: D_lib {dl:.4f}  D_harm {h:.4f}  D_flux {f:.4f}  D_flux/D_lib {q:.3f}  (flux in the groups left out: {bad:.2%})" for g, dl, h, f, q, bad in out))

# how many intermediate groups does the collapse need? Merge the fine groups of each coarse group into m intermediate groups (cross sections flux-weighted
# inside each: 1/(3 <sigma_tr>) there), then take the flux average of those D's: m = 1 is the library's D, m = all the fine groups is D_flux.
print("D_flux / D_lib as the number of intermediate groups per coarse group grows (fast | thermal):")
for pname, (r, c) in positions.items():
    dom = core.universes[r][c]
    mc = libs["coarse"].get_mgxs(dom, "transport")
    mf = libs["fine"].get_mgxs(dom, "transport")
    sig2 = np.asarray(mc.get_xs(xs_type="macro")).reshape(-1)
    sigf = np.nan_to_num(np.asarray(mf.get_xs(xs_type="macro")).reshape(-1))
    phi_f = np.nan_to_num(np.asarray(mf.tallies["flux (tracklength)"].get_values()).reshape(-1)[::-1])
    row = []
    for m in (1, 2, 4, 8, 16, 32, 60, 120, 240):
        vals = []
        for idx in (fast_fine, thermal_fine):
            if m > len(idx):
                vals.append(float("nan"))
                continue
            Dm, wm = [], []
            for part in np.array_split(idx, m):
                w = phi_f[part]
                if w.sum() <= 0:
                    continue
                sm = (w * sigf[part]).sum() / w.sum()
                if sm > 0:
                    Dm.append(1.0 / (3.0 * sm))
                    wm.append(w.sum())
            Dm, wm = np.array(Dm), np.array(wm)
            vals.append((wm * Dm).sum() / wm.sum() / (1.0 / (3.0 * sig2[0 if idx is fast_fine else 1])))
        row.append((m, vals))
    print(f"  {pname:13s}" + "".join(f" m={m}: {v[0]:.3f}|{v[1]:.3f}" for m, v in row))
print(f"total {time.time() - t_all:.0f} s")
