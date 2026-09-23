"""Session-scoped CAD jobs. Linux/WSL only until other process trees are tested.

One subprocess at a time, immutable input, private working directory, and atomic
job-correlated files. No pipe reads on the supervisor/cancellation path.

The contract with the worker (``openmc_studio.cad.job_worker``) is file based and
lives entirely inside the job's private ``work`` directory:

- the server writes ``source.step`` (read-only) and ``request.json``;
- the worker writes ``progress.json`` and finally ``result.json`` atomically, each
  carrying the job ID, and ``result.json`` either ``{"ok": true, ...}`` or
  ``{"ok": false, "error": ...}``;
- anything else the worker writes counts toward the job's disk budget.

A result is accepted only if it names this job, arrives before cancellation, and
fits the size limits. Nothing a client sends ever becomes a filesystem path.
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
MAX_RESULT = 4 * 1024 * 1024  # a native report lists up to 500 solids with their evidence
LOG_TAIL = 2048

# The adapter contract: what a job may ask the worker to do. Stages add modes here
# and in job_worker together; the HTTP layer only ever passes one of these names.
# needs_source: the job must carry an uploaded STEP file.
MODES = {
    "probe": {"needs_source": False},     # build a small solid and convert it end to end
    "csg-xml": {"needs_source": True},    # GEOUNED single-solid conversion to OpenMC XML
    "inspect": {"needs_source": True},    # per-solid inventory: names, validity, surfaces, bounds
    "native": {"needs_source": True},     # recognize and prove Studio primitives, solid by solid
}


def disk_usage(path):
    """Bytes under path. Files the worker renames or deletes mid-scan are skipped:
    the worker's own atomic writes (x.tmp -> x) must never fail a healthy job."""
    total = 0
    for p in Path(path).rglob("*"):
        try:
            if p.is_file():
                total += p.stat().st_size
        except FileNotFoundError:
            continue
    return total


def _tail(path, limit=LOG_TAIL):
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - limit))
            return f.read().decode("utf-8", "replace")
    except OSError:
        return ""


@dataclass
class Job:
    id: str
    name: str
    mode: str
    path: Path
    state: str = "queued"
    created: float = field(default_factory=time.time)
    ended: float | None = None
    progress: str = "queued"
    error: str | None = None
    diagnostics: str | None = None
    cancel: threading.Event = field(default_factory=threading.Event)
    result: dict | None = None

    def public(self):
        return {"id": self.id, "name": self.name, "mode": self.mode, "state": self.state,
                "created": self.created, "ended": self.ended, "progress": self.progress,
                "error": self.error, "diagnostics": self.diagnostics,
                "can_import_into_studio": False}


class CadJobs:
    def __init__(self, root, python=None, *, timeout=180, retention=3600,
                 max_pending=8, max_jobs=128, max_log=2 * 1024 * 1024,
                 max_disk=64 * 1024 * 1024, command=None, poll=0.05):
        self.root = Path(root).expanduser().resolve()
        repo = Path(__file__).resolve().parents[3]
        if self.root.is_relative_to(repo):
            raise ValueError("CAD job files must be outside the repository")
        self.python = python or os.environ.get("OPENMC_CAD_PYTHON")
        self.timeout, self.retention = timeout, retention
        self.max_pending, self.max_jobs = max_pending, max_jobs
        self.max_log, self.max_disk = max_log, max_disk
        self.poll = poll
        # command is injected only by lifecycle tests, never from HTTP requests.
        self.command = command
        self.jobs, self.pending = {}, deque()
        self.condition = threading.Condition(threading.RLock())
        self.thread = None
        self.closed = False
        self.lease = None
        self.running = None  # the job whose worker is alive, if any
        self.verified = None  # public summary of the last successful probe

    def capabilities(self):
        configured = bool(self.python and Path(self.python).is_file())
        available = sys.platform.startswith("linux") and configured and not self.closed
        verified = self.verified
        return {"available": available, "configured": configured,
                # Only a completed probe conversion counts; importable modules do not.
                "engine_verified": bool(verified), "probe": verified,
                "modes": sorted(MODES), "can_import_into_studio": False,
                "mode": "experimental-single-solid-xml",
                "platform": "linux-wsl", "max_input_bytes": MAX_INPUT,
                "timeout_seconds": self.timeout, "retention_seconds": self.retention,
                "reason": None if available else
                    "Set OPENMC_CAD_PYTHON to a tested Linux CAD interpreter; "
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

    def submit(self, data, filename, mode="csg-xml"):
        if mode not in MODES:
            raise ValueError(f"Unknown CAD job mode; expected one of {', '.join(sorted(MODES))}")
        if MODES[mode]["needs_source"]:
            if not isinstance(data, bytes) or not data or len(data) > MAX_INPUT:
                raise ValueError("Provide a nonempty STEP file no larger than 16 MiB")
            if not isinstance(filename, str) or Path(filename.replace("\\", "/")).suffix.lower() not in {".step", ".stp"}:
                raise ValueError("Only STEP/STP files are accepted")
            # A label only; no client-supplied value ever becomes a filesystem path.
            name = re.sub(r"[^\w .()-]", "_", filename.replace("\\", "/").rsplit("/", 1)[-1])[:120]
        else:
            if data or filename:
                raise ValueError(f"A '{mode}' job takes no file")
            name = mode
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
                if data:
                    source = work / "source.step"
                    source.write_bytes(data)
                    source.chmod(0o400)
                (work / "request.json").write_text(json.dumps({"id": job_id, "mode": mode}), encoding="utf-8")
                job = Job(job_id, name, mode, path)
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

    def list(self):
        with self.condition:
            return [j.public() for j in sorted(self.jobs.values(), key=lambda j: j.created)]

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

    def wait(self, job_id, timeout=None):
        """Block until the job is terminal (tests and CLI tools; HTTP never waits)."""
        deadline = None if timeout is None else time.monotonic() + timeout
        with self.condition:
            while True:
                job = self.jobs.get(job_id)
                if not job:
                    raise KeyError(job_id)
                if job.state in TERMINAL:
                    return job.public()
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    raise TimeoutError(job_id)
                self.condition.wait(timeout=remaining if remaining is not None else 1)

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
                    shutil.rmtree(path, ignore_errors=True)

    def _finish(self, job, state, error=None, result=None, diagnostics=None):
        with self.condition:
            # Cancellation wins even when it races with an already-written result.
            if job.cancel.is_set():
                state, error, result, diagnostics = "cancelled", None, None, None
            if state in {"cancelled", "timed_out"}:
                shutil.rmtree(job.path / "work", ignore_errors=True)
            job.state, job.error, job.result = state, error, result
            job.diagnostics = diagnostics
            job.progress, job.ended = state, time.time()
            if state == "succeeded" and job.mode == "probe":
                self.verified = {"job": job.id, "at": job.ended,
                                 "versions": (result or {}).get("versions"),
                                 "adapter": (result or {}).get("adapter")}
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

    def _read_result(self, job, work):
        """The worker's own verdict, if it left one that names this job; else None."""
        path = work / "result.json"
        try:
            size = path.stat().st_size
        except FileNotFoundError:
            return None
        if size > MAX_RESULT:
            raise ValueError("Oversized CAD report")
        result = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(result, dict) or result.get("id") != job.id:
            raise ValueError("Mismatched CAD result job ID")
        return result

    def _run(self, job):
        proc = None
        reader = None
        stopped = False
        work = job.path / "work"
        log = work / "worker.log"
        try:
            with self.condition:
                if job.cancel.is_set():  # cancelled between leaving the queue and starting
                    self._finish(job, "cancelled")
                    return
                job.state, job.progress = "running", "starting"
                self.running = job.id
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
                with log.open("wb") as out:
                    while chunk := proc.stdout.read(4096):
                        remaining = max(0, self.max_log - written)
                        out.write(chunk[:remaining])
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
                if overflow.is_set() or disk_usage(work) > self.max_disk:
                    failure = ("failed", "CAD output exceeded its size limit")
                    break
                progress = work / "progress.json"
                try:
                    small = progress.stat().st_size < 4096
                except FileNotFoundError:
                    small = False
                if small:
                    event = json.loads(progress.read_text(encoding="utf-8"))
                    if event.get("id") != job.id:
                        raise ValueError("Mismatched CAD progress job ID")
                    with self.condition:
                        job.progress = str(event.get("stage", "converting"))[:120]
                job.cancel.wait(self.poll)
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
                self._finish(job, *failure, diagnostics=_tail(log) or None)
                return
            if overflow.is_set() or disk_usage(work) > self.max_disk:
                raise ValueError("CAD output exceeded its size limit")
            result = self._read_result(job, work)
            if result is not None and result.get("ok") is False:
                # The worker explained its own failure; surface that, not an exit code.
                raise ValueError(str(result.get("error") or "CAD conversion failed")[:500])
            if code != 0:
                raise ValueError(f"CAD worker exited with code {code}")
            if result is None or result.get("ok") is not True:
                raise ValueError("Missing or failed CAD result")
            if result.get("mode") != job.mode:
                raise ValueError("CAD result is for a different job mode")
            if job.mode == "csg-xml":
                xml_path = work / "conversion" / "geometry.xml"
                if not xml_path.is_file() or not 0 < xml_path.stat().st_size <= MAX_XML:
                    raise ValueError("Missing or oversized CAD XML")
                result["xml_data"] = xml_path.read_text(encoding="utf-8")
            result.pop("xml", None)  # a worker-side path; never returned to clients
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
            self._finish(job, "failed", str(exc)[:500], diagnostics=_tail(log) or None)
        finally:
            if proc and not stopped:
                self._kill(proc)
            with self.condition:
                if self.running == job.id:
                    self.running = None

    def close(self):
        with self.condition:
            self.closed = True
            for job in self.jobs.values():
                if job.state not in TERMINAL:
                    job.cancel.set()
            self.condition.notify_all()
        try:
            if self.thread:
                self.thread.join(timeout=15)
                if self.thread.is_alive():
                    raise RuntimeError("CAD jobs did not shut down")
        finally:
            if self.lease:
                self.lease.close()
                self.lease = None


class DisabledCadJobs:
    """Stands in when CAD jobs can't be set up at all (for example a runs folder
    inside the checkout). CAD is optional: Studio keeps running and says why."""

    def __init__(self, reason):
        self.reason = reason

    def capabilities(self):
        return {"available": False, "configured": False, "engine_verified": False, "probe": None,
                "modes": sorted(MODES), "can_import_into_studio": False, "reason": self.reason}

    def submit(self, data, filename, mode="csg-xml"):
        raise RuntimeError(self.reason)

    def list(self):
        return []

    def get(self, job_id):
        raise KeyError(job_id)

    result = cancel = get

    def close(self):
        pass
