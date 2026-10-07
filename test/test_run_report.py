"""Tests for studio/openmc_studio/run_report.py.

Verifies report dictionary creation, formatting rules, HTML/Markdown rendering,
file output, error handling, and escaping safety without OpenMC or external services.
"""
import html
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "studio"))
from openmc_studio import run_report


class TestCompleteReport(unittest.TestCase):
    """Test 1: Complete hand-written record, summary and findings."""

    def test_complete_report(self):
        record = {
            "kind": "run",
            "written": "2026-10-07T12:00:00+0000",
            "environment": {
                "studio": {"version": "0.3.0", "git": {"commit": "1a2b3c4d5e", "dirty": True}},
                "python": "3.11.15",
                "platform": "Linux 5.15.0 x86_64",
                "openmc": {"python": "0.14.0", "executable": "OpenMC version 0.14.0"},
                "nuclear_data": {
                    "cross_sections": "/data/xs/cross_sections.xml",
                    "sha256": "feedbeefcafebabe",
                    "size": 5242880,
                },
                "exporter": {
                    "path": "/opt/exporter",
                    "git": {"commit": "exp9999", "dirty": False},
                },
                "montepy": "0.4.5",
            },
            "settings": {
                "seed": 42,
                "batches": 100,
                "particles": 10000,
                "runMode": "eigenvalue",
                "active": True,
            },
            "normalization": {
                "tallies": "per source particle",
                "dose": "pSv per source particle",
            },
            "files": {
                "model.py": "hash_model",
                "geometry.xml": "hash_geom",
            },
        }

        summary = {
            "run_mode": "eigenvalue",
            "batches": 100,
            "inactive": 20,
            "particles": 10000,
            "seed": 42,
            "runtime_s": 12.345,
            "keff": [1.00123, 0.00045],
        }

        findings = [
            {"level": "info", "code": "I01", "message": "all good", "detail": "extra"},
            {"level": "error", "code": "E01", "message": "critical issue", "detail": "bad"},
        ]

        report = run_report.build_report(record, summary=summary, findings=findings)

        self.assertEqual(report["title"], "run record written 2026-10-07T12:00:00+0000")

        expected_env_rows = [
            ["Studio version", "0.3.0"],
            ["Studio commit", "1a2b3c4d5e (uncommitted changes)"],
            ["Python", "3.11.15"],
            ["Platform", "Linux 5.15.0 x86_64"],
            ["OpenMC (Python)", "0.14.0"],
            ["OpenMC (executable)", "OpenMC version 0.14.0"],
            ["Nuclear data file", "/data/xs/cross_sections.xml"],
            ["Nuclear data SHA-256", "feedbeefcafebabe"],
            ["Nuclear data size (bytes)", "5242880"],
            ["Exporter commit", "exp9999"],
            ["MontePy", "0.4.5"],
        ]
        self.assertEqual(report["environment"], expected_env_rows)

        expected_settings_rows = [
            ["active", "True"],
            ["batches", "100"],
            ["particles", "10000"],
            ["runMode", "eigenvalue"],
            ["seed", "42"],
        ]
        self.assertEqual(report["settings"], expected_settings_rows)

        expected_norm_rows = [
            ["dose", "pSv per source particle"],
            ["tallies", "per source particle"],
        ]
        self.assertEqual(report["normalization"], expected_norm_rows)

        expected_files_rows = [
            ["geometry.xml", "hash_geom"],
            ["model.py", "hash_model"],
        ]
        self.assertEqual(report["files"], expected_files_rows)

        expected_results_rows = [
            ["Run mode", "eigenvalue"],
            ["Batches", "100"],
            ["Inactive batches", "20"],
            ["Particles per batch", "10000"],
            ["Seed", "42"],
            ["Runtime (s)", "12.345"],
            ["k effective", "1.00123 +/- 0.00045 (1 sigma)"],
        ]
        self.assertEqual(report["results"], expected_results_rows)

        expected_findings_rows = [
            ["error", "E01", "critical issue"],
            ["info", "I01", "all good"],
        ]
        self.assertEqual(report["findings"], expected_findings_rows)
        self.assertEqual(report["counts"], {"error": 1, "warning": 0, "info": 1, "not-compared": 0})
        self.assertEqual(report["notes"], ["record has uncommitted changes"])


class TestMissingData(unittest.TestCase):
    """Test 2: Missing data: empty environment, no files, no settings."""

    def test_empty_environment_and_null_values(self):
        record = {
            "environment": {},
        }
        report = run_report.build_report(record)

        self.assertEqual(report["title"], "unknown record written unknown")

        expected_env_rows = [
            ["Studio version", "unknown"],
            ["Studio commit", "unknown"],
            ["Python", "unknown"],
            ["Platform", "unknown"],
            ["OpenMC (Python)", "unknown"],
            ["OpenMC (executable)", "unknown"],
            ["Nuclear data file", "unknown"],
            ["Nuclear data SHA-256", "unknown"],
            ["Nuclear data size (bytes)", "unknown"],
        ]
        self.assertEqual(report["environment"], expected_env_rows)
        self.assertEqual(report["settings"], [])
        self.assertEqual(report["normalization"], [])
        self.assertEqual(report["files"], [])
        self.assertEqual(report["results"], [])
        self.assertEqual(report["findings"], [])
        self.assertEqual(report["counts"], {"error": 0, "warning": 0, "info": 0, "not-compared": 0})
        self.assertIn("no result summary supplied", report["notes"])
        self.assertIn("no findings supplied", report["notes"])

    def test_null_values_become_unknown(self):
        record = {
            "kind": None,
            "written": None,
            "environment": {
                "studio": {"version": None, "git": {"commit": None, "dirty": False}},
                "python": None,
                "platform": None,
                "openmc": {"python": None, "executable": None},
                "nuclear_data": {"cross_sections": None, "sha256": None, "size": None},
                "exporter": {"git": {"commit": None}},
                "montepy": None,
            },
            "settings": {"paramA": None, "paramB": ""},
            "normalization": {"normA": None},
            "files": {"fileA": None},
        }
        report = run_report.build_report(record, summary={}, findings=[])
        self.assertEqual(report["title"], "unknown record written unknown")
        for _label, val in report["environment"]:
            self.assertEqual(val, "unknown")
        self.assertEqual(report["settings"], [["paramA", "unknown"], ["paramB", "unknown"]])
        self.assertEqual(report["normalization"], [["normA", "unknown"]])
        self.assertEqual(report["files"], [["fileA", "unknown"]])


class TestFindingsOrderingAndCounts(unittest.TestCase):
    """Test 3: Findings ordered by level and counted; unknown level goes last."""

    def test_scrambled_findings(self):
        findings = [
            {"level": "not-compared", "code": "NC1", "message": "not compared item"},
            {"level": "info", "code": "I1", "message": "info item"},
            {"level": "custom-level", "code": "X1", "message": "unknown level item"},
            {"level": "error", "code": "E1", "message": "error item 1"},
            {"level": "warning", "code": "W1", "message": "warning item"},
            {"level": "error", "code": "E2", "message": "error item 2"},
        ]
        record = {"kind": "run", "written": "2026-10-07", "environment": {}}
        report = run_report.build_report(record, summary={}, findings=findings)

        expected_rows = [
            ["error", "E1", "error item 1"],
            ["error", "E2", "error item 2"],
            ["warning", "W1", "warning item"],
            ["info", "I1", "info item"],
            ["not-compared", "NC1", "not compared item"],
            ["custom-level", "X1", "unknown level item"],
        ]
        self.assertEqual(report["findings"], expected_rows)

        expected_counts = {
            "error": 2,
            "warning": 1,
            "info": 1,
            "not-compared": 1,
            "other": 1,
        }
        self.assertEqual(report["counts"], expected_counts)


class TestNotes(unittest.TestCase):
    """Test 4: Notes combinations."""

    def test_all_notes(self):
        record = {
            "environment": {
                "studio": {"git": {"commit": "123", "dirty": True}},
            }
        }
        report = run_report.build_report(record, summary=None, findings=None)
        expected_notes = [
            "no result summary supplied",
            "no findings supplied",
            "record has uncommitted changes",
        ]
        self.assertEqual(report["notes"], expected_notes)

    def test_no_notes_when_all_provided_and_clean(self):
        record = {
            "environment": {
                "studio": {"git": {"commit": "123", "dirty": False}},
            }
        }
        report = run_report.build_report(record, summary={}, findings=[])
        self.assertEqual(report["notes"], [])

    def test_individual_notes(self):
        # Summary present, findings None, clean git
        r1 = run_report.build_report({"environment": {}}, summary={}, findings=None)
        self.assertEqual(r1["notes"], ["no findings supplied"])

        # Summary None, findings present, clean git
        r2 = run_report.build_report({"environment": {}}, summary=None, findings=[])
        self.assertEqual(r2["notes"], ["no result summary supplied"])

        # Both present, dirty git
        r3 = run_report.build_report(
            {"environment": {"studio": {"git": {"dirty": True}}}},
            summary={},
            findings=[],
        )
        self.assertEqual(r3["notes"], ["record has uncommitted changes"])


class TestUnusableRecord(unittest.TestCase):
    """Test 5: Record with error key gives unusable report."""

    def test_record_with_error(self):
        record = {
            "kind": "run",
            "error": "disk quota exceeded during run initialization",
        }
        report = run_report.build_report(record)

        self.assertEqual(report["title"], "Run report (record unusable)")
        self.assertEqual(report["environment"], [])
        self.assertEqual(report["settings"], [])
        self.assertEqual(report["normalization"], [])
        self.assertEqual(report["files"], [])
        self.assertEqual(report["results"], [])
        self.assertEqual(report["findings"], [])
        self.assertEqual(report["counts"], {"error": 0, "warning": 0, "info": 0, "not-compared": 0})
        self.assertEqual(
            report["notes"],
            ["provenance record could not be made: disk quota exceeded during run initialization"],
        )


class TestHtmlSafety(unittest.TestCase):
    """Test 6: HTML safety and escaping."""

    def test_html_escaping_and_repeatability(self):
        bad_str = "<script>alert(1)</script> & \" ' "
        record = {
            "kind": f"run-{bad_str}",
            "written": "2026-10-07",
            "environment": {
                "python": bad_str,
            },
            "settings": {
                "danger": bad_str,
            },
            "files": {
                f"file-{bad_str}.txt": "abc",
            },
        }
        findings = [
            {"level": "error", "code": "E01", "message": bad_str},
        ]
        report = run_report.build_report(record, summary={}, findings=findings)

        html_text = run_report.render_html(report)

        self.assertNotIn("<script", html_text)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html_text)
        self.assertIn("&amp;", html_text)
        self.assertIn("&quot;", html_text)
        self.assertIn("&#x27;", html_text)

        # Repeating render_html must return identical output
        html_second = run_report.render_html(report)
        self.assertEqual(html_text, html_second)

        # Finding class and text
        self.assertIn('class="level-error"', html_text)
        self.assertIn("<td>error</td>", html_text)


class TestMarkdown(unittest.TestCase):
    """Test 7: Markdown formatting rules."""

    def test_markdown_escaping(self):
        record = {
            "kind": "test-kind",
            "written": "2026-10-07",
            "environment": {
                "python": "3.11",
            },
            "settings": {
                "pipe_val": "a|b",
                "newline_val": "line1\nline2",
            },
        }
        report = run_report.build_report(record, summary={}, findings=[])
        md_text = run_report.render_markdown(report)

        self.assertIn(r"a\|b", md_text)
        self.assertIn("line1 line2", md_text)
        # Check no raw newline inside any table row
        for line in md_text.splitlines():
            if line.startswith("|"):
                self.assertNotIn("\n", line)
                self.assertNotIn("\r", line)

        self.assertTrue(md_text.endswith("\n"))
        self.assertFalse(md_text.endswith("\n\n"))

        # No HTML tags
        self.assertNotIn("<", md_text)
        self.assertNotIn(">", md_text)


class TestWrite(unittest.TestCase):
    """Test 8: write function creates files, checks formats and errors."""

    def test_write_html_and_markdown(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            record = {"kind": "run", "written": "2026-10-07", "environment": {}}
            report = run_report.build_report(record, summary={}, findings=[])

            # HTML write
            html_path = run_report.write(tmp, report, fmt="html")
            self.assertEqual(html_path, tmp / "run-report.html")
            self.assertTrue(html_path.exists())
            html_bytes = html_path.read_bytes()
            self.assertNotIn(b"\r", html_bytes)
            self.assertEqual(html_bytes.decode("utf-8"), run_report.render_html(report))

            # Markdown write
            md_path = run_report.write(tmp, report, fmt="markdown")
            self.assertEqual(md_path, tmp / "run-report.md")
            self.assertTrue(md_path.exists())
            md_bytes = md_path.read_bytes()
            self.assertNotIn(b"\r", md_bytes)
            self.assertEqual(md_bytes.decode("utf-8"), run_report.render_markdown(report))

            # Invalid format
            with self.assertRaises(ValueError):
                run_report.write(tmp, report, fmt="pdf")

            # Non-existent folder
            non_existent = tmp / "does_not_exist"
            with self.assertRaises(OSError):
                run_report.write(non_existent, report, fmt="html")


class TestBadInputs(unittest.TestCase):
    """Test 9: Bad-input rule (Rule 10) asserting specific TypeErrors."""

    def test_record_type_error(self):
        with self.assertRaises(TypeError):
            run_report.build_report(["not", "a", "dict"])
        with self.assertRaises(TypeError):
            run_report.build_report("not a dict")
        with self.assertRaises(TypeError):
            run_report.build_report(123)
        with self.assertRaises(TypeError):
            run_report.build_report(None)

    def test_summary_type_error(self):
        with self.assertRaises(TypeError):
            run_report.build_report({}, summary="not-a-dict")
        with self.assertRaises(TypeError):
            run_report.build_report({}, summary=123)
        with self.assertRaises(TypeError):
            run_report.build_report({}, summary=["list"])

    def test_findings_type_error(self):
        with self.assertRaises(TypeError):
            run_report.build_report({}, findings={"not": "a list"})
        with self.assertRaises(TypeError):
            run_report.build_report({}, findings="not-a-list")
        with self.assertRaises(TypeError):
            run_report.build_report({}, findings=[123])
        with self.assertRaises(TypeError):
            run_report.build_report({}, findings=["string"])
        with self.assertRaises(TypeError):
            run_report.build_report({}, findings=[{"level": "error"}, "not a dict"])

    def test_render_and_write_type_error(self):
        with self.assertRaises(TypeError):
            run_report.render_html("not a dict")
        with self.assertRaises(TypeError):
            run_report.render_markdown(["not a dict"])
        with self.assertRaises(TypeError):
            run_report.write(".", "not a dict")


class TestEdgeCases(unittest.TestCase):
    """Test 10: Additional checks to attempt to falsify our work."""

    def test_keff_non_finite_or_malformed(self):
        record = {"environment": {}}
        # NaN std
        s1 = {"keff": [1.0, float("nan")]}
        r1 = run_report.build_report(record, summary=s1, findings=[])
        self.assertEqual([row[0] for row in r1["results"]], [])

        # Inf nominal
        s2 = {"keff": [float("inf"), 0.01]}
        r2 = run_report.build_report(record, summary=s2, findings=[])
        self.assertEqual([row[0] for row in r2["results"]], [])

        # Wrong length
        s3 = {"keff": [1.0]}
        r3 = run_report.build_report(record, summary=s3, findings=[])
        self.assertEqual([row[0] for row in r3["results"]], [])

        # Non-numeric
        s4 = {"keff": ["1.0", "0.01"]}
        r4 = run_report.build_report(record, summary=s4, findings=[])
        self.assertEqual([row[0] for row in r4["results"]], [])

    def test_summary_n_inactive_fallback(self):
        record = {"environment": {}}
        s = {"n_inactive": 15}
        r = run_report.build_report(record, summary=s, findings=[])
        self.assertEqual(r["results"], [["Inactive batches", "15"]])

    def test_exporter_without_montepy(self):
        record = {
            "environment": {
                "exporter": {"git": {"commit": "commit_exp"}},
            }
        }
        r = run_report.build_report(record, summary={}, findings=[])
        env_dict = dict(r["environment"])
        self.assertEqual(env_dict["Exporter commit"], "commit_exp")
        self.assertEqual(env_dict["MontePy"], "unknown")

    def test_montepy_without_exporter(self):
        record = {
            "environment": {
                "montepy": "0.3.0",
            }
        }
        r = run_report.build_report(record, summary={}, findings=[])
        env_dict = dict(r["environment"])
        self.assertEqual(env_dict["Exporter commit"], "unknown")
        self.assertEqual(env_dict["MontePy"], "0.3.0")

    def test_empty_sections_omitted_in_html_and_markdown(self):
        record = {
            "kind": "clean",
            "written": "2026-10-07",
            "environment": {},
        }
        # summary={} -> results is empty, findings=[] -> findings is empty, clean -> notes is empty
        r = run_report.build_report(record, summary={}, findings=[])
        html_out = run_report.render_html(r)
        md_out = run_report.render_markdown(r)

        # Environment is present
        self.assertIn("<h2>Environment</h2>", html_out)
        self.assertIn("## Environment", md_out)

        # Other sections are empty so headings must NOT be present
        self.assertNotIn("<h2>Settings</h2>", html_out)
        self.assertNotIn("## Settings", md_out)
        self.assertNotIn("<h2>Normalization</h2>", html_out)
        self.assertNotIn("## Normalization", md_out)
        self.assertNotIn("<h2>Files</h2>", html_out)
        self.assertNotIn("## Files", md_out)
        self.assertNotIn("<h2>Results</h2>", html_out)
        self.assertNotIn("## Results", md_out)
        self.assertNotIn("<h2>Findings</h2>", html_out)
        self.assertNotIn("## Findings", md_out)
        self.assertNotIn("<h2>Notes</h2>", html_out)
        self.assertNotIn("## Notes", md_out)

    def test_environment_none(self):
        record = {"environment": None}
        r = run_report.build_report(record)
        self.assertEqual(len(r["environment"]), 9)
        self.assertTrue(all(val == "unknown" for _label, val in r["environment"]))

    def test_inactive_zero_preserved(self):
        record = {"environment": {}}
        summary = {"inactive": 0}
        r = run_report.build_report(record, summary=summary, findings=[])
        self.assertEqual(r["results"], [["Inactive batches", "0"]])

    def test_empty_finding_dict(self):
        record = {"environment": {}}
        findings = [{}]
        r = run_report.build_report(record, summary={}, findings=findings)
        self.assertEqual(r["findings"], [["unknown", "", ""]])
        self.assertEqual(r["counts"]["other"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
