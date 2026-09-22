"""Automated test for OpenMC Studio CAD Worker protocol, analytical STEP generator,
and server-side CAD-to-CSG / CSG-to-CAD translation pipeline.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

# Add studio to sys.path so openmc_studio package is importable
repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root / "studio"))

from openmc_studio import cad_worker
from openmc_studio.server import CadWorker, Studio


class TestCadWorkerProtocol(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.runs_root = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_probe_environment(self):
        env = cad_worker.probe_environment()
        self.assertTrue(env["ready"])
        self.assertIn("engine", env)
        self.assertIn(".step", env["supported_inputs"])
        self.assertIn(".step", env["supported_outputs"])

    def test_analytical_step_export_and_parse(self):
        parts = [
            {"id": "p_box", "shape": "box", "name": "Core_Block", "x": 0.0, "y": 0.0, "z": 0.0, "sx": 10.0, "sy": 10.0, "sz": 10.0},
            {"id": "p_cyl", "shape": "cylinder", "name": "Fuel_Pin", "x": 5.0, "y": 5.0, "z": 0.0, "r": 1.5, "h": 20.0, "axis": "z"},
            {"id": "p_sph", "shape": "sphere", "name": "Central_Bead", "x": 0.0, "y": 0.0, "z": 15.0, "r": 2.5}
        ]
        step_file = self.runs_root / "model_test.step"
        size = cad_worker.export_step_analytical(parts, step_file, units="cm")
        self.assertGreater(size, 200)
        self.assertTrue(step_file.exists())

        # Verify STEP contents
        content = step_file.read_text(encoding="utf-8")
        self.assertIn("ISO-10303-21;", content)
        self.assertIn("SPHERICAL_SURFACE", content)
        self.assertIn("CYLINDRICAL_SURFACE", content)
        self.assertIn("BLOCK", content)
        self.assertIn("END-ISO-10303-21;", content)

        # Parse back using analytical parser
        parsed_parts = cad_worker.parse_step_analytical(step_file)
        self.assertEqual(len(parsed_parts), 3)

        shapes = [p["shape"] for p in parsed_parts]
        self.assertIn("box", shapes)
        self.assertIn("cylinder", shapes)
        self.assertIn("sphere", shapes)

    def test_cad_worker_manager_lifecycle(self):
        worker = CadWorker(self.runs_root)
        try:
            status = worker.get_status()
            self.assertTrue(status.get("ready"))
            self.assertTrue(status.get("active"))
            self.assertIn("env", status)

            # Test CSG to CAD export via worker
            project = {
                "settings": {"name": "TestReactor"},
                "parts": [
                    {"id": "p1", "shape": "box", "name": "Reflector", "x": 0, "y": 0, "z": 0, "sx": 20, "sy": 20, "sz": 20}
                ]
            }
            out_step = self.runs_root / "worker_out.step"
            res = worker.csg_to_cad(project, out_step, {"units": "cm"})
            self.assertTrue(res.get("ok"), f"Worker csg_to_cad failed: {res}")
            self.assertTrue(out_step.exists())

            # Test CAD to CSG import via worker
            imp_res = worker.cad_to_csg(out_step, {})
            self.assertTrue(imp_res.get("ok"), f"Worker cad_to_csg failed: {imp_res}")
            self.assertGreaterEqual(len(imp_res.get("parts", [])), 1)
        finally:
            worker.stop()

    def test_studio_cad_methods(self):
        studio = Studio(self.runs_root, token="test-token", port=8765)
        try:
            st = studio.cad_status()
            self.assertTrue(st.get("ready"))

            project = {
                "settings": {"name": "DemoCAD"},
                "parts": [
                    {"id": "p_c1", "shape": "cylinder", "name": "Guide_Tube", "x": 0, "y": 0, "z": 0, "r": 2.0, "h": 10.0}
                ]
            }
            exp_res = studio.csg_to_cad(project, units="cm")
            self.assertTrue(exp_res.get("ok"))
            self.assertIn("ISO-10303-21", exp_res.get("step_data", ""))

            # Test cad_to_csg upload
            step_bytes = exp_res["step_data"].encode("utf-8")
            imp_res = studio.cad_to_csg(step_bytes, "Guide_Tube.step")
            self.assertTrue(imp_res.get("ok"))
            self.assertGreaterEqual(len(imp_res.get("parts", [])), 1)
        finally:
            studio.cad.stop()


if __name__ == "__main__":
    unittest.main()
