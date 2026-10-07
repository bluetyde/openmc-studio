"""The refusals every run path shares (studio/openmc_studio/prerun_check.py) against the page's own list of errors.

test/fixtures/prerun/cases.json holds 73 projects and, for each, the errors the page's problems() gives it (made and kept
current by test/test_prerun_check_page.js). Python must give the same objects the same number of errors: a project the
page refuses must be refused here and one the page allows must be allowed, or a script could run what the page forbids, or be
stopped from running what the page allows.

Run: python test/test_prerun_check.py
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
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "studio"))
from openmc_studio import headless, prerun_check, server as srv  # noqa: E402

TOKEN = "t" * 32

CASES = json.loads((ROOT / "test" / "fixtures" / "prerun" / "cases.json").read_text(encoding="utf-8"))
KINDS = {"materials": "material", "parts": "part", "sources": "source", "tallies": "tally"}


def key(finding):
    """The page's "kind:id" for a finding's path: /settings is settings:, /materials/m1 is material:m1, /sources alone is '-'."""
    bits = [b for b in finding["path"].split("/") if b]
    if len(bits) == 1:
        return "-" if bits[0] in KINDS else f"{bits[0]}:"
    return f"{KINDS[bits[0]]}:{bits[1]}"


class ParityWithThePage(unittest.TestCase):
    def test_every_case_gets_the_same_errors_as_the_page(self):
        self.assertGreaterEqual(len(CASES), 60)
        for c in CASES:
            with self.subTest(case=c["name"]):
                self.assertEqual(sorted(key(f) for f in prerun_check.check(c["project"])), c["errors"])

    def test_cases_cover_every_rule_code(self):
        """Each code the module can give is reached by at least one case, so a rule cannot be changed without a case failing."""
        import re
        src = (ROOT / "studio" / "openmc_studio" / "prerun_check.py").read_text(encoding="utf-8")
        codes = set(re.findall(r'add\(\s*"([a-z0-9-]+)"', src))
        seen = {f["code"] for c in CASES for f in prerun_check.check(c["project"])}
        self.assertEqual(sorted(codes - seen), [], "rules no case reaches")


class Findings(unittest.TestCase):
    def test_a_finding_names_where_and_says_what(self):
        c = next(c for c in CASES if c["name"] == "material density zero")
        (f,) = prerun_check.check(c["project"])
        self.assertEqual((f["level"], f["code"], f["path"]), ("error", "material-density", "/materials/m1"))
        self.assertIn("density must be above 0", f["message"])

    def test_a_project_that_is_not_an_object_is_refused_not_crashed(self):
        for junk in (None, [], "x", 3):
            codes = {f["code"] for f in prerun_check.check(junk)}
            self.assertIn("source-none", codes)
            self.assertIn("settings-particles", codes)

    def test_numbers_that_are_strings_or_bools_are_not_numbers(self):
        c = next(c for c in CASES if c["name"] == "baseline: the demo model")
        for bad in ("100", True, None):
            p = json.loads(json.dumps(c["project"]))
            p["settings"]["particles"] = bad
            self.assertIn("settings-particles", {f["code"] for f in prerun_check.check(p)})

    def test_a_whole_number_written_as_a_float_is_accepted_as_the_page_does(self):
        c = next(c for c in CASES if c["name"] == "baseline: the demo model")
        p = json.loads(json.dumps(c["project"]))
        p["settings"]["particles"] = 5000.0
        self.assertEqual(prerun_check.check(p), [])


def case_project(name):
    return json.loads(json.dumps(next(c for c in CASES if c["name"] == name)["project"]))


class Headless(unittest.TestCase):
    def test_shared_errors_come_after_the_capability_checks(self):
        p = case_project("eigenvalue without fuel")  # an eigenvalue project: headless refuses the mode first
        problems = headless.check_project(p)
        self.assertEqual(problems[0]["code"], "E_UNSUPPORTED")
        self.assertEqual(problems[0]["path"], "/settings/runMode")
        self.assertIn("/settings", [x["path"] for x in problems], "and the shared 'needs fuel' error follows")

    def test_a_project_with_a_bad_material_is_refused_with_its_path(self):
        p = case_project("material density zero")
        found = [(x["code"], x["path"]) for x in headless.check_project(p)]
        self.assertIn(("E_SCHEMA_INVALID", "/materials/m1"), found)

    def test_an_error_headless_already_reports_is_not_repeated(self):
        p = case_project("particles zero")
        paths = [x["path"] for x in headless.check_project(p)]
        self.assertEqual(paths.count("/settings/particles"), 1)
        self.assertNotIn("/settings", paths)

    def test_a_good_project_has_no_problems(self):
        p = case_project("baseline: the demo model")
        p["settings"]["maxTracks"] = 0
        self.assertEqual(headless.check_project(p), [])


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@unittest.skipUnless(sys.platform.startswith("linux"), "the run server starts python; run this under WSL")
class RunEndpoint(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="prerun-http-"))
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
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def post(self, body):
        conn = HTTPConnection("127.0.0.1", self.port, timeout=30)
        conn.request("POST", "/api/run", json.dumps(body), {"Host": f"127.0.0.1:{self.port}", "X-Studio-Token": TOKEN,
                                                             "Content-Type": "application/json"})
        r = conn.getresponse()
        return r.status, json.loads(r.read())

    def runs(self):
        root = self.tmp / "runs"
        return sorted(p.name for p in root.iterdir()) if root.is_dir() else []

    def test_a_project_with_errors_is_refused_and_no_run_folder_is_made(self):
        before = self.runs()
        status, body = self.post({"script": "print('x')\n", "project": case_project("several errors at once"), "name": "bad"})
        self.assertEqual(status, 422)
        self.assertEqual(len(body["findings"]), 3)
        self.assertIn("3 errors", body["error"])
        self.assertEqual(self.runs(), before, "refused before any run folder exists")

    def test_a_good_project_starts(self):
        status, body = self.post({"script": "print('x')\n", "project": case_project("baseline: the demo model"), "name": "good"})
        self.assertEqual(status, 200, body)
        deadline = time.time() + 30
        while time.time() < deadline and self.studio.active and self.studio.active.status == "running":
            time.sleep(0.2)

    def test_no_project_means_no_check(self):
        status, body = self.post({"script": "print('x')\n", "name": "bare"})
        self.assertEqual(status, 200, body)
        deadline = time.time() + 30
        while time.time() < deadline and self.studio.active and self.studio.active.status == "running":
            time.sleep(0.2)


if __name__ == "__main__":
    unittest.main()
