"""What the server adds to a finished run: result checks, figure of merit, the record check, the one-page report.

Unit tests of run_checks.py on a run folder made here, and the three endpoints over real HTTP (results with findings and
FOM, record-check, report). The statepoint reader is replaced by a fixed summary, so no OpenMC run is needed; the provenance
record is the real one (provenance.write), so the record check compares against the machine this runs on.

Linux/WSL (it uses the same server startup as the CAD job tests). Run: python test/test_run_checks.py
"""
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import shutil
import socket
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "studio"))
from openmc_studio import provenance, results, run_checks, server as srv  # noqa: E402

TOKEN = "t" * 32
RID = "20261007-120000-demo"
SUMMARY = {"run_mode": "eigenvalue", "batches": 120, "particles": 20000, "seed": 1, "runtime_s": 50.0,
           "inactive": 30, "keff": [1.30622, 0.00052]}
RESULTS = {"summary": SUMMARY, "tracks": [], "tracks_truncated": False, "tallies": [
    {"name": "flux", "kind": "table", "filters": ["CellFilter"], "scores": ["flux"],
     "rows": [{"labels": ["fuel"], "score": "flux", "mean": 2.0, "std": 0.02, "rel_err": 0.01},
              {"labels": ["gap"], "score": "flux", "mean": 0.0, "std": 0.0, "rel_err": None}]}]}


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def codes(findings):
    return {f["code"]: f for f in findings}


class RunChecksUnit(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="run-checks-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_lost_particles_counts_lines_of_the_log(self):
        self.assertIsNone(run_checks.lost_particles(self.tmp), "no log, no count")
        (self.tmp / "run.log").write_text("ok\n WARNING: Particle 5 was lost\nParticle 9 could not be located\nfine\n")
        self.assertEqual(run_checks.lost_particles(self.tmp), 2)
        (self.tmp / "run.log").write_text("all particles tracked\n")
        self.assertEqual(run_checks.lost_particles(self.tmp), 0)

    def test_findings_use_only_limits_that_have_a_source(self):
        (self.tmp / "run.log").write_text("")
        by = codes(run_checks.findings(self.tmp, SUMMARY))
        self.assertEqual(by["particles-per-batch"]["level"], "info")  # 20,000 is above 5,000
        self.assertIn("MCNP 6.3 manual", by["particles-per-batch"]["message"], "the source is named in the finding")
        # no source gives a number for these two: they must say so, never invent a default
        self.assertEqual(by["active-batches"]["level"], "not-compared")
        self.assertEqual(by["entropy-settled"]["level"] if "entropy-settled" in by else "not-compared", "not-compared")
        self.assertEqual(by["lost-particles"]["level"], "info")
        self.assertIn("1 sigma", by["k-estimate"]["message"])

    def test_few_particles_is_a_warning_and_lost_particles_a_warning(self):
        (self.tmp / "run.log").write_text("Particle 3 was lost\n")
        by = codes(run_checks.findings(self.tmp, dict(SUMMARY, particles=1000)))
        self.assertEqual(by["particles-per-batch"]["level"], "warning")
        self.assertEqual(by["lost-particles"]["level"], "warning")

    def test_fixed_source_run_gets_one_info_line(self):
        out = run_checks.findings(self.tmp, {"run_mode": "fixed source", "batches": 10, "particles": 100})
        self.assertEqual([f["code"] for f in out], ["not-eigenvalue"])

    def test_figure_of_merit_is_one_over_r_squared_t(self):
        res = json.loads(json.dumps(RESULTS))
        run_checks.add_fom(res, 100.0)
        rows = res["tallies"][0]["rows"]
        self.assertAlmostEqual(rows[0]["fom"], 1 / (0.01 ** 2 * 100.0))  # 100
        self.assertNotIn("fom", rows[1], "a bin with no relative error has no figure")
        res2 = json.loads(json.dumps(RESULTS))
        run_checks.add_fom(res2, None)
        self.assertNotIn("fom", res2["tallies"][0]["rows"][0], "no time, no figure")

    def test_run_seconds_prefers_openmc_total_then_the_record(self):
        self.assertEqual(run_checks.run_seconds(self.tmp, {"runtime_s": 12.5}), 12.5)
        self.assertIsNone(run_checks.run_seconds(self.tmp, {}))
        (self.tmp / "provenance.json").write_text(json.dumps({"outcome": {"seconds": 33.0}}))
        self.assertEqual(run_checks.run_seconds(self.tmp, {}), 33.0)


class RunChecksHttp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="run-checks-http-"))
        cls.port = free_port()
        cls.studio = srv.Studio(cls.tmp / "runs", TOKEN, cls.port)
        cls.run_dir = cls.tmp / "runs" / RID
        cls.run_dir.mkdir(parents=True)
        (cls.run_dir / "model.py").write_text("print('model')\n")
        (cls.run_dir / "project.json").write_text(json.dumps({"settings": {"particles": 20000, "seed": 1}}))
        (cls.run_dir / "run.log").write_text("OpenMC finished\n")
        provenance.write(cls.run_dir, "run", {"settings": {"particles": 20000, "seed": 1}}, files=("model.py", "project.json"))
        cls.real_load = results.load
        results.load = lambda run_dir: json.loads(json.dumps(RESULTS))
        srv.Handler.studio = cls.studio
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", cls.port), srv.Handler)
        cls.httpd.daemon_threads = True
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        results.load = cls.real_load
        cls.httpd.shutdown()
        cls.httpd.server_close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def get(self, path, token=TOKEN):
        conn = HTTPConnection("127.0.0.1", self.port, timeout=30)
        conn.request("GET", path, headers={"Host": f"127.0.0.1:{self.port}", "X-Studio-Token": token} if token else
                     {"Host": f"127.0.0.1:{self.port}"})
        r = conn.getresponse()
        body = r.read()
        return r.status, dict(r.getheaders()), body

    def test_results_carry_findings_and_fom(self):
        status, _, body = self.get(f"/api/runs/{RID}/results")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertIn("k-estimate", {f["code"] for f in data["findings"]})
        self.assertAlmostEqual(data["tallies"][0]["rows"][0]["fom"], 1 / (0.01 ** 2 * 50.0))

    def test_report_is_a_locked_down_html_page(self):
        status, headers, body = self.get(f"/api/runs/{RID}/report")
        self.assertEqual(status, 200)
        self.assertTrue(headers["Content-Type"].startswith("text/html"))
        self.assertIn("default-src 'none'", headers["Content-Security-Policy"])
        text = body.decode()
        self.assertIn("1.3062", text, "the k value is on the page")
        self.assertNotIn("<script", text.lower())

    def test_record_check_matches_then_sees_a_changed_file(self):
        status, _, body = self.get(f"/api/runs/{RID}/record-check")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["status"], "match")
        (self.run_dir / "model.py").write_text("print('edited')\n")
        try:
            data = json.loads(self.get(f"/api/runs/{RID}/record-check")[2])
        finally:
            (self.run_dir / "model.py").write_text("print('model')\n")
        self.assertEqual(data["status"], "differences")
        self.assertEqual(data["counts"]["files_changed"], 1)

    def test_endpoints_need_the_token_and_a_real_run(self):
        self.assertEqual(self.get(f"/api/runs/{RID}/report", token=None)[0], 401)
        self.assertEqual(self.get("/api/runs/20261007-120000-nope/record-check")[0], 404)


if __name__ == "__main__":
    unittest.main()
