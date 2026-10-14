"""Nodal package P2: what the experiments of docs/design/nodal-p2/ found, kept as tests.

No Monte Carlo at test time except one small run: the cores' Monte Carlo data are the three saved runs in docs/design/nodal-p2/data/*.npz
(20,000 x 150 particles each: an 9 x 9 and an 11 x 11 zoned core and an 8 x 8 checkerboard of two enrichments, vacuum outside). Each test solves the same cores with
openndm and compares with those runs. The reference is OpenMC's own k and its kappa-fission power per assembly, never a number out of the nodal code.

What is held, and the experiment each comes from (plan: docs/design/nodal-package-plan.md):
  DataIntegrity       the saved runs are the ones the plan quotes, and their arrays agree with each other (node flux x kappa sigma_f = tallied power).
  ReadingRules        what a wrapper around openndm must do (E11b, E3 to E5): its per-node results are listed bottom-up, its y faces are the lattice's flipped ones.
                      Each rule has a negative control: reading it the wrong way must fail the check.
  DiffusionCoefficient  the library's D is 1/(3 <sigma_tr>) over the whole group; the flux average of D is 1.2 to 1.35 times larger, and Fick's law with it gives
                      the Monte Carlo currents (E8, E9, E10). With the old D k is +3k to +6k off on every core, with the flux-averaged D within 1.5k.
  LibraryPath         OpenMC's own condensing gives the flux-averaged D from an intermediate structure (E12): equal to a hand formula on the same tallies, and larger with
                      CASMO-25 than with CASMO-8. One small run of an infinite assembly.
  Limits              things the experiments found NOT to work, kept so that a change which fixes them is noticed and the page updated (the parabola at a vacuum face).

Needs openmc, openndm 0.3.0 and nuclear data (OPENMC_CROSS_SECTIONS); run it through `node test/run_all.cjs nodal` (OPENNDM_PYTHON, OPENMC_PYTHON, OPENMC_CROSS_SECTIONS)
or directly:  python test/nodal/test_nodal_p2.py
"""
import os
import sys
import unittest
import warnings
from pathlib import Path

import numpy as np

try:
    import openmc
    import openmc.mgxs
    import openndm
    from openndm.gc import lattice_universes
    from openndm.gc.mgxs import from_mgxs_library
except ImportError as e:  # a test that cannot run is a failure, not a quiet pass
    raise SystemExit(f"test_nodal_p2: needs openmc and openndm ({e}). Run it with `node test/run_all.cjs nodal` and OPENNDM_PYTHON set.")

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "docs" / "design" / "nodal-p2" / "data"
CORES = {"zoned1": 1.01726, "zoned2": 1.03703, "checker1": 0.94469}     # OpenMC k of the saved runs
KINDS = ("A", "B", "R")


# ── the reading rules a wrapper has to follow (kept here until the wrapper exists) ─────────────────────────────────────────────────────
def load(name):
    d = np.load(DATA / f"{name}.npz")
    core = {k: d[k] for k in d.files}
    core["kinds"] = [[str(x) for x in row] for row in d["kinds"]]
    core["NC"] = len(core["kinds"])
    return core


def library(core, D):
    NC = core["NC"]
    xs = openndm.XSLibrary(2, NC * NC)
    for r in range(NC):
        for c in range(NC):
            xs.set_composition(r * NC + c, D=D[r, c], absorption=core["c_absorption"][r, c], nu_fission=core["c_nu_fission"][r, c],
                               kappa_fission=core["c_kappa_fission"][r, c], chi=core["c_chi"][r, c], scatter=core["c_scatter"][r, c].reshape(2, 2),
                               inv_velocity=core["c_inv_velocity"][r, c])
    return xs


def geometry(core):
    NC, asm = core["NC"], float(core["asm"])
    openmc.reset_auto_ids()
    lat = openmc.RectLattice()
    lat.pitch, lat.lower_left = (asm, asm), (-NC * asm / 2, -NC * asm / 2)
    unis = [[openmc.Universe(cells=[openmc.Cell()]) for _ in range(NC)] for _ in range(NC)]
    lat.universes = unis
    bc = {f: "vacuum" for f in ("x_min", "x_max", "y_min", "y_max")} | {"z_min": "reflective", "z_max": "reflective"}
    doms = [unis[r][c] for r in range(NC) for c in range(NC)]
    return lambda: openndm.Geometry.from_openmc(lat, domains=doms, dz=[float(core["hz"])], boundaries=bc, outside="vacuum", subdivide=1)


def solve(core, D, mode="none", swap_y=True, flip_rows=True, kernel="sanm"):
    """k error (pcm) against the Monte Carlo run and the assembly-power error (rms %) over the fuel nodes.
    mode: "none" (no factors) or "old" (face flux over node average). swap_y: hand the y faces over swapped (openndm's -y is the lattice's +y).
    flip_rows: read openndm's per-node results bottom-up (they are listed with physical y up; the lattice and the Monte Carlo arrays list the top row first)."""
    NC = core["NC"]
    xs = library(core, D)
    factors = np.ones((NC, NC, 4, 2)) if mode == "none" else core["face"] / core["phi"][:, :, None, :]
    for r in range(NC):
        for c in range(NC):
            a = factors[r, c].copy()
            if swap_y:
                a[[2, 3]] = a[[3, 2]]
            xs.set_adf(r * NC + c, a, n_axes=2)
    xs.finalize(warn=False)
    res = openndm.Model(geometry(core)(), xs, openndm.Settings(kernel=kernel, verbosity=0)).solve()
    fuel = np.array([[core["kinds"][r][c] != "R" for c in range(NC)] for r in range(NC)])
    ref = core["power"] / core["power"][fuel].mean()
    p = res.radial_power()
    p = p[::-1] if flip_rows else p
    p = p / p[fuel].mean()
    err = 100 * (p[fuel] / ref[fuel] - 1)
    return (res.k_eff - float(core["k"])) * 1e5, float(np.sqrt((err ** 2).mean())), res


def interfaces(core):
    """Shared faces between two nodes: (kind a, kind b, net current a to b, (phi_b - phi_a) / h, D_a, D_b), per group."""
    NC, h, kinds = core["NC"], float(core["asm"]), core["kinds"]
    out = []
    for r in range(NC):
        for c in range(NC):
            if c + 1 < NC:
                j = 0.5 * (core["curr"][r, c, 1] + core["curr"][r, c + 1, 0])
                out.append(((r, c), (r, c + 1), j, (core["phi"][r, c + 1] - core["phi"][r, c]) / h))
            if r + 1 < NC:
                j = -0.5 * (core["curr"][r, c, 2] + core["curr"][r + 1, c, 3])
                out.append(((r, c), (r + 1, c), j, (core["phi"][r + 1, c] - core["phi"][r, c]) / h))
    return out


def fick_ratio(core, D, group, kinds_pair):
    """Median over the shared faces of that pair of kinds of (Monte Carlo net current) / (Fick's law with the harmonic-mean coupling of the two nodes' D)."""
    ratios = []
    for a, b, j, dphi in interfaces(core):
        ka, kb = core["kinds"][a[0]][a[1]], core["kinds"][b[0]][b[1]]
        if tuple(sorted((ka, kb))) != tuple(sorted(kinds_pair)):
            continue
        Da, Db = D[a[0], a[1], group], D[b[0], b[1], group]
        ratios.append(j[group] / (-(2 * Da * Db / (Da + Db)) * dphi[group]))
    return float(np.median(ratios)), len(ratios)


class DataIntegrity(unittest.TestCase):
    def test_the_saved_runs_are_the_ones_the_plan_quotes(self):
        for name, k in CORES.items():
            core = load(name)
            self.assertAlmostEqual(float(core["k"]), k, delta=1e-5, msg=name)
            self.assertEqual((int(core["particles"]), int(core["batches"])), (20000, 150), name)

    def test_node_flux_times_kappa_sigma_f_is_the_tallied_power(self):
        """The Monte Carlo arrays (mesh tallies) and the constants (per-universe tallies) agree at every node, so the arrays are in the right row order."""
        for name in CORES:
            core = load(name)
            p = (core["c_kappa_fission"] * core["phi"]).sum(axis=2)
            fuel = np.array([[core["kinds"][r][c] != "R" for c in range(core["NC"])] for r in range(core["NC"])])
            # the two differ by one constant (units: a flux density against a tally over a mesh cell), so compare after dividing each by its fuel mean
            rel = np.abs((p[fuel] / p[fuel].mean()) / (core["power"][fuel] / core["power"][fuel].mean()) - 1)
            self.assertLess(rel.max(), 1e-6, name)

    def test_the_checkerboard_is_not_symmetric_under_a_vertical_flip(self):
        """What makes it the test of the row order: flipping its rows swaps the two enrichments, the zoned cores are unchanged by it."""
        chk = np.array(load("checker1")["kinds"])
        self.assertFalse((chk == chk[::-1]).all())
        for name in ("zoned1", "zoned2"):
            z = np.array(load(name)["kinds"])
            self.assertTrue((z == z[::-1]).all(), name)


class ReadingRules(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.chk = load("checker1")
        cls.z1 = load("zoned1")

    def test_results_are_listed_bottom_up(self):
        """E11b: read the right way the checkerboard's assembly power is within 4 % rms of OpenMC's; read the other way, A and B are swapped and it is 10 % or worse."""
        _, good, _ = solve(self.chk, self.chk["c_Dflux"], flip_rows=True)
        _, bad, _ = solve(self.chk, self.chk["c_Dflux"], flip_rows=False)
        self.assertLess(good, 4.0)
        self.assertGreater(bad, 10.0)

    def test_the_node_flux_is_listed_bottom_up_too(self):
        """The thermal node flux, flipped, is closer to the Monte Carlo one than as listed (E11b: 3.0 against 6.6 % rms)."""
        _, _, res = solve(self.chk, self.chk["c_Dflux"])
        NC = self.chk["NC"]
        fuel = np.array([[self.chk["kinds"][r][c] != "R" for c in range(NC)] for r in range(NC)])
        f = np.asarray(res.flux)[:, 1].reshape(NC, NC)

        def rms(a):
            a, b = a[fuel] / a[fuel].mean(), self.chk["phi"][:, :, 1][fuel] / self.chk["phi"][:, :, 1][fuel].mean()
            return float(np.sqrt(((a / b - 1) ** 2).mean()))

        self.assertLess(rms(f[::-1]), 0.5 * rms(f))

    def test_the_y_faces_are_handed_over_swapped(self):
        """E1: openndm's -y face is the lattice's +y face. With the factors of the old definition on the zoned core, swapped gives k within 4k of OpenMC's, not swapped is 8k or more further out."""
        k_swapped, _, _ = solve(self.z1, self.z1["c_D"], mode="old", swap_y=True)
        k_wrong, _, _ = solve(self.z1, self.z1["c_D"], mode="old", swap_y=False)
        self.assertLess(abs(k_swapped), 4000)
        self.assertGreater(abs(k_wrong - k_swapped), 8000)


class DiffusionCoefficient(unittest.TestCase):
    def test_old_d_gives_k_far_too_high_and_the_flux_averaged_d_does_not(self):
        """E10: no factors, SANM. The library's D = 1/(3 <sigma_tr>): +3k to +6k on every core; the flux-averaged D: within 1.5k, power within 5 % rms."""
        for name in CORES:
            core = load(name)
            k_old, _, _ = solve(core, core["c_D"])
            k_new, power, _ = solve(core, core["c_Dflux"])
            self.assertTrue(3000 < k_old < 6500, f"{name}: old D {k_old:+.0f} pcm")
            self.assertLess(abs(k_new), 1500, f"{name}: flux-averaged D {k_new:+.0f} pcm")
            self.assertLess(power, 5.0, name)

    def test_the_flux_averaged_d_is_larger_by_the_amounts_found(self):
        """E10: fast group 1.2 to 1.3 in the fuel and 1.3 to 1.4 in the reflector, thermal group 1.15 to 1.25 (the same on all three cores)."""
        for name in CORES:
            core = load(name)
            for kd, fast, thermal in (("A", (1.20, 1.28), (1.15, 1.25)), ("B", (1.20, 1.28), (1.15, 1.26)), ("R", (1.28, 1.40), (1.12, 1.25))):
                sel = np.array([[core["kinds"][r][c] == kd for c in range(core["NC"])] for r in range(core["NC"])])
                ratio = (core["c_Dflux"] / core["c_D"])[sel].mean(axis=0)
                self.assertTrue(fast[0] < ratio[0] < fast[1], f"{name} {kd} fast {ratio[0]:.3f}")
                self.assertTrue(thermal[0] < ratio[1] < thermal[1], f"{name} {kd} thermal {ratio[1]:.3f}")

    def test_the_library_d_is_the_inverse_of_the_averaged_sigma_tr(self):
        """E10's collapse check: the 2-group library's D equals 1/(3 <sigma_tr>) of the 120-group tally collapsed the library's way: the mean over the nodes of each kind
        within 0.5 %, every node within 4 % (the worst are a few reflector corner nodes with little flux, 0.6 to 2.6 %)."""
        for name in CORES:
            core = load(name)
            rel = core["c_Dharm"] / core["c_D"] - 1
            self.assertLess(np.abs(rel).max(), 0.04, name)
            for kd in KINDS:
                sel = np.array([[core["kinds"][r][c] == kd for c in range(core["NC"])] for r in range(core["NC"])])
                self.assertLess(np.abs(rel[sel].mean(axis=0)).max(), 0.005, f"{name} {kd}")

    def test_ficks_law_with_the_flux_averaged_d_gives_the_monte_carlo_current_between_fuel_nodes(self):
        """E9, E10: fast group, between two fuel nodes (the flat interior). Old D: the Monte Carlo current is 1.15 to 1.45 times Fick's; flux-averaged D: 0.9 to 1.1."""
        for name in CORES:
            core = load(name)
            pairs = [("B", "B")] if name != "checker1" else [("A", "B")]
            for pair in pairs:
                old, n = fick_ratio(core, core["c_D"], 0, pair)
                new, _ = fick_ratio(core, core["c_Dflux"], 0, pair)
                self.assertGreater(n, 5, name)
                self.assertTrue(1.15 < old < 1.45, f"{name} {pair} old D: {old:.2f}")
                self.assertTrue(0.9 < new < 1.1, f"{name} {pair} flux-averaged D: {new:.2f}")


class LibraryPath(unittest.TestCase):
    """One small run: an infinite lattice of a 5 x 5 pin assembly with a guide tube, tallied in CASMO-8 and CASMO-25 and in the 2 groups."""

    @classmethod
    def setUpClass(cls):
        if not os.environ.get("OPENMC_CROSS_SECTIONS"):
            raise SystemExit("test_nodal_p2: LibraryPath needs OPENMC_CROSS_SECTIONS")
        import tempfile
        openmc.reset_auto_ids()
        fuel = openmc.Material(name="UO2 2.4 %")
        fuel.add_nuclide("U235", 0.024)
        fuel.add_nuclide("U238", 0.976)
        fuel.add_nuclide("O16", 2.0)
        fuel.set_density("g/cm3", 10.4)
        clad = openmc.Material(name="clad")
        clad.add_element("Zr", 1.0)
        clad.set_density("g/cm3", 6.55)
        water = openmc.Material(name="water")
        water.add_nuclide("H1", 2.0)
        water.add_nuclide("O16", 1.0)
        water.set_density("g/cm3", 0.74)
        water.add_s_alpha_beta("c_H_in_H2O")
        pitch, n = 1.26, 5
        f, c1 = openmc.ZCylinder(r=0.4096), openmc.ZCylinder(r=0.475)
        pin = openmc.Universe(cells=[openmc.Cell(fill=fuel, region=-f), openmc.Cell(fill=clad, region=+f & -c1), openmc.Cell(fill=water, region=+c1)])
        g1, g2 = openmc.ZCylinder(r=0.56), openmc.ZCylinder(r=0.60)
        tube = openmc.Universe(cells=[openmc.Cell(fill=water, region=-g1), openmc.Cell(fill=clad, region=+g1 & -g2), openmc.Cell(fill=water, region=+g2)])
        lat = openmc.RectLattice()
        lat.pitch, lat.lower_left = (pitch, pitch), (-n * pitch / 2, -n * pitch / 2)
        lat.universes = [[tube if (i == n // 2 and j == n // 2) else pin for i in range(n)] for j in range(n)]
        side = n * pitch
        box = openmc.model.RectangularPrism(side, side, boundary_type="reflective")
        z0, z1 = openmc.ZPlane(-0.5, boundary_type="reflective"), openmc.ZPlane(0.5, boundary_type="reflective")
        asm = openmc.Universe(cells=[openmc.Cell(fill=lat, region=-box & +z0 & -z1)])
        geometry = openmc.Geometry(asm)
        settings = openmc.Settings()
        settings.particles, settings.batches, settings.inactive = 4000, 35, 10
        settings.source = openmc.IndependentSource(space=openmc.stats.Box((-side / 2, -side / 2, -0.5), (side / 2, side / 2, 0.5)), constraints={"fissionable": True})
        types = ["absorption", "transport", "diffusion-coefficient", "nu-fission", "kappa-fission", "chi", "inverse-velocity", "consistent nu-scatter matrix", "consistent scatter matrix"]
        cls.two = openmc.mgxs.EnergyGroups([0.0, 0.625, 20.0e6])
        cls.libs = {}
        tallies = openmc.Tallies()
        for name, edges in (("2", cls.two.group_edges), ("CASMO-8", openmc.mgxs.GROUP_STRUCTURES["CASMO-8"]), ("CASMO-25", openmc.mgxs.GROUP_STRUCTURES["CASMO-25"])):
            lib = openmc.mgxs.Library(geometry)
            lib.energy_groups = openmc.mgxs.EnergyGroups(edges)
            lib.legendre_order, lib.correction = 0, "P0"
            lib.mgxs_types, lib.domain_type, lib.by_nuclide = types, "universe", False
            lib.domains = [asm]
            lib.build_library()
            lib.add_to_tallies(tallies, merge=True) if hasattr(lib, "add_to_tallies") else lib.add_to_tallies_file(tallies, merge=True)
            cls.libs[name] = lib
        cls.domain = asm
        work = tempfile.mkdtemp(prefix="nodal-p2-lib-")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            sp_path = openmc.Model(geometry, openmc.Materials([fuel, clad, water]), settings, tallies).run(output=False, cwd=work)
            with openmc.StatePoint(sp_path) as sp:
                for lib in cls.libs.values():
                    lib.load_from_statepoint(sp)

    def fast_d(self, lib):
        return float(np.asarray(lib.get_mgxs(self.domain, "diffusion-coefficient").get_xs(xs_type="macro")).reshape(-1)[0])

    def test_condensing_is_the_flux_average_of_d(self):
        """The condensed fast D equals sum(phi_j / (3 sigma_tr,j)) / sum(phi_j) over the CASMO-25 groups above 0.625 eV, computed here from the same tallies."""
        lib = self.libs["CASMO-25"]
        cond = lib.get_condensed_library(self.two)
        mg = lib.get_mgxs(self.domain, "transport")
        sigma = np.asarray(mg.get_xs(xs_type="macro")).reshape(-1)                     # fast group first
        phi = np.asarray(mg.tallies["flux (tracklength)"].get_values()).reshape(-1)[::-1]   # the energy filter is ascending
        lower = np.asarray(openmc.mgxs.GROUP_STRUCTURES["CASMO-25"])[:-1][::-1]      # the lower edge of each group, fast group first
        fast = lower >= 0.625 - 1e-9
        by_hand = float((phi[fast] / (3.0 * sigma[fast])).sum() / phi[fast].sum())
        self.assertAlmostEqual(self.fast_d(cond) / by_hand, 1.0, places=6)

    def test_an_intermediate_structure_raises_d_and_more_groups_raise_it_more(self):
        """E12: CASMO-25 gives 1.2 to 1.3 times the 2-group D in the fast group, CASMO-8 less than CASMO-25 and more than 1."""
        base = self.fast_d(self.libs["2"])
        r8 = self.fast_d(self.libs["CASMO-8"].get_condensed_library(self.two)) / base
        r25 = self.fast_d(self.libs["CASMO-25"].get_condensed_library(self.two)) / base
        self.assertTrue(1.0 < r8 < r25, f"CASMO-8 {r8:.3f}, CASMO-25 {r25:.3f}")
        self.assertTrue(1.12 < r25 < 1.35, f"CASMO-25 {r25:.3f}")

    def test_the_2_group_diffusion_coefficient_type_is_no_better_than_transport(self):
        """A 2-group library gives 1/(3 <sigma_tr>) whichever type it carries: the new path needs the intermediate groups."""
        lib = self.libs["2"]
        d = self.fast_d(lib)
        tr = float(np.asarray(lib.get_mgxs(self.domain, "transport").get_xs(xs_type="macro")).reshape(-1)[0])
        self.assertAlmostEqual(d * 3.0 * tr, 1.0, places=6)

    def test_openndm_warns_when_the_two_estimators_differ_and_a_wrapper_has_to_raise_the_tolerance(self):
        cond = self.libs["CASMO-25"].get_condensed_library(self.two)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            from_mgxs_library(cond)
        self.assertTrue(any("diffusion-coefficient" in str(x.message) or "transport" in str(x.message) for x in w), [str(x.message)[:80] for x in w])
        with warnings.catch_warnings(record=True) as w2:
            warnings.simplefilter("always")
            from_mgxs_library(cond, d_tolerance=10.0)
        self.assertFalse(any("differ" in str(x.message) for x in w2), [str(x.message)[:80] for x in w2])


class Limits(unittest.TestCase):
    def vacuum_factors(self, core, D):
        """Median over the vacuum faces of (true face flux) / (the parabola's face flux through the Monte Carlo node flux and net currents), fast and thermal."""
        NC, h = core["NC"], float(core["asm"])
        hom = np.zeros_like(core["face"])
        for lo, hi in ((0, 1), (2, 3)):
            jl, jr = core["curr"][:, :, lo], core["curr"][:, :, hi]
            b = -(jl + jr) / (2 * D)
            cc = -(jr - jl) / (2 * D * h)
            hom[:, :, lo] = core["phi"] - b * h / 2 + cc * h * h / 6
            hom[:, :, hi] = core["phi"] + b * h / 2 + cc * h * h / 6
        eq = core["face"] / hom
        vac = np.array([eq[r, c, f] for r in range(NC) for c in range(NC) for f in range(4)
                        if (c + (-1, 1, 0, 0)[f] not in range(NC)) or (r + (0, 0, 1, -1)[f] not in range(NC))])
        interior = np.array([eq[r, c, f] for r in range(1, NC - 1) for c in range(1, NC - 1) for f in range(4) if core["kinds"][r][c] != "R"])
        return np.median(vac, axis=0), np.median(interior, axis=0)

    def test_the_vacuum_factor_of_the_parabola_depends_on_the_d_it_is_given(self):
        """E8 found a factor of about 3 at the vacuum faces and called the parabola unusable there; the D it used was the library's old one. With the flux-averaged D the same parabola
        gives 1.0 to 1.4 in the fast group and 0.3 to 0.95 in the thermal group (the 2-layer core has a few faces where it goes through zero with the old D; medians are used).
        Whether the new values are right is not established: E10 found a factor of 1 at the vacuum faces as good or better. The interior factors are about 1 either way."""
        for name in ("zoned1", "checker1"):
            core = load(name)
            old_v, old_i = self.vacuum_factors(core, core["c_D"])
            new_v, new_i = self.vacuum_factors(core, core["c_Dflux"])
            self.assertTrue(2.0 < old_v[0] < 4.0, f"{name} old D, fast {old_v[0]:.2f}")
            self.assertTrue(0.95 < new_v[0] < 1.4, f"{name} flux-averaged D, fast {new_v[0]:.2f}")
            self.assertTrue(0.3 < new_v[1] < 0.95, f"{name} flux-averaged D, thermal {new_v[1]:.2f}")
            for v in (old_i, new_i):
                self.assertTrue(0.9 < v[0] < 1.1, f"{name} interior fast {v[0]:.2f}")


if __name__ == "__main__":
    unittest.main()
