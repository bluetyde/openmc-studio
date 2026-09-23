"""CAD stage 2 gate, engine half: native STEP import through the real job API.

Runs every case of the stage-2 corpus - FreeCAD-written files
(test/fixtures/cad/native_fixtures.py) and files written without FreeCAD
(test/fixtures/cad/external/, from handwritten_step.py) - as 'native' jobs on the
real FreeCAD/GEOUNED engine, and compares each solid with values derived from the
construction parameters, not from the recognizer. Also checks that the
equivalence test rejects hair-width errors.

Like the stage-1 engine gate it FAILS, never skips, without the engine.
Run:  OPENMC_CAD_PYTHON=/path/to/openmc-cad/bin/python python test/test_cad_native_engine.py
"""
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "test" / "fixtures" / "cad"
sys.path.insert(0, str(ROOT / "studio"))
sys.path.insert(0, str(FIXTURES))
from openmc_studio.cad.jobs import CadJobs  # noqa: E402
from handwritten_step import rot  # noqa: E402 - the tests' own rotation arithmetic

CAD_PYTHON = os.environ.get("OPENMC_CAD_PYTHON")
IN_CAD = ("import sys, json; sys.path[:0] = [sys.argv[2] + '/studio', sys.argv[2] + '/test/fixtures/cad']; "
          "import native_fixtures as n; ")


def cad(script, *args, timeout=600):
    run = subprocess.run([CAD_PYTHON, "-c", IN_CAD + script, *args], capture_output=True, text=True, timeout=timeout)
    if run.returncode:
        raise RuntimeError("CAD helper failed:\n" + run.stdout[-3000:] + run.stderr[-3000:])
    return run.stdout


def axis_of(part):
    """World direction of the part's local +z, from Studio's conventions."""
    base = {"z": [0, 0, 1], "x": [1, 0, 0], "y": [0, 1, 0]}[part.get("axis", "z")] if part["shape"] == "cylinder" else [0, 0, 1]
    R = rot(part.get("rx", 0), part.get("ry", 0), part.get("rz", 0))
    return [sum(R[i][k] * base[k] for k in range(3)) for i in range(3)]


def box_axes(part):
    R = rot(part.get("rx", 0), part.get("ry", 0), part.get("rz", 0))
    return [([R[i][k] for i in range(3)], part[s]) for k, s in enumerate(("sx", "sy", "sz"))]


class NativeImportEngine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not sys.platform.startswith("linux"):
            raise RuntimeError("The CAD engine gate runs on Linux/WSL only")
        if not CAD_PYTHON or not Path(CAD_PYTHON).is_file():
            raise RuntimeError("OPENMC_CAD_PYTHON must name the pinned CAD interpreter; this gate never skips")
        cls.tmp = Path(tempfile.mkdtemp(prefix="cad-native-gate-"))
        cls.corpus = cls.tmp / "corpus"
        cad("n.main(sys.argv[1])", str(cls.corpus), str(ROOT))
        cls.cases = json.loads((cls.corpus / "expected.json").read_text())
        cls.external = json.loads((FIXTURES / "expected" / "external.json").read_text())
        cls.jobs = CadJobs(cls.tmp / "jobs", python=CAD_PYTHON, timeout=300)
        cls.reports = {}

    @classmethod
    def tearDownClass(cls):
        if getattr(cls, "jobs", None):
            cls.jobs.close()
        shutil.rmtree(getattr(cls, "tmp", "/nonexistent"), ignore_errors=True)

    def native(self, path, name=None):
        job = self.jobs.submit(Path(path).read_bytes(), name or Path(path).name, "native")
        done = self.jobs.wait(job["id"], timeout=600)
        return done, (self.jobs.result(job["id"]) if done["state"] == "succeeded" else None)

    def assertClose(self, a, b, tol, what):
        self.assertLessEqual(abs(a - b), tol, f"{what}: {a} != {b}")

    def check_solid(self, row, want, where):
        self.assertEqual(row["status"], want["status"], f"{where}: {row.get('reasons')}")
        if want["status"] == "rejected":
            text = " ".join(row["reasons"])
            for phrase in want["reason_contains"]:
                self.assertIn(phrase, text, where)
            self.assertNotIn("part", row, f"{where}: a rejected solid must not carry a part")
            return
        part = row["part"]
        self.assertEqual(part["shape"], want["shape"], where)
        self.assertNotIn("id", part, f"{where}: IDs are assigned in the browser at commit")
        scale = max(1.0, *(abs(c) for c in want["center_cm"]))
        for axis, got, exp in zip("xyz", (part["x"], part["y"], part["z"]), want["center_cm"]):
            self.assertClose(got, exp, 1e-6 * scale, f"{where}: centre {axis}")
        if want["shape"] == "sphere":
            self.assertClose(part["r"], want["r_cm"], 1e-9, f"{where}: r")
        elif want["shape"] == "box":
            got = box_axes(part)
            for exp in want["axes"]:
                match = [size for d, size in got if abs(abs(sum(x * y for x, y in zip(d, exp["dir"]))) - 1) < 1e-9]
                self.assertEqual(len(match), 1, f"{where}: no box axis along {exp['dir']}")
                self.assertClose(match[0], exp["size_cm"], 1e-9 * max(1, exp["size_cm"]), f"{where}: size")
        else:
            a = axis_of(part)
            dot = sum(x * y for x, y in zip(a, want["axis"]))
            if want["shape"] == "cylinder":
                self.assertClose(abs(dot), 1.0, 1e-9, f"{where}: cylinder axis")  # symmetric end to end
            else:
                self.assertClose(dot, 1.0, 1e-9, f"{where}: cone axis must run from the wide end")
            self.assertClose(part["r"], want["r_cm"], 1e-9, f"{where}: r")
            self.assertClose(part["h"], want["h_cm"], 1e-9 * max(1, want["h_cm"]), f"{where}: h")
            if want["shape"] == "cone":
                self.assertClose(part["r2"], want["r2_cm"], 1e-9, f"{where}: r2")
        ev = row["evidence"]
        self.assertLessEqual(ev["symmetric_difference_mm3"], ev["allowed_mm3"], where)
        self.assertGreater(ev["points_compared"], 300, where)
        self.assertGreater(ev["points_inside"], 0, where)

    def check_case(self, name, case):
        done, report = self.native(self.corpus / case["file"])
        if case.get("job_fails"):
            self.assertEqual(done["state"], "failed", name)
            self.assertIn("could not read", done["error"], name)
            return None
        self.assertEqual(done["state"], "succeeded", f"{name}: {done}")
        rows = report["solids"]
        self.assertEqual(len(rows), len(case["solids"]), f"{name}: every solid appears exactly once")
        self.assertEqual(len({r["key"] for r in rows}), len(rows), f"{name}: keys must be distinct")
        if list(case["solids"]) == [""]:
            self.check_solid(rows[0], case["solids"][""], name)
        else:
            by_key = {r["key"]: r for r in rows}
            for key, want in case["solids"].items():
                self.assertIn(key, by_key, f"{name}: missing {key}; have {sorted(by_key)}")
                self.check_solid(by_key[key], want, f"{name} / {key}")
        self.assertEqual(report["counts"]["accepted"] + report["counts"]["rejected"] + report["counts"]["failed"], len(rows))
        self.assertEqual(report["kernel_units"], "mm")
        return report

    def test_corpus_written_by_freecad(self):
        for name, case in self.cases.items():
            with self.subTest(case=name):
                self.reports[name] = self.check_case(name, case)

    def test_files_written_without_freecad(self):
        for name, case in self.external.items():
            with self.subTest(case=name):
                done, report = self.native(FIXTURES / "external" / f"{name}.step")
                self.assertEqual(done["state"], "succeeded", done)
                rows = report["solids"]
                self.assertEqual(len(rows), len(case["solids"]), f"{name}: every solid appears exactly once")
                if list(case["solids"]) == [""]:
                    self.check_solid(rows[0], {**case["solids"][""], "status": "accepted"}, name)
                    continue
                by_key = {r["key"]: r for r in rows}
                for key, want in case["solids"].items():
                    self.assertIn(key, by_key, f"{name}: missing {key}; have {sorted(by_key)}")
                    self.check_solid(by_key[key], {**want, "status": "accepted"}, f"{name} / {key}")

    def test_declared_units_give_identical_parts(self):
        parts = []
        for unit in ("mm", "cm", "m", "inch"):
            done, report = self.native(self.corpus / f"units_{unit}.step")
            parts.append(report["solids"][0]["part"])
        for other in parts[1:]:
            for k in ("x", "y", "z", "sx", "sy", "sz"):
                self.assertClose(other[k], parts[0][k], 1e-9 * max(1, abs(parts[0][k])), f"unit-dependent {k}")

    def test_overlapping_solids_are_reported(self):
        done, report = self.native(self.corpus / "overlap.step")
        (overlap,) = report["overlaps"]
        self.assertClose(overlap["volume_cm3"], self.cases["overlap"]["overlap_cm3"], 1e-9, "overlap volume")

    def test_inspect_lists_every_solid_without_classifying(self):
        job = self.jobs.submit((self.corpus / "assembly.step").read_bytes(), "assembly.step", "inspect")
        done = self.jobs.wait(job["id"], timeout=300)
        self.assertEqual(done["state"], "succeeded", done)
        rows = self.jobs.result(job["id"])["solids"]
        self.assertEqual(sorted(r["key"] for r in rows), sorted(self.cases["assembly"]["solids"]))
        self.assertTrue(all("part" not in r and r["valid"] for r in rows))

    def test_equivalence_check_rejects_hair_width_errors(self):
        results = json.loads(cad("print(json.dumps(n.teeth(None)))", "-", str(ROOT)).strip().splitlines()[-1])
        for case, outcome in results.items():
            with self.subTest(case=case):
                if case.endswith("unmodified"):
                    self.assertEqual(outcome, "accepted")
                else:
                    self.assertTrue(outcome.startswith("rejected"), f"{case}: {outcome}")
        self.assertGreaterEqual(len(results), 20)


if __name__ == "__main__":
    unittest.main(verbosity=2)
