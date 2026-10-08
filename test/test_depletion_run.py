"""What a depletion run needs from the server (depletion_run.py and the /api/run path that uses it).

Unit tests of the chain-file lookup, the script text and the chain record; then /api/run over real HTTP: a project that asks for
depletion with no chain file is refused before a run folder exists, and with one it gets deplete.py beside model.py and a
provenance record that names the chain by its hash. The run itself is not a real depletion (the script text posted has no model, so the
run ends at once): a real depletion of a pin cell is test/manual_depletion_run.py, which takes minutes.

Linux/WSL (the run server starts python). Run: python test/test_depletion_run.py
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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "studio"))
from openmc_studio import depletion_run, server as srv  # noqa: E402

TOKEN = "t" * 32
CASES = json.loads((ROOT / "test" / "fixtures" / "prerun" / "cases.json").read_text(encoding="utf-8"))


def project(name="depletion with a burnable fuel in an eigenvalue run"):
    return json.loads(json.dumps(next(c for c in CASES if c["name"] == name)["project"]))


class Unit(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="depletion-run-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_wants_only_when_depletion_is_on(self):
        self.assertTrue(depletion_run.wants(project()))
        self.assertFalse(depletion_run.wants(project("baseline: the demo model")))
        for junk in (None, {}, {"settings": None}, {"settings": {"depletion": "yes"}}, {"settings": {"depletion": 1}}):
            self.assertFalse(depletion_run.wants(junk), junk)

    def test_an_explicit_chain_file_wins_and_a_missing_one_is_none(self):
        chain = self.tmp / "mine.xml"
        chain.write_text("<depletion_chain/>")
        self.assertEqual(depletion_run.find_chain_file({"OPENMC_CHAIN_FILE": str(chain)}), chain)
        self.assertIsNone(depletion_run.find_chain_file({"OPENMC_CHAIN_FILE": str(self.tmp / "nope.xml")}), "named but missing: no guessing")

    def test_the_chains_folder_beside_the_nuclear_data_is_found_and_pwr_is_preferred(self):
        (self.tmp / "data" / "lib").mkdir(parents=True)
        (self.tmp / "data" / "chains").mkdir()
        (self.tmp / "data" / "chains" / "chain_a_sfr.xml").write_text("<x/>")
        (self.tmp / "data" / "chains" / "chain_b_pwr.xml").write_text("<x/>")
        xs = self.tmp / "data" / "lib" / "cross_sections.xml"
        xs.write_text("<x/>")
        self.assertEqual(depletion_run.find_chain_file({"OPENMC_CROSS_SECTIONS": str(xs)}).name, "chain_b_pwr.xml")
        self.assertIsNone(depletion_run.find_chain_file({}))
        self.assertIsNone(depletion_run.find_chain_file({"OPENMC_CROSS_SECTIONS": str(self.tmp / "elsewhere" / "x" / "cross_sections.xml")}))

    def test_the_steps_and_the_script(self):
        self.assertEqual(depletion_run.steps_days("1, 4,10 ,25, 60"), [1.0, 4.0, 10.0, 25.0, 60.0])
        text = depletion_run.script_text(project(), self.tmp / "model.py", self.tmp / "chain.xml")
        self.assertIn("reduce_chain_level=6", text)
        self.assertIn("power_density=38.0", text)
        self.assertIn("[1.0, 4.0, 10.0, 25.0, 60.0]", text)
        self.assertIn("CECMIntegrator", text)
        self.assertIn('namespace["prepare_depletion"](model)', text)
        self.assertIn(repr(str(self.tmp / "model.py")), text)

    def test_the_chain_record_names_the_file_by_its_hash(self):
        chain = self.tmp / "chain.xml"
        chain.write_bytes(b"<depletion_chain>" + b"x" * 3000 + b"</depletion_chain>")
        rec = depletion_run.chain_record(chain)
        self.assertEqual(rec["sha256"], hashlib.sha256(chain.read_bytes()).hexdigest())
        self.assertEqual((rec["size"], rec["path"]), (chain.stat().st_size, str(chain)))


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@unittest.skipUnless(sys.platform.startswith("linux"), "the run server starts python; run this under WSL")
class Http(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="depletion-http-"))
        cls.port = free_port()
        cls.studio = srv.Studio(cls.tmp / "runs", TOKEN, cls.port)
        srv.Handler.studio = cls.studio
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", cls.port), srv.Handler)
        cls.httpd.daemon_threads = True
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.saved = {k: os.environ.get(k) for k in ("OPENMC_CHAIN_FILE", "OPENMC_CROSS_SECTIONS")}

    @classmethod
    def tearDownClass(cls):
        for k, v in cls.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        cls.httpd.shutdown()
        cls.httpd.server_close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def call(self, method, path, body=None):
        conn = HTTPConnection("127.0.0.1", self.port, timeout=30)
        conn.request(method, path, json.dumps(body) if body is not None else None,
                     {"Host": f"127.0.0.1:{self.port}", "X-Studio-Token": TOKEN, "Content-Type": "application/json"})
        r = conn.getresponse()
        return r.status, json.loads(r.read())

    def runs(self):
        root = self.tmp / "runs"
        return sorted(p.name for p in root.iterdir()) if root.is_dir() else []

    def wait(self):
        deadline = time.time() + 30
        while time.time() < deadline and self.studio.active and self.studio.active.status == "running":
            time.sleep(0.2)

    def test_no_chain_file_is_refused_before_a_run_folder_exists(self):
        os.environ.pop("OPENMC_CHAIN_FILE", None)
        os.environ["OPENMC_CROSS_SECTIONS"] = str(self.tmp / "nowhere" / "x" / "cross_sections.xml")
        before = self.runs()
        status, body = self.call("POST", "/api/run", {"script": "print('x')\n", "project": project(), "name": "dep"})
        self.assertEqual(status, 422)
        self.assertIn("depletion chain file", body["error"])
        self.assertEqual(self.runs(), before)
        self.assertIsNone(self.call("GET", "/api/health")[1]["depletion_chain"])

    def test_with_a_chain_file_the_run_gets_deplete_py_and_a_record_of_the_chain(self):
        chain = self.tmp / "chain_test_pwr.xml"
        chain.write_text("<depletion_chain/>")
        os.environ["OPENMC_CHAIN_FILE"] = str(chain)
        self.assertEqual(self.call("GET", "/api/health")[1]["depletion_chain"], str(chain))
        status, body = self.call("POST", "/api/run", {"script": "print('model')\n", "project": project(), "name": "dep ok"})
        self.assertEqual(status, 200, body)
        self.wait()
        run_dir = self.tmp / "runs" / body["id"]
        text = (run_dir / "deplete.py").read_text()
        self.assertIn(repr(str(run_dir / "model.py")), text)
        self.assertIn(repr(str(chain)), text)
        self.assertIn("reduce_chain_level=6", text)
        rec = json.loads((run_dir / "provenance.json").read_text())
        self.assertEqual(rec["depletion"]["chain"]["sha256"], hashlib.sha256(chain.read_bytes()).hexdigest())
        self.assertIn("deplete.py", rec["files"])
        self.assertEqual(rec["settings"]["depIntegrator"], "CECMIntegrator")
        self.assertEqual(self.studio.runs[body["id"]].status, "failed", "the posted script has no model, so deplete.py stops: this is not a real depletion")

    def test_a_depletion_run_that_ends_well_gets_its_record_and_one_that_fails_does_not(self):
        from openmc_studio import depletion_writer
        chain = self.tmp / "chain_hook_pwr.xml"
        chain.write_text("<depletion_chain/>")
        os.environ["OPENMC_CHAIN_FILE"] = str(chain)
        real_script, real_from_run = depletion_run.script_text, depletion_writer.from_run
        called = []
        depletion_writer.from_run = lambda folder: called.append(Path(folder).name) or {"id": "f" * 64, "provenance": {"checks": {}}}
        try:
            depletion_run.script_text = lambda project, model_path, chain_file: "print('burned')\n"  # stands in for a successful burn
            status, body = self.call("POST", "/api/run", {"script": "print('model')\n", "project": project(), "name": "dep hook"})
            self.assertEqual(status, 200, body)
            self.wait()
            run = self.studio.runs[body["id"]]
            self.assertEqual(run.status, "done")
            self.assertEqual(called, [body["id"]], "the record is written after the run ends well")
            self.assertTrue(any("Depletion record written" in line for line in run.lines))
            depletion_run.script_text = lambda project, model_path, chain_file: "raise SystemExit(3)\n"  # a burn that fails
            called.clear()
            status, body = self.call("POST", "/api/run", {"script": "print('model')\n", "project": project(), "name": "dep fail"})
            self.wait()
            self.assertEqual(self.studio.runs[body["id"]].status, "failed")
            self.assertEqual(called, [], "no record for a failed run")
        finally:
            depletion_run.script_text, depletion_writer.from_run = real_script, real_from_run

    def test_a_project_without_depletion_runs_model_py_as_before(self):
        status, body = self.call("POST", "/api/run", {"script": "print('model')\n", "project": project("baseline: the demo model"), "name": "plain"})
        self.assertEqual(status, 200, body)
        self.wait()
        run_dir = self.tmp / "runs" / body["id"]
        self.assertFalse((run_dir / "deplete.py").exists())
        self.assertNotIn("depletion", json.loads((run_dir / "provenance.json").read_text()))
        self.assertEqual(self.studio.runs[body["id"]].status, "done")


if __name__ == "__main__":
    unittest.main()
