"""Nodal solver wrapper (plan P1): studio/openmc_studio/nodal.py checked against things it did not produce.

References, and what each one is:
  IAEA-2D           the benchmark ANL-7416 problem 11 (the 2D IAEA PWR problem): its constants, its 177-assembly map (read from the public FeenoX example geometry
                    iaea-2dpwr-quarter.geo, where the regions are polygons), and the published reference k 1.02959 (the plan's P1 gate: openndm's own number is
                    +21.5 pcm from it with SANM). An independent reference, not a number out of the wrapper.
  Orientation       one fuel node in a corner of a map: the power must sit in that corner of the array. A flip-symmetric map hides a wrong flip, so these maps are not
                    symmetric. Negative controls: the same maps read the wrong way must fail the same check.
  E15 reproduction  the saved fine-group data of the infinite lattices (docs/design/nodal-p2/data/fine_inf.npz) collapsed by `critical_buckling_fuel` give the constants and
                    the two-step k of E15's printed output (docs/design/nodal-p2/e15_output.txt), and the three saved Monte Carlo cores give E15's "core run's own
                    constants" k. Those are the experiment's results, typed from its console, which is why the tolerance is a few pcm and not zero.
  Refusals          bad maps and constants, a version of openndm outside [0.3.0, 0.4.0).

Needs openmc, openndm 0.3.0 and OPENMC_CROSS_SECTIONS only through the imports; no Monte Carlo is run here. Run it with `node test/run_all.cjs nodal` or
    python test/nodal/test_nodal_wrapper.py
"""
import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "studio"))
try:
    import openndm
    from openmc_studio import nodal
except ImportError as e:  # a test that cannot run is a failure, not a quiet pass
    raise SystemExit(f"test_nodal_wrapper: needs openndm ({e}). Run it with `node test/run_all.cjs nodal` and OPENNDM_PYTHON set.")

DATA = ROOT / "docs" / "design" / "nodal-p2" / "data"

# ── the IAEA 2D benchmark ────────────────────────────────────────────────────────────────────────────────────────────────────────────
BG2 = 0.8e-4                       # axial buckling of the 2D problem: Sigma_a,g += D_g * BG2
_FUEL = dict(D=[1.5, 0.4], nu_fission=[0.0, 0.135], chi=[1.0, 0.0], scatter=[[0.0, 0.02], [0.0, 0.0]])
IAEA = {1: dict(_FUEL, absorption=[0.010, 0.080]), 2: dict(_FUEL, absorption=[0.010, 0.085]), 3: dict(_FUEL, absorption=[0.010, 0.130]),
        4: dict(D=[2.0, 0.3], absorption=[0.000, 0.010], nu_fission=[0.0, 0.0], chi=[1.0, 0.0], scatter=[[0.0, 0.04], [0.0, 0.0]])}
for _m in IAEA.values():
    _m["absorption"] = list(np.asarray(_m["absorption"]) + np.asarray(_m["D"]) * BG2)
# the quarter core from the centre of the centre assembly (index 0) outwards, 20 cm assemblies; 0 = outside the reflector ring
QUARTER = """3 2 2 2 3 2 2 1 4
2 2 2 2 2 2 2 1 4
2 2 2 2 2 2 1 1 4
2 2 2 2 2 2 1 4 4
3 2 2 2 3 1 1 4 0
2 2 2 2 1 1 4 4 0
2 2 1 1 1 4 4 0 0
1 1 1 4 4 4 0 0 0
4 4 4 4 0 0 0 0 0"""
REFERENCE_K = 1.02959


def iaea_layout():
    q = np.array([[int(x) for x in line.split()] for line in QUARTER.splitlines()])
    idx = np.abs(np.arange(-8, 9))
    full = q[np.ix_(idx, idx)]
    return [[int(v) if v else None for v in row] for row in full]


def iaea_constants():
    return {m: {k: np.asarray(v, float) for k, v in c.items()} for m, c in IAEA.items()}


class IAEA2D(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.layout = iaea_layout()
        cls.sanm = nodal.solve_core(cls.layout, iaea_constants(), 20.0, 1.0, kernel="sanm")
        cls.fdm = nodal.solve_core(cls.layout, iaea_constants(), 20.0, 1.0, kernel="fdm")

    def test_the_map_is_the_benchmarks(self):
        flat = [v for r in self.layout for v in r if v is not None]
        self.assertEqual(len(self.layout), 17)
        self.assertEqual(sum(v in (1, 2, 3) for v in flat), 177, "the benchmark core has 177 fuel assemblies")
        self.assertEqual(sum(v == 3 for v in flat), 9, "9 fully rodded assemblies in the 2D problem")
        self.assertEqual(sum(1 for v in self.layout[8] if v in (1, 2, 3)), 15, "15 fuel assemblies across the diameter")

    def test_k_against_the_reference(self):
        # one node per assembly: SANM is 34 pcm above the benchmark's 1.02959 (the plan quoted +21.5 from openndm's own documentation, whose setup is not known here;
        # the refinement below shows the constants and the map are the benchmark's)
        d = (self.sanm.k_eff - REFERENCE_K) * 1e5
        self.assertAlmostEqual(d, 34, delta=6, msg=f"SANM k {self.sanm.k_eff:.5f} is {d:+.0f} pcm from the reference {REFERENCE_K}")
        self.assertTrue(self.sanm.converged)

    def test_the_data_are_the_benchmarks_because_refining_the_mesh_reaches_the_reference(self):
        # an independent check of the map and the constants (not of the wrapper): 4 x 4 nodes per assembly, both kernels, within 5 pcm of 1.02959
        kinds = [1, 2, 3, 4]
        comp = np.array([[kinds.index(v) if v else openndm.INACTIVE for v in r] for r in self.layout])
        geom = openndm.Geometry.from_lattice(comp, pitch=20.0, dz=[1.0], boundaries={"z_min": "reflective", "z_max": "reflective"}, outside="vacuum", subdivide=4)
        cons = iaea_constants()
        xs = openndm.XSLibrary(2, 4)
        for i, k in enumerate(kinds):
            c = cons[k]
            xs.set_composition(i, D=c["D"], absorption=c["absorption"], nu_fission=c["nu_fission"], kappa_fission=c["nu_fission"], chi=c["chi"], scatter=c["scatter"],
                               inv_velocity=[1.0, 1.0])
            xs.set_adf(i, np.ones((4, 2)), n_axes=2)
        xs.finalize(warn=False)
        for kernel in ("sanm", "nem"):
            k = openndm.Model(geom, xs, openndm.Settings(kernel=kernel, verbosity=0)).solve().k_eff
            self.assertLess(abs(k - REFERENCE_K) * 1e5, 5, f"{kernel} at 4 x 4 nodes per assembly: {k:.5f}")

    def test_the_kernels_agree_to_the_known_scale(self):
        # the finite-difference kernel at one node per assembly is not expected to be as close; it must still be within a percent
        self.assertLess(abs(self.fdm.k_eff - REFERENCE_K), 0.01)

    def test_power_is_four_fold_symmetric_and_zero_outside_the_fuel(self):
        p = self.sanm.power
        fuel = np.array([[v in (1, 2, 3) for v in r] for r in self.layout])
        np.testing.assert_allclose(p, p[::-1], atol=5e-5)
        np.testing.assert_allclose(p, p[:, ::-1], atol=5e-5)
        np.testing.assert_allclose(p, p.T, atol=5e-5)
        self.assertTrue(np.all(p[~fuel] == 0))
        self.assertAlmostEqual(float(p[fuel].mean()), 1.0, places=6)

    def test_the_power_peak_is_in_the_known_zone(self):
        # the highest power of the benchmark sits in the interior fuel-type-2 assemblies next to the rodded ones, never at the edge
        p = self.sanm.power
        i, j = np.unravel_index(np.argmax(p), p.shape)
        self.assertEqual(self.layout[i][j], 2)
        self.assertLess(p.max(), 1.6)
        edge = [p[r, c] for r in range(17) for c in range(17) if self.layout[r][c] in (1, 2, 3) and any(
            (self.layout[r + dr][c + dc] is None or self.layout[r + dr][c + dc] == 4) for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)))]
        self.assertLess(max(edge), p.max())


# ── orientation (E11b) ───────────────────────────────────────────────────────────────────────────────────────────────────────────────
def two_kinds():
    return {"F": dict(D=[1.4, 0.4], absorption=[0.008, 0.07], nu_fission=[0.006, 0.12], chi=[1.0, 0.0], scatter=[[0.0, 0.02], [0.0, 0.0]]),
            "R": dict(D=[1.3, 0.3], absorption=[0.001, 0.02], nu_fission=[0.0, 0.0], chi=[1.0, 0.0], scatter=[[0.0, 0.03], [0.0, 0.0]])}


class Orientation(unittest.TestCase):
    """A map with fuel only in one corner (not symmetric under any flip): the power belongs in that corner of the returned array."""

    def one(self, corner):
        m = [["R"] * 5 for _ in range(5)]
        r, c = {"top-left": (0, 0), "top-right": (0, 4), "bottom-left": (4, 0), "bottom-right": (4, 4)}[corner]
        m[r][c] = "F"
        m[r + (1 if r == 0 else -1)][c] = "F"          # a second fuel node beside it along y, so a flip in x and one in y differ
        return m, r, c

    def test_power_stays_where_the_fuel_is(self):
        for corner in ("top-left", "top-right", "bottom-left", "bottom-right"):
            m, r, c = self.one(corner)
            res = nodal.solve_core(m, two_kinds(), 20.0, 1.0)
            want = np.array([[k == "F" for k in row] for row in m])
            self.assertTrue(np.all(res.power[~want] == 0), corner)
            self.assertTrue(np.all(res.power[want] > 0), corner)

    def test_a_wrong_flip_fails_the_same_check(self):
        for corner in ("top-left", "bottom-right"):
            m, r, c = self.one(corner)
            res = nodal.solve_core(m, two_kinds(), 20.0, 1.0)
            want = np.array([[k == "F" for k in row] for row in m])
            for name, wrong in (("flipped in y", res.power[::-1]), ("flipped in x", res.power[:, ::-1])):
                self.assertFalse(np.all(wrong[~want] == 0), f"{corner}: the check must catch a map read {name}")

    def test_a_graded_core_puts_its_peak_at_the_rich_end(self):
        # three kinds of fuel by reactivity along y only, top richest: the top row has the highest power
        cons = two_kinds()
        cons["H"] = dict(cons["F"], nu_fission=np.array([0.0066, 0.132]))
        cons["L"] = dict(cons["F"], nu_fission=np.array([0.0054, 0.108]))
        rows = [["H"] * 4, ["F"] * 4, ["L"] * 4]
        m = [["R"] * 6] + [["R"] + r + ["R"] for r in rows] + [["R"] * 6]
        res = nodal.solve_core(m, cons, 20.0, 1.0)
        by_row = [res.power[i, 1:5].mean() for i in (1, 2, 3)]
        self.assertGreater(by_row[0], by_row[1])
        self.assertGreater(by_row[1], by_row[2])
        flipped = nodal.solve_core(m[::-1], cons, 20.0, 1.0)
        np.testing.assert_allclose(flipped.power, res.power[::-1], atol=5e-5)

    def test_the_x_boundary_names_follow_the_map(self):
        # reflective on the left only: power rises on the left side of a uniform strip; vacuum on both sides is symmetric
        cons = two_kinds()
        m = [["F"] * 6 for _ in range(2)]
        sym = nodal.solve_core(m, cons, 20.0, 1.0)
        np.testing.assert_allclose(sym.power, sym.power[:, ::-1], atol=5e-5)
        left = nodal.solve_core(m, cons, 20.0, 1.0, boundaries={"x_min": "reflective"})
        self.assertGreater(left.power[0, 0], left.power[0, -1])
        top = nodal.solve_core([["F"] for _ in range(6)], cons, 20.0, 1.0, boundaries={"y_max": "reflective"})
        self.assertGreater(top.power[0, 0], top.power[-1, 0], "y_max is the TOP of the map")
        self.assertGreater(left.k_eff, sym.k_eff)


# ── E15 reproduced through the wrapper ───────────────────────────────────────────────────────────────────────────────────────────────
def core_by_kind(core):
    out = {}
    for kd in ("A", "B", "R"):
        sel = np.array([[core["kinds"][r][c] == kd for c in range(core["NC"])] for r in range(core["NC"])])
        out[kd] = {f: core["c_" + f][sel].mean(axis=0) for f in ("D", "absorption", "nu_fission", "kappa_fission", "chi", "scatter", "inv_velocity")}
        out[kd]["D"] = core["c_Dflux"][sel].mean(axis=0)
    return out


def load_core(name):
    d = np.load(DATA / f"{name}.npz")
    core = {k: d[k] for k in d.files}
    core["kinds"] = [[str(x) for x in row] for row in d["kinds"]]
    core["NC"] = len(core["kinds"])
    return core


FINE = np.load(DATA / "fine_inf.npz")
PIECES = np.load(DATA / "pieces.npz")
FIELDS = ("D", "absorption", "nu_fission", "kappa_fission", "chi", "scatter", "inv_velocity")


def fine(tag):
    return {f: np.asarray(FINE[f"{tag}__{f}"], float) for f in FIELDS + ("flux",)}


def reflector(name):
    if name == "checker1":
        return {f: np.asarray(PIECES[f"reflC__{f}"], float).reshape(-1) for f in FIELDS}
    return {f: np.asarray(FINE[f"reflZ__{f}"], float).reshape(-1) for f in FIELDS}


# E15 (docs/design/nodal-p2/e15_output.txt): nodal k minus OpenMC k, SANM, no factors
E15_TWO_STEP = {"zoned1": 539, "zoned2": 1150, "checker1": 1018}
E15_PLAIN = {"zoned1": 2257, "zoned2": 2725, "checker1": 2713}
E15_OWN = {"zoned1": 185, "zoned2": 702, "checker1": 381}


class E15ThroughTheWrapper(unittest.TestCase):
    edges = FINE["edges"]

    def test_the_corrected_fuel_constants(self):
        a = nodal.critical_buckling_fuel(fine("A"), self.edges)
        np.testing.assert_allclose(a["D"], [1.3132, 0.3705], atol=6e-5)
        np.testing.assert_allclose(a["absorption"], [0.00873, 0.08732], atol=6e-6)
        np.testing.assert_allclose(a["nu_fission"], [0.00599, 0.14196], atol=6e-6)
        np.testing.assert_allclose(a["scatter"].reshape(-1), [0.28633, 0.01666, 0.00046, 0.99672], atol=6e-6)
        b = nodal.critical_buckling_fuel(fine("B"), self.edges)
        np.testing.assert_allclose(b["D"], [1.3173, 0.3769], atol=6e-5)
        np.testing.assert_allclose(b["scatter"].reshape(-1), [0.28566, 0.01610, 0.00054, 0.97224], atol=6e-6)

    def test_the_plain_collapse_is_not_the_corrected_one(self):
        plain = nodal.critical_buckling_fuel(fine("A"), self.edges, correct=False)
        np.testing.assert_allclose(plain["D"], [1.2996, 0.3698], atol=6e-5)
        np.testing.assert_allclose(plain["scatter"].reshape(-1), [0.2881, 0.01775, 0.00045, 0.99838], atol=6e-5)

    def test_the_homogeneous_medium_numbers(self):
        a = fine("A")
        self.assertAlmostEqual(nodal.spectrum(a, 0.0)[1], 1.3053, places=3)
        self.assertAlmostEqual(nodal.critical_b2(a), 0.00536, places=5)
        self.assertAlmostEqual(nodal.spectrum(a, nodal.critical_b2(a))[1], 1.0, places=6)

    def test_the_two_step_k_of_each_core(self):
        for name in ("zoned1", "zoned2", "checker1"):
            core = load_core(name)
            cons = {"A": nodal.critical_buckling_fuel(fine("A"), self.edges), "B": nodal.critical_buckling_fuel(fine("B"), self.edges), "R": reflector(name)}
            res = nodal.solve_core(core["kinds"], cons, float(core["asm"]), float(core["hz"]))
            d = (res.k_eff - float(core["k"])) * 1e5
            self.assertAlmostEqual(d, E15_TWO_STEP[name], delta=6, msg=name)
            plain = {"A": nodal.critical_buckling_fuel(fine("A"), self.edges, correct=False), "B": nodal.critical_buckling_fuel(fine("B"), self.edges, correct=False),
                     "R": reflector(name)}
            dp = (nodal.solve_core(core["kinds"], plain, float(core["asm"]), float(core["hz"])).k_eff - float(core["k"])) * 1e5
            self.assertAlmostEqual(dp, E15_PLAIN[name], delta=6, msg=name + " plain")
            self.assertGreater(dp - d, 1000, "the correction is worth more than a thousand pcm on every core")

    def test_the_core_runs_own_constants_and_power(self):
        for name in ("zoned1", "zoned2", "checker1"):
            core = load_core(name)
            res = nodal.solve_core(core["kinds"], core_by_kind(core), float(core["asm"]), float(core["hz"]))
            self.assertAlmostEqual((res.k_eff - float(core["k"])) * 1e5, E15_OWN[name], delta=6, msg=name)
            fuel = np.array([[k != "R" for k in row] for row in core["kinds"]])
            ref = core["power"] / core["power"][fuel].mean()
            p = res.power / res.power[fuel].mean()
            rms = 100 * np.sqrt(((p[fuel] / ref[fuel] - 1) ** 2).mean())
            self.assertLess(rms, 4.0, f"{name}: assembly power rms {rms:.1f} % against the Monte Carlo run")

    def test_the_checkerboard_power_is_not_read_upside_down(self):
        # E11b: the 8 x 8 checkerboard shows it (rows flipped swap the two enrichments); the same power map read flipped is 10 % or more off
        core = load_core("checker1")
        res = nodal.solve_core(core["kinds"], core_by_kind(core), float(core["asm"]), float(core["hz"]))
        fuel = np.array([[k != "R" for k in row] for row in core["kinds"]])
        ref = core["power"] / core["power"][fuel].mean()

        def rms(p):
            p = p / p[fuel].mean()
            return 100 * np.sqrt(((p[fuel] / ref[fuel] - 1) ** 2).mean())
        self.assertLess(rms(res.power), 4.0)
        self.assertGreater(rms(res.power[::-1]), 8.0, "reading the rows upside down must be visibly wrong on this core")


# ── E16 to E18: where the two-step's remaining gap sits, kept as numbers ──────────────────────────────────────────────────────────────────
# (docs/design/nodal-p2/e16_output.txt, e17_output.txt, e18_output.txt: the experiments' console output; deterministic from the saved data, so the tolerance is a few pcm)
E16 = {   # nodal k minus OpenMC k, pcm: (F1+R1 the two-step, F1+R0, F0+R1, F0+R0)
    "zoned1": (539, 411, 317, 185), "zoned2": (1150, 739, 1132, 702), "checker1": (1018, 854, 551, 381)}
E17 = {   # fuel = the core run's own; reflector by kind, by distance to the fuel, by node
    "zoned1": (185, 223, 239), "zoned2": (702, 981, 1001), "checker1": (381, 427, 450)}


def node_own(core, r, c):
    return {f: np.asarray(core["c_" + f][r, c], float).reshape(-1) for f in FIELDS[1:]} | {"D": np.asarray(core["c_Dflux"][r, c], float)}


def mean_nodes(core, nodes):
    cs = [node_own(core, r, c) for r, c in nodes]
    return {f: np.mean([x[f] for x in cs], axis=0) for f in cs[0]}


def pcm(core, layout, cons):
    res = nodal.solve_core(layout, cons, float(core["asm"]), float(core["hz"]))
    return (res.k_eff - float(core["k"])) * 1e5


class ReflectorGap(unittest.TestCase):
    edges = FINE["edges"]

    def test_the_remaining_gap_split_between_fuel_and_reflector(self):
        for name, want in E16.items():
            core = load_core(name)
            own = core_by_kind(core)
            f1 = {"A": nodal.critical_buckling_fuel(fine("A"), self.edges), "B": nodal.critical_buckling_fuel(fine("B"), self.edges)}
            r1 = reflector(name)
            got = (pcm(core, core["kinds"], {**f1, "R": r1}), pcm(core, core["kinds"], {**f1, "R": own["R"]}),
                   pcm(core, core["kinds"], {"A": own["A"], "B": own["B"], "R": r1}), pcm(core, core["kinds"], own))
            for g, w, label in zip(got, want, ("F1+R1", "F1+R0", "F0+R1", "F0+R0")):
                self.assertAlmostEqual(g, w, delta=8, msg=f"{name} {label}")
        # the reading E16 draws: the reflector carries most of the gap only on the core with two reflector layers
        z2 = E16["zoned2"]
        self.assertGreater((z2[0] - z2[1]) / (z2[0] - z2[3]), 0.85)           # reflector share of the gap on the 11 x 11 core
        self.assertLess((E16["zoned1"][0] - E16["zoned1"][1]) / (E16["zoned1"][0] - E16["zoned1"][3]), 0.5)
        self.assertLess((E16["checker1"][0] - E16["checker1"][1]) / (E16["checker1"][0] - E16["checker1"][3]), 0.5)

    def test_more_reflector_sets_make_k_worse_not_better(self):
        """E17, kept as a limit: splitting the reflector by distance to the fuel, or per node, moves k AWAY from OpenMC's on every core (by 40 to 300 pcm). The idea of 'one kind per layer' does not help;
        a change that makes this fail has found something new, and the page of E17 should be revisited."""
        for name, want in E17.items():
            core = load_core(name)
            nc = core["NC"]
            kinds = core["kinds"]
            fuel = [(r, c) for r in range(nc) for c in range(nc) if kinds[r][c] != "R"]
            dist = {(r, c): min(abs(r - fr) + abs(c - fc) for fr, fc in fuel) for r in range(nc) for c in range(nc) if kinds[r][c] == "R"}
            base = {kd: mean_nodes(core, [(r, c) for r in range(nc) for c in range(nc) if kinds[r][c] == kd]) for kd in ("A", "B")}
            by_kind = dict(base, R=mean_nodes(core, list(dist)))
            labels_d = [[kinds[r][c] if kinds[r][c] != "R" else f"R{dist[(r, c)]}" for c in range(nc)] for r in range(nc)]
            by_dist = dict(base)
            for dd in sorted(set(dist.values())):
                by_dist[f"R{dd}"] = mean_nodes(core, [n for n, v in dist.items() if v == dd])
            labels_n = [[kinds[r][c] if kinds[r][c] != "R" else f"R_{r}_{c}" for c in range(nc)] for r in range(nc)]
            by_node = dict(base)
            for (r, c) in dist:
                by_node[f"R_{r}_{c}"] = node_own(core, r, c)
            got = (pcm(core, kinds, by_kind), pcm(core, labels_d, by_dist), pcm(core, labels_n, by_node))
            for g, w, label in zip(got, want, ("by kind", "by distance", "by node")):
                self.assertAlmostEqual(g, w, delta=8, msg=f"{name} {label}")
            self.assertGreater(got[1], got[0] + 20, f"{name}: splitting by distance does not help")
            self.assertGreater(got[2], got[0] + 20, f"{name}: per-node constants do not help")

    def test_the_strip_reproduced_by_its_own_constants(self):
        """E18: the strip [B B A | R] solved as four nodes. SANM with the strip's own constants is 500 pcm above OpenMC's strip, FDM 46 below; the corrected infinite-lattice fuel with the strip's
        reflector gives SANM -4 pcm. The method error at this interface, with no factors, is of the size of the two-step's remaining gap."""
        k_mc = float(PIECES["k_stripZ"])

        def piece(name):
            return {f: np.asarray(PIECES[f"{name}__{f}"], float).reshape(-1) for f in FIELDS}

        def run(cons, kernel):
            res = nodal.solve_core([["B", "B", "A", "R"]], cons, 6.3, 1.0, kernel=kernel,
                                   boundaries={"x_min": "reflective", "x_max": "vacuum", "y_min": "reflective", "y_max": "reflective"})
            return (res.k_eff - k_mc) * 1e5
        own = {"A": piece("stripZ_A"), "B": piece("stripZ_B"), "R": piece("reflZ")}
        self.assertAlmostEqual(run(own, "sanm"), 502, delta=8)
        self.assertAlmostEqual(run(own, "fdm"), -46, delta=8)
        corr = {"A": nodal.critical_buckling_fuel(fine("A"), self.edges), "B": nodal.critical_buckling_fuel(fine("B"), self.edges), "R": piece("reflZ")}
        self.assertAlmostEqual(run(corr, "sanm"), -4, delta=8)
        plain = {"A": nodal.critical_buckling_fuel(fine("A"), self.edges, correct=False), "B": nodal.critical_buckling_fuel(fine("B"), self.edges, correct=False), "R": piece("reflZ")}
        self.assertAlmostEqual(run(plain, "sanm"), 1419, delta=8)


STRIPS = np.load(DATA / "strips_e19.npz")


def strip_nodal(order, tag, x_max, kernel, sub):
    """E19/E20: a row of nodes with the saved per-node constants of the run `tag`, reflective at the left, `x_max` at the right, each node split sub x sub."""
    kinds = sorted(set(order))
    comp = np.array([[kinds.index(k) for k in order]], dtype=int)
    bc = {"x_min": "reflective", "x_max": x_max, "y_min": "reflective", "y_max": "reflective", "z_min": "reflective", "z_max": "reflective"}
    geom = openndm.Geometry.from_lattice(comp, pitch=6.3, dz=[1.0], boundaries=bc, outside="vacuum", subdivide=(sub, sub, 1))
    xs = openndm.XSLibrary(2, len(kinds))
    for i, name in enumerate(kinds):
        c = nodal.check_constants(name, {f: np.asarray(STRIPS[f"{tag}__{name}__{f}"], float) for f in FIELDS})
        xs.set_composition(i, D=c["D"], absorption=c["absorption"], nu_fission=c["nu_fission"], kappa_fission=c["kappa_fission"], chi=c["chi"], scatter=c["scatter"], inv_velocity=c["inv_velocity"])
        xs.set_adf(i, np.ones((4, 2)), n_axes=2)
    xs.finalize(warn=False)
    return (openndm.Model(geom, xs, openndm.Settings(kernel=kernel, verbosity=0)).solve().k_eff - float(STRIPS[f"{tag}__k"])) * 1e5


class StripControls(unittest.TestCase):
    """E19 and E20 (docs/design/nodal-p2/e19_output.txt, e20_output.txt): where the strip's error sits. Not a claim about accuracy: the error of the nodal solution with node-averaged constants and no
    factors, against OpenMC's own k for the same row of nodes (k with about 60 pcm of statistical error)."""

    def test_only_the_faces_to_vacuum_and_reflector_cost_anything(self):
        self.assertAlmostEqual(strip_nodal(["B0", "B1", "A2"], "periodic", "reflective", "sanm", 1), 27, delta=8)       # fuel/fuel faces: right
        self.assertAlmostEqual(strip_nodal(["B0", "B1", "A2"], "vacuum", "vacuum", "sanm", 1), -1065, delta=8)           # fuel next to vacuum: 1,000 pcm too low
        self.assertAlmostEqual(strip_nodal(["B0", "B1", "A2", "R3"], "reflector", "vacuum", "sanm", 1), 369, delta=8)    # a reflector layer in front of the vacuum: 370 pcm too high

    def test_the_error_is_the_constants_not_the_mesh(self):
        """SANM at one node per assembly has converged: splitting every node 4 x 4 moves k by under 10 pcm. FDM does not: it drifts towards SANM's value as the mesh is refined, so its
        small error at one node per assembly was an accident of cancellation."""
        for order, tag, xmax in ((["B0", "B1", "A2"], "vacuum", "vacuum"), (["B0", "B1", "A2", "R3"], "reflector", "vacuum")):
            coarse, fine4 = strip_nodal(order, tag, xmax, "sanm", 1), strip_nodal(order, tag, xmax, "sanm", 4)
            self.assertLess(abs(coarse - fine4), 10, tag)
        f1, f4 = strip_nodal(["B0", "B1", "A2", "R3"], "reflector", "vacuum", "fdm", 1), strip_nodal(["B0", "B1", "A2", "R3"], "reflector", "vacuum", "fdm", 4)
        self.assertGreater(f4 - f1, 300, "FDM moves by hundreds of pcm on refinement")
        self.assertAlmostEqual(f4, 264, delta=8)

    def test_the_recipe_constants_reproduce_the_strip_at_any_mesh(self):
        """E20, last row: the recipe's constants (corrected infinite-lattice fuel, the strip's reflector) give the strip's k within 10 pcm for SANM at 1, 2 and 4 sub-nodes. The core's remaining
        +500 to +1,100 pcm is therefore not an error this strip can show."""
        k_mc = float(PIECES["k_stripZ"])
        edges = FINE["edges"]
        cons = {"A": nodal.critical_buckling_fuel(fine("A"), edges), "B": nodal.critical_buckling_fuel(fine("B"), edges), "R": {f: np.asarray(PIECES[f"reflZ__{f}"], float).reshape(-1) for f in FIELDS}}
        for sub in (1, 2, 4):
            kinds = ["A", "B", "R"]
            comp = np.array([[1, 1, 0, 2]], dtype=int)
            bc = {"x_min": "reflective", "x_max": "vacuum", "y_min": "reflective", "y_max": "reflective", "z_min": "reflective", "z_max": "reflective"}
            geom = openndm.Geometry.from_lattice(comp, pitch=6.3, dz=[1.0], boundaries=bc, outside="vacuum", subdivide=(sub, sub, 1))
            xs = openndm.XSLibrary(2, 3)
            for i, name in enumerate(kinds):
                c = nodal.check_constants(name, cons[name])
                xs.set_composition(i, D=c["D"], absorption=c["absorption"], nu_fission=c["nu_fission"], kappa_fission=c["kappa_fission"], chi=c["chi"], scatter=c["scatter"],
                                   inv_velocity=c["inv_velocity"])
                xs.set_adf(i, np.ones((4, 2)), n_axes=2)
            xs.finalize(warn=False)
            d = (openndm.Model(geom, xs, openndm.Settings(kernel="sanm", verbosity=0)).solve().k_eff - k_mc) * 1e5
            self.assertLess(abs(d), 10, f"sub {sub}: {d:+.0f} pcm")


# ── refusals ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
class Refusals(unittest.TestCase):
    def solve(self, layout=None, cons=None, **kw):
        return nodal.solve_core([["F", "R"]] if layout is None else layout, cons or two_kinds(), kw.pop("pitch", 20.0), 1.0, **kw)

    def test_bad_maps(self):
        with self.assertRaises(nodal.NodalInputError):
            self.solve([])
        with self.assertRaises(nodal.NodalInputError):
            self.solve([["F", "R"], ["F"]])
        with self.assertRaises(nodal.NodalInputError):
            self.solve([[None, None]])
        with self.assertRaises(nodal.NodalInputError):
            self.solve([["F", "X"]])                       # no constants for X

    def test_bad_constants(self):
        for field, value in (("D", [0.0, 0.4]), ("D", [1.4, np.nan]), ("absorption", [-0.1, 0.07]), ("chi", [0.5, 0.2]), ("scatter", [1.0, 2.0, 3.0])):
            cons = two_kinds()
            cons["F"][field] = value
            with self.assertRaises(nodal.NodalInputError, msg=f"{field} {value}"):
                self.solve(cons=cons)
        cons = two_kinds()
        del cons["F"]["absorption"]
        with self.assertRaises(nodal.NodalInputError):
            self.solve(cons=cons)

    def test_nothing_fissile_and_bad_numbers(self):
        cons = two_kinds()
        with self.assertRaises(nodal.NodalInputError):
            self.solve([["R", "R"]], cons)                  # no fissile kind in the map
        with self.assertRaises(nodal.NodalInputError):
            self.solve(pitch=-1.0)
        with self.assertRaises(nodal.NodalInputError):
            self.solve(boundaries={"left": "vacuum"})

    def test_an_unchecked_openndm_version_is_refused(self):
        real = openndm.__version__
        try:
            for v in ("0.4.0", "0.2.9", "1.0"):
                openndm.__version__ = v
                with self.assertRaises(nodal.NodalUnavailable, msg=v):
                    nodal.require_openndm()
            openndm.__version__ = "0.3.7"
            self.assertIs(nodal.require_openndm(), openndm)
        finally:
            openndm.__version__ = real

    def test_the_structure_without_the_cutoff_edge_is_refused(self):
        with self.assertRaises(nodal.NodalInputError):
            nodal.fast_mask([0.0, 1.0, 20.0e6])


if __name__ == "__main__":
    unittest.main(verbosity=2)
