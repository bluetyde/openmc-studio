"""The server side of the Core (nodal) tab, without the nodal package: studio/openmc_studio/nodal_run.py and the /api/nodal routes.

With OPENNDM_PYTHON pointing nowhere the package is absent, which is what the physics environment looks like: the status says why, a run is refused with "Needs the nodal package"
before any run folder is made, bad settings are refused first and by name, and the token is still required. The command and environment the child gets are checked as data.
A real run through the server is test/nodal/test_nodal_route_run.py (profile `nodal`).

    python test/test_nodal_route.py
"""
import json
import os
import socket
import sys
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "studio"))
from openmc_studio import nodal_run, server as srv  # noqa: E402

TOKEN = "t" * 32


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Settings(unittest.TestCase):
    def test_defaults(self):
        s = nodal_run.clean_settings(None)
        self.assertEqual((s["particles"], s["batches"], s["inactive"], s["kernel"], s["reflective"], s["lattice"]), (6000, 60, 15, "sanm", [], None))

    def test_each_bad_value_is_named(self):
        for bad, word in (({"particles": 50}, "particles"), ({"particles": 10**7}, "particles"), ({"particles": 1.5}, "particles"), ({"particles": True}, "particles"),
                          ({"batches": 5}, "batches"), ({"batches": 20, "inactive": 20}, "inactive"), ({"seed": 0}, "seed"), ({"threads": 0}, "threads"),
                          ({"kernel": "x"}, "kernel"), ({"reflective": ["left"]}, "reflective"), ({"reflective": ["x_min", "x_min"]}, "reflective"),
                          ({"reflective": "x_min"}, "reflective"), ({"lattice": ""}, "lattice"), ({"lattice": 3}, "lattice"), ({"unknown": 1}, "unknown"), ("text", "object")):
            with self.assertRaises(nodal_run.NodalRequestError, msg=str(bad)) as cm:
                nodal_run.clean_settings(bad)
            self.assertIn(word, str(cm.exception))

    def test_only_the_checked_openndm_line_is_accepted(self):
        for v in ("0.3.0", "0.3.9", "0.3"):
            self.assertIsNone(nodal_run.version_problem(v), v)
        for v in ("0.2.9", "0.4.0", "1.3.0", "0", "x"):
            self.assertIn("0.3.x only", nodal_run.version_problem(v) or "", v)

    def test_the_command_and_environment(self):
        env = {"OPENNDM_PYTHON": "/venv/bin/python", "PATH": "/usr/bin", "PYTHONPATH": "/x"}
        s = nodal_run.clean_settings({"particles": 1234, "batches": 30, "inactive": 5, "seed": 9, "threads": 2, "kernel": "nem", "reflective": ["x_min", "y_max"], "lattice": "Core"})
        argv = nodal_run.command(s, env)
        self.assertEqual(argv[:5], ["/venv/bin/python", "-W", "ignore", "-m", "openmc_studio.nodal_driver"])
        for pair in (("--particles", "1234"), ("--batches", "30"), ("--inactive", "5"), ("--seed", "9"), ("--threads", "2"), ("--kernel", "nem"), ("--lattice", "Core"), ("--out", "nodal.json")):
            self.assertEqual(argv[argv.index(pair[0]) + 1], pair[1])
        self.assertEqual(argv[argv.index("--reflective") + 1:], ["x_min", "y_max"])
        e = nodal_run.child_env(env)
        self.assertEqual(e["PATH"].split(os.pathsep)[0], os.path.dirname("/venv/bin/python"), "the nodal Python's folder (its openmc executable) comes first")
        self.assertTrue(e["PYTHONPATH"].startswith(nodal_run.PACKAGE_PARENT) and e["PYTHONPATH"].endswith("/x"))
        self.assertEqual(e["PYTHONUNBUFFERED"], "1")
        self.assertNotIn("--reflective", nodal_run.command(nodal_run.clean_settings({}), env))


class Http(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.saved = os.environ.get("OPENNDM_PYTHON")
        os.environ["OPENNDM_PYTHON"] = str(Path(tempfile.gettempdir()) / "no-such-python-for-nodal")
        nodal_run._cache.update(at=0.0, key=None, value=None)
        cls.tmp = Path(tempfile.mkdtemp(prefix="nodal-route-"))
        cls.port = free_port()
        cls.studio = srv.Studio(cls.tmp / "runs", TOKEN, cls.port)
        srv.Handler.studio = cls.studio
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", cls.port), srv.Handler)
        cls.httpd.daemon_threads = True
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        if cls.saved is None:
            os.environ.pop("OPENNDM_PYTHON", None)
        else:
            os.environ["OPENNDM_PYTHON"] = cls.saved
        nodal_run._cache.update(at=0.0, key=None, value=None)
        import shutil
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def call(self, method, path, body=None, token=TOKEN):
        conn = HTTPConnection("127.0.0.1", self.port, timeout=30)
        headers = {"Host": f"127.0.0.1:{self.port}", "Content-Type": "application/json"}
        if token:
            headers["X-Studio-Token"] = token
        conn.request(method, path, json.dumps(body) if body is not None else None, headers)
        r = conn.getresponse()
        return r.status, json.loads(r.read())

    def test_status_says_why_it_is_off(self):
        code, out = self.call("GET", "/api/nodal/status")
        self.assertEqual(code, 200)
        self.assertFalse(out["available"])
        self.assertIn("OPENNDM_PYTHON", out["reason"])
        self.assertIn("openndm", out["reason"])

    def test_a_run_is_refused_before_any_run_folder_is_made(self):
        before = sorted(p.name for p in (self.tmp / "runs").iterdir())
        code, out = self.call("POST", "/api/nodal/run", {"script": "x = 1", "project": {}, "name": "m", "settings": {}})
        self.assertEqual(code, 422)
        self.assertTrue(out["error"].startswith("Needs the nodal package."), out["error"])
        self.assertEqual(sorted(p.name for p in (self.tmp / "runs").iterdir()), before)

    def test_bad_requests_are_refused_by_name_first(self):
        code, out = self.call("POST", "/api/nodal/run", {"script": "x = 1", "settings": {"particles": 5}})
        self.assertEqual(code, 400)
        self.assertIn("particles", out["error"])
        code, out = self.call("POST", "/api/nodal/run", {"script": "  ", "settings": {}})
        self.assertEqual((code, out["error"]), (400, "No script to run."))

    def test_the_token_is_required(self):
        self.assertEqual(self.call("GET", "/api/nodal/status", token=None)[0], 401)
        self.assertEqual(self.call("POST", "/api/nodal/run", {"script": "x"}, token=None)[0], 401)
        self.assertEqual(self.call("POST", "/api/nodal/run", {"script": "x"}, token="wrong")[0], 401)

    def test_a_run_has_a_kind_and_the_nodal_file_is_not_found_without_it(self):
        self.assertEqual(srv.Run("20260101-000000-x", self.tmp, "x").meta()["kind"], "openmc")
        code, out = self.call("GET", "/api/runs/20260101-000000-nothing/nodal")
        self.assertEqual(code, 404)


if __name__ == "__main__":
    unittest.main(verbosity=2)
