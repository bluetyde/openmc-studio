"""CAD stage 1 gate with the real engine: jobs driving FreeCAD and GEOUNED.

This is the integration half of the stage-1 gate. It FAILS - it never skips -
when the engine is missing, so a green run always means real conversions ran.

Needs Linux/WSL, OPENMC_CAD_PYTHON pointing at the pinned CAD interpreter
(setup/cad), and openmc importable in the Python running this test (the Studio
server's own environment). Job files go to a fresh directory outside the repo.

Run:  OPENMC_CAD_PYTHON=/path/to/openmc-cad/bin/python python test/test_cad_jobs_engine.py
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "studio"))
from openmc_studio.cad.jobs import CadJobs  # noqa: E402

CAD_PYTHON = os.environ.get("OPENMC_CAD_PYTHON")

# Runs inside the CAD interpreter. The work lives in a module because importing
# FreeCAD clears names from __main__ (test/fixtures/cad/export_gate_fixtures.py).
GENERATE = ("import sys; sys.path[:0] = [sys.argv[2] + '/studio', sys.argv[2] + '/test/fixtures/cad']; "
            "import export_gate_fixtures as g; g.main(sys.argv[1])")


class RealEngineJobs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not sys.platform.startswith("linux"):
            raise RuntimeError("The CAD engine gate runs on Linux/WSL only")
        if not CAD_PYTHON or not Path(CAD_PYTHON).is_file():
            raise RuntimeError("OPENMC_CAD_PYTHON must name the pinned CAD interpreter; "
                               "this gate never skips (see setup/cad/README.md)")
        cls.tmp = Path(tempfile.mkdtemp(prefix="cad-engine-gate-"))
        cls.fixtures = cls.tmp / "fixtures"
        cls.fixtures.mkdir()
        made = subprocess.run([CAD_PYTHON, "-c", GENERATE, str(cls.fixtures), str(ROOT)], timeout=300,
                              capture_output=True, text=True)
        if made.returncode:
            raise RuntimeError("Fixture generation failed:\n" + made.stdout[-2000:] + made.stderr[-2000:])
        cls.meta = json.loads((cls.fixtures / "meta.json").read_text())
        cls.jobs = CadJobs(cls.tmp / "jobs", python=CAD_PYTHON, timeout=240)

    @classmethod
    def tearDownClass(cls):
        if getattr(cls, "jobs", None):
            cls.jobs.close()
        shutil.rmtree(getattr(cls, "tmp", "/nonexistent"), ignore_errors=True)

    def convert(self, name, timeout=300):
        job = self.jobs.submit((self.fixtures / f"{name}.step").read_bytes(), f"{name}.step", "csg-xml")
        return self.jobs.wait(job["id"], timeout=timeout)

    def processes_in(self, directory):
        """PIDs whose working directory is inside directory (the job's worker tree)."""
        found = []
        for proc in Path("/proc").iterdir():
            if proc.name.isdigit():
                try:
                    if Path(os.readlink(proc / "cwd")).is_relative_to(directory):
                        found.append(int(proc.name))
                except OSError:
                    continue
        return found

    def test_1_probe_verifies_the_real_engine(self):
        self.assertFalse(self.jobs.capabilities()["engine_verified"])
        job = self.jobs.submit(None, None, "probe")
        done = self.jobs.wait(job["id"], timeout=300)
        self.assertEqual(done["state"], "succeeded", done)
        caps = self.jobs.capabilities()
        self.assertTrue(caps["engine_verified"])
        self.assertEqual(caps["probe"]["versions"]["geouned"], "1.6.2")
        self.assertEqual(self.jobs.result(job["id"])["probe"]["points_checked"], 3)

    def test_2_real_conversion_keeps_the_hole(self):
        import openmc
        for name in ("drilled_block_rotated", "annular_cylinder"):
            with self.subTest(name=name):
                done = self.convert(name)
                self.assertEqual(done["state"], "succeeded", done)
                result = self.jobs.result(done["id"])
                self.assertNotIn("xml", result)
                self.assertEqual(result["xml_units"], "cm")
                tree = ET.fromstring(result["xml_data"])
                surfaces = {int(e.attrib["id"]): openmc.Surface.from_xml_element(e) for e in tree.findall("surface")}
                (cell,) = tree.findall("cell")
                region = openmc.Region.from_expression(cell.attrib["region"], surfaces)
                for point_mm, inside in self.meta[name]["probes"]:
                    self.assertEqual(tuple(c / 10 for c in point_mm) in region, inside,
                                     f"{name}: probe {point_mm} mm")
                self.assertAlmostEqual(result["volume_cm3"], self.meta[name]["volume_mm3"] / 1000, places=6)

    def test_3_engine_rejections_reach_the_client_with_reasons(self):
        for name, reason in (("torus", "Unsupported surfaces"), ("two_solids", "exactly one valid closed solid")):
            with self.subTest(name=name):
                done = self.convert(name)
                self.assertEqual(done["state"], "failed", done)
                self.assertIn(reason, done["error"])
                with self.assertRaises(RuntimeError):
                    self.jobs.result(done["id"])

    def test_4_cancelling_a_real_conversion_leaves_nothing_running(self):
        data = (self.fixtures / "annular_cylinder.step").read_bytes()
        job = self.jobs.submit(data, "annular_cylinder.step", "csg-xml")
        work = self.tmp / "jobs" / job["id"] / "work"
        deadline = time.time() + 120
        while time.time() < deadline:
            state = self.jobs.get(job["id"])
            if state["state"] == "running" and self.processes_in(work):
                break
            time.sleep(0.02)
        self.assertTrue(self.processes_in(work), "the real worker never started")
        self.jobs.cancel(job["id"])
        done = self.jobs.wait(job["id"], timeout=60)
        self.assertEqual(done["state"], "cancelled")
        time.sleep(0.3)
        self.assertEqual(self.processes_in(self.tmp / "jobs" / job["id"]), [], "a CAD process outlived its job")
        self.assertFalse(work.exists(), "cancelled scratch must be deleted")
        # And the engine still works afterwards.
        self.assertEqual(self.convert("drilled_block_rotated")["state"], "succeeded")


if __name__ == "__main__":
    unittest.main(verbosity=2)
