"""The live model.mcnp tab shows a deck as soon as it is translated and checks it against OpenMC in the background.

server.Validator runs studio/openmc_studio/mcnp_validate.py on a copy of the deck and model.xml in its own process (no
MCNPy, no Java). These tests check, with the exporter's pin-cell deck and real OpenMC:
  - a verdict arrives and is right: a good deck passes, a deck with a wrong density fails with the validator's text;
  - the copy: the live folder is reused by the next job, so deleting the original must not matter;
  - one verdict per deck: a newer deck kills the older check and the older id answers "superseded", never a verdict;
  - what goes wrong is said: a check that dies without a result, or whose model can't be read, reports an error;
and (needs the MCNPy gateway, port 25333: claim it first where agents share a machine) the whole flow through the real
worker: a live job returns the deck with the check pending, and the verdict of the background check equals the one a
synchronous job (the Export button) gives for the same model.

Needs OPENMC_MCNP_PROJECT (the exporter) and OpenMC. Run: python test/test_mcnp_validation_bg.py
"""
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "studio"))
from openmc_studio.server import McnpWorker, Validator  # noqa: E402

EXPORTER = Path(os.environ["OPENMC_MCNP_PROJECT"])
SLEEP = lambda work, name, samples: [sys.executable, "-c", "import time; time.sleep(600)"]  # a check that never ends


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    try:
        return Path(f"/proc/{pid}/stat").read_text().split()[2] != "Z"
    except OSError:
        return False


def wait_for(v, jid, secs=180):
    end = time.time() + secs
    while time.time() < end:
        s = v.get(jid)
        if s["status"] != "running":
            return s
        time.sleep(0.3)
    raise AssertionError(f"the check {jid} did not finish in {secs} s: {v.get(jid)}")


class Checks(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="validation-bg-"))
        self.live = self.tmp / "mcnp-live"
        self.live.mkdir()
        self.validators = []

    def tearDown(self):
        for v in self.validators:
            v.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def validator(self, **kw):
        v = Validator(lambda: EXPORTER, **kw)
        self.validators.append(v)
        return v

    def pin_cell(self, deck_edit=None):
        """The live folder as the worker leaves it: model.xml and <name>_runnable.mcnp; returns the report."""
        import openmc
        model = openmc.Model.from_xml(str(EXPORTER / "geometry.xml"), str(EXPORTER / "materials.xml"), str(EXPORTER / "settings.xml"))
        model.export_to_model_xml(str(self.live / "model.xml"))
        text = (EXPORTER / "pin_cell_runnable.mcnp").read_text()
        if deck_edit:
            text = deck_edit(text)
        (self.live / "pin_cell_runnable.mcnp").write_text(text)
        return {"runnable": str(self.live / "pin_cell_runnable.mcnp"), "model": str(self.live / "model.xml"), "samples": 2000}

    def test_a_good_deck_passes(self):
        v = self.validator()
        jid = v.start(1, self.live, self.pin_cell())
        self.assertEqual(v.get(jid)["status"], "running")
        done = wait_for(v, jid)
        self.assertEqual(done["status"], "done", done)
        self.assertTrue(done["ok"], done)
        self.assertIn("geometry matches OpenMC", done["validation"])
        self.assertGreater(done["seconds"], 0)

    def test_a_wrong_density_fails_with_the_validators_text(self):
        v = self.validator()
        report = self.pin_cell(lambda t: t.replace("1 1 -10.4 -1", "1 1 -9.9 -1"))
        done = wait_for(v, v.start(1, self.live, report))
        self.assertEqual(done["status"], "done", done)
        self.assertFalse(done["ok"])
        self.assertRegex(done["validation"], r"density 10\.4 g/cm3 in OpenMC but 9\.9 g/cm3 in MCNP")

    def test_the_live_folder_can_be_reused_while_it_runs(self):
        v = self.validator()
        report = self.pin_cell()
        jid = v.start(1, self.live, report)
        os.remove(report["runnable"])  # the next job removes and rewrites these
        os.remove(report["model"])
        done = wait_for(v, jid)
        self.assertEqual((done["status"], done["ok"]), ("done", True), done)

    def test_a_newer_deck_kills_the_older_check_and_the_older_id_gets_no_verdict(self):
        v = self.validator(command=SLEEP)
        report = self.pin_cell()
        v.start(1, self.live, report)
        first = v.proc.pid
        self.assertTrue(alive(first))
        v.start(2, self.live, report)
        time.sleep(0.3)
        self.assertFalse(alive(first), "the older check was left running")
        self.assertEqual(v.get(1), {"id": 1, "status": "superseded"})
        self.assertEqual(v.get(2)["status"], "running")
        self.assertEqual(v.get(99)["status"], "superseded", "an id the server never started has no verdict either")
        v.stop()
        self.assertEqual(v.get(2)["status"], "superseded")

    def test_the_old_check_finishing_late_cannot_overwrite_the_new_one(self):
        v = self.validator()
        report = self.pin_cell()
        v.start(1, self.live, report)
        v.command = SLEEP
        v.start(2, self.live, report)   # kills 1 before it can write a verdict
        time.sleep(3)
        self.assertEqual(v.get(2)["status"], "running")
        self.assertEqual(v.get(1)["status"], "superseded")

    def test_a_check_that_dies_without_a_result_says_so(self):
        v = self.validator(command=lambda w, n, s: [sys.executable, "-c", "import sys; print('boom'); sys.exit(3)"])
        done = wait_for(v, v.start(1, self.live, self.pin_cell()), secs=30)
        self.assertEqual(done["status"], "error", done)
        self.assertIn("exit 3", done["error"])
        self.assertIn("boom", done["error"])

    def test_a_model_that_cannot_be_read_is_an_error_not_a_verdict(self):
        v = self.validator()
        report = self.pin_cell()
        Path(report["model"]).write_text("this is not xml")
        done = wait_for(v, v.start(1, self.live, report), secs=60)
        self.assertEqual(done["status"], "error", done)
        self.assertNotIn("ok", done)
        self.assertTrue(done["error"])


class LiveFlow(unittest.TestCase):
    """Needs MCNPy. A live job (validate=False) against a synchronous one (validate=True, what Export uses)."""

    def test_live_job_returns_the_deck_with_the_check_pending_and_the_verdicts_agree(self):
        script = (Path(__file__).parent / "generated" / "current_box_mcnp.py").read_text()
        tmp = Path(tempfile.mkdtemp(prefix="validation-flow-"))
        worker = McnpWorker(tmp)
        try:
            live = worker.run(script, "box", tmp / "live", seq=1, client="t", validate=False)
            self.assertTrue(live.get("deck"), live)
            self.assertTrue(live["validation_pending"])
            self.assertIsNone(live["ok"])
            self.assertEqual(live["validation"], "")
            self.assertIsInstance(live["validation_id"], int)
            verdict = wait_for(worker.validator, live["validation_id"])
            self.assertEqual(verdict["status"], "done", verdict)
            sync = worker.run(script, "box", tmp / "sync", seq=None)
            self.assertNotIn("validation_pending", sync)
            self.assertTrue(sync["ok"], sync.get("validation", "")[-800:])
            self.assertEqual(verdict["ok"], sync["ok"])
            # the header names the deck's path (a copy for the background check); the rest is the same check
            body = lambda text: text.split(chr(10), 1)[1]
            self.assertEqual(body(verdict["validation"]), body(sync["validation"]), "the same check, the same text")
            self.assertEqual(live["deck"], sync["deck"], "the deck is the same either way")
        finally:
            worker.validator.stop()
            worker.stop()
            shutil.rmtree(tmp, ignore_errors=True)

    def test_a_second_live_job_stops_the_check_of_the_first(self):
        script = (Path(__file__).parent / "generated" / "current_box_mcnp.py").read_text()
        tmp = Path(tempfile.mkdtemp(prefix="validation-flow-"))
        worker = McnpWorker(tmp)
        try:
            first = worker.run(script, "box", tmp / "live", seq=1, client="t", validate=False)
            worker.validator.command = SLEEP  # make the first check outlast the next job
            worker.validator.start(first["validation_id"], tmp / "live", first)
            second = worker.run(script, "box", tmp / "live", seq=2, client="t", validate=False)
            self.assertEqual(worker.validator.get(first["validation_id"])["status"], "superseded")
            self.assertNotEqual(second["validation_id"], first["validation_id"])
        finally:
            worker.validator.stop()
            worker.stop()
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
