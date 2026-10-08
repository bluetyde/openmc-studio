"""Fixes after the Codex review of 2026-10-08 (specification-gap and silent-failure auditors) of the depletion, pre-run, material, pin-power and wiring work.

Each test is a case the review reproduced: a run left "running" when the record step fails, a pre-run check that approved what it could not read, a symmetry
verdict with no uncertainty behind it, a report that dropped its findings, a depletion record whose shares or fission Q were not checked, a stopped burn whose
record the Results route could not hand over.

Linux/WSL. Run: python test/test_codex_review_fixes.py
"""
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "studio"))
from openmc_studio import depletion_record, depletion_writer, pin_power_view, provenance, results, run_report, run_checks, server as srv  # noqa: E402
from openmc_studio.depletion_writer import WriterError, build  # noqa: E402

PIN = json.loads((ROOT / "test" / "fixtures" / "depletion" / "pin_run_data.json").read_text())


class FakeProc:
    stdout = iter(["a line"])

    def wait(self):
        return 0


class RunIsAlwaysFinished(unittest.TestCase):
    def test_a_failing_record_step_does_not_leave_the_run_running(self):
        tmp = Path(tempfile.mkdtemp(prefix="pump-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        (tmp / "deplete.py").write_text("")
        (tmp / "depletion_results.h5").write_bytes(b"not hdf5")
        (tmp / "meta.json").write_text("{}")
        provenance.write(tmp, "run", {"settings": {}}, files=("deplete.py",))
        studio = srv.Studio(tmp / "runs", "t" * 32, 0)
        run = srv.Run("r1", tmp, "demo")
        run.proc = FakeProc()
        real = provenance.update
        provenance.update = lambda *a, **k: (_ for _ in ()).throw(PermissionError("read-only"))   # the error path of the record step writes provenance
        try:
            studio._pump(run)
        finally:
            provenance.update = real
        self.assertNotEqual(run.status, "running", "the stream must end and the next run must be allowed")
        self.assertTrue(any("record step failed" in line and "PermissionError" in line for line in run.lines), run.lines)


class PreRunGateFailsClosed(unittest.TestCase):
    def test_a_project_the_check_cannot_read_is_refused_with_the_reason(self):
        bad = {"settings": {"particles": 0}, "materials": [{"id": []}], "parts": [{"id": "p", "material": []}]}
        refused = srv.prerun_gate(bad)
        self.assertIsNotNone(refused, "a check that raised used to approve the project")
        self.assertIn("could not read this project", refused["error"])
        self.assertEqual(refused["findings"][0]["code"], "prerun-check-failed")


class SymmetryNeedsAnUncertainty(unittest.TestCase):
    def mesh(self, values, std):
        return {"name": "m", "kind": "mesh", "mesh_type": "regular", "dims": [2, 2, 1], "lower": [0, 0, 0], "upper": [2, 2, 1], "scores": ["kappa-fission"],
                "values": {"kappa-fission": values}, "std": {"kappa-fission": std}}

    def test_pins_that_differ_with_zero_sigma_are_not_within_noise(self):
        a = pin_power_view.analyse(self.mesh([1.0, 1.0, 1.0, 9.0], [0.0] * 4))
        self.assertFalse(a["symmetry"]["within_noise"])
        self.assertIsNone(a["symmetry"]["max_z"])
        self.assertGreater(a["symmetry"]["max_deviation"], 1.0)
        json.dumps(a)  # no NaN or infinity in what goes to the page

    def test_equal_pins_with_zero_sigma_and_pins_that_differ_with_sigma_behave_as_before(self):
        self.assertTrue(pin_power_view.analyse(self.mesh([2.0] * 4, [0.0] * 4))["symmetry"]["within_noise"])
        b = pin_power_view.analyse(self.mesh([1.0, 1.0, 1.0, 9.0], [0.1] * 4))
        self.assertFalse(b["symmetry"]["within_noise"])
        self.assertGreater(b["symmetry"]["max_z"], 3.0)


class ReportKeepsWhatWasSupplied(unittest.TestCase):
    def test_an_unusable_record_still_reports_the_results_and_findings(self):
        rep = run_report.build_report({"error": "no provenance.json"}, {"run_mode": "eigenvalue", "batches": 10, "keff": [1.3, 0.001]},
                                      [{"level": "warning", "code": "lost-particles", "message": "5 lost particles"}])
        self.assertEqual(rep["title"], "Run report (record unusable)")
        self.assertEqual(rep["environment"], [])
        self.assertIn(["warning", "lost-particles", "5 lost particles"], rep["findings"])
        self.assertEqual(rep["counts"]["warning"], 1)
        self.assertTrue(any(r[0] == "Run mode" for r in rep["results"]))
        self.assertTrue(rep["notes"][0].startswith("provenance record could not be made"))

    def test_no_summary_and_no_findings_still_gives_the_old_minimal_report(self):
        rep = run_report.build_report({"error": "x"})
        self.assertEqual((rep["results"], rep["findings"]), ([], []))
        self.assertEqual(rep["counts"], {"error": 0, "warning": 0, "info": 0, "not-compared": 0})


class RecordWriterChecks(unittest.TestCase):
    def test_a_single_region_must_get_the_whole_source_rate_too(self):
        data = json.loads(json.dumps(PIN))
        data["regions"][0]["power_fraction"] = [0.5, 0.5]
        with self.assertRaises(WriterError) as ctx:
            build(data)
        self.assertIn("add up", str(ctx.exception))

    def test_the_record_carries_the_whole_starting_heavy_metal_for_every_region(self):
        rec = build(PIN)
        start = rec["provenance"]["heavy_metal_atoms_start"]
        self.assertEqual(list(start), [r["name"] for r in rec["regions"]])
        self.assertEqual(start[PIN["regions"][0]["name"]], PIN["regions"][0]["hm_atoms"][0])
        self.assertIn("heavy_metal_atoms_start", rec["provenance"]["units"])
        depletion_record.validate(rec)

    def test_fission_q_uses_the_fissile_nuclides_there_and_otherwise_any_heavy_one_the_chain_can_fission(self):
        class R:
            def __init__(self, q):
                self.type, self.Q = "fission", q

        class Nuc:
            def __init__(self, q):
                self.reactions = [R(q)] if q else []

        class Chain:
            nuclide_dict = {"U235": 0, "U238": 1, "Th232": 2}

            def __getitem__(self, n):
                return {"U235": Nuc(200e6), "U238": Nuc(205e6), "Th232": Nuc(None)}[n]

        atoms = {"U235": [1.0, 0.5], "U238": [9.0, 8.0], "Th232": [0.0, 0.0], "Pu239": [0.0, 0.0]}
        self.assertEqual(depletion_writer._fission_qs(Chain(), atoms, ["U235", "U238", "Th232", "Pu239"]), [200e6])   # U-235 is there: its Q alone
        blanket = {"U238": [9.0, 8.0], "U235": [0.0, 0.0], "Th232": [0.0, 0.0], "Pu239": [0.0, 0.0]}
        self.assertEqual(depletion_writer._fission_qs(Chain(), blanket, ["U238", "U235", "Th232", "Pu239"]), [205e6], "a fertile blanket with nothing bred: U-238's own Q")
        none = {"U235": [0.0, 0.0], "U238": [0.0, 0.0]}
        self.assertEqual(depletion_writer._fission_qs(Chain(), none, ["U235", "U238"]), [])
        notin = {"Cm244": [1.0, 1.0]}
        self.assertEqual(depletion_writer._fission_qs(Chain(), notin, ["Cm244"]), [], "a heavy nuclide the chain does not know is skipped, not a KeyError")


class StoppedBurnCanBeOpened(unittest.TestCase):
    def test_results_of_a_run_with_only_a_record_and_no_statepoint_hand_the_record_over(self):
        tmp = Path(tempfile.mkdtemp(prefix="stopped-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        (tmp / "deplete.py").write_text("")
        (tmp / "meta.json").write_text(json.dumps({"started": 1000.0, "ended": 1060.0}))
        rec = build(dict(PIN, steps_planned=5, provenance={"run": "r", "integrator": "PredictorIntegrator"}))
        self.assertFalse(rec["provenance"]["complete"])
        depletion_record.write(tmp, rec)
        out = results.load(str(tmp))
        self.assertEqual(out["depletion"]["record"]["id"], rec["id"])
        self.assertIsNone(out["summary"])
        aug = run_checks.augment(tmp, out)   # the route does this next; it must not need a statepoint
        self.assertIn("depletion", aug)


if __name__ == "__main__":
    unittest.main()
