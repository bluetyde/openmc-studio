"""Tests for openmc_studio.peak_stats.

Covers:
- expected_max_normal exact Simpson integration against closed forms and published tables.
- Monte Carlo verification of expected_max_normal(7).
- Blom approximation accuracy and boundary conditions.
- peaking_summary aggregation, exclusion handling, ties, and noise allowance.
- csv_safe_cell spreadsheet formula injection escaping.
- Comprehensive ValueError handling for invalid inputs across all functions.
"""
import math
from pathlib import Path
import random
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "studio"))

from openmc_studio.peak_stats import (  # noqa: E402
    csv_safe_cell,
    expected_max_normal,
    expected_max_normal_blom,
    peaking_summary,
)


class TestExpectedMaxNormal(unittest.TestCase):
    def test_closed_forms_and_table_values(self):
        # 1. expected_max_normal: m=1 is 0.0; m=2 and m=3 equal their closed forms to 1e-9;
        # m=4, 5, 10 equal the table values to 1e-6; m = 1..30 is strictly increasing.
        self.assertEqual(expected_max_normal(1), 0.0)

        closed_m2 = 1.0 / math.sqrt(math.pi)
        self.assertAlmostEqual(expected_max_normal(2), closed_m2, delta=1e-9)

        closed_m3 = 1.5 / math.sqrt(math.pi)
        self.assertAlmostEqual(expected_max_normal(3), closed_m3, delta=1e-9)

        # Published table references
        self.assertAlmostEqual(expected_max_normal(4), 1.0293753730, delta=1e-6)
        self.assertAlmostEqual(expected_max_normal(5), 1.1629644736, delta=1e-6)
        self.assertAlmostEqual(expected_max_normal(10), 1.5387527308, delta=1e-6)

        # Strictly increasing sequence for m = 1..30
        values = [expected_max_normal(m) for m in range(1, 31)]
        for i in range(len(values) - 1):
            self.assertLess(values[i], values[i + 1], f"Failed monotonicity at m={i + 1}")

    def test_monte_carlo_check(self):
        # 2. Monte Carlo check: random.Random(2026), 200,000 trials of max of m=7 draws of rng.gauss(0, 1);
        # sample mean within 0.01 of expected_max_normal(7).
        rng = random.Random(2026)
        trials = 200000
        m = 7
        gauss = rng.gauss
        sample_sum = sum(max(gauss(0, 1) for _ in range(m)) for _ in range(trials))
        sample_mean = sample_sum / trials
        exact_val = expected_max_normal(7)
        self.assertAlmostEqual(sample_mean, exact_val, delta=0.01)

    def test_bad_inputs_expected_max_normal(self):
        # 3. expected_max_normal(0), (-3), (2.5), (True), ("3"), (100001) -> ValueError
        for bad_m in (0, -3, 2.5, True, "3", 100001):
            with self.subTest(bad_m=bad_m):
                with self.assertRaises(ValueError):
                    expected_max_normal(bad_m)

    def test_large_m_near_integration_limit(self):
        # Edge test near upper limit m=100000
        val = expected_max_normal(100000)
        self.assertTrue(math.isfinite(val))
        self.assertGreater(val, 4.0)
        # 100001 raises ValueError
        with self.assertRaises(ValueError):
            expected_max_normal(100001)


class TestExpectedMaxNormalBlom(unittest.TestCase):
    def test_blom_accuracy_and_m1(self):
        # 4. expected_max_normal_blom: for m=2..5 within 0.03 of exact value;
        # for m in [10, 20, 50, 100, 1000, 10000] within 0.02 of exact value;
        # m=1 is 0.0; bad m -> ValueError.
        self.assertEqual(expected_max_normal_blom(1), 0.0)

        for m in (2, 3, 4, 5):
            with self.subTest(m=m):
                exact = expected_max_normal(m)
                blom = expected_max_normal_blom(m)
                self.assertAlmostEqual(blom, exact, delta=0.03)

        for m in (10, 20, 50, 100, 1000, 10000):
            with self.subTest(m=m):
                exact = expected_max_normal(m)
                blom = expected_max_normal_blom(m)
                self.assertAlmostEqual(blom, exact, delta=0.02)

    def test_blom_bad_inputs(self):
        for bad_m in (0, -3, 2.5, True, "3"):
            with self.subTest(bad_m=bad_m):
                with self.assertRaises(ValueError):
                    expected_max_normal_blom(bad_m)


class TestPeakingSummary(unittest.TestCase):
    def test_peaking_summary_basic(self):
        # 5. peaking_summary basic: values=[1.0, 1.2, 0.8, 1.0], sigmas=[0.01]*4 ->
        # n_used 4, mean 1.0, max 1.2, max_index 1, peaking_factor 1.2,
        # noise_allowance equal to 0.01 * expected_max_normal(4) to 1e-12,
        # noise_allowance_relative equal to the same divided by 1.0.
        res = peaking_summary(values=[1.0, 1.2, 0.8, 1.0], sigmas=[0.01] * 4)
        self.assertEqual(res["n_total"], 4)
        self.assertEqual(res["n_used"], 4)
        self.assertEqual(res["n_excluded"], 0)
        self.assertEqual(res["mean"], 1.0)
        self.assertEqual(res["max"], 1.2)
        self.assertEqual(res["max_index"], 1)
        self.assertEqual(res["peaking_factor"], 1.2)
        expected_na = 0.01 * expected_max_normal(4)
        self.assertAlmostEqual(res["noise_allowance"], expected_na, delta=1e-12)
        self.assertAlmostEqual(res["noise_allowance_relative"], expected_na / 1.0, delta=1e-12)

    def test_excluding_peak_and_duplicates(self):
        # 6. Excluding the peak: excluded=(1,) on the same data ->
        # n_used 3, n_excluded 1, mean equal to (1.0 + 0.8 + 1.0) / 3 to 1e-12,
        # max 1.0, max_index 0 (first of the tie), and noise_allowance uses expected_max_normal(3).
        # Duplicates in excluded count once.
        res = peaking_summary(values=[1.0, 1.2, 0.8, 1.0], sigmas=[0.01] * 4, excluded=(1,))
        self.assertEqual(res["n_total"], 4)
        self.assertEqual(res["n_used"], 3)
        self.assertEqual(res["n_excluded"], 1)
        self.assertAlmostEqual(res["mean"], (1.0 + 0.8 + 1.0) / 3, delta=1e-12)
        self.assertEqual(res["max"], 1.0)
        self.assertEqual(res["max_index"], 0)
        expected_na = 0.01 * expected_max_normal(3)
        self.assertAlmostEqual(res["noise_allowance"], expected_na, delta=1e-12)

        # Duplicates in excluded count once
        res_dup = peaking_summary(values=[1.0, 1.2, 0.8, 1.0], sigmas=[0.01] * 4, excluded=(1, 1))
        self.assertEqual(res_dup["n_total"], 4)
        self.assertEqual(res_dup["n_used"], 3)
        self.assertEqual(res_dup["n_excluded"], 1)
        self.assertEqual(res_dup["max_index"], 0)

    def test_non_uniform_sigmas(self):
        # 7. Non-uniform sigmas: values=[1, 1, 1, 1], sigmas=[0.01, 0.02, 0.03, 0.04] ->
        # rms_sigma is sqrt((0.0001 + 0.0004 + 0.0009 + 0.0016) / 4); assert noise_allowance against it.
        sigmas = [0.01, 0.02, 0.03, 0.04]
        res = peaking_summary(values=[1, 1, 1, 1], sigmas=sigmas)
        rms_sigma = math.sqrt((0.0001 + 0.0004 + 0.0009 + 0.0016) / 4)
        expected_na = rms_sigma * expected_max_normal(4)
        self.assertAlmostEqual(res["noise_allowance"], expected_na, delta=1e-12)

    def test_bad_inputs_peaking_summary(self):
        # 8. Bad input, each ValueError: different lengths; empty lists; a nan; an inf;
        # a negative sigma; a bool entry; an excluded index out of range (4 of 4 pins, and -1);
        # an excluded bool; all pins excluded; mean of used values 0; a string entry.

        # Different lengths
        with self.assertRaises(ValueError):
            peaking_summary([1.0, 2.0], [0.01])

        # Empty lists
        with self.assertRaises(ValueError):
            peaking_summary([], [])

        # NaN
        with self.assertRaises(ValueError):
            peaking_summary([float("nan"), 1.0], [0.01, 0.01])
        with self.assertRaises(ValueError):
            peaking_summary([1.0, 1.0], [float("nan"), 0.01])

        # Inf
        with self.assertRaises(ValueError):
            peaking_summary([float("inf"), 1.0], [0.01, 0.01])
        with self.assertRaises(ValueError):
            peaking_summary([1.0, 1.0], [float("inf"), 0.01])
        with self.assertRaises(ValueError):
            peaking_summary([float("-inf"), 1.0], [0.01, 0.01])

        # Negative sigma
        with self.assertRaises(ValueError):
            peaking_summary([1.0, 1.0], [-0.01, 0.01])

        # Bool entry
        with self.assertRaises(ValueError):
            peaking_summary([True, 1.0], [0.01, 0.01])
        with self.assertRaises(ValueError):
            peaking_summary([1.0, 1.0], [False, 0.01])

        # Excluded index out of range (4 of 4 pins, and -1)
        with self.assertRaises(ValueError):
            peaking_summary([1.0, 1.0, 1.0, 1.0], [0.01] * 4, excluded=(4,))
        with self.assertRaises(ValueError):
            peaking_summary([1.0, 1.0, 1.0, 1.0], [0.01] * 4, excluded=(-1,))

        # Excluded bool
        with self.assertRaises(ValueError):
            peaking_summary([1.0, 1.0], [0.01, 0.01], excluded=(True,))
        with self.assertRaises(ValueError):
            peaking_summary([1.0, 1.0], [0.01, 0.01], excluded=(False,))

        # All pins excluded
        with self.assertRaises(ValueError):
            peaking_summary([1.0, 1.0], [0.01, 0.01], excluded=(0, 1))

        # Mean of used values 0 (or <= 0)
        with self.assertRaises(ValueError):
            peaking_summary([0.0, 0.0], [0.01, 0.01])
        with self.assertRaises(ValueError):
            peaking_summary([-1.0, 1.0], [0.01, 0.01])
        with self.assertRaises(ValueError):
            peaking_summary([-2.0, -1.0], [0.01, 0.01])

        # String entry
        with self.assertRaises(ValueError):
            peaking_summary(["1.0", 1.0], [0.01, 0.01])
        with self.assertRaises(ValueError):
            peaking_summary([1.0, 1.0], ["0.01", 0.01])

    def test_ties_and_subsequent_exclusion(self):
        # Additional falsification test for ties and exclusions
        values = [2.0, 1.0, 2.0, 0.5]
        sigmas = [0.01] * 4
        # Tie between index 0 and 2; index 0 must be chosen
        res1 = peaking_summary(values, sigmas)
        self.assertEqual(res1["max_index"], 0)
        self.assertEqual(res1["max"], 2.0)

        # Excluding index 0; index 2 must be chosen
        res2 = peaking_summary(values, sigmas, excluded=(0,))
        self.assertEqual(res2["max_index"], 2)
        self.assertEqual(res2["max"], 2.0)


class TestCsvSafeCell(unittest.TestCase):
    def test_csv_safe_cell(self):
        # 9. csv_safe_cell: each of =SUM(A1), +1, -1, @x, "\tx", "\rx" gets a leading ';
        # "normal", "", " =x", "'x" unchanged;
        # -1.5 (float), 3 (int), True unchanged and the same object type;
        # None -> "".
        self.assertEqual(csv_safe_cell("=SUM(A1)"), "'=SUM(A1)")
        self.assertEqual(csv_safe_cell("+1"), "'+1")
        self.assertEqual(csv_safe_cell("-1"), "'-1")
        self.assertEqual(csv_safe_cell("@x"), "'@x")
        self.assertEqual(csv_safe_cell("\tx"), "'\tx")
        self.assertEqual(csv_safe_cell("\rx"), "'\rx")

        self.assertEqual(csv_safe_cell("normal"), "normal")
        self.assertEqual(csv_safe_cell(""), "")
        self.assertEqual(csv_safe_cell(" =x"), " =x")
        self.assertEqual(csv_safe_cell("'x"), "'x")

        # Non-string values
        f_val = csv_safe_cell(-1.5)
        self.assertEqual(f_val, -1.5)
        self.assertIs(type(f_val), float)

        i_val = csv_safe_cell(3)
        self.assertEqual(i_val, 3)
        self.assertIs(type(i_val), int)

        b_val = csv_safe_cell(True)
        self.assertEqual(b_val, True)
        self.assertIs(type(b_val), bool)

        self.assertEqual(csv_safe_cell(None), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
