"""Resume of a stopped depletion run: depletion_run.resume_plan (what is refused and why), copy_for_resume, and POST /api/runs/<id>/resume over real HTTP.

The results file is stood in for by a fake `openmc.deplete.Results` (a list of entries with times and reaction rates), except where the test is
that a file which is not HDF5 is refused, which uses the real one. A real stop-and-resume of a pin cell, compared with a burn that was never
stopped, is test/manual_depletion_resume.py (minutes). The refusal that matters most is "no reaction rates": OpenMC does not refuse those, it burns wrongly
(measured in test/manual_resume_r0.py), so the check reads the rates and does not trust a flag.

Linux/WSL. Run: python test/test_depletion_resume.py
"""
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import sys
import tempfile
import threading
import time
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "studio"))
import openmc.deplete as dep  # noqa: E402
from openmc_studio import depletion_run, server as srv  # noqa: E402
from openmc_studio.depletion_run import ResumeRefused, resume_plan  # noqa: E402

TOKEN = "t" * 32
CASES = json.loads((ROOT / "test" / "fixtures" / "prerun" / "cases.json").read_text(encoding="utf-8"))


def project(steps="1, 4, 10"):
    p = json.loads(json.dumps(next(c for c in CASES if c["name"] == "depletion with a burnable fuel in an eigenvalue run")["project"]))
    p["settings"]["depSteps"] = steps
    return p


class FakeEntry:
    def __init__(self, rates):
        self.rates = np.asarray(rates, dtype=float)


class FakeResults(list):
    """What openmc.deplete.Results gives resume_plan: entries (with .rates) and get_times."""
    times = [0.0, 1.0, 5.0]
    rates = [7.8e-5, 7.7e-5, 7.7e-5]

    def __init__(self, path):
        super().__init__(FakeEntry(r) for r in type(self).rates)

    def get_times(self, units="d"):
        return np.array(type(self).times)


def make_run(tmp, name="20261010-100000-stopped", steps="1, 4, 10", chain_sha=None, model="def prepare_depletion(model, measure_volumes=True):\n    pass\n", n_statepoints=3):
    run = Path(tmp) / name
    run.mkdir(parents=True)
    (run / "deplete.py").write_text("print('x')\n")
    (run / "model.py").write_text(model)
    (run / "project.json").write_text(json.dumps(project(steps)))
    (run / "depletion_results.h5").write_bytes(b"results v1")
    for i in range(n_statepoints):
        (run / f"openmc_simulation_n{i}.h5").write_bytes(f"statepoint {i}".encode())
    (run / "provenance.json").write_text(json.dumps({"depletion": {"chain": {"sha256": chain_sha}}, "environment": {"openmc": {"python": "0.15.3"}, "nuclear_data": {"sha256": "abc"}}}))
    return run


class Plan(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="resume-plan-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.chain = self.tmp / "chain.xml"
        self.chain.write_text("<depletion_chain/>")
        self.sha = hashlib.sha256(self.chain.read_bytes()).hexdigest()
        self.real = dep.Results
        dep.Results = FakeResults
        FakeResults.times, FakeResults.rates = [0.0, 1.0, 5.0], [7.8e-5, 7.7e-5, 7.7e-5]
        self.addCleanup(setattr, dep, "Results", self.real)

    def refused(self, run, why, **kw):
        with self.assertRaises(ResumeRefused) as ctx:
            resume_plan(run, kw.pop("chain", self.chain), kw.pop("env", None))
        self.assertIn(why, str(ctx.exception))

    def test_a_stopped_burn_gives_a_plan_with_what_to_copy_and_the_results_hash(self):
        run = make_run(self.tmp, chain_sha=self.sha)
        plan = resume_plan(run, self.chain)
        self.assertEqual((plan["steps_done"], plan["steps_planned"]), (2, 3))
        self.assertEqual(plan["results_sha256"], hashlib.sha256(b"results v1").hexdigest())
        self.assertEqual(plan["files"], ["model.py", "project.json", "depletion_results.h5", "openmc_simulation_n0.h5", "openmc_simulation_n1.h5", "openmc_simulation_n2.h5"])
        self.assertEqual(plan["warnings"], [])

    def test_statepoints_beyond_the_saved_steps_are_not_copied(self):
        run = make_run(self.tmp, chain_sha=self.sha, n_statepoints=5)   # n3 and n4: a solve that was cut off
        self.assertNotIn("openmc_simulation_n3.h5", resume_plan(run, self.chain)["files"])

    def test_not_a_depletion_run_or_no_results(self):
        run = make_run(self.tmp, chain_sha=self.sha)
        (run / "deplete.py").unlink()
        self.refused(run, "not a depletion run")
        run = make_run(self.tmp, name="20261010-100001-b", chain_sha=self.sha)
        (run / "depletion_results.h5").unlink()
        self.refused(run, "not a depletion run")
        run = make_run(self.tmp, name="20261010-100002-c", chain_sha=self.sha)
        (run / "provenance.json").unlink()
        self.refused(run, "provenance.json is missing")

    def test_a_project_that_did_not_ask_for_depletion_is_refused(self):
        run = make_run(self.tmp, chain_sha=self.sha)
        p = project()
        p["settings"]["depletion"] = False
        (run / "project.json").write_text(json.dumps(p))
        self.refused(run, "did not ask for depletion")

    def test_a_model_py_from_before_resume_existed_is_refused(self):
        run = make_run(self.tmp, chain_sha=self.sha, model="def prepare_depletion(model):\n    pass\n")
        self.refused(run, "from before resume existed")

    def test_no_chain_file_and_another_chain_file_are_refused(self):
        run = make_run(self.tmp, chain_sha=self.sha)
        self.refused(run, "depletion chain file", chain=None)
        other = self.tmp / "other.xml"
        other.write_text("<depletion_chain version='2'/>")
        self.refused(run, "not the one this burn used", chain=other)
        run2 = make_run(self.tmp, name="20261010-100003-n", chain_sha=None)
        self.refused(run2, "not the one this burn used")

    def test_a_results_file_that_is_not_readable_is_refused_with_the_reason(self):
        dep.Results = self.real   # the real class on a file that is not HDF5
        run = make_run(self.tmp, chain_sha=self.sha)
        self.refused(run, "can't be read")

    def test_a_burn_that_finished_has_nothing_to_resume(self):
        FakeResults.times, FakeResults.rates = [0.0, 1.0, 5.0, 15.0], [7.8e-5] * 4
        self.refused(make_run(self.tmp, chain_sha=self.sha), "finished all 3 steps")

    def test_results_without_reaction_rates_are_refused_because_openmc_would_burn_wrongly(self):
        FakeResults.rates = [7.8e-5, 7.7e-5, 0.0]
        self.refused(make_run(self.tmp, chain_sha=self.sha), "no reaction rates")
        FakeResults.rates = [7.8e-5, 7.7e-5, []]       # an empty rate array, which is what a run without write_rates leaves
        self.refused(make_run(self.tmp, name="20261010-100004-e", chain_sha=self.sha), "no reaction rates")

    def test_only_the_last_entry_rates_matter_and_they_are_what_is_checked(self):
        FakeResults.rates = [0.0, 0.0, 7.7e-5]         # earlier entries empty, the one a restart reads is not
        self.assertEqual(resume_plan(make_run(self.tmp, chain_sha=self.sha), self.chain)["steps_done"], 2)

    def test_steps_that_differ_from_the_projects_list_are_refused(self):
        self.refused(make_run(self.tmp, steps="1, 3, 10", chain_sha=self.sha), "not the same burn")

    def test_another_openmc_or_other_nuclear_data_only_warns(self):
        run = make_run(self.tmp, chain_sha=self.sha)
        plan = resume_plan(run, self.chain, {"openmc": {"python": "0.16.0"}, "nuclear_data": {"sha256": "different"}})
        self.assertEqual(len(plan["warnings"]), 2)
        self.assertIn("0.16.0", plan["warnings"][0])
        self.assertIn("nuclear data", plan["warnings"][1])

    def test_copy_for_resume_copies_the_files_and_leaves_the_stopped_run_as_it_was(self):
        run = make_run(self.tmp, chain_sha=self.sha)
        before = {p.name: p.read_bytes() for p in run.iterdir()}
        new = self.tmp / "20261010-100005-new"
        new.mkdir()
        depletion_run.copy_for_resume(run, new, resume_plan(run, self.chain))
        self.assertEqual({p.name: p.read_bytes() for p in run.iterdir()}, before)
        self.assertEqual((new / "depletion_results.h5").read_bytes(), b"results v1")
        self.assertEqual((new / "openmc_simulation_n1.h5").read_bytes(), b"statepoint 1")


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@unittest.skipUnless(sys.platform.startswith("linux"), "the run server starts python; run this under WSL")
class Http(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="resume-http-"))
        cls.port = free_port()
        cls.studio = srv.Studio(cls.tmp / "runs", TOKEN, cls.port)
        srv.Handler.studio = cls.studio
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", cls.port), srv.Handler)
        cls.httpd.daemon_threads = True
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.chain = cls.tmp / "chain_pwr.xml"
        cls.chain.write_text("<depletion_chain/>")
        cls.saved = os.environ.get("OPENMC_CHAIN_FILE")
        os.environ["OPENMC_CHAIN_FILE"] = str(cls.chain)
        cls.real_results = dep.Results

    @classmethod
    def tearDownClass(cls):
        dep.Results = cls.real_results
        if cls.saved is None:
            os.environ.pop("OPENMC_CHAIN_FILE", None)
        else:
            os.environ["OPENMC_CHAIN_FILE"] = cls.saved
        cls.httpd.shutdown()
        cls.httpd.server_close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def call(self, method, path, body=None):
        conn = HTTPConnection("127.0.0.1", self.port, timeout=30)
        conn.request(method, path, json.dumps(body) if body is not None else None,
                     {"Host": f"127.0.0.1:{self.port}", "X-Studio-Token": TOKEN, "Content-Type": "application/json"})
        r = conn.getresponse()
        return r.status, json.loads(r.read())

    def wait(self):
        deadline = time.time() + 30
        while time.time() < deadline and self.studio.active and self.studio.active.status == "running":
            time.sleep(0.2)

    def test_resume_makes_a_new_folder_with_the_copies_a_resume_script_and_a_provenance_that_names_the_old_run(self):
        sha = hashlib.sha256(self.chain.read_bytes()).hexdigest()
        run = make_run(self.tmp / "runs", chain_sha=sha)
        dep.Results = FakeResults
        FakeResults.times, FakeResults.rates = [0.0, 1.0, 5.0], [7.8e-5, 7.7e-5, 7.7e-5]
        before = {p.name: p.read_bytes() for p in run.iterdir()}
        real_script = depletion_run.script_text
        seen = {}
        depletion_run.script_text = lambda project, model_path, chain_file, resume=False: seen.update(resume=resume) or "print('resumed burn')\n"
        try:
            status, body = self.call("POST", f"/api/runs/{run.name}/resume")
            self.assertEqual(status, 200, body)
            self.wait()
        finally:
            depletion_run.script_text = real_script
        self.assertTrue(seen["resume"], "the script is asked for in resume mode")
        new = self.tmp / "runs" / body["id"]
        self.assertNotEqual(new, run)
        self.assertTrue(body["id"].endswith("resumed"))
        for name in ("model.py", "project.json", "depletion_results.h5", "openmc_simulation_n0.h5", "openmc_simulation_n2.h5", "deplete.py"):
            self.assertTrue((new / name).is_file(), name)
        self.assertEqual({p.name: p.read_bytes() for p in run.iterdir()}, before, "the stopped run is exactly as it was")
        prov = json.loads((new / "provenance.json").read_text())
        r = prov["depletion"]["resumed_from"]
        self.assertEqual((r["run"], r["steps_done"], r["steps_planned"]), (run.name, 2, 3))
        self.assertEqual(r["results_sha256"], hashlib.sha256(b"results v1").hexdigest())
        self.assertEqual(prov["depletion"]["chain"]["sha256"], sha)
        run_obj = self.studio.runs[body["id"]]
        self.assertTrue(any(line.startswith(f"Resuming {run.name} after step 2 of 3") for line in run_obj.lines), run_obj.lines)

    def test_refusals_come_back_as_422_with_the_reason_and_make_no_folder(self):
        run = make_run(self.tmp / "runs", name="20261010-110000-norates", chain_sha=hashlib.sha256(self.chain.read_bytes()).hexdigest())
        dep.Results = FakeResults
        FakeResults.times, FakeResults.rates = [0.0, 1.0, 5.0], [7.8e-5, 7.7e-5, 0.0]
        before = sorted(p.name for p in (self.tmp / "runs").iterdir())
        status, body = self.call("POST", f"/api/runs/{run.name}/resume")
        self.assertEqual(status, 422)
        self.assertIn("no reaction rates", body["error"])
        self.assertEqual(sorted(p.name for p in (self.tmp / "runs").iterdir()), before)

    def test_an_unknown_run_is_404_and_a_run_that_is_going_is_409(self):
        self.assertEqual(self.call("POST", "/api/runs/20261010-120000-nope/resume")[0], 404)
        run = make_run(self.tmp / "runs", name="20261010-130000-ok", chain_sha=hashlib.sha256(self.chain.read_bytes()).hexdigest())
        dep.Results = FakeResults
        FakeResults.times, FakeResults.rates = [0.0, 1.0, 5.0], [7.8e-5, 7.7e-5, 7.7e-5]
        busy = srv.Run("busy", self.tmp / "runs" / "busy", "busy")
        self.studio.active = busy
        try:
            status, body = self.call("POST", f"/api/runs/{run.name}/resume")
        finally:
            self.studio.active = None
        self.assertEqual(status, 409)
        self.assertIn("already going", body["error"])

    def test_it_needs_the_token(self):
        conn = HTTPConnection("127.0.0.1", self.port, timeout=30)
        conn.request("POST", "/api/runs/20261010-100000-stopped/resume", "{}", {"Host": f"127.0.0.1:{self.port}", "Content-Type": "application/json"})
        self.assertEqual(conn.getresponse().status, 401)


if __name__ == "__main__":
    unittest.main()
