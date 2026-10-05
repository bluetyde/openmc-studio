"""openmc_studio.headless against real OpenMC (fixed-source triso example), plus fake model scripts for the failure paths.

Run in the OpenMC environment with OPENMC_CROSS_SECTIONS set:  python test/test_headless.py
Fails (does not skip) when OpenMC or its data are missing: a run that proved nothing must not look like a pass.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "studio"
EX = ROOT / "examples" / "triso-particle"
PROJECT = EX / "triso-particle.openmc-studio.json"
MODEL = EX / "model.py"
ENV = dict(os.environ, PYTHONPATH=str(PKG), PYTHONDONTWRITEBYTECODE="1")


def headless(*args, check=True):
    r = subprocess.run([sys.executable, "-m", "openmc_studio.headless", *args], capture_output=True, text=True, env=ENV, timeout=900)
    line = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else "{}"
    return r.returncode, json.loads(line)


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


class Headless(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        assert os.environ.get("OPENMC_CROSS_SECTIONS") and Path(os.environ["OPENMC_CROSS_SECTIONS"]).is_file(), "OPENMC_CROSS_SECTIONS must name cross_sections.xml"
        cls.tmp = Path(tempfile.mkdtemp(prefix="headless-"))
        cls.project = json.loads(PROJECT.read_text(encoding="utf-8"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def project_file(self, name, mutate):
        p = json.loads(json.dumps(self.project))
        mutate(p)
        f = self.tmp / name
        f.write_text(json.dumps(p), encoding="utf-8")
        return f

    def fake_model(self, name, body):
        f = self.tmp / name
        f.write_text(body, encoding="utf-8")
        return f

    # -- describe / validate
    def test_describe_and_validate(self):
        code, d = headless("describe")
        self.assertEqual((code, d["ok"], d["runModes"]), (0, True, ["fixed source"]))
        self.assertTrue(d["nuclearData"]["sha256"])
        code, v = headless("validate", str(PROJECT))
        self.assertEqual((code, v["ok"], v["problems"], v["setup"]), (0, True, [], []))

    def test_validate_refuses_outside_the_first_slice(self):
        cases = [
            (lambda p: p["settings"].update(runMode="eigenvalue"), "E_UNSUPPORTED", "/settings/runMode"),
            (lambda p: p["settings"].update(particles=10_000_000), "E_LIMIT", "/settings/particles"),
            (lambda p: p["settings"].update(batches=0), "E_SCHEMA_INVALID", "/settings/batches"),
            (lambda p: p["settings"].update(seed=None), "E_SCHEMA_INVALID", "/settings/seed"),
            (lambda p: p["settings"].update(maxTracks=5), "E_UNSUPPORTED", "/settings/maxTracks"),
            (lambda p: p.update(tallies=[]), "E_SCHEMA_INVALID", "/tallies"),
        ]
        for i, (mutate, code, path) in enumerate(cases):
            rc, v = headless("validate", str(self.project_file(f"v{i}.json", mutate)))
            self.assertEqual(rc, 1)
            self.assertIn((code, path), [(x["code"], x["path"]) for x in v["problems"]], (i, v))

    # -- a real run
    def test_real_run_commits_a_hashed_manifest_and_is_repeatable(self):
        out = self.tmp / "real"
        out.mkdir()
        docs = []
        for rid in ("a", "b"):
            rc, r = headless("run", str(MODEL), str(PROJECT), "--out", str(out), "--run-id", rid, "--timeout", "600", "--threads", "1")
            self.assertEqual((rc, r["status"]), (0, "completed"), r)
            folder = out / rid
            m = json.loads((folder / "manifest.json").read_text())
            self.assertEqual((m["status"], m["format"]), ("completed", "openmc-studio-headless-run"))
            names = {f["path"] for f in m["files"]}
            self.assertTrue({"model.py", "project.json", "results.json", "run.log", "provenance.json"} <= names)
            self.assertTrue(any(n.startswith("statepoint.") for n in names))
            self.assertNotIn("manifest.json", names)
            for f in m["files"]:
                self.assertEqual(sha(folder / f["path"]), f["sha256"], f["path"])
            docs.append((folder, json.loads((folder / "results.json").read_text())))
        res = docs[0][1]
        self.assertEqual((res["summary"]["run_mode"], res["summary"]["particles"], res["summary"]["batches"], res["summary"]["seed"]), ("fixed source", 1000, 10, 12345))
        self.assertNotIn("runtime_s", res["summary"])
        self.assertTrue(res["tallies"])
        # same seed and thread count: the same file, byte for byte
        self.assertEqual((docs[0][0] / "results.json").read_bytes(), (docs[1][0] / "results.json").read_bytes())
        # more threads reorder floating-point sums: the same numbers to rounding, not the same bytes. SEED compares with a tolerance.
        rc, r = headless("run", str(MODEL), str(PROJECT), "--out", str(out), "--run-id", "t4", "--timeout", "600", "--threads", "4")
        self.assertEqual(rc, 0, r)
        many = json.loads((out / "t4" / "results.json").read_text())
        for ta, tb in zip(res["tallies"], many["tallies"]):
            for ra, rb in zip(ta["rows"], tb["rows"]):
                self.assertEqual((ra["labels"], ra["score"]), (rb["labels"], rb["score"]))
                self.assertAlmostEqual(ra["mean"], rb["mean"], delta=1e-9 * abs(ra["mean"]) + 1e-30)

    def test_existing_run_folder_is_refused(self):
        out = self.tmp / "dup"
        (out / "x").mkdir(parents=True)
        rc, r = headless("run", str(MODEL), str(PROJECT), "--out", str(out), "--run-id", "x")
        self.assertEqual((rc, r["errors"][0]["code"]), (1, "E_EXISTS"))

    # -- failure paths (fake scripts, no transport)
    def test_failed_script_is_failed_with_the_log_tail(self):
        out = self.tmp / "fail"
        out.mkdir()
        rc, r = headless("run", str(self.fake_model("boom.py", "print('about to fail')\nraise SystemExit(3)\n")), str(PROJECT), "--out", str(out), "--run-id", "f")
        self.assertEqual((rc, r["status"], r["errors"][0]["code"]), (1, "failed", "E_APP_FAILED"))
        m = json.loads((out / "f" / "manifest.json").read_text())
        self.assertEqual(m["status"], "failed")
        self.assertIn("about to fail", (out / "f" / "run.log").read_text())
        self.assertFalse((out / "f" / "results.json").exists())

    def test_exit_zero_without_a_statepoint_is_not_success(self):
        out = self.tmp / "nosp"
        out.mkdir()
        rc, r = headless("run", str(self.fake_model("quiet.py", "print('done')\n")), str(PROJECT), "--out", str(out), "--run-id", "q")
        self.assertEqual((rc, r["status"], r["errors"][0]["code"]), (1, "failed", "E_OUTPUT_INCOMPLETE"))

    def test_statepoint_that_disagrees_with_the_project_is_refused(self):
        out = self.tmp / "mismatch"
        out.mkdir()
        asked = self.project_file("asked.json", lambda p: p["settings"].update(particles=500))
        rc, r = headless("run", str(MODEL), str(asked), "--out", str(out), "--run-id", "m", "--threads", "2")
        self.assertEqual((rc, r["errors"][0]["code"]), (1, "E_OUTPUT_INCOMPLETE"))
        self.assertIn("particles", r["errors"][0]["message"])

    def test_timeout_kills_the_whole_process_group(self):
        out = self.tmp / "slow"
        out.mkdir()
        script = self.fake_model("slow.py", "import subprocess, sys, time\nsubprocess.Popen([sys.executable, '-c', 'import time; time.sleep(600)'])\ntime.sleep(600)\n")
        t0 = time.time()
        rc, r = headless("run", str(script), str(PROJECT), "--out", str(out), "--run-id", "s", "--timeout", "3")
        self.assertEqual((rc, r["status"], r["errors"][0]["code"]), (1, "failed", "E_TIMEOUT"))
        self.assertLess(time.time() - t0, 60)
        child = json.loads((out / "s" / "child.json").read_text())
        self.assertFalse(alive(child["pid"]))
        left = subprocess.run(["pgrep", "-g", str(child["pgid"])], capture_output=True, text=True).stdout.split()
        self.assertEqual(left, [])

    # -- cancel
    def _start_slow(self, name, rid):
        out = self.tmp / name
        out.mkdir()
        script = self.fake_model(name + ".py", "import time\ntime.sleep(600)\n")
        proc = subprocess.Popen([sys.executable, "-m", "openmc_studio.headless", "run", str(script), str(PROJECT), "--out", str(out), "--run-id", rid, "--timeout", "900"],
                                env=ENV, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        folder = out / rid
        end = time.time() + 30
        while time.time() < end and not (folder / "child.json").exists():
            time.sleep(0.1)
        self.assertTrue((folder / "child.json").exists())
        return proc, folder

    def test_cancel_stops_the_run_and_marks_it_cancelled(self):
        proc, folder = self._start_slow("c1", "c")
        child = json.loads((folder / "child.json").read_text())
        rc, r = headless("cancel", str(folder))
        self.assertEqual((rc, r["status"], r["cancelled"], r["stopped"]), (0, "cancelled", True, True), r)
        proc.wait(timeout=30)
        self.assertFalse(alive(child["pid"]))
        self.assertEqual(json.loads((folder / "manifest.json").read_text())["status"], "cancelled")
        self.assertFalse((folder / "results.json").exists())

    def test_cancel_refuses_a_process_that_is_not_the_runs_child(self):
        proc, folder = self._start_slow("c2", "c")
        stranger = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])
        try:
            child = json.loads((folder / "child.json").read_text())
            forged = dict(child, pid=stranger.pid, pgid=stranger.pid)  # a live process, but not the one recorded
            (folder / "child.json").write_text(json.dumps(forged))
            rc, r = headless("cancel", str(folder))
            self.assertEqual((rc, r["errors"][0]["code"]), (1, "E_NOT_OWNED"))
            self.assertTrue(alive(stranger.pid))
        finally:
            stranger.kill()
            stranger.wait()
            (folder / "child.json").write_text(json.dumps(child))
            headless("cancel", str(folder))
            proc.wait(timeout=30)

    def test_cancel_of_a_finished_run_changes_nothing(self):
        out = self.tmp / "done"
        out.mkdir()
        headless("run", str(self.fake_model("e.py", "raise SystemExit(1)\n")), str(PROJECT), "--out", str(out), "--run-id", "d")
        before = (out / "d" / "manifest.json").read_bytes()
        rc, r = headless("cancel", str(out / "d"))
        self.assertEqual((rc, r["cancelled"]), (0, False))
        self.assertEqual((out / "d" / "manifest.json").read_bytes(), before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
