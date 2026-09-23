"""CAD stage 1 gate: the job API over real HTTP.

Starts Studio's own ThreadingHTTPServer and Handler on a free local port with the
job manager's worker replaced by test/cad_fake_worker.py, then checks
authentication, malformed requests, the 202/poll/result/cancel flow and
concurrent submissions. No CAD engine is needed.

Linux/WSL only. Run: python test/test_cad_jobs_http.py
"""
import base64
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "studio"))
from openmc_studio import server as srv  # noqa: E402
from openmc_studio.cad.jobs import CadJobs, MAX_INPUT  # noqa: E402

FAKE = Path(__file__).resolve().parent / "cad_fake_worker.py"
TOKEN = "t" * 32
STEP = base64.b64encode(b"ISO-10303-21;\nEND-ISO-10303-21;\n").decode()


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@unittest.skipUnless(sys.platform.startswith("linux"), "CAD jobs are Linux/WSL only; run this under WSL")
class CadJobsHttp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="cad-http-test-"))
        cls.side = cls.tmp / "side"
        cls.side.mkdir()
        cls.port = free_port()
        cls.studio = srv.Studio(cls.tmp / "runs", TOKEN, cls.port)
        # The upload's filename label picks the fake's behaviour ("hang.step" hangs), so
        # nothing has to be attached to a job after the server has accepted it.
        cls.studio.cad_jobs = CadJobs(
            cls.tmp / "runs" / "cad-jobs", python=sys.executable, max_pending=4,
            command=lambda job: [sys.executable, str(FAKE),
                                 "ok" if job.mode == "probe" else job.name.rsplit(".", 1)[0], str(cls.side)])
        srv.Handler.studio = cls.studio
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", cls.port), srv.Handler)
        cls.httpd.daemon_threads = True
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.studio.cad_jobs.close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def request(self, method, path, body=None, *, token=TOKEN, host=None, origin=None, raw=None, headers=None):
        conn = HTTPConnection("127.0.0.1", self.port, timeout=30)
        h = {"Host": host or f"127.0.0.1:{self.port}"}
        if token:
            h["X-Studio-Token"] = token
        if origin:
            h["Origin"] = origin
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        if data is not None:
            h["Content-Type"] = "application/json"
            h["Content-Length"] = str(len(data))
        h.update(headers or {})
        conn.request(method, path, body=data, headers=h)
        r = conn.getresponse()
        payload = r.read()
        conn.close()
        try:
            return r.status, json.loads(payload or b"null"), r
        except json.JSONDecodeError:
            return r.status, payload, r

    def submit(self, behaviour="ok", **body):
        return self.request("POST", "/api/cad/jobs", {"filename": f"{behaviour}.step", "data": STEP, **body})

    def wait(self, job_id, timeout=30):
        deadline = time.time() + timeout
        while time.time() < deadline:
            status, job, _ = self.request("GET", f"/api/cad/jobs/{job_id}")
            self.assertEqual(status, 200)
            if job["state"] in {"succeeded", "failed", "cancelled", "timed_out"}:
                return job
            time.sleep(0.05)
        self.fail(f"job {job_id} did not finish")

    # ── authentication and origin ──
    def test_every_cad_route_needs_the_token(self):
        for method, path in [("GET", "/api/cad/capabilities"), ("GET", "/api/cad/jobs"),
                             ("GET", "/api/cad/jobs/" + "a" * 32), ("POST", "/api/cad/jobs"),
                             ("DELETE", "/api/cad/jobs/" + "a" * 32)]:
            with self.subTest(method=method, path=path):
                for token in (None, "wrong"):
                    status, _, _ = self.request(method, path, {} if method == "POST" else None, token=token)
                    self.assertEqual(status, 401)

    def test_foreign_origin_and_host_are_refused(self):
        status, _, _ = self.request("POST", "/api/cad/jobs", {"data": STEP, "filename": "a.step"},
                                    origin="http://evil.example")
        self.assertEqual(status, 403)
        status, _, _ = self.request("DELETE", "/api/cad/jobs/" + "a" * 32, origin="http://evil.example")
        self.assertEqual(status, 403)
        status, _, _ = self.request("GET", "/api/cad/capabilities", host="evil.example")
        self.assertEqual(status, 403)

    # ── malformed requests ──
    def test_malformed_bodies_are_400_and_create_nothing(self):
        before = {j["id"] for j in self.request("GET", "/api/cad/jobs")[1]["jobs"]}
        cases = {
            "not json": b"{not json",
            "json array": b"[1, 2]",
            "extra key": json.dumps({"filename": "a.step", "data": STEP, "path": "/etc"}).encode(),
            "bad base64": json.dumps({"filename": "a.step", "data": "@@@"}).encode(),
            "oversized base64": json.dumps({"filename": "a.step", "data": "A" * (4 * ((MAX_INPUT + 2) // 3) + 4)}).encode(),
            "not a string": json.dumps({"filename": "a.step", "data": 12}).encode(),
            "wrong extension": json.dumps({"filename": "a.stl", "data": STEP}).encode(),
            "unknown mode": json.dumps({"filename": "a.step", "data": STEP, "mode": "shell"}).encode(),
            "mode not a string": json.dumps({"filename": "a.step", "data": STEP, "mode": ["probe"]}).encode(),
            "probe with a file": json.dumps({"mode": "probe", "filename": "a.step", "data": STEP}).encode(),
            "no data": json.dumps({"filename": "a.step"}).encode(),
        }
        for label, raw in cases.items():
            with self.subTest(label):
                status, body, _ = self.request("POST", "/api/cad/jobs", raw=raw)
                self.assertEqual(status, 400, body)
        status, body, _ = self.request("POST", "/api/cad/jobs", raw=b"{}", headers={"Content-Length": "-5"})
        self.assertEqual(status, 400, body)
        self.assertEqual({j["id"] for j in self.request("GET", "/api/cad/jobs")[1]["jobs"]}, before,
                         "a rejected request must not create a job")

    def test_unknown_and_malformed_job_ids_are_404(self):
        for path in ("/api/cad/jobs/" + "a" * 32, "/api/cad/jobs/" + "a" * 32 + "/result",
                     "/api/cad/jobs/../../etc", "/api/cad/jobs/XYZ"):
            with self.subTest(path=path):
                self.assertEqual(self.request("GET", path)[0], 404)
        self.assertEqual(self.request("DELETE", "/api/cad/jobs/" + "b" * 32)[0], 404)
        self.assertEqual(self.request("DELETE", "/api/cad/jobs/not-an-id")[0], 404)

    # ── the job flow ──
    def test_submit_returns_202_and_the_result_arrives_later(self):
        status, job, r = self.submit("slow-ok")
        self.assertEqual(status, 202)
        self.assertEqual(r.getheader("Location"), f"/api/cad/jobs/{job['id']}")
        self.assertIn(job["state"], {"queued", "running"})
        early, body, _ = self.request("GET", f"/api/cad/jobs/{job['id']}/result")
        if self.request("GET", f"/api/cad/jobs/{job['id']}")[1]["state"] != "succeeded":
            self.assertEqual(early, 409, "a result before success must be refused, not empty")
        done = self.wait(job["id"])
        self.assertEqual(done["state"], "succeeded")
        status, result, _ = self.request("GET", f"/api/cad/jobs/{job['id']}/result")
        self.assertEqual(status, 200)
        self.assertIn("<geometry>", result["xml_data"])
        self.assertNotIn("xml", result)
        self.assertFalse(result["can_import_into_studio"])
        listed = [j["id"] for j in self.request("GET", "/api/cad/jobs")[1]["jobs"]]
        self.assertIn(job["id"], listed)

    def test_worker_failure_reaches_the_client_with_its_reason(self):
        _, job, _ = self.submit("self-fail")
        done = self.wait(job["id"])
        self.assertEqual(done["state"], "failed")
        self.assertIn("exactly one valid closed solid", done["error"])
        self.assertIn("GEOUNED", done["diagnostics"])
        self.assertEqual(self.request("GET", f"/api/cad/jobs/{job['id']}/result")[0], 409)

    def test_delete_cancels_a_running_job(self):
        _, job, _ = self.submit("hang")
        deadline = time.time() + 20
        while self.request("GET", f"/api/cad/jobs/{job['id']}")[1]["state"] != "running" and time.time() < deadline:
            time.sleep(0.05)
        status, body, _ = self.request("DELETE", f"/api/cad/jobs/{job['id']}")
        self.assertEqual(status, 202)
        self.assertIn(body["state"], {"cancelling", "cancelled"})
        self.assertEqual(self.wait(job["id"])["state"], "cancelled")
        # Cancelling a finished job is harmless and reports its final state.
        self.assertEqual(self.request("DELETE", f"/api/cad/jobs/{job['id']}")[1]["state"], "cancelled")

    def test_concurrent_posts_each_get_a_job_until_capacity(self):
        results = []

        def post():
            # Accepted jobs hang, so none frees its slot while the requests race in.
            results.append(self.submit("hang"))
        try:
            threads = [threading.Thread(target=post) for _ in range(6)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            statuses = sorted(s for s, _, _ in results)
            accepted = [b["id"] for s, b, _ in results if s == 202]
            self.assertEqual(len(set(accepted)), len(accepted), "job IDs must be unique")
            self.assertEqual(statuses, [202] * 4 + [409] * 2, "exactly max_pending jobs are accepted")
            # Serialized: at most one of them has a live worker.
            states = [self.request("GET", f"/api/cad/jobs/{i}")[1]["state"] for i in accepted]
            self.assertLessEqual(states.count("running"), 1, states)
        finally:
            for _, body, _ in results:
                if isinstance(body, dict) and "id" in body:
                    self.request("DELETE", f"/api/cad/jobs/{body['id']}")
        for job_id in accepted:
            self.assertEqual(self.wait(job_id)["state"], "cancelled")

    def test_capabilities_are_honest(self):
        status, caps, _ = self.request("GET", "/api/cad/capabilities")
        self.assertEqual(status, 200)
        self.assertTrue(caps["available"])
        self.assertFalse(caps["can_import_into_studio"])
        self.assertIn("probe", caps["modes"])

    def test_probe_over_http_verifies_the_engine(self):
        status, job, _ = self.request("POST", "/api/cad/jobs", {"mode": "probe"})
        self.assertEqual(status, 202, job)
        self.assertEqual(self.wait(job["id"])["state"], "succeeded")
        self.assertTrue(self.request("GET", "/api/cad/capabilities")[1]["engine_verified"])


@unittest.skipUnless(sys.platform.startswith("linux"), "Linux/WSL only")
class StudioWithoutCad(unittest.TestCase):
    def test_runs_folder_inside_the_checkout_keeps_studio_running(self):
        runs = ROOT / "test" / "generated" / "runs-inside-repo"
        try:
            studio = srv.Studio(runs, TOKEN, 1)
            caps = studio.cad_jobs.capabilities()
            self.assertFalse(caps["available"])
            self.assertIn("outside the repository", caps["reason"])
            with self.assertRaises(RuntimeError):
                studio.cad_jobs.submit(b"x", "a.step")
        finally:
            shutil.rmtree(runs, ignore_errors=True)

    def test_unconfigured_engine_refuses_jobs_with_409(self):
        old = os.environ.pop("OPENMC_CAD_PYTHON", None)
        tmp = Path(tempfile.mkdtemp(prefix="cad-none-"))
        port = free_port()
        try:
            studio = srv.Studio(tmp / "runs", TOKEN, port)
            srv.Handler.studio = studio
            httpd = ThreadingHTTPServer(("127.0.0.1", port), srv.Handler)
            threading.Thread(target=httpd.serve_forever, daemon=True).start()
            conn = HTTPConnection("127.0.0.1", port, timeout=10)
            body = json.dumps({"filename": "a.step", "data": STEP}).encode()
            conn.request("POST", "/api/cad/jobs", body=body, headers={
                "Host": f"127.0.0.1:{port}", "X-Studio-Token": TOKEN,
                "Content-Type": "application/json", "Content-Length": str(len(body))})
            r = conn.getresponse()
            self.assertEqual(r.status, 409)
            self.assertIn("OPENMC_CAD_PYTHON", json.loads(r.read())["error"])
            httpd.shutdown()
            httpd.server_close()
        finally:
            if old is not None:
                os.environ["OPENMC_CAD_PYTHON"] = old
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
