"""A real Core (nodal) solve through the Studio server: POST /api/nodal/run with a Studio-style model.py, wait, read nodal.json; and stop one half way.

The model is the saved 8 x 8 checkerboard (test_nodal_driver.script_text); the pieces are small (3,000 x 40). References: OpenMC's own k of the saved run (0.94469) and E15's
printed two-step offset (+1,018 pcm at 20,000 x 150), with the same wide window as test_nodal_driver.py. What is checked beyond the numbers: the run is its own folder with kind
"nodal", nodal.json is hashed in provenance.json, the log carries the pieces' progress, a second run while one is going is refused (409), and a stopped run leaves no child process.

Needs openmc, openndm 0.3.0 and OPENMC_CROSS_SECTIONS; run it with `node test/run_all.cjs nodal` or  python test/nodal/test_nodal_route_run.py
"""
import json
import os
import socket
import sys
import tempfile
import threading
import time
import unittest
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "studio"))
sys.path.insert(0, str(HERE))
try:
    import test_nodal_driver as td
    from openmc_studio import nodal_run, server as srv
except (ImportError, SystemExit) as e:  # a test that cannot run is a failure, not a quiet pass
    raise SystemExit(f"test_nodal_route_run: needs openmc and openndm ({e}). Run it with `node test/run_all.cjs nodal`.")

TOKEN = "n" * 32


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Run(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.saved = os.environ.get("OPENNDM_PYTHON")
        os.environ["OPENNDM_PYTHON"] = sys.executable
        nodal_run._cache.update(at=0.0, key=None, value=None)
        cls.tmp = Path(tempfile.mkdtemp(prefix="nodal-route-run-"))
        cls.port = free_port()
        cls.studio = srv.Studio(cls.tmp / "runs", TOKEN, cls.port)
        srv.Handler.studio = cls.studio
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", cls.port), srv.Handler)
        cls.httpd.daemon_threads = True
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.script = td.script_text(td.load("checker1")["kinds"])

    @classmethod
    def tearDownClass(cls):
        if cls.studio.active and cls.studio.active.status == "running":
            cls.studio.stop(cls.studio.active.id)
        cls.httpd.shutdown()
        cls.httpd.server_close()
        if cls.saved is None:
            os.environ.pop("OPENNDM_PYTHON", None)
        else:
            os.environ["OPENNDM_PYTHON"] = cls.saved
        nodal_run._cache.update(at=0.0, key=None, value=None)
        import shutil
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def call(self, method, path, body=None):
        conn = HTTPConnection("127.0.0.1", self.port, timeout=60)
        conn.request(method, path, json.dumps(body) if body is not None else None, {"Host": f"127.0.0.1:{self.port}", "X-Studio-Token": TOKEN, "Content-Type": "application/json"})
        r = conn.getresponse()
        return r.status, json.loads(r.read())

    def wait(self, seconds=420):
        end = time.time() + seconds
        while time.time() < end and self.studio.active and self.studio.active.status == "running":
            time.sleep(0.5)
        self.assertNotEqual(self.studio.active.status, "running", "the run did not finish")

    def in_folder(self):
        """Names of the processes whose working directory is inside this test's runs folder (Linux /proc)."""
        out = []
        for d in Path("/proc").iterdir():
            if d.name.isdigit():
                try:
                    if os.readlink(d / "cwd").startswith(str(self.tmp)):
                        out.append((d / "comm").read_text().strip())
                except OSError:
                    pass
        return sorted(out)

    def test_a_1_status_is_available(self):
        code, out = self.call("GET", "/api/nodal/status")
        self.assertEqual(code, 200)
        self.assertTrue(out["available"], out)
        self.assertTrue(str(out["openndm"]).startswith("0.3"))

    def test_b_a_run_gives_nodal_json_in_its_own_folder(self):
        code, meta = self.call("POST", "/api/nodal/run", {"script": self.script, "project": {}, "name": "checker", "settings": {"particles": 3000, "batches": 40, "inactive": 10, "seed": 5}})
        self.assertEqual(code, 200, meta)
        self.assertEqual(meta["kind"], "nodal")
        code2, again = self.call("POST", "/api/nodal/run", {"script": self.script, "project": {}, "name": "second", "settings": {}})
        self.assertEqual(code2, 409, "a second run while one is going is refused")
        self.wait()
        run = self.studio.runs[meta["id"]]
        log = (run.path / "run.log").read_text(encoding="utf-8")
        self.assertEqual(run.status, "done", log[-1500:])
        self.assertIn("piece 1 of 4", log)
        self.assertIn("Nodal k =", log)
        code, doc = self.call("GET", f"/api/runs/{meta['id']}/nodal")
        self.assertEqual(code, 200)
        d = (doc["k_eff"] - float(td.load("checker1")["k"])) * 1e5
        self.assertLess(abs(d - td.E15["checker1"]), 1500, f"{d:+.0f} pcm")
        self.assertEqual(doc["provenance"]["boundaries"]["x_min"], "vacuum")
        self.assertEqual(doc["settings"]["particles"] if "settings" in doc else doc["provenance"]["settings"]["particles"], 3000)
        prov = json.loads((run.path / "provenance.json").read_text(encoding="utf-8"))
        self.assertEqual(prov["kind"], "nodal-run")
        self.assertIn("nodal.json", prov["outputs"])
        self.assertEqual(prov["nodal"]["settings"]["seed"], 5)
        self.assertEqual(prov["nodal"]["versions"]["openndm"][:3], "0.3")
        listed = next(r for r in self.call("GET", "/api/runs")[1]["runs"] if r["id"] == meta["id"])
        self.assertEqual((listed["kind"], listed["status"]), ("nodal", "done"))

    def test_c_stopping_leaves_no_child_process(self):
        code, meta = self.call("POST", "/api/nodal/run", {"script": self.script, "project": {}, "name": "stopme", "settings": {"particles": 20000, "batches": 150, "inactive": 30}})
        self.assertEqual(code, 200, meta)
        time.sleep(8)                                        # long enough for the first piece's openmc to be running
        alive = self.in_folder()
        self.assertTrue(any(c == "python" or c.startswith("python") for c in alive) and "openmc" in alive, f"the control: the driver and an openmc piece run in the folder, saw {alive}")
        self.assertTrue(self.studio.stop(meta["id"]))
        self.wait(60)
        self.assertEqual(self.studio.runs[meta["id"]].status, "stopped")
        time.sleep(2)
        self.assertEqual(self.in_folder(), [], "nothing of the stopped run is still running")
        code, out = self.call("GET", f"/api/runs/{meta['id']}/nodal")
        self.assertEqual(code, 404, "a stopped run has no nodal.json")


if __name__ == "__main__":
    unittest.main(verbosity=2)
