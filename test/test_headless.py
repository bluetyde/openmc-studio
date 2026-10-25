"""openmc_studio.headless against real OpenMC (fixed-source triso example, and a small eigenvalue pin cell), plus fake model scripts for the failure paths.

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
GEN = ROOT / "test" / "generated"
EIG_PROJECT = GEN / "eigenvalue_pin.project.json"   # node test/generate_fixtures.js writes these
EIG_MODEL = GEN / "eigenvalue_pin.py"
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
        self.assertEqual((code, d["ok"], d["runModes"]), (0, True, ["fixed source", "eigenvalue"]))
        self.assertEqual(d["limits"]["eigenvalue"], {"minActiveBatches": 30, "minParticlesPerBatch": 1000})
        self.assertTrue(d["nuclearData"]["sha256"])
        code, v = headless("validate", str(PROJECT))
        self.assertEqual((code, v["ok"], v["problems"], v["setup"]), (0, True, [], []))

    def test_validate_refuses_outside_the_first_slice(self):
        cases = [
            (lambda p: p["settings"].update(runMode="criticality"), "E_UNSUPPORTED", "/settings/runMode"),
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

    # -- eigenvalue: accepted, with minimums
    def eig_project(self, name, mutate=None):
        p = json.loads(EIG_PROJECT.read_text(encoding="utf-8"))
        if mutate:
            mutate(p)
        f = self.tmp / name
        f.write_text(json.dumps(p), encoding="utf-8")
        return f

    def test_validate_takes_an_eigenvalue_project_and_refuses_one_too_noisy_to_judge(self):
        rc, v = headless("validate", str(self.eig_project("e0.json")))
        self.assertEqual((rc, v["ok"], v["problems"]), (0, True, []))
        ok = [  # the edges are accepted: 30 active batches, 1000 particles; and no tally is needed
            lambda p: p["settings"].update(batches=30, inactive=0),
            lambda p: p["settings"].update(particles=1000, batches=31, inactive=1),
            lambda p: p.update(tallies=[]),
        ]
        for i, m in enumerate(ok):
            rc, v = headless("validate", str(self.eig_project(f"ok{i}.json", m)))
            self.assertEqual((rc, v["problems"]), (0, []), i)
        bad = [
            (lambda p: p["settings"].update(batches=39), "E_LIMIT", "/settings/batches"),                      # 29 active
            (lambda p: p["settings"].update(batches=30, inactive=1), "E_LIMIT", "/settings/batches"),
            (lambda p: p["settings"].update(particles=999), "E_LIMIT", "/settings/particles"),
            (lambda p: p["settings"].update(inactive=40), "E_SCHEMA_INVALID", "/settings/inactive"),
            (lambda p: p["settings"].update(inactive=None), "E_SCHEMA_INVALID", "/settings/inactive"),
            (lambda p: p["settings"].update(inactive=-1), "E_SCHEMA_INVALID", "/settings/inactive"),
            (lambda p: p["settings"].update(depletion=True), "E_UNSUPPORTED", "/settings/depletion"),
            (lambda p: p["settings"].update(particles=10_000_000), "E_LIMIT", "/settings/particles"),
            (lambda p: p["settings"].update(batches=100_000), "E_LIMIT", "/settings/batches"),
        ]
        for i, (mutate, code, path) in enumerate(bad):
            rc, v = headless("validate", str(self.eig_project(f"bad{i}.json", mutate)))
            self.assertEqual(rc, 1, i)
            self.assertIn((code, path), [(x["code"], x["path"]) for x in v["problems"]], (i, v))

    def test_the_fixed_source_rules_are_unchanged(self):
        # a fixed-source project still needs a tally and has no minimum on batches or particles
        rc, v = headless("validate", str(self.project_file("fs-few.json", lambda p: p["settings"].update(particles=10, batches=2))))
        self.assertEqual((rc, v["problems"]), (0, []))
        rc, v = headless("validate", str(self.project_file("fs-none.json", lambda p: p.update(tallies=[]))))
        self.assertEqual(rc, 1)

    def test_real_eigenvalue_run_reports_keff_with_its_standard_deviation(self):
        out = self.tmp / "eig"
        out.mkdir()
        docs = []
        for rid in ("a", "b"):
            rc, r = headless("run", str(EIG_MODEL), str(EIG_PROJECT), "--out", str(out), "--run-id", rid, "--timeout", "600", "--threads", "1")
            self.assertEqual((rc, r["status"]), (0, "completed"), r)
            m = json.loads((out / rid / "manifest.json").read_text())
            self.assertEqual(m["status"], "completed")
            docs.append(json.loads((out / rid / "results.json").read_text()))
        s = docs[0]["summary"]
        self.assertEqual((s["run_mode"], s["particles"], s["batches"], s["inactive"], s["seed"]), ("eigenvalue", 1000, 40, 10, 12345))
        k, sd = s["keff"]
        self.assertTrue(0.5 < k < 2.0 and 0 < sd < 0.05, s["keff"])               # a UO2 pin cell: k about 1.3, 1000 x 30 histories: a few hundred pcm
        self.assertEqual(len(s["k_generation"]), 40)
        self.assertEqual(s["n_inactive"], 10)
        self.assertEqual(len(s["k_combined"]), 2)
        self.assertNotIn("runtime_s", s)
        self.assertEqual(docs[0]["tallies"], [])
        # same seed and thread count: the same file byte for byte (k-eff included)
        self.assertEqual((out / "a" / "results.json").read_bytes(), (out / "b" / "results.json").read_bytes())
        # the standard deviation is the one OpenMC reports for the combined estimator over the active batches
        import openmc
        with openmc.StatePoint(str(out / "a" / s["statepoint"])) as sp:
            self.assertAlmostEqual(k, sp.keff.nominal_value, places=12)
            self.assertAlmostEqual(sd, sp.keff.std_dev, places=12)

    def test_a_statepoint_of_the_wrong_run_mode_is_not_success(self):
        # an eigenvalue project run with the fixed-source script: the statepoint is a fixed-source one, so the result is refused, not reported without k-eff
        out = self.tmp / "wrongmode"
        out.mkdir()
        rc, r = headless("run", str(MODEL), str(EIG_PROJECT), "--out", str(out), "--run-id", "w", "--timeout", "600")
        self.assertEqual((rc, r["status"], r["errors"][0]["code"]), (1, "failed", "E_OUTPUT_INCOMPLETE"), r)
        self.assertIn("fixed source", r["errors"][0]["message"])
        self.assertFalse((out / "w" / "results.json").exists())

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
