"""Unit tests for studio/openmc_studio/variance_stats.py.

Covers:
1. figure_of_merit and fom_ratio calculations and input validation.
2. histories_needed calculation and input validation.
3. compare_bins with three hand-computed bins, empty bins, zero sigmas,
   negative means, and bad input validation.
4. unbiasedness_summary with a 5-bin set (including empty bin), hand-computed
   metrics, and all-bins-empty error check.
5. Verdicts for no limits, consistent limits, failing limits, and infinite z.
6. Strict limits structure and field validation.
7. Bad-input error assertion rules.

Run: python test/test_variance_stats.py
"""
import math
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "studio"))
from openmc_studio.variance_stats import (  # noqa: E402
    VarianceError,
    compare_bins,
    figure_of_merit,
    fom_ratio,
    histories_needed,
    unbiasedness_summary,
)


class TestFigureOfMerit(unittest.TestCase):
    def test_figure_of_merit_values(self):
        self.assertAlmostEqual(figure_of_merit(0.01, 100), 100.0, delta=1e-9)
        self.assertAlmostEqual(figure_of_merit(0.05, 4), 100.0, delta=1e-9)

    def test_fom_ratio_values(self):
        self.assertEqual(fom_ratio(200.0, 100.0), 2.0)

    def test_figure_of_merit_bad_rel_error(self):
        bad_values = [0, 0.0, -0.01, -5, float("nan"), float("inf"), float("-inf"), True, False, "0.01", None]
        for bad in bad_values:
            with self.subTest(bad=bad):
                with self.assertRaises(VarianceError) as ctx:
                    figure_of_merit(bad, 100.0)
                self.assertIn("rel_error", str(ctx.exception))

    def test_figure_of_merit_bad_time_s(self):
        bad_values = [0, 0.0, -1, -100.0, float("nan"), float("inf"), float("-inf"), True, False, "100", None]
        for bad in bad_values:
            with self.subTest(bad=bad):
                with self.assertRaises(VarianceError) as ctx:
                    figure_of_merit(0.01, bad)
                self.assertIn("time_s", str(ctx.exception))

    def test_fom_ratio_bad_inputs(self):
        bad_values = [0, 0.0, -10.0, float("nan"), float("inf"), float("-inf"), True, False, "200", None]
        for bad in bad_values:
            with self.subTest(bad=bad):
                with self.assertRaises(VarianceError) as ctx:
                    fom_ratio(bad, 100.0)
                self.assertIn("fom_windowed", str(ctx.exception))
                with self.assertRaises(VarianceError) as ctx:
                    fom_ratio(200.0, bad)
                self.assertIn("fom_analog", str(ctx.exception))


class TestHistoriesNeeded(unittest.TestCase):
    def test_histories_needed_values(self):
        self.assertEqual(histories_needed(0.10, 1000, 0.05), 4000.0)
        expected = 5e6 * (0.02 / 0.05) ** 2
        actual = histories_needed(0.02, 5e6, 0.05)
        self.assertAlmostEqual(actual, expected, delta=expected * 1e-6)

    def test_histories_needed_bad_inputs(self):
        bad_values = [0, 0.0, -1, float("nan"), float("inf"), float("-inf"), True, False, "1000", None]
        for bad in bad_values:
            with self.subTest(arg="rel_error_now", bad=bad):
                with self.assertRaises(VarianceError) as ctx:
                    histories_needed(bad, 1000, 0.05)
                self.assertIn("rel_error_now", str(ctx.exception))

            with self.subTest(arg="histories_now", bad=bad):
                with self.assertRaises(VarianceError) as ctx:
                    histories_needed(0.10, bad, 0.05)
                self.assertIn("histories_now", str(ctx.exception))

            with self.subTest(arg="rel_error_target", bad=bad):
                with self.assertRaises(VarianceError) as ctx:
                    histories_needed(0.10, 1000, bad)
                self.assertIn("rel_error_target", str(ctx.exception))


class TestCompareBins(unittest.TestCase):
    def test_three_bins_hand_computed(self):
        analog = [(10.0, 0.5), (20.0, 1.2), (30.0, 0.8)]
        windowed = [(10.3, 0.4), (19.4, 0.9), (30.8, 0.7)]

        expected = []
        for i in range(len(analog)):
            ma, sa = analog[i]
            mw, sw = windowed[i]
            expected_z = (mw - ma) / math.sqrt(sa**2 + sw**2)
            expected.append({
                "bin": i,
                "analog": float(ma),
                "windowed": float(mw),
                "z": expected_z,
                "empty": False,
            })

        result = compare_bins(analog, windowed)
        self.assertEqual(len(result), 3)
        for r, exp in zip(result, expected):
            self.assertEqual(r["bin"], exp["bin"])
            self.assertEqual(r["analog"], exp["analog"])
            self.assertEqual(r["windowed"], exp["windowed"])
            self.assertAlmostEqual(r["z"], exp["z"], delta=1e-12)
            self.assertEqual(r["empty"], exp["empty"])

    def test_empty_bin(self):
        res = compare_bins([(0.0, 0.0)], [(0.0, 0.0)])
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["bin"], 0)
        self.assertEqual(res[0]["analog"], 0.0)
        self.assertEqual(res[0]["windowed"], 0.0)
        self.assertEqual(res[0]["z"], 0.0)
        self.assertTrue(res[0]["empty"])

    def test_equal_means_zero_sigmas(self):
        res = compare_bins([(42.0, 0.0)], [(42.0, 0.0)])
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["z"], 0.0)
        self.assertFalse(res[0]["empty"])

    def test_different_means_zero_sigmas(self):
        res_pos = compare_bins([(10.0, 0.0)], [(15.0, 0.0)])
        self.assertEqual(res_pos[0]["z"], math.inf)
        self.assertFalse(res_pos[0]["empty"])

        res_neg = compare_bins([(15.0, 0.0)], [(10.0, 0.0)])
        self.assertEqual(res_neg[0]["z"], -math.inf)
        self.assertFalse(res_neg[0]["empty"])

    def test_negative_means_allowed(self):
        res = compare_bins([(-10.0, 0.3)], [(-8.0, 0.4)])
        expected_z = (-8.0 - (-10.0)) / math.sqrt(0.3**2 + 0.4**2)
        self.assertAlmostEqual(res[0]["z"], expected_z, delta=1e-12)
        self.assertFalse(res[0]["empty"])

    def test_bad_inputs_compare_bins(self):
        # Wrong lengths
        with self.assertRaises(VarianceError) as ctx:
            compare_bins([(1.0, 0.1), (2.0, 0.2)], [(1.0, 0.1)])
        self.assertTrue("analog" in str(ctx.exception) or "windowed" in str(ctx.exception))

        # Empty lists
        with self.assertRaises(VarianceError):
            compare_bins([], [])
        with self.assertRaises(VarianceError):
            compare_bins([(1.0, 0.1)], [])
        with self.assertRaises(VarianceError):
            compare_bins([], [(1.0, 0.1)])

        # Negative sigma
        with self.assertRaises(VarianceError):
            compare_bins([(1.0, -0.1)], [(1.0, 0.1)])
        with self.assertRaises(VarianceError):
            compare_bins([(1.0, 0.1)], [(1.0, -0.1)])

        # NaN values
        with self.assertRaises(VarianceError):
            compare_bins([(float("nan"), 0.1)], [(1.0, 0.1)])
        with self.assertRaises(VarianceError):
            compare_bins([(1.0, float("nan"))], [(1.0, 0.1)])
        with self.assertRaises(VarianceError):
            compare_bins([(1.0, 0.1)], [(float("nan"), 0.1)])
        with self.assertRaises(VarianceError):
            compare_bins([(1.0, 0.1)], [(1.0, float("nan"))])

        # Inf values in mean or sigma
        with self.assertRaises(VarianceError):
            compare_bins([(float("inf"), 0.1)], [(1.0, 0.1)])
        with self.assertRaises(VarianceError):
            compare_bins([(1.0, float("inf"))], [(1.0, 0.1)])

        # Bool values
        with self.assertRaises(VarianceError):
            compare_bins([(True, 0.1)], [(1.0, 0.1)])
        with self.assertRaises(VarianceError):
            compare_bins([(1.0, False)], [(1.0, 0.1)])
        with self.assertRaises(VarianceError):
            compare_bins([(1.0, 0.1)], [(False, 0.1)])
        with self.assertRaises(VarianceError):
            compare_bins([(1.0, 0.1)], [(1.0, True)])

        # Pair of wrong size
        with self.assertRaises(VarianceError):
            compare_bins([(1.0,)], [(1.0, 0.1)])
        with self.assertRaises(VarianceError):
            compare_bins([(1.0, 0.1, 0.2)], [(1.0, 0.1)])
        with self.assertRaises(VarianceError):
            compare_bins([(1.0, 0.1)], [(1.0,)])
        with self.assertRaises(VarianceError):
            compare_bins([(1.0, 0.1)], [(1.0, 0.1, 0.2)])

        # Not a list
        with self.assertRaises(VarianceError):
            compare_bins("not a list", [(1.0, 0.1)])
        with self.assertRaises(VarianceError):
            compare_bins([(1.0, 0.1)], "not a list")
        with self.assertRaises(VarianceError):
            compare_bins([1.0], [(1.0, 0.1)])


class TestUnbiasednessSummary(unittest.TestCase):
    def test_five_bins_hand_computed_summary(self):
        analog = [
            (10.0, 0.6),    # bin 0: used
            (0.0, 0.0),     # bin 1: empty
            (25.0, 1.2),    # bin 2: used
            (4.0, 0.3),     # bin 3: used
            (-15.0, 0.8),   # bin 4: used
        ]
        windowed = [
            (10.8, 0.8),    # bin 0
            (0.0, 0.0),     # bin 1
            (23.2, 0.9),    # bin 2
            (4.9, 0.4),     # bin 3
            (-12.5, 0.6),   # bin 4
        ]

        used_indices = [0, 2, 3, 4]
        hand_z = []
        for idx in used_indices:
            ma, sa = analog[idx]
            mw, sw = windowed[idx]
            comb = math.sqrt(sa**2 + sw**2)
            hand_z.append((mw - ma) / comb)

        expected_mean_z = sum(hand_z) / len(hand_z)
        expected_rms_z = math.sqrt(sum(z * z for z in hand_z) / len(hand_z))
        expected_max_abs_z = max(abs(z) for z in hand_z)
        expected_frac_2 = sum(1 for z in hand_z if abs(z) <= 2.0) / len(hand_z)
        expected_frac_3 = sum(1 for z in hand_z if abs(z) <= 3.0) / len(hand_z)

        summary = unbiasedness_summary(analog, windowed)
        self.assertEqual(summary["n_bins"], 5)
        self.assertEqual(summary["n_used"], 4)
        self.assertAlmostEqual(summary["mean_z"], expected_mean_z, delta=1e-12)
        self.assertAlmostEqual(summary["rms_z"], expected_rms_z, delta=1e-12)
        self.assertAlmostEqual(summary["max_abs_z"], expected_max_abs_z, delta=1e-12)
        self.assertAlmostEqual(summary["fraction_within_2"], expected_frac_2, delta=1e-12)
        self.assertAlmostEqual(summary["fraction_within_3"], expected_frac_3, delta=1e-12)

    def test_all_bins_empty(self):
        all_empty_analog = [(0.0, 0.0), (0.0, 0.0)]
        all_empty_windowed = [(0.0, 0.0), (0.0, 0.0)]
        with self.assertRaises(VarianceError):
            unbiasedness_summary(all_empty_analog, all_empty_windowed)


class TestVerdicts(unittest.TestCase):
    def setUp(self):
        # A test set with known z values:
        # Bin 0: (10, 1) vs (11, 1) -> z = 1 / sqrt(2) ~= 0.7071
        # Bin 1: (20, 1) vs (22, 1) -> z = 2 / sqrt(2) ~= 1.4142
        self.analog = [(10.0, 1.0), (20.0, 1.0)]
        self.windowed = [(11.0, 1.0), (22.0, 1.0)]

    def test_no_limits_verdict(self):
        res_none = unbiasedness_summary(self.analog, self.windowed, limits=None)
        self.assertEqual(res_none["verdict"], "not-compared")
        self.assertEqual(res_none["reasons"], ["no limit with a source was supplied"])

        res_empty = unbiasedness_summary(self.analog, self.windowed, limits={})
        self.assertEqual(res_empty["verdict"], "not-compared")
        self.assertEqual(res_empty["reasons"], ["no limit with a source was supplied"])

    def test_both_limits_holding(self):
        limits = {
            "rms_z_limit": {"value": 2.0, "source": "Literature A"},
            "max_abs_z_limit": {"value": 3.0, "source": "Literature B"},
        }
        res = unbiasedness_summary(self.analog, self.windowed, limits=limits)
        self.assertEqual(res["verdict"], "consistent")
        self.assertEqual(res["reasons"], [])

    def test_rms_z_limit_failing(self):
        limits = {
            "rms_z_limit": {"value": 0.5, "source": "Conservative RMS Spec"},
            "max_abs_z_limit": {"value": 5.0, "source": "Standard Max Spec"},
        }
        res = unbiasedness_summary(self.analog, self.windowed, limits=limits)
        self.assertEqual(res["verdict"], "inconsistent")
        self.assertEqual(len(res["reasons"]), 1)
        reason = res["reasons"][0]
        self.assertIn("rms_z_limit", reason)
        self.assertIn("0.5", reason)
        self.assertIn(str(res["rms_z"]), reason)
        self.assertIn("Conservative RMS Spec", reason)

    def test_both_limits_failing(self):
        limits = {
            "rms_z_limit": {"value": 0.5, "source": "Strict RMS Source"},
            "max_abs_z_limit": {"value": 1.0, "source": "Strict Max Source"},
        }
        res = unbiasedness_summary(self.analog, self.windowed, limits=limits)
        self.assertEqual(res["verdict"], "inconsistent")
        self.assertEqual(len(res["reasons"]), 2)
        r0, r1 = res["reasons"]
        self.assertIn("rms_z_limit", r0)
        self.assertIn("0.5", r0)
        self.assertIn(str(res["rms_z"]), r0)
        self.assertIn("Strict RMS Source", r0)

        self.assertIn("max_abs_z_limit", r1)
        self.assertIn("1.0", r1)
        self.assertIn(str(res["max_abs_z"]), r1)
        self.assertIn("Strict Max Source", r1)

    def test_infinite_z_with_limits(self):
        analog_inf = [(5.0, 0.0), (10.0, 1.0)]
        windowed_inf = [(8.0, 0.0), (10.0, 1.0)]  # first bin has mw != ma and comb == 0 -> z = inf
        limits = {
            "rms_z_limit": {"value": 1000.0, "source": "Huge Limit RMS"},
            "max_abs_z_limit": {"value": 1000.0, "source": "Huge Limit Max"},
        }
        res = unbiasedness_summary(analog_inf, windowed_inf, limits=limits)
        self.assertEqual(res["verdict"], "inconsistent")
        self.assertTrue(math.isinf(res["rms_z"]))
        self.assertTrue(math.isinf(res["max_abs_z"]))


class TestLimitsValidation(unittest.TestCase):
    def setUp(self):
        self.analog = [(1.0, 0.1)]
        self.windowed = [(1.0, 0.1)]

    def test_unknown_name(self):
        with self.assertRaises(VarianceError) as ctx:
            unbiasedness_summary(self.analog, self.windowed, limits={"foo_limit": {"value": 1.0, "source": "src"}})
        self.assertIn("limits", str(ctx.exception).lower())

    def test_missing_source(self):
        with self.assertRaises(VarianceError) as ctx:
            unbiasedness_summary(self.analog, self.windowed, limits={"rms_z_limit": {"value": 1.0}})
        self.assertIn("limits", str(ctx.exception).lower())

    def test_source_whitespace_only(self):
        with self.assertRaises(VarianceError) as ctx:
            unbiasedness_summary(self.analog, self.windowed, limits={"rms_z_limit": {"value": 1.0, "source": "   "}})
        self.assertIn("limits", str(ctx.exception).lower())

    def test_value_zero(self):
        with self.assertRaises(VarianceError) as ctx:
            unbiasedness_summary(self.analog, self.windowed, limits={"rms_z_limit": {"value": 0, "source": "src"}})
        self.assertIn("limits", str(ctx.exception).lower())
        with self.assertRaises(VarianceError) as ctx:
            unbiasedness_summary(self.analog, self.windowed, limits={"rms_z_limit": {"value": 0.0, "source": "src"}})
        self.assertIn("limits", str(ctx.exception).lower())

    def test_value_negative(self):
        with self.assertRaises(VarianceError) as ctx:
            unbiasedness_summary(self.analog, self.windowed, limits={"rms_z_limit": {"value": -1.5, "source": "src"}})
        self.assertIn("limits", str(ctx.exception).lower())

    def test_value_nan(self):
        with self.assertRaises(VarianceError) as ctx:
            unbiasedness_summary(self.analog, self.windowed, limits={"rms_z_limit": {"value": float("nan"), "source": "src"}})
        self.assertIn("limits", str(ctx.exception).lower())

    def test_value_bool(self):
        with self.assertRaises(VarianceError) as ctx:
            unbiasedness_summary(self.analog, self.windowed, limits={"rms_z_limit": {"value": True, "source": "src"}})
        self.assertIn("limits", str(ctx.exception).lower())
        with self.assertRaises(VarianceError) as ctx:
            unbiasedness_summary(self.analog, self.windowed, limits={"rms_z_limit": {"value": False, "source": "src"}})
        self.assertIn("limits", str(ctx.exception).lower())

    def test_entry_not_a_dict(self):
        with self.assertRaises(VarianceError) as ctx:
            unbiasedness_summary(self.analog, self.windowed, limits={"rms_z_limit": 1.0})
        self.assertIn("limits", str(ctx.exception).lower())
        with self.assertRaises(VarianceError) as ctx:
            unbiasedness_summary(self.analog, self.windowed, limits={"rms_z_limit": "not a dict"})
        self.assertIn("limits", str(ctx.exception).lower())

    def test_entry_extra_key(self):
        with self.assertRaises(VarianceError) as ctx:
            unbiasedness_summary(
                self.analog,
                self.windowed,
                limits={"rms_z_limit": {"value": 1.0, "source": "src", "extra": 42}},
            )
        self.assertIn("limits", str(ctx.exception).lower())

    def test_limits_not_a_dict(self):
        with self.assertRaises(VarianceError) as ctx:
            unbiasedness_summary(self.analog, self.windowed, limits="invalid")
        self.assertIn("limits", str(ctx.exception).lower())
        with self.assertRaises(VarianceError) as ctx:
            unbiasedness_summary(self.analog, self.windowed, limits=[1, 2, 3])
        self.assertIn("limits", str(ctx.exception).lower())


class TestFalsificationEdgeCases(unittest.TestCase):
    def test_positive_and_negative_infinite_z_produces_nan_mean(self):
        # When one bin produces +inf and another produces -inf, mean arithmetic produces nan
        # while rms produces inf. Verdict must still be inconsistent.
        analog = [(0.0, 0.0), (1.0, 0.0), (10.0, 0.0)]
        windowed = [(0.0, 0.0), (2.0, 0.0), (5.0, 0.0)]
        limits = {"rms_z_limit": {"value": 2.0, "source": "Ref"}}
        res = unbiasedness_summary(analog, windowed, limits=limits)
        self.assertEqual(res["n_bins"], 3)
        self.assertEqual(res["n_used"], 2)
        self.assertTrue(math.isnan(res["mean_z"]))
        self.assertTrue(math.isinf(res["rms_z"]))
        self.assertTrue(math.isinf(res["max_abs_z"]))
        self.assertEqual(res["verdict"], "inconsistent")

    def test_single_limit_rms_only(self):
        analog = [(1.0, 1.0)]
        windowed = [(3.0, 1.0)]  # z = 2 / sqrt(2) ~= 1.4142
        limits = {"rms_z_limit": {"value": 2.0, "source": "Only RMS"}}
        res = unbiasedness_summary(analog, windowed, limits=limits)
        self.assertEqual(res["verdict"], "consistent")
        self.assertEqual(res["reasons"], [])

    def test_single_limit_max_abs_only(self):
        analog = [(1.0, 1.0)]
        windowed = [(3.0, 1.0)]  # z = 2 / sqrt(2) ~= 1.4142
        limits = {"max_abs_z_limit": {"value": 1.0, "source": "Only Max"}}
        res = unbiasedness_summary(analog, windowed, limits=limits)
        self.assertEqual(res["verdict"], "inconsistent")
        self.assertEqual(len(res["reasons"]), 1)
        self.assertIn("max_abs_z_limit", res["reasons"][0])

class TestAddedByTheDispatcher(unittest.TestCase):
    """Added by the dispatcher after a mutation check showed a gap in the brief's test list."""

    def test_a_limit_is_met_when_the_measure_equals_it(self):
        """One bin, analog (0, sigma 1), windowed (1, sigma 0): z is exactly 1, so rms_z and max_abs_z are exactly 1.
        A limit of exactly 1 holds (the comparison is less than or equal), a limit just below 1 does not."""
        analog = [(0.0, 1.0)]
        windowed = [(1.0, 0.0)]
        holds = {"rms_z_limit": {"value": 1.0, "source": "own choice"}, "max_abs_z_limit": {"value": 1.0, "source": "own choice"}}
        res = unbiasedness_summary(analog, windowed, holds)
        self.assertEqual(res["rms_z"], 1.0)
        self.assertEqual(res["max_abs_z"], 1.0)
        self.assertEqual(res["verdict"], "consistent")
        self.assertEqual(res["reasons"], [])
        fails = {"rms_z_limit": {"value": 0.999999, "source": "own choice"}}
        self.assertEqual(unbiasedness_summary(analog, windowed, fails)["verdict"], "inconsistent")


if __name__ == "__main__":
    unittest.main(verbosity=2)
