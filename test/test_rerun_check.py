"""Tests for openmc_studio.rerun_check: verifying provenance records against disk and environment."""
import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "studio"))
from openmc_studio import provenance, rerun_check  # noqa: E402

BASE_ENV = {
    "studio": {"version": "0.2.0", "git": {"commit": "abc1234", "dirty": False}},
    "python": "3.11.0",
    "platform": "Linux 6.0.0 x86_64",
    "openmc": {"python": "0.14.0", "executable": "/usr/bin/openmc"},
    "nuclear_data": {
        "cross_sections": "/path/to/cross_sections.xml",
        "sha256": "11223344556677889900aabbccddeeff11223344556677889900aabbccddeeff",
        "size": 123456,
        "libraries": 10,
    },
}


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def make_record(files=None, env=None, **extra):
    rec = {
        "kind": "run",
        "written": "2026-10-07T12:00:00+00:00",
        "environment": copy.deepcopy(env if env is not None else BASE_ENV),
        "settings": {},
        "normalization": {},
    }
    if files is not None:
        rec["files"] = files
    rec.update(extra)
    return rec


class TestRerunCheck(unittest.TestCase):
    def test_match(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            (p / "f1.txt").write_bytes(b"first content")
            (p / "f2.txt").write_bytes(b"second content")
            files_map = {
                "f1.txt": sha256_bytes(b"first content"),
                "f2.txt": sha256_bytes(b"second content"),
            }
            (p / "provenance.json").write_text(json.dumps(make_record(files=files_map)))

            res = rerun_check.check(p, current=BASE_ENV)
            self.assertEqual(res["status"], "match")
            self.assertEqual(res["counts"], {
                "files_changed": 0,
                "files_missing": 0,
                "files_other": 0,
                "environment_warnings": 0,
                "environment_info": 0,
            })
            self.assertEqual(len(res["files"]), 2)
            self.assertEqual(res["files"][0]["name"], "f1.txt")
            self.assertEqual(res["files"][0]["state"], "ok")
            self.assertEqual(res["files"][0]["actual"], files_map["f1.txt"])
            self.assertEqual(res["files"][1]["name"], "f2.txt")
            self.assertEqual(res["files"][1]["state"], "ok")
            self.assertEqual(res["files"][1]["actual"], files_map["f2.txt"])
            self.assertEqual(res["environment"], [])
            self.assertEqual(res["notes"], [])

    def test_file_edited_afterwards(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            (p / "f1.txt").write_bytes(b"original content")
            files_map = {"f1.txt": sha256_bytes(b"original content")}
            (p / "provenance.json").write_text(json.dumps(make_record(files=files_map)))

            (p / "f1.txt").write_bytes(b"modified content")
            res = rerun_check.check(p, current=BASE_ENV)

            self.assertEqual(res["status"], "differences")
            self.assertEqual(res["counts"], {
                "files_changed": 1,
                "files_missing": 0,
                "files_other": 0,
                "environment_warnings": 0,
                "environment_info": 0,
            })
            self.assertEqual(len(res["files"]), 1)
            self.assertEqual(res["files"][0]["name"], "f1.txt")
            self.assertEqual(res["files"][0]["state"], "changed")
            self.assertEqual(res["files"][0]["expected"], sha256_bytes(b"original content"))
            self.assertEqual(res["files"][0]["actual"], sha256_bytes(b"modified content"))

    def test_file_deleted(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            files_map = {"missing.txt": "deadbeef1234"}
            (p / "provenance.json").write_text(json.dumps(make_record(files=files_map)))

            res = rerun_check.check(p, current=BASE_ENV)
            self.assertEqual(res["status"], "differences")
            self.assertEqual(res["counts"], {
                "files_changed": 0,
                "files_missing": 1,
                "files_other": 0,
                "environment_warnings": 0,
                "environment_info": 0,
            })
            self.assertEqual(len(res["files"]), 1)
            self.assertEqual(res["files"][0]["name"], "missing.txt")
            self.assertEqual(res["files"][0]["state"], "missing")
            self.assertIsNone(res["files"][0]["actual"])

    def test_file_outside_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            outside = p / "outside.txt"
            outside.write_text("secret outside")
            run_dir = p / "run"
            run_dir.mkdir()

            files_map = {"../outside.txt": "fake_hash"}
            (run_dir / "provenance.json").write_text(json.dumps(make_record(files=files_map)))

            res = rerun_check.check(run_dir, current=BASE_ENV)
            self.assertEqual(res["status"], "differences")
            self.assertEqual(res["counts"], {
                "files_changed": 0,
                "files_missing": 0,
                "files_other": 1,
                "environment_warnings": 0,
                "environment_info": 0,
            })
            self.assertEqual(len(res["files"]), 1)
            self.assertEqual(res["files"][0]["name"], "../outside.txt")
            self.assertEqual(res["files"][0]["state"], "rejected")
            self.assertIsNone(res["files"][0]["actual"])

    def test_environment_warning(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            (p / "provenance.json").write_text(json.dumps(make_record(files={})))

            cur = copy.deepcopy(BASE_ENV)
            cur["openmc"]["python"] = "0.99.0"

            res = rerun_check.check(p, current=cur)
            self.assertEqual(res["status"], "differences")
            self.assertEqual(res["counts"], {
                "files_changed": 0,
                "files_missing": 0,
                "files_other": 0,
                "environment_warnings": 1,
                "environment_info": 0,
            })
            self.assertEqual(len(res["environment"]), 1)
            self.assertEqual(res["environment"][0], {
                "path": "openmc.python",
                "recorded": "0.14.0",
                "current": "0.99.0",
                "level": "warning",
            })

    def test_environment_info_only(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            (p / "provenance.json").write_text(json.dumps(make_record(files={})))

            cur = copy.deepcopy(BASE_ENV)
            cur["openmc"]["executable"] = "/new/openmc"
            cur["nuclear_data"]["cross_sections"] = "/new/cross_sections.xml"

            res = rerun_check.check(p, current=cur)
            self.assertEqual(res["status"], "match")
            self.assertEqual(res["counts"], {
                "files_changed": 0,
                "files_missing": 0,
                "files_other": 0,
                "environment_warnings": 0,
                "environment_info": 2,
            })
            self.assertEqual(len(res["environment"]), 2)
            self.assertEqual(res["environment"][0], {
                "path": "nuclear_data.cross_sections",
                "recorded": BASE_ENV["nuclear_data"]["cross_sections"],
                "current": "/new/cross_sections.xml",
                "level": "info",
            })
            self.assertEqual(res["environment"][1], {
                "path": "openmc.executable",
                "recorded": BASE_ENV["openmc"]["executable"],
                "current": "/new/openmc",
                "level": "info",
            })

    def test_path_only_in_record(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            rec_env = copy.deepcopy(BASE_ENV)
            rec_env["montepy"] = "0.1.0"
            (p / "provenance.json").write_text(json.dumps(make_record(files={}, env=rec_env)))

            res = rerun_check.check(p, current=BASE_ENV)
            self.assertEqual(res["status"], "differences")
            self.assertEqual(res["counts"], {
                "files_changed": 0,
                "files_missing": 0,
                "files_other": 0,
                "environment_warnings": 1,
                "environment_info": 0,
            })
            self.assertEqual(res["environment"], [{
                "path": "montepy",
                "recorded": "0.1.0",
                "current": None,
                "level": "warning",
            }])

    def test_no_record(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            res = rerun_check.check(p, current=BASE_ENV)
            self.assertEqual(res["status"], "no-record")
            self.assertEqual(res["run_dir"], str(p))
            self.assertIsNone(res["recorded"])
            self.assertEqual(res["files"], [])
            self.assertEqual(res["environment"], [])
            self.assertEqual(res["notes"], [])
            self.assertEqual(res["counts"], {
                "files_changed": 0,
                "files_missing": 0,
                "files_other": 0,
                "environment_warnings": 0,
                "environment_info": 0,
            })

    def test_bad_records(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            prov = p / "provenance.json"

            # Invalid JSON text
            prov.write_text("{this is not valid json")
            res = rerun_check.check(p, current=BASE_ENV)
            self.assertEqual(res["status"], "bad-record")
            self.assertIsNone(res["recorded"])
            self.assertEqual(res["counts"], {
                "files_changed": 0,
                "files_missing": 0,
                "files_other": 0,
                "environment_warnings": 0,
                "environment_info": 0,
            })
            self.assertTrue(len(res["notes"]) >= 1)

            # JSON list
            prov.write_text(json.dumps([1, 2, 3]))
            res = rerun_check.check(p, current=BASE_ENV)
            self.assertEqual(res["status"], "bad-record")
            self.assertIsNone(res["recorded"])
            self.assertEqual(res["counts"], {
                "files_changed": 0,
                "files_missing": 0,
                "files_other": 0,
                "environment_warnings": 0,
                "environment_info": 0,
            })
            self.assertTrue(len(res["notes"]) >= 1)

            # Record with error key
            prov.write_text(json.dumps({"kind": "run", "error": "boom"}))
            res = rerun_check.check(p, current=BASE_ENV)
            self.assertEqual(res["status"], "bad-record")
            self.assertIsNone(res["recorded"])
            self.assertEqual(res["counts"], {
                "files_changed": 0,
                "files_missing": 0,
                "files_other": 0,
                "environment_warnings": 0,
                "environment_info": 0,
            })
            self.assertTrue(any("boom" in note for note in res["notes"]))

            # files set to a list
            prov.write_text(json.dumps({"kind": "run", "environment": BASE_ENV, "files": ["not", "a", "dict"]}))
            res = rerun_check.check(p, current=BASE_ENV)
            self.assertEqual(res["status"], "bad-record")
            self.assertIsNone(res["recorded"])
            self.assertEqual(res["counts"], {
                "files_changed": 0,
                "files_missing": 0,
                "files_other": 0,
                "environment_warnings": 0,
                "environment_info": 0,
            })
            self.assertTrue(len(res["notes"]) >= 1)

    def test_no_files_key(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            (p / "provenance.json").write_text(json.dumps({
                "kind": "export",
                "written": "2026-10-07T12:00:00+00:00",
                "environment": BASE_ENV,
            }))

            res = rerun_check.check(p, current=BASE_ENV)
            self.assertEqual(res["status"], "match")
            self.assertEqual(res["recorded"], {"kind": "export", "written": "2026-10-07T12:00:00+00:00"})
            self.assertEqual(res["files"], [])
            self.assertEqual(res["environment"], [])
            self.assertEqual(res["counts"], {
                "files_changed": 0,
                "files_missing": 0,
                "files_other": 0,
                "environment_warnings": 0,
                "environment_info": 0,
            })

    def test_recorded_exporter_path_does_not_exist(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            missing_exp = p / "nonexistent_exporter_dir"
            rec_env = copy.deepcopy(BASE_ENV)
            rec_env["exporter"] = {"path": str(missing_exp)}
            (p / "provenance.json").write_text(json.dumps(make_record(files={}, env=rec_env)))

            res = rerun_check.check(p)
            self.assertTrue(any("recorded exporter path does not exist" in n for n in res["notes"]))
            self.assertIn(res["status"], ("match", "differences"))
            self.assertIsNotNone(res["counts"])

    def test_cli(self):
        env = {**os.environ, "PYTHONPATH": str(ROOT / "studio")}
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)

            # Empty folder exits 2
            r_empty = subprocess.run(
                [sys.executable, "-m", "openmc_studio.rerun_check", str(p)],
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(r_empty.returncode, 2)
            self.assertIn("status: no-record", r_empty.stdout)

            # Real provenance record with matching file exits 0
            real_env = provenance.environment()
            (p / "file.txt").write_bytes(b"content")
            files_map = {"file.txt": provenance.sha256(p / "file.txt")}
            rec = {
                "kind": "run",
                "written": "2026-10-07T12:00:00+00:00",
                "environment": real_env,
                "files": files_map,
            }
            (p / "provenance.json").write_text(json.dumps(rec))

            r_match = subprocess.run(
                [sys.executable, "-m", "openmc_studio.rerun_check", str(p)],
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(r_match.returncode, 0)
            self.assertIn("status: match", r_match.stdout)

            # Same record with environment["python"] = "0.0.0" exits 1 and stdout has python
            rec["environment"]["python"] = "0.0.0"
            (p / "provenance.json").write_text(json.dumps(rec))

            r_diff = subprocess.run(
                [sys.executable, "-m", "openmc_studio.rerun_check", str(p)],
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(r_diff.returncode, 1)
            self.assertIn("python", r_diff.stdout)

            # --json output parses as JSON and has key "status"
            r_json = subprocess.run(
                [sys.executable, "-m", "openmc_studio.rerun_check", str(p), "--json"],
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(r_json.returncode, 1)
            data = json.loads(r_json.stdout)
            self.assertIn("status", data)
            self.assertEqual(data["status"], "differences")

    def test_bad_inputs_rule10(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)

            # 1. provenance.json is an unreadable directory -> bad-record
            (p / "provenance.json").mkdir()
            res = rerun_check.check(p, current=BASE_ENV)
            self.assertEqual(res["status"], "bad-record")
            self.assertEqual(res["counts"], {
                "files_changed": 0,
                "files_missing": 0,
                "files_other": 0,
                "environment_warnings": 0,
                "environment_info": 0,
            })
            (p / "provenance.json").rmdir()

            # 2. environment is not an object (a string or list) -> bad-record
            (p / "provenance.json").write_text(json.dumps({"kind": "run", "environment": "not-an-object"}))
            res = rerun_check.check(p, current=BASE_ENV)
            self.assertEqual(res["status"], "bad-record")
            self.assertEqual(res["counts"], {
                "files_changed": 0,
                "files_missing": 0,
                "files_other": 0,
                "environment_warnings": 0,
                "environment_info": 0,
            })

            # 3. files is not an object (an int) -> bad-record
            (p / "provenance.json").write_text(json.dumps({"kind": "run", "environment": BASE_ENV, "files": 42}))
            res = rerun_check.check(p, current=BASE_ENV)
            self.assertEqual(res["status"], "bad-record")
            self.assertEqual(res["counts"], {
                "files_changed": 0,
                "files_missing": 0,
                "files_other": 0,
                "environment_warnings": 0,
                "environment_info": 0,
            })

            # 4. absolute file name -> rejected
            (p / "provenance.json").write_text(json.dumps(make_record(files={"/etc/shadow": "fake_hash"})))
            res = rerun_check.check(p, current=BASE_ENV)
            self.assertEqual(res["status"], "differences")
            self.assertEqual(res["files"][0]["name"], "/etc/shadow")
            self.assertEqual(res["files"][0]["state"], "rejected")
            self.assertIsNone(res["files"][0]["actual"])
            self.assertEqual(res["counts"], {
                "files_changed": 0,
                "files_missing": 0,
                "files_other": 1,
                "environment_warnings": 0,
                "environment_info": 0,
            })

            # 5. a recorded file that cannot be read -> unreadable. A directory in its place fails the read for any user, root
            # included (a chmod 000 file is still readable by root, which the suite runs as in WSL).
            unreadable = p / "unreadable.txt"
            unreadable.mkdir()
            (p / "provenance.json").write_text(json.dumps(make_record(files={"unreadable.txt": "expected_hash"})))
            res = rerun_check.check(p, current=BASE_ENV)
            self.assertEqual(res["status"], "differences")
            self.assertEqual(res["files"][0]["name"], "unreadable.txt")
            self.assertEqual(res["files"][0]["state"], "unreadable")
            self.assertIsNone(res["files"][0]["actual"])
            self.assertEqual(res["counts"], {
                "files_changed": 0,
                "files_missing": 0,
                "files_other": 1,
                "environment_warnings": 0,
                "environment_info": 0,
            })

            # 6. non-path run_dir programming error propagates TypeError
            with self.assertRaises(TypeError):
                rerun_check.check(12345)

    def test_symlink_escaping_folder_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            sym = p / "sym_dir"
            sym.symlink_to(p.parent)
            files_map = {"sym_dir/outside.txt": "dummy_digest"}
            (p / "provenance.json").write_text(json.dumps(make_record(files=files_map)))

            res = rerun_check.check(p, current=BASE_ENV)
            self.assertEqual(res["status"], "differences")
            self.assertEqual(res["files"][0]["name"], "sym_dir/outside.txt")
            self.assertEqual(res["files"][0]["state"], "rejected")
            self.assertIsNone(res["files"][0]["actual"])
            self.assertEqual(res["counts"], {
                "files_changed": 0,
                "files_missing": 0,
                "files_other": 1,
                "environment_warnings": 0,
                "environment_info": 0,
            })

    def test_files_are_listed_sorted_by_name(self):
        """Added by the dispatcher (a gap in the brief: the first test data was already in order)."""
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            files_map = {}
            for name in ("c.txt", "a.txt", "b.txt"):
                (p / name).write_bytes(name.encode())
                files_map[name] = sha256_bytes(name.encode())
            (p / "provenance.json").write_text(json.dumps(make_record(files=files_map)))
            res = rerun_check.check(p, current=BASE_ENV)
            self.assertEqual([f["name"] for f in res["files"]], ["a.txt", "b.txt", "c.txt"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

