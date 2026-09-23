"""Session-scoped CAD jobs. Linux/WSL only until other process trees are tested.

One subprocess at a time, immutable input, private working directory, and atomic
job-correlated files. No pipe reads on the supervisor/cancellation path.
"""
from collections import deque
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid

JOB_ID = re.compile(r"^[0-9a-f]{32}$")
TERMINAL = {"succeeded", "failed", "cancelled", "timed_out"}
MAX_INPUT = 16 * 1024 * 1024
MAX_XML = 8 * 1024 * 1024


@dataclass
class Job:
    id: str
    name: str
    path: Path
    state: str = "queued"
    created: float = field(default_factory=time.time)
    ended: float | None = None
    progress: str = "queued"
    error: str | None = None
    cancel: threading.Event = field(default_factory=threading.Event)
    result: dict | None = None

    def public(self):
        return {"id": self.id, "name": self.name, "state": self.state,
                "created": self.created, "ended": self.ended, "progress": self.progress,
                "error": self.error, "can_import_into_studio": False}


class CadJobs:
    def __init__(self, root, python=None, *, timeout=180, retention=3600,
                 max_pending=8, max_jobs=128, max_log=2 * 1024 * 1024,
                 max_disk=64 * 1024 * 1024, command=None):
        self.root = Path(root).expanduser().resolve()
        repo = Path(__file__).resolve().parents[3]
        if self.root.is_relative_to(repo):
            raise ValueError("CAD job files must be outside the repository")
        self.python = python or os.environ.get("OPENMC_CAD_PYTHON")
        self.timeout, self.retention = timeout, retention
        self.max_pending, self.max_jobs = max_pending, max_jobs
        self.max_log, self.max_disk = max_log, max_disk
        # command is injected only by lifecycle tests, never from HTTP requests.
        self.command = command
        self.jobs, self.pending = {}, deque()
        self.condition = threading.Condition(threading.RLock())
        self.thread = None
        self.closed = False
        self.lease = None

    def capabilities(self):
        configured = bool(self.python and Path(self.python).is_file())
        return {"available": sys.platform.startswith("linux") and configured and not self.closed,
                "configured": configured, "engine_verified": False,
                "can_import_into_studio": False, "mode": "experimental-single-solid-xml",
                "platform": "linux-wsl", "max_input_bytes": MAX_INPUT,
                "timeout_seconds": self.timeout, "retention_seconds": self.retention,
                "reason": "Set OPENMC_CAD_PYTHON to a tested Linux CAD interpreter; "
                          "job success is conversion only, not Studio import or transport validation."}

    def _start(self):
        if self.thread:
            return
        if not self.capabilities()["available"]:
            raise RuntimeError("CAD jobs require Linux/WSL and an explicit OPENMC_CAD_PYTHON executable")
        import fcntl
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        lease = (self.root / ".lock").open("a")
        try:
            fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            lease.close()
            raise RuntimeError("Another Studio owns this CAD job directory") from None
        self.lease = lease
        self.thread = threading.Thread(target=self._loop, name="cad-jobs", daemon=True)
        self.thread.start()

    def submit(self, data, filename):
        if not isinstance(data, bytes) or not data or len(data) > MAX_INPUT:
            raise ValueError("Provide a nonempty STEP file no larger than 16 MiB")
        if not isinstance(filename, str) or Path(filename).suffix.lower() not in {".step", ".stp"}:
            raise ValueError("Only STEP/STP files are accepted")
        # A label only; no client-supplied value ever becomes a filesystem path.
        name = re.sub(r"[^\w .()-]", "_", filename.replace("\\", "/").rsplit("/", 1)[-1])[:120]
        with self.condition:
            if self.closed:
                raise RuntimeError("CAD jobs are shutting down")
            self._start()
            self._prune()
            active = sum(j.state not in TERMINAL for j in self.jobs.values())
            if active >= self.max_pending or len(self.jobs) >= self.max_jobs:
                raise RuntimeError("CAD job capacity reached; cancel a job or wait for retained jobs to expire")
            job_id = uuid.uuid4().hex
            path = self.root / job_id
            path.mkdir(mode=0o700)
            try:
                work = path / "work"
                work.mkdir()
                source = work / "source.step"
                source.write_bytes(data)
                source.chmod(0o400)
                job = Job(job_id, name, path)
                self.jobs[job_id] = job
                self.pending.append(job_id)
                self.condition.notify_all()
                return job.public()
            except Exception:
                shutil.rmtree(path)
                raise

    def get(self, job_id):
        with self.condition:
            job = self.jobs.get(job_id)
            if not job:
                raise KeyError(job_id)
            return job.public()

    def result(self, job_id):
        with self.condition:
            job = self.jobs.get(job_id)
            if not job:
                raise KeyError(job_id)
            if job.state != "succeeded":
                raise RuntimeError("CAD result is not available")
            return dict(job.result)

    def cancel(self, job_id):
        with self.condition:
            job = self.jobs.get(job_id)
            if not job:
                raise KeyError(job_id)
            if job.state not in TERMINAL:
                job.cancel.set()
                job.state = "cancelling"
                self.condition.notify_all()
            return job.public()

    def _prune(self):
        now = time.time()
        for job_id, job in list(self.jobs.items()):
            if job.ended is not None and now - job.ended >= self.retention:
                shutil.rmtree(job.path, ignore_errors=True)
                del self.jobs[job_id]
        # Crash leftovers are inaccessible to the new session and expire by age.
        for path in self.root.iterdir():
            if JOB_ID.fullmatch(path.name) and path.name not in self.jobs and path.is_dir():
                if now - path.stat().st_mtime >= self.retention:
                    shutil.rmtree(path)

    def _finish(self, job, state, error=None, result=None):
        with self.condition:
            # Cancellation wins even when it races with an already-written result.
            if job.cancel.is_set():
                state, error, result = "cancelled", None, None
            if state in {"cancelled", "timed_out"}:
                shutil.rmtree(job.path / "work", ignore_errors=True)
            job.state, job.error, job.result = state, error, result
            job.progress, job.ended = state, time.time()
            (job.path / "status.json").write_text(json.dumps(job.public()), encoding="utf-8")
            self.condition.notify_all()

    def _loop(self):
        while True:
            with self.condition:
                self._prune()
                if not self.pending:
                    if self.closed:
                        return
                    self.condition.wait(timeout=1)
                    continue
                job = self.jobs[self.pending.popleft()]
            if job.cancel.is_set():
                self._finish(job, "cancelled")
            else:
                self._run(job)

    @staticmethod
    def _kill(proc):
        # The worker owns a new session. Kill its entire group before closing any
        # stdout reader, including descendants that outlive the group leader.
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait(timeout=5)

    def _run(self, job):
        proc = None
        reader = None
        stopped = False
        work = job.path / "work"
        try:
            with self.condition:
                job.state, job.progress = "running", "starting"
            env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONDONTWRITEBYTECODE="1")
            env["PYTHONPATH"] = str(Path(__file__).resolve().parents[2])
            argv = self.command(job) if self.command else [
                self.python, "-m", "openmc_studio.cad_worker", "--job", job.id]
            # A bounded drain thread prevents both pipe blockage and unbounded logs.
            proc = subprocess.Popen(argv, cwd=work, env=env, stdin=subprocess.DEVNULL,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    start_new_session=True)
            overflow = threading.Event()
            def drain():
                written = 0
                with (work / "worker.log").open("wb") as log:
                    while chunk := proc.stdout.read(4096):
                        remaining = max(0, self.max_log - written)
                        log.write(chunk[:remaining])
                        written += len(chunk)
                        if written > self.max_log:
                            overflow.set()
            reader = threading.Thread(target=drain, daemon=True)
            reader.start()
            deadline = time.monotonic() + self.timeout
            failure = None
            while proc.poll() is None:
                if job.cancel.is_set():
                    break
                if time.monotonic() >= deadline:
                    failure = ("timed_out", "CAD conversion exceeded its time limit")
                    break
                size = sum(p.stat().st_size for p in work.rglob("*") if p.is_file())
                if overflow.is_set() or size > self.max_disk:
                    failure = ("failed", "CAD output exceeded its size limit")
                    break
                progress = work / "progress.json"
                if progress.exists() and progress.stat().st_size < 4096:
                    event = json.loads(progress.read_text())
                    if event.get("id") != job.id:
                        raise ValueError("Mismatched CAD progress job ID")
                    with self.condition:
                        job.progress = str(event.get("stage", "converting"))[:120]
                job.cancel.wait(0.05)
            code = proc.poll()
            self._kill(proc)
            stopped = True
            reader.join(timeout=5)
            if reader.is_alive():
                raise RuntimeError("CAD output reader did not stop")
            proc.stdout.close()
            if job.cancel.is_set():
                self._finish(job, "cancelled")
                return
            if failure:
                self._finish(job, *failure)
                return
            if overflow.is_set() or sum(p.stat().st_size for p in work.rglob("*") if p.is_file()) > self.max_disk:
                raise ValueError("CAD output exceeded its size limit")
            if code != 0:
                raise ValueError(f"CAD worker exited with code {code}; inspect worker.log")
            result_path = work / "result.json"
            if result_path.stat().st_size > 128 * 1024:
                raise ValueError("Oversized CAD report")
            result = json.loads(result_path.read_text())
            if result.get("id") != job.id or result.get("ok") is not True:
                raise ValueError("Missing, failed or mismatched CAD result")
            xml_path = work / "conversion" / "geometry.xml"
            if not 0 < xml_path.stat().st_size <= MAX_XML:
                raise ValueError("Missing or oversized CAD XML")
            result.pop("xml", None)
            result["xml_data"] = xml_path.read_text(encoding="utf-8")
            result["can_import_into_studio"] = False
            result["validation"] = "engine-conversion-only"
            self._finish(job, "succeeded", result=result)
        except Exception as exc:
            if proc and not stopped:
                self._kill(proc)
                stopped = True
            if reader:
                reader.join(timeout=5)
            if proc and proc.stdout:
                proc.stdout.close()
            self._finish(job, "failed", str(exc)[:500])
        finally:
            if proc and not stopped:
                self._kill(proc)

    def close(self):
        with self.condition:
            self.closed = True
            for job in self.jobs.values():
                if job.state not in TERMINAL:
                    job.cancel.set()
            self.condition.notify_all()
        if self.thread:
            self.thread.join(timeout=15)
            if self.thread.is_alive():
                raise RuntimeError("CAD jobs did not shut down")
        if self.lease:
            self.lease.close()
            self.lease = None
