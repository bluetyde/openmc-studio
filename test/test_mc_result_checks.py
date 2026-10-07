"""Tests for studio/openmc_studio/mc_result_checks.py.

Exercises eigenvalue result trustworthiness checks, threshold handling,
entropy settling analysis, and k formatting per JCGM 100:2008 (GUM).
"""
import math
from pathlib import Path
import statistics
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "studio"))

from openmc_studio import mc_result_checks
from openmc_studio.mc_result_checks import check_eigenvalue, entropy_settling_batch, format_k


class TestMCResultChecks(unittest.TestCase):
    """Test suite for OpenMC result quality checks and formatters."""

    def test_01_fixed_source_summary(self):
        """1. A fixed-source summary returns exactly one finding, not-eigenvalue."""
        summary = {"run_mode": "fixed source", "batches": 10, "particles": 100}
        findings = check_eigenvalue(summary)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["level"], "info")
        self.assertEqual(findings[0]["code"], "not-eigenvalue")
        self.assertIn("fixed source", findings[0]["message"])
        self.assertEqual(findings[0]["detail"], {})

    def test_02_no_thresholds_all_not_compared(self):
        """2. No thresholds at all yields k-estimate info and expected not-compared findings."""
        summary = {
            "run_mode": "eigenvalue",
            "keff": [1.00123, 0.00045],
            "particles": 1000,
            "batches": 100,
            "n_inactive": 20,
            "entropy": [5.0 + 0.01 * math.sin(i) for i in range(100)],
        }
        findings = check_eigenvalue(summary)
        codes = {f["code"]: f for f in findings}

        self.assertIn("k-estimate", codes)
        self.assertEqual(codes["k-estimate"]["level"], "info")
        self.assertIn("1 sigma, standard uncertainty", codes["k-estimate"]["message"])

        self.assertIn("lost-particles", codes)
        self.assertEqual(codes["lost-particles"]["level"], "not-compared")
        self.assertEqual(codes["lost-particles"]["message"], "lost particle count not available")

        for name, code in [
            ("min_particles_per_batch", "particles-per-batch"),
            ("min_active_batches", "active-batches"),
            ("entropy_band_sigma", "entropy-settled"),
        ]:
            self.assertIn(code, codes)
            self.assertEqual(codes[code]["level"], "not-compared")
            self.assertEqual(
                codes[code]["message"],
                f"no threshold with a source was supplied for {name}",
            )

    def test_03_threshold_and_basic_input_validation(self):
        """3. Threshold validation and basic parameter validation each raise ValueError or TypeError."""
        base_summary = {
            "run_mode": "eigenvalue",
            "keff": [1.0, 0.001],
            "particles": 1000,
            "batches": 10,
            "n_inactive": 2,
        }

        # Threshold validation errors
        bad_thresholds = [
            ({"min_particles_per_batch": {"value": 1000}}, "missing source"),
            ({"min_particles_per_batch": {"value": 1000, "source": "   "}}, "blank source"),
            ({"unknown_threshold": {"value": 1000, "source": "src"}}, "unknown name"),
            ({"min_particles_per_batch": {"value": 0, "source": "src"}}, "value 0"),
            ({"min_particles_per_batch": {"value": -5, "source": "src"}}, "value negative"),
            ({"min_particles_per_batch": {"value": float("nan"), "source": "src"}}, "value nan"),
            ({"min_particles_per_batch": {"value": True, "source": "src"}}, "value True"),
            ({"min_particles_per_batch": 1000}, "entry not a dict"),
            ({"min_particles_per_batch": {"source": "src"}}, "missing value"),
            ({"min_particles_per_batch": {"value": 1000, "source": "src", "extra": 1}}, "extra key"),
        ]
        for thresh, label in bad_thresholds:
            with self.subTest(label=label):
                with self.assertRaises(ValueError):
                    check_eigenvalue(base_summary, thresholds=thresh)

        # Non-dict thresholds
        with self.assertRaises(ValueError):
            check_eigenvalue(base_summary, thresholds="invalid")

        # lost_particles validation
        for bad_lp in [-1, 1.5, True]:
            with self.subTest(bad_lp=bad_lp):
                with self.assertRaises(ValueError):
                    check_eigenvalue(base_summary, lost_particles=bad_lp)

        # summary is a list
        with self.assertRaises(TypeError):
            check_eigenvalue([1, 2, 3])

    def test_04_lost_particles(self):
        """4. Lost particles: 0 -> info; 3 -> warning with '3' in message and detail."""
        summary = {
            "run_mode": "eigenvalue",
            "keff": [1.0, 0.001],
            "particles": 1000,
            "batches": 10,
            "n_inactive": 2,
        }

        findings_0 = check_eigenvalue(summary, lost_particles=0)
        codes_0 = {f["code"]: f for f in findings_0}
        self.assertEqual(codes_0["lost-particles"]["level"], "info")
        self.assertEqual(codes_0["lost-particles"]["detail"], {"lost_particles": 0})

        findings_3 = check_eigenvalue(summary, lost_particles=3)
        codes_3 = {f["code"]: f for f in findings_3}
        self.assertEqual(codes_3["lost-particles"]["level"], "warning")
        self.assertIn("3", codes_3["lost-particles"]["message"])
        self.assertEqual(codes_3["lost-particles"]["detail"], {"lost_particles": 3})

    def test_05_particles_per_batch(self):
        """5. Particles per batch: 1000 vs 5000 -> warning; 5000 vs 5000 -> info; source in message."""
        source_tag = "OECD/NEA benchmark guidelines"
        thresh = {"min_particles_per_batch": {"value": 5000, "source": source_tag}}

        summary_low = {
            "run_mode": "eigenvalue",
            "keff": [1.0, 0.001],
            "particles": 1000,
            "batches": 10,
            "n_inactive": 2,
        }
        findings_low = check_eigenvalue(summary_low, thresholds=thresh)
        codes_low = {f["code"]: f for f in findings_low}
        self.assertEqual(codes_low["particles-per-batch"]["level"], "warning")
        self.assertIn(source_tag, codes_low["particles-per-batch"]["message"])

        summary_ok = {
            "run_mode": "eigenvalue",
            "keff": [1.0, 0.001],
            "particles": 5000,
            "batches": 10,
            "n_inactive": 2,
        }
        findings_ok = check_eigenvalue(summary_ok, thresholds=thresh)
        codes_ok = {f["code"]: f for f in findings_ok}
        self.assertEqual(codes_ok["particles-per-batch"]["level"], "info")
        self.assertIn(source_tag, codes_ok["particles-per-batch"]["message"])

    def test_06_active_batches(self):
        """6. Active batches comparisons, inactive fallback, and inactive-missing handling."""
        source_tag = "Best practice guidelines"
        thresh_80 = {"min_active_batches": {"value": 80, "source": source_tag}}
        thresh_70 = {"min_active_batches": {"value": 70, "source": source_tag}}

        # batches 100, n_inactive 30 -> 70 active
        summary_n_inactive = {
            "run_mode": "eigenvalue",
            "keff": [1.0, 0.001],
            "particles": 1000,
            "batches": 100,
            "n_inactive": 30,
        }
        f_80 = {f["code"]: f for f in check_eigenvalue(summary_n_inactive, thresholds=thresh_80)}
        self.assertEqual(f_80["active-batches"]["level"], "warning")

        f_70 = {f["code"]: f for f in check_eigenvalue(summary_n_inactive, thresholds=thresh_70)}
        self.assertEqual(f_70["active-batches"]["level"], "info")

        # only 'inactive' present
        summary_inactive_only = {
            "run_mode": "eigenvalue",
            "keff": [1.0, 0.001],
            "particles": 1000,
            "batches": 100,
            "inactive": 30,
        }
        f_inact_80 = {f["code"]: f for f in check_eigenvalue(summary_inactive_only, thresholds=thresh_80)}
        self.assertEqual(f_inact_80["active-batches"]["level"], "warning")

        f_inact_70 = {f["code"]: f for f in check_eigenvalue(summary_inactive_only, thresholds=thresh_70)}
        self.assertEqual(f_inact_70["active-batches"]["level"], "info")

        # neither present
        summary_neither = {
            "run_mode": "eigenvalue",
            "keff": [1.0, 0.001],
            "particles": 1000,
            "batches": 100,
        }
        findings_neither = check_eigenvalue(summary_neither, thresholds=thresh_70)
        codes_neither = [f["code"] for f in findings_neither]
        self.assertIn("inactive-missing", codes_neither)
        self.assertNotIn("active-batches", codes_neither)
        self.assertNotIn("entropy-settled", codes_neither)

    def test_07_entropy_synthetic_and_checks(self):
        """7. Entropy synthetic series verified with plain loop, settling comparisons, and edge cases."""
        # Synthetic series
        H = [5.0 - 3.0 * math.exp(-i / 5.0) + 0.1 * math.sin(7.3 * i) for i in range(100)]
        band_sigma = 3

        # Independently compute settling index via plain loop
        final_half = H[len(H) // 2:]
        mean_f = statistics.mean(final_half)
        std_f = statistics.stdev(final_half)
        threshold = band_sigma * std_f

        expected_idx = len(H)
        for i in range(len(H)):
            if all(abs(H[j] - mean_f) <= threshold for j in range(i, len(H))):
                expected_idx = i
                break

        actual_idx = entropy_settling_batch(H, band_sigma)
        self.assertEqual(actual_idx, expected_idx)

        source_tag = "Brown (2006) heuristic"
        thresh = {"entropy_band_sigma": {"value": band_sigma, "source": source_tag}}

        # n_inactive = 5 -> warning
        summary_5 = {
            "run_mode": "eigenvalue",
            "keff": [1.0, 0.001],
            "particles": 1000,
            "batches": 100,
            "n_inactive": 5,
            "entropy": H,
        }
        f_5 = {f["code"]: f for f in check_eigenvalue(summary_5, thresholds=thresh)}
        self.assertEqual(f_5["entropy-settled"]["level"], "warning")
        self.assertEqual(f_5["entropy-settled"]["detail"], {"index": actual_idx, "n_inactive": 5})

        # n_inactive = 60 -> info
        summary_60 = {
            "run_mode": "eigenvalue",
            "keff": [1.0, 0.001],
            "particles": 1000,
            "batches": 100,
            "n_inactive": 60,
            "entropy": H,
        }
        f_60 = {f["code"]: f for f in check_eigenvalue(summary_60, thresholds=thresh)}
        self.assertEqual(f_60["entropy-settled"]["level"], "info")
        self.assertEqual(f_60["entropy-settled"]["detail"], {"index": actual_idx, "n_inactive": 60})

        # Constant series
        summary_const = {
            "run_mode": "eigenvalue",
            "keff": [1.0, 0.001],
            "particles": 1000,
            "batches": 50,
            "n_inactive": 10,
            "entropy": [4.5] * 50,
        }
        f_const = {f["code"]: f for f in check_eigenvalue(summary_const, thresholds=thresh)}
        self.assertEqual(f_const["entropy-settled"]["level"], "not-compared")
        self.assertEqual(f_const["entropy-settled"]["message"], "entropy series too short or constant, settling cannot be judged")

        # 3-element series
        summary_3 = {
            "run_mode": "eigenvalue",
            "keff": [1.0, 0.001],
            "particles": 1000,
            "batches": 3,
            "n_inactive": 1,
            "entropy": [4.0, 4.2, 4.1],
        }
        f_3 = {f["code"]: f for f in check_eigenvalue(summary_3, thresholds=thresh)}
        self.assertEqual(f_3["entropy-settled"]["level"], "not-compared")
        self.assertEqual(f_3["entropy-settled"]["message"], "entropy series too short or constant, settling cannot be judged")

        # No entropy key
        summary_no_ent = {
            "run_mode": "eigenvalue",
            "keff": [1.0, 0.001],
            "particles": 1000,
            "batches": 100,
            "n_inactive": 20,
        }
        f_no_ent = {f["code"]: f for f in check_eigenvalue(summary_no_ent, thresholds=thresh)}
        self.assertEqual(f_no_ent["entropy-settled"]["level"], "not-compared")
        self.assertEqual(f_no_ent["entropy-settled"]["message"], "no entropy series (the run had no Shannon entropy mesh)")

        # Series of wrong length
        summary_bad_len = {
            "run_mode": "eigenvalue",
            "keff": [1.0, 0.001],
            "particles": 1000,
            "batches": 100,
            "n_inactive": 20,
            "entropy": [4.0] * 50,
        }
        f_bad_len = {f["code"]: f for f in check_eigenvalue(summary_bad_len, thresholds=thresh)}
        self.assertEqual(f_bad_len["entropy-length"]["level"], "error")

    def test_08_entropy_settling_batch_direct(self):
        """8. entropy_settling_batch returns 0 for in-band, 10 for delayed settling, and validates band_sigma."""
        # A series that never leaves the band: e.g. slight oscillation well within band
        # 20 elements, alternating 1.0 and 1.01
        in_band = [1.0 if i % 2 == 0 else 1.01 for i in range(20)]
        self.assertEqual(entropy_settling_batch(in_band, 3.0), 0)

        # First 10 values far outside, next 10 inside
        delayed = [100.0] * 10 + [1.0 if i % 2 == 0 else 1.01 for i in range(10)]
        self.assertEqual(entropy_settling_batch(delayed, 3.0), 10)

        # Band edge tests:
        # [0.0, 0.0, 1.0, 2.0, 3.0] -> final half [1.0, 2.0, 3.0] has mean 2.0, std 1.0.
        # At band_sigma = 1.0, threshold is 1.0.
        # index 2 has val 1.0 -> abs(1.0 - 2.0) = 1.0 <= 1.0 (inside on exact edge).
        # indices 3, 4 are inside. Settling batch is 2.
        self.assertEqual(entropy_settling_batch([0.0, 0.0, 1.0, 2.0, 3.0], 1.0), 2)
        # If index 2 is slightly outside (0.99), settling batch is 3.
        self.assertEqual(entropy_settling_batch([0.0, 0.0, 0.99, 2.0, 3.0], 1.0), 3)

        # band_sigma 0 or negative
        with self.assertRaises(ValueError):
            entropy_settling_batch(in_band, 0)
        with self.assertRaises(ValueError):
            entropy_settling_batch(in_band, -1.5)

    def test_09_missing_or_malformed_inputs(self):
        """9. Missing or non-int batches/particles, and missing or malformed keff handling."""
        # Missing or non-int batches
        summary_no_batches = {
            "run_mode": "eigenvalue",
            "keff": [1.0, 0.001],
            "particles": 1000,
            "n_inactive": 10,
        }
        f_no_b = {f["code"]: f for f in check_eigenvalue(summary_no_batches)}
        self.assertEqual(f_no_b["batches-missing"]["level"], "error")
        self.assertNotIn("active-batches", f_no_b)
        self.assertNotIn("entropy-settled", f_no_b)

        for bad_b in ["100", 100.5, True]:
            with self.subTest(bad_b=bad_b):
                s = dict(summary_no_batches, batches=bad_b)
                f = {entry["code"]: entry for entry in check_eigenvalue(s)}
                self.assertEqual(f["batches-missing"]["level"], "error")

        # Missing or non-int particles
        summary_no_parts = {
            "run_mode": "eigenvalue",
            "keff": [1.0, 0.001],
            "batches": 50,
            "n_inactive": 10,
        }
        f_no_p = {f["code"]: f for f in check_eigenvalue(summary_no_parts)}
        self.assertEqual(f_no_p["particles-missing"]["level"], "error")
        self.assertIn("active-batches", f_no_p)

        for bad_p in ["1000", 1000.5, True]:
            with self.subTest(bad_p=bad_p):
                s = dict(summary_no_parts, particles=bad_p)
                f = {entry["code"]: entry for entry in check_eigenvalue(s)}
                self.assertEqual(f["particles-missing"]["level"], "error")

        # Missing or malformed keff: later checks still run
        base_s = {
            "run_mode": "eigenvalue",
            "particles": 1000,
            "batches": 50,
            "n_inactive": 10,
        }
        for bad_keff in [None, [1.0], "1.0 +/- 0.01", []]:
            with self.subTest(bad_keff=bad_keff):
                s = dict(base_s)
                if bad_keff is not None:
                    s["keff"] = bad_keff
                findings = check_eigenvalue(s)
                codes = {f["code"]: f for f in findings}
                self.assertEqual(codes["k-missing"]["level"], "error")
                self.assertIn("particles-per-batch", codes)
                self.assertIn("active-batches", codes)

    def test_10_format_k(self):
        """10. format_k worked examples, uncertainty not available, invalid inputs, and rounding carry."""
        # 4 worked examples from specification
        self.assertEqual(format_k(1.00123, 0.00045), "1.00123 +/- 0.00045")
        self.assertEqual(format_k(1.23456, 0.0123), "1.235 +/- 0.012")
        self.assertEqual(format_k(0.99876, 0.0996), "1.00 +/- 0.10")
        self.assertEqual(format_k(1.0, 0.0), "1 (uncertainty not available)")

        # nan std
        self.assertEqual(format_k(1.0, float("nan")), "1 (uncertainty not available)")

        # non-finite nominal -> ValueError
        with self.assertRaises(ValueError):
            format_k(float("inf"), 0.1)
        with self.assertRaises(ValueError):
            format_k(float("nan"), 0.1)

        # uncertainty too large -> ValueError
        with self.assertRaises(ValueError):
            format_k(1.0, 123.0)

        # Rounding carry cases
        self.assertEqual(format_k(0.5, 0.0996), "0.50 +/- 0.10")
        self.assertEqual(format_k(0.9996, 0.000996), "0.9996 +/- 0.0010")
        self.assertEqual(format_k(9.996, 0.0996), "10.00 +/- 0.10")

    def test_11_bad_input_rule(self):
        """11. Bad inputs for every input kind assert specific error or finding without silent failure."""
        summary = {
            "run_mode": "eigenvalue",
            "keff": [1.0, 0.001],
            "particles": 1000,
            "batches": 10,
            "n_inactive": 2,
        }

        # bad summary type
        with self.assertRaises(TypeError):
            check_eigenvalue("not a dict")
        with self.assertRaises(TypeError):
            check_eigenvalue(None)

        # bad lost_particles
        with self.assertRaises(ValueError):
            check_eigenvalue(summary, lost_particles="zero")
        with self.assertRaises(ValueError):
            check_eigenvalue(summary, lost_particles=False)

        # bad thresholds fields
        for field in ["min_particles_per_batch", "min_active_batches", "entropy_band_sigma"]:
            with self.subTest(field=field, bad_val=0):
                with self.assertRaises(ValueError):
                    check_eigenvalue(summary, thresholds={field: {"value": 0, "source": "s"}})
            with self.subTest(field=field, bad_src=""):
                with self.assertRaises(ValueError):
                    check_eigenvalue(summary, thresholds={field: {"value": 10, "source": ""}})
            with self.subTest(field=field, bad_src_type=123):
                with self.assertRaises(ValueError):
                    check_eigenvalue(summary, thresholds={field: {"value": 10, "source": 123}})

        # bad entropy in entropy_settling_batch
        with self.assertRaises(TypeError):
            entropy_settling_batch("not a list", 1.0)
        with self.assertRaises(ValueError):
            entropy_settling_batch([1.0, float("nan"), 2.0, 3.0], 1.0)
        with self.assertRaises(ValueError):
            entropy_settling_batch([1.0, float("inf"), 2.0, 3.0], 1.0)
        with self.assertRaises(ValueError):
            entropy_settling_batch([1.0, True, 2.0, 3.0], 1.0)
        with self.assertRaises(ValueError):
            entropy_settling_batch([1.0, 2.0, 3.0, 4.0], float("nan"))
        with self.assertRaises(ValueError):
            entropy_settling_batch([1.0, 2.0, 3.0, 4.0], True)

        # bad keff values in check_eigenvalue
        bad_keffs = [
            [float("nan"), 0.001],
            [True, 0.001],
            [1.0, True],
            [1.0, "0.001"],
            [1.0, 123.0],
        ]
        for bk in bad_keffs:
            with self.subTest(bad_keff=bk):
                s = dict(summary, keff=bk)
                findings = check_eigenvalue(s)
                codes = {f["code"]: f for f in findings}
                self.assertEqual(codes["k-missing"]["level"], "error")


if __name__ == "__main__":
    unittest.main(verbosity=2)
