"""CAD stage 1 gate: job lifecycle without the CAD engine.

Covers the plan's stage-1 list - concurrent requests, crash, timeout,
cancellation, stale replies, malformed inputs and cleanup - using a stand-in
worker (test/cad_fake_worker.py). The real engine is exercised separately by
test/test_cad_jobs_engine.py.

Linux/WSL only: the job manager relies on process groups and flock.
Run: python test/test_cad_jobs.py
"""
import os
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "studio"))
from openmc_studio.cad import jobs as jobsmod  # noqa: E402
from openmc_studio.cad.jobs import CadJobs, Job, disk_usage  # noqa: E402

FAKE = Path(__file__).resolve().parent / "cad_fake_worker.py"
STEP = b"ISO-10303-21;\nHEADER;\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;\n"


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    # A zombie still answers kill(0); read its state to tell.
    try:
        return Path(f"/proc/{pid}/stat").read_text().split()[2] != "Z"
    except OSError:
        return False


@unittest.skipUnless(sys.platform.startswith("linux"), "CAD jobs are Linux/WSL only; run this under WSL")
class CadJobLifecycle(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cad-jobs-test-"))
        self.side = self.tmp / "side"
        self.side.mkdir()
        self.behaviour = {}  # job id -> behaviour; default "ok"
        self.managers = []

    def tearDown(self):
        for m in self.managers:
            try:
                m.close()
            except RuntimeError:
                pass
        shutil.rmtree(self.tmp, ignore_errors=True)

    def manager(self, name="jobs", default="ok", **kw):
        def command(job):
            return [sys.executable, str(FAKE), self.behaviour.get(job.id, default), str(self.side)]
        m = CadJobs(self.tmp / name, python=sys.executable, command=command, **kw)
        self.managers.append(m)
        return m

    def run_job(self, m, behaviour, mode="csg-xml", timeout=30):
        return m.wait(self.submit(m, behaviour, mode)["id"], timeout=timeout)

    def submit(self, m, behaviour, mode="csg-xml"):
        # Pause the queue while we attach a behaviour, so the worker can't start first.
        with m.condition:
            job = m.submit(None if mode == "probe" else STEP, None if mode == "probe" else "part.step", mode)
            self.behaviour[job["id"]] = behaviour
        return job

    def children(self):
        return {p.name[6:-4]: int(p.read_text()) for p in self.side.glob("child-*.pid")}

    # ── success ──
    def test_success_returns_xml_and_never_a_worker_path(self):
        m = self.manager()
        done = self.run_job(m, "ok")
        self.assertEqual(done["state"], "succeeded", done)
        result = m.result(done["id"])
        self.assertIn("<geometry>", result["xml_data"])
        self.assertNotIn("xml", result, "worker-side paths must not reach clients")
        self.assertFalse(result["can_import_into_studio"])
        self.assertEqual(result["validation"], "engine-conversion-only")

    # ── concurrent requests ──
    def test_concurrent_submissions_run_one_at_a_time(self):
        m = self.manager(default="slow-ok")
        ids, errors = [], []

        def post():
            try:
                ids.append(m.submit(STEP, "part.step")["id"])
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)
        threads = [threading.Thread(target=post) for _ in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        self.assertEqual(len(set(ids)), 6, "every request gets its own job")
        for i in ids:
            self.assertEqual(m.wait(i, timeout=30)["state"], "succeeded")
        # start/end markers from each worker: intervals must never overlap.
        events = [line.split() for line in (self.side / "events.log").read_text().splitlines()]
        spans = {}
        for kind, job, t in events:
            spans.setdefault(job, {})[kind] = float(t)
        ordered = sorted(spans.values(), key=lambda s: s["start"])
        for a, b in zip(ordered, ordered[1:]):
            self.assertLessEqual(a["end"], b["start"], "two CAD workers ran at the same time")

    def test_capacity_limit_is_explicit(self):
        m = self.manager(default="hang", max_pending=2)
        a = self.submit(m, "hang")
        b = self.submit(m, "hang")
        with self.assertRaisesRegex(RuntimeError, "capacity"):
            m.submit(STEP, "third.step")
        for j in (a, b):
            m.cancel(j["id"])

    # ── crash ──
    def test_crash_fails_the_job_and_not_the_next_one(self):
        m = self.manager()
        crashed = self.run_job(m, "segv")
        self.assertEqual(crashed["state"], "failed")
        self.assertIn("code -11", crashed["error"])
        self.assertEqual(self.run_job(m, "ok")["state"], "succeeded", "a crash must not poison later jobs")

    def test_exit_without_result_reports_the_log(self):
        m = self.manager()
        done = self.run_job(m, "exit3")
        self.assertEqual(done["state"], "failed")
        self.assertIn("code 3", done["error"])
        self.assertIn("something went wrong", done["diagnostics"], "the log tail must reach the client")

    def test_worker_reported_failure_is_surfaced_verbatim(self):
        m = self.manager()
        done = self.run_job(m, "self-fail")
        self.assertEqual(done["state"], "failed")
        self.assertIn("exactly one valid closed solid", done["error"])
        self.assertIn("GEOUNED: the solid has no faces", done["diagnostics"])

    # ── timeout ──
    def test_timeout_kills_the_whole_process_group(self):
        m = self.manager(timeout=1)
        done = self.run_job(m, "hang")
        self.assertEqual(done["state"], "timed_out")
        (pid,) = self.children().values()
        time.sleep(0.2)
        self.assertFalse(alive(pid), "a descendant of a timed-out worker survived")
        self.assertFalse((self.tmp / "jobs" / done["id"] / "work").exists(), "timed-out scratch must be deleted")

    # ── cancellation ──
    def test_cancel_running_job_kills_descendants_and_deletes_scratch(self):
        m = self.manager()
        job = self.submit(m, "hang")
        deadline = time.time() + 20
        while m.get(job["id"])["progress"] != "decomposing solids" and time.time() < deadline:
            time.sleep(0.02)
        self.assertEqual(m.get(job["id"])["progress"], "decomposing solids", "worker progress must reach the client")
        m.cancel(job["id"])
        done = m.wait(job["id"], timeout=20)
        self.assertEqual(done["state"], "cancelled")
        time.sleep(0.2)
        self.assertFalse(alive(self.children()[job["id"]]))
        self.assertFalse((self.tmp / "jobs" / job["id"] / "work").exists())
        with self.assertRaises(RuntimeError):
            m.result(job["id"])

    def test_cancel_queued_job_never_starts(self):
        m = self.manager()
        first = self.submit(m, "hang")
        second = self.submit(m, "ok")
        self.assertEqual(m.cancel(second["id"])["state"], "cancelling")
        m.cancel(first["id"])
        self.assertEqual(m.wait(second["id"], timeout=20)["state"], "cancelled")
        started = (self.side / "events.log").read_text() if (self.side / "events.log").exists() else ""
        self.assertNotIn(second["id"], started, "a cancelled queued job must never launch a worker")

    def test_cancel_wins_over_a_result_already_written(self):
        m = self.manager()
        job = self.submit(m, "result-then-wait")
        deadline = time.time() + 20
        while "result-written" not in ((self.side / "events.log").read_text()
                                       if (self.side / "events.log").exists() else "") and time.time() < deadline:
            time.sleep(0.05)
        m.cancel(job["id"])
        done = m.wait(job["id"], timeout=20)
        self.assertEqual(done["state"], "cancelled", "a late result must not beat cancellation")

    def test_job_cancelled_just_before_start_stays_cancelled(self):
        m = self.manager()
        m._start()
        path = self.tmp / "jobs" / ("a" * 32)
        (path / "work").mkdir(parents=True)
        job = Job("a" * 32, "x", "csg-xml", path)
        job.cancel.set()
        job.state = "cancelling"
        m.jobs[job.id] = job
        m._run(job)
        self.assertEqual(job.state, "cancelled", "a cancelled job must not flip back to running")
        self.assertEqual(self.children(), {}, "no worker may be launched")

    # ── stale / mismatched replies ──
    def test_result_for_another_job_is_rejected(self):
        done = self.run_job(self.manager(), "stale-result")
        self.assertEqual(done["state"], "failed")
        self.assertIn("Mismatched CAD result", done["error"])

    def test_progress_for_another_job_is_rejected(self):
        done = self.run_job(self.manager(), "stale-progress")
        self.assertEqual(done["state"], "failed")
        self.assertIn("Mismatched CAD progress", done["error"])

    def test_result_for_another_mode_is_rejected(self):
        done = self.run_job(self.manager(), "wrong-mode")
        self.assertEqual(done["state"], "failed")
        self.assertIn("different job mode", done["error"])

    def test_success_without_xml_is_a_failure(self):
        done = self.run_job(self.manager(), "missing-xml")
        self.assertEqual(done["state"], "failed")
        self.assertIn("Missing or oversized CAD XML", done["error"])

    # ── bounded output ──
    def test_log_flood_is_bounded(self):
        m = self.manager(max_log=64 * 1024)
        done = self.run_job(m, "log-flood")
        self.assertEqual(done["state"], "failed")
        self.assertIn("size limit", done["error"])
        self.assertLessEqual(len(done["diagnostics"] or ""), jobsmod.LOG_TAIL)

    def test_disk_flood_is_bounded(self):
        done = self.run_job(self.manager(max_disk=1024 * 1024), "disk-flood")
        self.assertEqual(done["state"], "failed")
        self.assertIn("size limit", done["error"])

    def test_oversized_report_is_rejected(self):
        done = self.run_job(self.manager(), "big-result")
        self.assertEqual(done["state"], "failed")
        self.assertIn("Oversized CAD report", done["error"])

    def test_atomic_rewrites_never_fail_a_healthy_job(self):
        # The size scan used to stat files the worker had just renamed away.
        m = self.manager(poll=0.001)
        done = self.run_job(m, "churn")
        self.assertEqual(done["state"], "succeeded", done)
        self.assertGreater(m.result(done["id"])["rewrites"], 100)

    def test_disk_usage_tolerates_vanishing_files(self):
        d = self.tmp / "churn"
        d.mkdir()
        stop = threading.Event()

        def churn():
            while not stop.is_set():
                t = d / "p.tmp"
                t.write_bytes(b"x")
                t.replace(d / "p.json")
        th = threading.Thread(target=churn)
        th.start()
        try:
            for _ in range(3000):
                disk_usage(d)
        finally:
            stop.set()
            th.join()

    # ── malformed inputs ──
    def test_malformed_submissions_are_rejected_before_any_file_is_written(self):
        m = self.manager()
        cases = [
            (b"", "a.step", "csg-xml", "nonempty"),
            (b"x" * (jobsmod.MAX_INPUT + 1), "a.step", "csg-xml", "16 MiB"),
            (STEP, "a.iges", "csg-xml", "STEP/STP"),
            (STEP, "a.step.exe", "csg-xml", "STEP/STP"),
            (STEP, None, "csg-xml", "STEP/STP"),
            (STEP, "a.step", "rm -rf", "Unknown CAD job mode"),
            (STEP, "a.step", "probe", "takes no file"),
            ("text", "a.step", "csg-xml", "nonempty"),
        ]
        for data, name, mode, message in cases:
            with self.subTest(name=name, mode=mode):
                with self.assertRaisesRegex(ValueError, message):
                    m.submit(data, name, mode)
        root = self.tmp / "jobs"
        self.assertEqual([p.name for p in root.iterdir() if p.name != ".lock"] if root.exists() else [], [])

    def test_client_filename_is_a_label_never_a_path(self):
        m = self.manager()
        job = self.submit(m, "ok")
        for name in ("../../../etc/passwd.step", "..\\..\\evil.step", "/abs/x.step", "a\nb.step"):
            j = m.submit(STEP, name)
            self.assertNotIn("/", j["name"])
            self.assertNotIn("\\", j["name"])
            self.assertNotIn("\n", j["name"])
        m.wait(job["id"], timeout=30)
        for p in self.tmp.rglob("*"):
            self.assertTrue(p.resolve().is_relative_to(self.tmp.resolve()))
        self.assertFalse((self.tmp / "etc").exists())
        self.assertFalse(Path("/abs").exists())

    # ── cleanup and ownership ──
    def test_root_inside_the_repository_is_refused(self):
        with self.assertRaisesRegex(ValueError, "outside the repository"):
            CadJobs(ROOT / "cad-jobs", python=sys.executable)

    def test_second_manager_on_the_same_root_is_refused(self):
        a = self.manager()
        a._start()
        b = self.manager()
        with self.assertRaisesRegex(RuntimeError, "Another Studio owns"):
            b.submit(STEP, "x.step")

    def test_retention_prunes_finished_jobs_and_crash_leftovers(self):
        m = self.manager(retention=0.3)
        done = self.run_job(m, "ok")
        leftover = self.tmp / "jobs" / ("b" * 32)
        leftover.mkdir()
        os.utime(leftover, (time.time() - 10, time.time() - 10))
        unrelated = self.tmp / "jobs" / "keep-me"
        unrelated.mkdir()
        time.sleep(0.5)
        with m.condition:
            m._prune()
        self.assertFalse((self.tmp / "jobs" / done["id"]).exists())
        self.assertFalse(leftover.exists())
        self.assertTrue(unrelated.exists(), "prune must only remove job-shaped directories")
        with self.assertRaises(KeyError):
            m.get(done["id"])

    def test_close_cancels_running_work_and_releases_the_directory(self):
        m = self.manager()
        job = self.submit(m, "hang")
        deadline = time.time() + 20
        while not self.children() and time.time() < deadline:
            time.sleep(0.05)
        m.close()
        self.assertEqual(m.get(job["id"])["state"], "cancelled")
        time.sleep(0.2)
        self.assertFalse(alive(self.children()[job["id"]]))
        with self.assertRaisesRegex(RuntimeError, "shutting down"):
            m.submit(STEP, "x.step")
        # The lock is released: a new session may own the directory.
        again = self.manager()
        again._start()

    # ── capabilities ──
    def test_engine_is_verified_only_by_a_successful_probe(self):
        m = self.manager()
        self.assertFalse(m.capabilities()["engine_verified"])
        self.assertEqual(self.run_job(m, "self-fail", mode="probe")["state"], "failed")
        self.assertFalse(m.capabilities()["engine_verified"], "a failed probe must not verify the engine")
        self.assertEqual(self.run_job(m, "ok", mode="probe")["state"], "succeeded")
        caps = m.capabilities()
        self.assertTrue(caps["engine_verified"])
        self.assertEqual(caps["probe"]["versions"], {"fake": "1"})

    def test_unconfigured_engine_is_unavailable_and_says_why(self):
        m = CadJobs(self.tmp / "none", python=str(self.tmp / "no-such-python"))
        self.managers.append(m)
        caps = m.capabilities()
        self.assertFalse(caps["available"])
        self.assertIn("OPENMC_CAD_PYTHON", caps["reason"])
        with self.assertRaisesRegex(RuntimeError, "OPENMC_CAD_PYTHON"):
            m.submit(STEP, "x.step")


if __name__ == "__main__":
    unittest.main(verbosity=2)
