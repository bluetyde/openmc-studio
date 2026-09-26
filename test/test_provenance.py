"""provenance.json: every run and MCNP export folder records what produced it (Codex tech-debt review).

A real run through the server's Studio.start (a model.py that only writes a file) must leave a record with the
Studio version, Python, OpenMC, the nuclear data's hash, the run settings, hashes of model.py and the project,
and after it ends the outcome and the outputs' hashes. An export record names the exporter checkout's commit.
A record that can't be made must not stop the run.
Run: python test/test_provenance.py   (needs OpenMC for the version fields; OPENMC_CROSS_SECTIONS optional)
"""
import hashlib
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "studio"))
from openmc_studio import provenance  # noqa: E402
from openmc_studio.server import Studio  # noqa: E402

PROJECT = {"settings": {"runMode": "fixed source", "particles": 1234, "batches": 7, "seed": 42, "sourceRate": 1e8,
                        "name": "prov"}, "parts": [], "materials": []}
SCRIPT = 'open("statepoint.7.h5", "wb").write(b"not really hdf5")\nprint("done")\n'


class RunRecord(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="studio-prov-")
        studio = Studio(cls.tmp, "t", 0)
        run = studio.start(SCRIPT, PROJECT, "prov")
        for _ in range(600):
            if run.status != "running":
                break
            time.sleep(0.1)
        time.sleep(0.3)
        cls.studio_run = run  # not cls.run: that name is unittest's own
        cls.rec = json.loads((run.path / "provenance.json").read_text())

    def test_what_produced_it(self):
        env = self.rec["environment"]
        self.assertEqual(self.rec["kind"], "run")
        self.assertTrue(env["studio"]["version"])
        self.assertEqual(len(env["studio"]["git"]["commit"]), 40, "this checkout's commit")
        self.assertTrue(env["python"])
        self.assertTrue(env["openmc"]["python"], "the openmc package version")
        xs = os.environ.get("OPENMC_CROSS_SECTIONS")
        if xs:
            self.assertEqual(env["nuclear_data"]["sha256"], provenance.sha256(xs))
        else:
            self.assertIn("not set", env["nuclear_data"]["note"])

    def test_settings_and_hashes(self):
        self.assertEqual(self.rec["settings"], {"runMode": "fixed source", "particles": 1234, "batches": 7,
                                                "seed": 42, "sourceRate": 1e8})
        self.assertEqual(self.rec["files"]["model.py"], hashlib.sha256(SCRIPT.encode()).hexdigest())
        self.assertIn("project.json", self.rec["files"])
        self.assertIn("per source particle", self.rec["normalization"]["tallies"])

    def test_outcome_and_outputs(self):
        self.assertEqual(self.rec["outcome"]["status"], "done")
        self.assertEqual(self.rec["outcome"]["returncode"], 0)
        self.assertEqual(self.rec["outputs"]["statepoint.7.h5"], hashlib.sha256(b"not really hdf5").hexdigest())


class ExportRecord(unittest.TestCase):
    def test_exporter_commit(self):
        folder = Path(tempfile.mkdtemp(prefix="studio-prov-exp-"))
        (folder / "m_runnable.mcnp").write_text("deck\n")
        rec = provenance.write(folder, "mcnp-export", PROJECT, files=["m_runnable.mcnp"], exporter=ROOT,
                               extra={"validated": True})
        self.assertEqual(rec["environment"]["exporter"]["git"]["commit"],
                         json.loads((folder / "provenance.json").read_text())["environment"]["exporter"]["git"]["commit"])
        self.assertTrue(rec["validated"])
        self.assertEqual(rec["files"]["m_runnable.mcnp"], hashlib.sha256(b"deck\n").hexdigest())

    def test_a_failed_record_never_stops_the_work(self):
        folder = Path(tempfile.mkdtemp(prefix="studio-prov-bad-"))
        self.assertIsNone(provenance.write(folder, "run", object(), files=["x"]))  # a project that isn't JSON
        self.assertIn("error", json.loads((folder / "provenance.json").read_text()))


if __name__ == "__main__":
    unittest.main(verbosity=2)
