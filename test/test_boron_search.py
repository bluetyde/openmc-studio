"""Unit tests for studio/openmc_studio/boron_search.py.

Verifies reactivity conversion, boron worth calculations (two-point and least-squares),
and Illinois regula falsi search for critical boron concentration.
Run: python test/test_boron_search.py
"""
import math
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "studio"))
from openmc_studio.boron_search import (  # noqa: E402
    SearchError,
    boron_worth,
    find_critical,
    reactivity_pcm,
)


class TestReactivityPcm(unittest.TestCase):
    """Test reactivity_pcm calculation and input validation."""

    def test_reactivity_exact_values(self):
        """1. reactivity_pcm(1.0, 0.001) is (0.0, 100.0) to 1e-9;
        reactivity_pcm(1.1, 0.001) equals (1e5 * 0.1 / 1.1, 1e5 * 0.001 / 1.21) to 1e-9.
        """
        rho, s_rho = reactivity_pcm(1.0, 0.001)
        self.assertAlmostEqual(rho, 0.0, delta=1e-9)
        self.assertAlmostEqual(s_rho, 100.0, delta=1e-9)

        rho2, s_rho2 = reactivity_pcm(1.1, 0.001)
        expected_rho2 = 1e5 * 0.1 / 1.1
        expected_s_rho2 = 1e5 * 0.001 / 1.21
        self.assertAlmostEqual(rho2, expected_rho2, delta=1e-9)
        self.assertAlmostEqual(s_rho2, expected_s_rho2, delta=1e-9)

    def test_reactivity_bad_inputs(self):
        """1. Bad inputs (0, negative, nan, bool, negative sigma) -> SearchError."""
        bad_k_cases = [0, 0.0, -1.0, float("nan"), float("inf"), float("-inf"), True, False]
        for val in bad_k_cases:
            with self.subTest(k=val):
                with self.assertRaises(SearchError) as cm:
                    reactivity_pcm(val, 0.001)
                self.assertIn("k", str(cm.exception))

        bad_sigma_cases = [-0.001, -1.0, float("nan"), float("inf"), float("-inf"), True, False]
        for val in bad_sigma_cases:
            with self.subTest(sigma_k=val):
                with self.assertRaises(SearchError) as cm:
                    reactivity_pcm(1.0, val)
                self.assertIn("sigma_k", str(cm.exception))


class TestBoronWorth(unittest.TestCase):
    """Test boron_worth two-point and least-squares calculations."""

    def test_boron_worth_two_points(self):
        """2. boron_worth two points: ppm 0 with k 1.20000 sigma 0.00020 and ppm 1000
        with k 1.10000 sigma 0.00020: compute expected slope and sigma independently
        in the test from definitions (not by calling module helper) and compare to 1e-9;
        slope is negative.
        """
        c1, k1, sk1 = 0.0, 1.20000, 0.00020
        c2, k2, sk2 = 1000.0, 1.10000, 0.00020

        # Independent calculation from definitions
        rho1 = 1e5 * (k1 - 1.0) / k1
        s1 = 1e5 * sk1 / (k1 ** 2)
        rho2 = 1e5 * (k2 - 1.0) / k2
        s2 = 1e5 * sk2 / (k2 ** 2)
        expected_slope = (rho2 - rho1) / (c2 - c1)
        expected_sigma = math.sqrt(s1 ** 2 + s2 ** 2) / abs(c2 - c1)

        res = boron_worth([(c1, k1, sk1), (c2, k2, sk2)])
        self.assertEqual(res["method"], "two-point")
        self.assertEqual(res["n_points"], 2)
        self.assertAlmostEqual(res["slope_pcm_per_ppm"], expected_slope, delta=1e-9)
        self.assertAlmostEqual(res["sigma_pcm_per_ppm"], expected_sigma, delta=1e-9)
        self.assertLess(res["slope_pcm_per_ppm"], 0.0)

        # Reversed order gives identical results
        res_rev = boron_worth([(c2, k2, sk2), (c1, k1, sk1)])
        self.assertAlmostEqual(res_rev["slope_pcm_per_ppm"], expected_slope, delta=1e-9)
        self.assertAlmostEqual(res_rev["sigma_pcm_per_ppm"], expected_sigma, delta=1e-9)

    def test_boron_worth_collinear_and_scatter(self):
        """3. boron_worth 3+ points on exact straight line in rho: slope equals line slope
        to 1e-9 and sigma_pcm_per_ppm is 0.0 to 1e-9; with deliberate scatter, OLS slope
        and SE match plain loop in test; points in scrambled order give same result.
        """
        # Exact straight line in rho
        target_slope = -8.5
        target_intercept = 15000.0
        ppms = [0.0, 400.0, 800.0, 1200.0, 1600.0]
        collinear_points = []
        for p in ppms:
            rho_p = target_intercept + target_slope * p
            k_p = 1e5 / (1e5 - rho_p)
            collinear_points.append((p, k_p, 0.0002))

        res_collinear = boron_worth(collinear_points)
        self.assertEqual(res_collinear["method"], "least-squares")
        self.assertEqual(res_collinear["n_points"], len(ppms))
        self.assertAlmostEqual(res_collinear["slope_pcm_per_ppm"], target_slope, delta=1e-9)
        self.assertAlmostEqual(res_collinear["sigma_pcm_per_ppm"], 0.0, delta=1e-9)

        # Deliberate scatter
        scatter_points = [
            (0.0, 1.25, 0.0002),
            (400.0, 1.18, 0.0002),
            (800.0, 1.11, 0.0002),
            (1200.0, 1.06, 0.0002),
            (1600.0, 0.99, 0.0002),
        ]
        # Plain-loop calculation in the test
        rhos = [1e5 * (kp - 1.0) / kp for _, kp, _ in scatter_points]
        xs = [pt[0] for pt in scatter_points]
        n = len(scatter_points)
        xb = sum(xs) / n
        yb = sum(rhos) / n
        sxx = sum((x - xb) ** 2 for x in xs)
        sxy = sum((x - xb) * (y - yb) for x, y in zip(xs, rhos))
        expected_b = sxy / sxx
        expected_a = yb - expected_b * xb
        rss = sum((y - (expected_a + expected_b * x)) ** 2 for x, y in zip(xs, rhos))
        s2 = rss / (n - 2)
        expected_se = math.sqrt(s2 / sxx)

        res_scatter = boron_worth(scatter_points)
        self.assertAlmostEqual(res_scatter["slope_pcm_per_ppm"], expected_b, delta=1e-9)
        self.assertAlmostEqual(res_scatter["sigma_pcm_per_ppm"], expected_se, delta=1e-9)

        # Scrambled order
        scrambled_points = [scatter_points[2], scatter_points[0], scatter_points[4], scatter_points[1], scatter_points[3]]
        res_scrambled = boron_worth(scrambled_points)
        self.assertAlmostEqual(res_scrambled["slope_pcm_per_ppm"], res_scatter["slope_pcm_per_ppm"], delta=1e-9)
        self.assertAlmostEqual(res_scrambled["sigma_pcm_per_ppm"], res_scatter["sigma_pcm_per_ppm"], delta=1e-9)

    def test_boron_worth_bad_inputs(self):
        """4. boron_worth bad inputs, each SearchError: one point, repeated ppm,
        negative ppm, nan, bool, k of 0, negative sigma.
        """
        # One point
        with self.assertRaises(SearchError) as cm:
            boron_worth([(0.0, 1.1, 0.001)])
        self.assertIn("points", str(cm.exception))

        # Repeated ppm
        with self.assertRaises(SearchError) as cm:
            boron_worth([(500.0, 1.1, 0.001), (500.0, 1.05, 0.001)])
        self.assertIn("points", str(cm.exception))

        # Negative ppm
        with self.assertRaises(SearchError) as cm:
            boron_worth([(-10.0, 1.1, 0.001), (500.0, 1.05, 0.001)])
        self.assertIn("points", str(cm.exception))

        # nan in ppm, k, sigma_k
        with self.assertRaises(SearchError) as cm:
            boron_worth([(float("nan"), 1.1, 0.001), (500.0, 1.05, 0.001)])
        self.assertIn("points", str(cm.exception))

        with self.assertRaises(SearchError) as cm:
            boron_worth([(0.0, float("nan"), 0.001), (500.0, 1.05, 0.001)])
        self.assertIn("points", str(cm.exception))

        with self.assertRaises(SearchError) as cm:
            boron_worth([(0.0, 1.1, float("nan")), (500.0, 1.05, 0.001)])
        self.assertIn("points", str(cm.exception))

        # bool in ppm, k, sigma_k
        with self.assertRaises(SearchError) as cm:
            boron_worth([(True, 1.1, 0.001), (500.0, 1.05, 0.001)])
        self.assertIn("points", str(cm.exception))

        with self.assertRaises(SearchError) as cm:
            boron_worth([(0.0, True, 0.001), (500.0, 1.05, 0.001)])
        self.assertIn("points", str(cm.exception))

        with self.assertRaises(SearchError) as cm:
            boron_worth([(0.0, 1.1, True), (500.0, 1.05, 0.001)])
        self.assertIn("points", str(cm.exception))

        # k of 0 or negative
        with self.assertRaises(SearchError) as cm:
            boron_worth([(0.0, 0.0, 0.001), (500.0, 1.05, 0.001)])
        self.assertIn("points", str(cm.exception))

        with self.assertRaises(SearchError) as cm:
            boron_worth([(0.0, -1.0, 0.001), (500.0, 1.05, 0.001)])
        self.assertIn("points", str(cm.exception))

        # negative sigma
        with self.assertRaises(SearchError) as cm:
            boron_worth([(0.0, 1.1, -0.001), (500.0, 1.05, 0.001)])
        self.assertIn("points", str(cm.exception))

        # Malformed entries
        with self.assertRaises(SearchError) as cm:
            boron_worth([(0.0, 1.1), (500.0, 1.05)])
        self.assertIn("points", str(cm.exception))

        with self.assertRaises(SearchError) as cm:
            boron_worth("not-a-list")
        self.assertIn("points", str(cm.exception))


class TestFindCritical(unittest.TestCase):
    """Test find_critical root-finding and stop criteria."""

    def test_find_critical_synthetic_wiggle(self):
        """5. find_critical on k(x) = 1.2 - 0.0002 * x with sigma_k = 0.0002 and small
        deterministic wiggle (0.0001 * math.sin(12.9898 * x)), target 1.0, bracket 0 to 2000:
        status converged, abs(k - 1.0) <= 2 * 0.0002, runs <= 12, runs list length equals
        number of calls counted by test counter, interval contains 1000.
        """
        calls = 0

        def run(x):
            nonlocal calls
            calls += 1
            k = 1.2 - 0.0002 * x + 0.0001 * math.sin(12.9898 * x)
            return (k, 0.0002)

        res = find_critical(run, target_k=1.0, lo=0.0, hi=2000.0)
        self.assertEqual(res["status"], "converged")
        self.assertLessEqual(abs(res["k"] - 1.0), 2.0 * 0.0002)
        self.assertLessEqual(len(res["runs"]), 12)
        self.assertEqual(len(res["runs"]), calls)
        self.assertIsNotNone(res["interval"])
        self.assertLessEqual(res["interval"][0], 1000.0)
        self.assertGreaterEqual(res["interval"][1], 1000.0)

    def test_find_critical_increasing_and_nonlinear(self):
        """6. Increasing function (k(x) = 0.8 + 0.0002 * x) works the same;
        non-linear function k(x) = 1.3 / (1 + 0.001 * x) with sigma_k = 1e-6 converges
        within max_runs 12 and abs(k - 1) <= 2e-6.
        """
        # Increasing function
        inc_calls = 0

        def run_inc(x):
            nonlocal inc_calls
            inc_calls += 1
            return (0.8 + 0.0002 * x, 0.0002)

        res_inc = find_critical(run_inc, target_k=1.0, lo=0.0, hi=2000.0)
        self.assertEqual(res_inc["status"], "converged")
        self.assertLessEqual(abs(res_inc["k"] - 1.0), 2.0 * 0.0002)
        self.assertLessEqual(len(res_inc["runs"]), 12)
        self.assertEqual(len(res_inc["runs"]), inc_calls)
        self.assertIsNotNone(res_inc["interval"])
        self.assertLessEqual(res_inc["interval"][0], 1000.0)
        self.assertGreaterEqual(res_inc["interval"][1], 1000.0)

        # Non-linear function
        nonlin_calls = 0

        def run_nonlin(x):
            nonlocal nonlin_calls
            nonlin_calls += 1
            return (1.3 / (1.0 + 0.001 * x), 1e-6)

        res_nonlin = find_critical(run_nonlin, target_k=1.0, lo=0.0, hi=1000.0, max_runs=12)
        self.assertEqual(res_nonlin["status"], "converged")
        self.assertLessEqual(len(res_nonlin["runs"]), 12)
        self.assertEqual(len(res_nonlin["runs"]), nonlin_calls)
        self.assertLessEqual(abs(res_nonlin["k"] - 1.0), 2e-6)

    def test_find_critical_not_bracketed_and_end_root(self):
        """7. "not-bracketed" when target is outside both end values (2 runs, interval None);
        root exactly at lo returns converged after 2 runs; sigma_k = 0 with linear noiseless
        function converges to within 1e-12 in k.
        """
        # Target outside both end values
        calls_nb = 0

        def run_nb(x):
            nonlocal calls_nb
            calls_nb += 1
            return (1.2 - 0.0001 * x, 1e-5)

        res_nb = find_critical(run_nb, target_k=1.0, lo=0.0, hi=500.0)
        self.assertEqual(res_nb["status"], "not-bracketed")
        self.assertEqual(len(res_nb["runs"]), 2)
        self.assertEqual(calls_nb, 2)
        self.assertIsNone(res_nb["interval"])

        # Root exactly at lo
        calls_lo = 0

        def run_lo(x):
            nonlocal calls_lo
            calls_lo += 1
            return (1.0 - 0.0002 * x, 0.0002)

        res_lo = find_critical(run_lo, target_k=1.0, lo=0.0, hi=1000.0)
        self.assertEqual(res_lo["status"], "converged")
        self.assertEqual(len(res_lo["runs"]), 2)
        self.assertEqual(calls_lo, 2)
        self.assertEqual(res_lo["x"], 0.0)
        self.assertAlmostEqual(res_lo["k"], 1.0, delta=1e-9)

        # Root exactly at hi
        calls_hi = 0

        def run_hi(x):
            nonlocal calls_hi
            calls_hi += 1
            return (1.2 - 0.0002 * x, 0.0002)

        res_hi = find_critical(run_hi, target_k=1.0, lo=0.0, hi=1000.0)
        self.assertEqual(res_hi["status"], "converged")
        self.assertEqual(len(res_hi["runs"]), 2)
        self.assertEqual(calls_hi, 2)
        self.assertEqual(res_hi["x"], 1000.0)
        self.assertAlmostEqual(res_hi["k"], 1.0, delta=1e-9)

        # sigma_k = 0 with linear noiseless function
        def run_zero_sigma(x):
            return (1.2 - 0.0002 * x, 0.0)

        res_zero = find_critical(run_zero_sigma, target_k=1.0, lo=0.0, hi=2000.0)
        self.assertEqual(res_zero["status"], "converged")
        self.assertLessEqual(abs(res_zero["k"] - 1.0), 1e-12)

    def test_find_critical_max_runs(self):
        """8. "max-runs": with max_runs = 2 and bracketed non-trivial case the status is
        max-runs after exactly 2 runs and x is the best evaluated point; run is never called
        more than max_runs times (count it).
        """
        calls = 0

        def run_nontrivial(x):
            nonlocal calls
            calls += 1
            return (1.2 - 0.0002 * x, 1e-6)

        res = find_critical(run_nontrivial, target_k=1.0, lo=0.0, hi=2000.0, max_runs=2)
        self.assertEqual(res["status"], "max-runs")
        self.assertEqual(len(res["runs"]), 2)
        self.assertEqual(calls, 2)
        self.assertIn(res["x"], [0.0, 2000.0])
        self.assertIsNotNone(res["interval"])

        # Also test with max_runs = 3
        calls3 = 0

        def run_3(x):
            nonlocal calls3
            calls3 += 1
            return (1.3 / (1.0 + 0.001 * x), 1e-12)

        res3 = find_critical(run_3, target_k=1.0, lo=0.0, hi=1000.0, max_runs=3)
        self.assertEqual(res3["status"], "max-runs")
        self.assertEqual(len(res3["runs"]), 3)
        self.assertEqual(calls3, 3)

    def test_find_critical_bracket_collapsed(self):
        """Bracket collapses if bracket width falls below 1e-9 * (hi - lo)."""
        def run_step(x):
            # Step jump across target k=1.0 with tight sigma
            return (1.2 if x < 1000.0 else 0.8, 1e-15)

        res = find_critical(run_step, target_k=1.0, lo=0.0, hi=2000.0, max_runs=100)
        self.assertEqual(res["status"], "bracket-collapsed")
        self.assertIsNotNone(res["interval"])

    def test_noise_not_chased(self):
        """9. Noise is not chased: a function whose k is constant 1.0001 with sigma_k 0.001
        (always within tolerance) converges after the 2 end runs, never more.
        """
        calls = 0

        def run_noisy(x):
            nonlocal calls
            calls += 1
            return (1.0001, 0.001)

        res = find_critical(run_noisy, target_k=1.0, lo=0.0, hi=2000.0, tolerance_sigma=2.0)
        self.assertEqual(res["status"], "converged")
        self.assertEqual(len(res["runs"]), 2)
        self.assertEqual(calls, 2)

    def test_find_critical_bad_inputs(self):
        """10. find_critical bad inputs, each SearchError: lo >= hi, run not callable,
        target_k 0 or nan, tolerance_sigma 0 or negative or bool, max_runs 1, 2.5 or True;
        a run that returns a single number, a pair with nan, a negative k, or a negative
        sigma raises SearchError and message contains the x value.
        11. Bad-input rule: every kind of input has a test that feeds a bad value and
        asserts the specific error without except Exception.
        """
        def ok_run(x):
            return (1.2 - 0.0002 * x, 0.0002)

        # lo >= hi
        with self.assertRaises(SearchError) as cm:
            find_critical(ok_run, 1.0, lo=1000.0, hi=1000.0)
        self.assertIn("lo", str(cm.exception))

        with self.assertRaises(SearchError) as cm:
            find_critical(ok_run, 1.0, lo=2000.0, hi=1000.0)
        self.assertIn("lo", str(cm.exception))

        # run not callable
        with self.assertRaises(SearchError) as cm:
            find_critical("not callable", 1.0, lo=0.0, hi=1000.0)
        self.assertIn("run", str(cm.exception))

        # target_k 0 or nan or negative or bool
        for bad_tgt in [0, 0.0, -1.0, float("nan"), float("inf"), True, False]:
            with self.subTest(target_k=bad_tgt):
                with self.assertRaises(SearchError) as cm:
                    find_critical(ok_run, target_k=bad_tgt, lo=0.0, hi=1000.0)
                self.assertIn("target_k", str(cm.exception))

        # lo / hi not finite or bool
        for bad_lo in [float("nan"), float("inf"), True, False]:
            with self.subTest(lo=bad_lo):
                with self.assertRaises(SearchError) as cm:
                    find_critical(ok_run, 1.0, lo=bad_lo, hi=1000.0)
                self.assertIn("lo", str(cm.exception))

        for bad_hi in [float("nan"), float("inf"), True, False]:
            with self.subTest(hi=bad_hi):
                with self.assertRaises(SearchError) as cm:
                    find_critical(ok_run, 1.0, lo=0.0, hi=bad_hi)
                self.assertIn("hi", str(cm.exception))

        # tolerance_sigma 0 or negative or bool or nan
        for bad_tol in [0, 0.0, -2.0, float("nan"), float("inf"), True, False]:
            with self.subTest(tolerance_sigma=bad_tol):
                with self.assertRaises(SearchError) as cm:
                    find_critical(ok_run, 1.0, lo=0.0, hi=1000.0, tolerance_sigma=bad_tol)
                self.assertIn("tolerance_sigma", str(cm.exception))

        # max_runs 1, 2.5, or True
        for bad_mr in [1, 0, -5, 2.5, True, False, "12"]:
            with self.subTest(max_runs=bad_mr):
                with self.assertRaises(SearchError) as cm:
                    find_critical(ok_run, 1.0, lo=0.0, hi=1000.0, max_runs=bad_mr)
                self.assertIn("max_runs", str(cm.exception))

        # run returning single number
        with self.assertRaises(SearchError) as cm:
            find_critical(lambda x: 1.0, 1.0, lo=123.45, hi=1000.0)
        self.assertIn("123.45", str(cm.exception))

        # run returning pair with nan in k
        with self.assertRaises(SearchError) as cm:
            find_critical(lambda x: (float("nan"), 0.001), 1.0, lo=456.78, hi=1000.0)
        self.assertIn("456.78", str(cm.exception))

        # run returning pair with nan in sigma
        with self.assertRaises(SearchError) as cm:
            find_critical(lambda x: (1.05, float("nan")), 1.0, lo=789.01, hi=1000.0)
        self.assertIn("789.01", str(cm.exception))

        # run returning negative k
        with self.assertRaises(SearchError) as cm:
            find_critical(lambda x: (-0.5, 0.001), 1.0, lo=333.33, hi=1000.0)
        self.assertIn("333.33", str(cm.exception))

        # run returning negative sigma
        with self.assertRaises(SearchError) as cm:
            find_critical(lambda x: (1.05, -0.001), 1.0, lo=444.44, hi=1000.0)
        self.assertIn("444.44", str(cm.exception))

        # run returning bool
        with self.assertRaises(SearchError) as cm:
            find_critical(lambda x: (True, 0.001), 1.0, lo=555.55, hi=1000.0)
        self.assertIn("555.55", str(cm.exception))

        with self.assertRaises(SearchError) as cm:
            find_critical(lambda x: (1.05, True), 1.0, lo=666.66, hi=1000.0)
        self.assertIn("666.66", str(cm.exception))


class TestAddedByTheDispatcher(unittest.TestCase):
    """Tests added by the dispatcher after mutation checks showed gaps in the brief's test list."""

    def test_illinois_converges_where_plain_false_position_does_not(self):
        """k(x) = 1 + 0.4 (exp(-x/100) - exp(-0.5)) is strongly curved; the root is x = 50. Plain regula falsi keeps one
        end fixed and does not converge within 12 runs; the Illinois rule does (10 runs)."""
        def f(x):
            return 1.0 + 0.4 * (math.exp(-x / 100.0) - math.exp(-0.5))

        res = find_critical(lambda x: (f(x), 1e-9), 1.0, 0.0, 1000.0, 2.0, 12)
        self.assertEqual(res["status"], "converged")
        self.assertLessEqual(len(res["runs"]), 12)
        self.assertLessEqual(abs(res["k"] - 1.0), 2e-9)
        self.assertLess(abs(res["x"] - 50.0), 1e-5)

    def test_zero_sigma_nonlinear_function_converges_to_1e_12(self):
        res = find_critical(lambda x: (1.3 / (1.0 + 0.001 * x), 0.0), 1.0, 0.0, 1000.0, 2.0, 40)
        self.assertEqual(res["status"], "converged")
        self.assertLessEqual(abs(res["k"] - 1.0), 1e-12)
        self.assertLess(abs(res["x"] - 300.0), 1e-6)

    def test_best_point_is_judged_by_distance_in_sigmas(self):
        """Both ends are above the target. The low end is 0.2 away with sigma 0.05 (4 sigma), the high end 0.19 away
        with sigma 0.0001 (1900 sigma): the best point is the low end, although the high end is closer in k."""
        values = {0.0: (1.2, 0.05), 1000.0: (1.19, 0.0001)}
        res = find_critical(lambda x: values[x], 1.0, 0.0, 1000.0)
        self.assertEqual(res["status"], "not-bracketed")
        self.assertEqual(len(res["runs"]), 2)
        self.assertEqual(res["x"], 0.0)

    def test_tolerance_sigma_argument_is_used(self):
        """A constant k of 1.003 with sigma 0.001 is 3 sigma from the target: not converged at 2, converged at 5."""
        run = lambda x: (1.003, 0.001)
        self.assertEqual(find_critical(run, 1.0, 0.0, 100.0, 2.0)["status"], "not-bracketed")
        res = find_critical(run, 1.0, 0.0, 100.0, 5.0)
        self.assertEqual(res["status"], "converged")
        self.assertEqual(len(res["runs"]), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
