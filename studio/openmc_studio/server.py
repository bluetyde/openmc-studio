"""HTTP server for OpenMC Studio, standard library only.

Security model: the server runs the Python that the page sends it, so it only
listens on 127.0.0.1, checks the Host header (blocks DNS rebinding), rejects
cross-origin POSTs, and requires a per-launch token on every /api call except
/api/ping.
"""
import json
import os
import queue
import re
import secrets
import signal
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import __version__

STATIC = Path(__file__).parent / "static"
MAX_BODY = 25 * 1024 * 1024
RUN_ID = re.compile(r"^[0-9]{8}-[0-9]{6}-[a-z0-9-]{1,40}$")


class Run:
    def __init__(self, rid, path, name):
        self.id, self.path, self.name = rid, path, name
        self.lines = []
        self.status = "running"
        self.returncode = None
        self.started = time.time()
        self.ended = None
        self.proc = None
        self.stop_requested = False
        self.cond = threading.Condition()

    def meta(self):
        return {"id": self.id, "name": self.name, "status": self.status, "returncode": self.returncode,
                "started": self.started, "ended": self.ended}

    def add(self, text):
        with self.cond:
            self.lines.append(text)
            self.cond.notify_all()

    def finish(self, code):
        with self.cond:
            self.returncode = code
            self.status = "stopped" if self.stop_requested else ("done" if code == 0 else "failed")
            self.ended = time.time()
            self.cond.notify_all()
        (self.path / "meta.json").write_text(json.dumps(self.meta(), indent=2))


class Studio:
    def __init__(self, runs_dir, token, port):
        self.root = Path(runs_dir).expanduser()
        self.root.mkdir(parents=True, exist_ok=True)
        self.token, self.port = token, port
        self.runs = {}
        self.active = None
        self.lock = threading.Lock()
        self.mcnp = McnpWorker(self.root)
        self.cad = CadWorker(self.root)
        from .cad.jobs import CadJobs
        self.cad_jobs = CadJobs(self.root / "cad-jobs")

    # ── runs ──
    def start(self, script, project, name):
        with self.lock:
            if self.active and self.active.status == "running":
                raise RuntimeError("A run is already going. Stop it or wait for it to finish.")
            slug = re.sub(r"[^a-z0-9]+", "-", (name or "model").lower()).strip("-")[:40] or "model"
            rid = time.strftime("%Y%m%d-%H%M%S") + "-" + slug
            path = self.root / rid
            path.mkdir(parents=True, exist_ok=False)
            (path / "model.py").write_text(script, encoding="utf-8")
            (path / "project.json").write_text(json.dumps(project, indent=2), encoding="utf-8")
            run = Run(rid, path, name or slug)
            (path / "meta.json").write_text(json.dumps(run.meta(), indent=2))
            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"
            run.proc = subprocess.Popen([sys.executable, "model.py"], cwd=path, env=env, stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT, text=True, bufsize=1, start_new_session=True)
            self.runs[rid] = run
            self.active = run
        threading.Thread(target=self._pump, args=(run,), daemon=True).start()
        return run

    def _pump(self, run):
        with open(run.path / "run.log", "w", encoding="utf-8") as log:
            for line in run.proc.stdout:
                line = line.rstrip("\n")
                log.write(line + "\n")
                log.flush()
                run.add(line)
        run.finish(run.proc.wait())

    def export_mcnp(self, script, project, name):
        """Export button: validated deck into a new ~/OpenMC-runs/mcnp-exports/<time>-<name>/ folder."""
        slug = re.sub(r"[^a-z0-9]+", "-", (name or "model").lower()).strip("-")[:40] or "model"
        folder = self.root / "mcnp-exports" / (time.strftime("%Y%m%d-%H%M%S") + "-" + slug)
        folder.mkdir(parents=True, exist_ok=False)
        (folder / "project.json").write_text(json.dumps(project, indent=2), encoding="utf-8")
        report = self.mcnp.run(script, slug, folder, seq=None)
        report.update(folder=str(folder), name=slug)
        return report

    def mcnp_live(self, script, name, seq, client=""):
        """Live model.mcnp tab: same worker, one reused folder; stale requests are skipped."""
        slug = re.sub(r"[^a-z0-9]+", "-", (name or "model").lower()).strip("-")[:40] or "model"
        report = self.mcnp.run(script, slug, self.root / "mcnp-live", seq=seq, client=client)
        report.update(name=slug)
        return report

    def cad_status(self):
        return self.cad.get_status()

    def cad_progress(self):
        return self.cad.get_progress()

    def cad_to_csg(self, cad_bytes, filename, options=None):
        from .cad_worker import IMPORT_ERROR
        return {"ok": False, "error": IMPORT_ERROR}

    def csg_to_cad(self, project, units="mm", options=None):
        import tempfile
        work_dir = self.root / "_cad_work"
        work_dir.mkdir(parents=True, exist_ok=True)
        name = re.sub(r"[^\w-]+", "_", str((project.get("settings") or {}).get("name") or "model"))[:80]
        opts = dict(options or {})
        opts["units"] = units
        with tempfile.TemporaryDirectory(prefix="export_", dir=work_dir) as temp:
            out_path = Path(temp) / "model.step"
            res = self.cad.csg_to_cad(project, out_path, opts)
            if res and res.get("ok") and out_path.exists():
                data = out_path.read_text(encoding="utf-8")
                return {"ok": True, "step_data": data, "filename": f"{name}.step",
                        "size": out_path.stat().st_size, "units": "mm"}
            return res

    def stop(self, rid):
        run = self.runs.get(rid)
        if not run or run.status != "running":
            return False
        run.stop_requested = True
        try:
            os.killpg(run.proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        return True

    def list_runs(self):
        out = []
        for d in sorted(self.root.iterdir(), reverse=True):
            if not (d.is_dir() and RUN_ID.match(d.name)):
                continue
            if d.name in self.runs:
                out.append(self.runs[d.name].meta())
                continue
            try:
                meta = json.loads((d / "meta.json").read_text())
                if meta.get("status") == "running":  # server stopped mid-run
                    meta["status"] = "interrupted"
                out.append(meta)
            except (OSError, ValueError):
                continue
        return out[:200]

    def run_path(self, rid):
        if not RUN_ID.match(rid or ""):
            return None
        p = self.root / rid
        return p if p.is_dir() else None


class McnpWorker:
    """One long-running `python -m openmc_studio.mcnp_worker` process (MCNPy's Java bridge stays up).

    Jobs run one at a time. Live-tab requests carry a sequence number; a request that is
    still waiting when a newer one arrives returns {"superseded": true} without running.
    """

    def __init__(self, runs_root):
        self.runs_root = Path(runs_root)
        self.proc = None
        self.results = None
        self.lock = threading.Lock()
        self.latest = {}  # page-load id -> newest sequence number seen (numbers restart on reload)
        self.job = 0
        self.progress = None

    def _remembered_path_file(self):
        return self.runs_root / "mcnp_project_path.txt"

    def _candidates(self):
        """Places to look for the openmc-mcnp-project repo, in order. Never hardcodes
        a username or a specific machine's layout -- Path.home() resolves per-user
        on macOS, Linux and Windows alike."""
        home = Path.home()
        yield home / "openmc-mcnp-project"
        for base in ("Developer", "Projects", "Documents", "code", "git", "repos"):
            yield home / base / "openmc-mcnp-project"

    def _project(self):
        """Explicit override, then a path remembered from a previous successful
        start (works across users/machines without re-exporting anything), then
        a short list of conventional locations."""
        env = os.environ.get("OPENMC_MCNP_PROJECT")
        if env:
            return Path(env).expanduser()
        remembered = self._remembered_path_file()
        if remembered.exists():
            p = Path(remembered.read_text().strip())
            if (p / "src" / "export_mcnp.py").exists():
                return p
        for c in self._candidates():
            if (c / "src" / "export_mcnp.py").exists():
                return c
        return next(self._candidates())  # default guess, just so callers have a path to report

    def _remember(self, project):
        try:
            self.runs_root.mkdir(parents=True, exist_ok=True)
            self._remembered_path_file().write_text(str(project), encoding="utf-8")
        except OSError:
            pass  # remembering is a convenience, not required for this run to work

    def _reader(self, proc, results):
        for line in proc.stdout:
            if line.startswith("@@RESULT "):
                try:
                    self.progress = None
                    results.put(json.loads(line[len("@@RESULT "):]))
                except ValueError:
                    pass
            elif line.startswith("@@PROGRESS "):
                try:
                    self.progress = json.loads(line[len("@@PROGRESS "):])
                except ValueError:
                    pass
        results.put(None)  # process ended

    def _start(self):
        project = self._project()
        if not (project / "src" / "export_mcnp.py").exists():
            checked = "\n  ".join(str(c) for c in self._candidates())
            return (f"Can't find openmc-mcnp-project. Checked:\n  {checked}\n"
                    f"Set OPENMC_MCNP_PROJECT to its folder -- Studio will remember that path "
                    f"(in {self._remembered_path_file()}) so you only need to set it once.")
        self._remember(project)
        env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONDONTWRITEBYTECODE="1")
        log = open(self.runs_root / "mcnp-worker.log", "a", encoding="utf-8")
        self.proc = subprocess.Popen([sys.executable, "-W", "ignore", "-m", "openmc_studio.mcnp_worker", str(project)],
                                     cwd=str(Path(__file__).resolve().parent.parent), env=env, text=True, bufsize=1,
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log, start_new_session=True)
        self.results = queue.Queue()
        threading.Thread(target=self._reader, args=(self.proc, self.results), daemon=True).start()
        try:
            ready = self.results.get(timeout=180)
        except queue.Empty:
            ready = None
        if not ready or not ready.get("ready"):
            self.stop()
            return (ready or {}).get("error") or "The MCNP worker didn't start (see mcnp-worker.log in the runs folder)."
        return None

    def get_progress(self):
        return self.progress

    def stop(self):
        self.progress = None
        if self.proc and self.proc.poll() is None:
            try:
                os.killpg(self.proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        self.proc = None

    def run(self, script, name, folder, seq, client=""):
        if seq is not None:
            if len(self.latest) > 50:
                self.latest.clear()
            self.latest[client] = max(self.latest.get(client, 0), seq)
        with self.lock:
            if seq is not None and seq < self.latest.get(client, 0):
                return {"superseded": True, "seq": seq}
            if self.proc is None or self.proc.poll() is not None:
                err = self._start()
                if err:
                    return {"ok": False, "error": err, "seq": seq}
            folder = Path(folder)
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "model.py").write_text(script, encoding="utf-8")
            self.job += 1
            self.progress = {"id": self.job, "step": 0, "total": 8, "stage": "start", "text": "Starting...", "elapsed": 0.0}
            job = {"id": self.job, "folder": str(folder), "name": name, "samples": 20000}
            try:
                self.proc.stdin.write(json.dumps(job) + "\n")
                self.proc.stdin.flush()
                result = self.results.get(timeout=1800)
            except (BrokenPipeError, OSError, queue.Empty):
                result = None
            self.progress = None
            if not result or result.get("id") != job["id"]:
                self.stop()
                return {"ok": False, "error": "The MCNP worker stopped or timed out; it will restart on the next request.", "seq": seq}
            result["seq"] = seq
            return result


class CadWorker:
    """Worker process for CAD import (STEP/IGES to CSG) and export (CSG to STEP)."""

    def __init__(self, runs_root):
        self.runs_root = Path(runs_root)
        self.proc = None
        self.results = None
        self.lock = threading.Lock()
        self.job = 0
        self.progress = None
        self.env_status = None

    def _reader(self, proc, results):
        for line in proc.stdout:
            if line.startswith("@@RESULT "):
                try:
                    self.progress = None
                    results.put(json.loads(line[len("@@RESULT "):]))
                except ValueError:
                    pass
            elif line.startswith("@@PROGRESS "):
                try:
                    self.progress = json.loads(line[len("@@PROGRESS "):])
                except ValueError:
                    pass
        results.put(None)

    def _start(self):
        if self.proc and self.proc.poll() is None:
            return None
        env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONDONTWRITEBYTECODE="1")
        self.runs_root.mkdir(parents=True, exist_ok=True)
        self.log_file = open(self.runs_root / "cad-worker.log", "a", encoding="utf-8")
        cad_py = os.environ.get("OPENMC_CAD_PYTHON", sys.executable)
        self.proc = subprocess.Popen(
            [cad_py, "-W", "ignore", "-m", "openmc_studio.cad_worker"],
            cwd=str(Path(__file__).resolve().parent.parent),
            env=env, text=True, bufsize=1,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.log_file,
            start_new_session=True
        )
        self.results = queue.Queue()
        self.reader_thread = threading.Thread(target=self._reader, args=(self.proc, self.results), daemon=True)
        self.reader_thread.start()
        try:
            ready = self.results.get(timeout=30)
            if ready and ready.get("ready"):
                self.env_status = ready.get("env")
                return None
        except queue.Empty:
            ready = None
        self.stop()
        return (ready or {}).get("error") or "The CAD worker didn't start (see cad-worker.log in the runs folder)."

    def get_progress(self):
        return self.progress

    def get_status(self):
        with self.lock:
            if self.env_status:
                return {"ready": True, "active": True, "env": self.env_status}
            err = self._start()
            if err:
                return {"ready": False, "active": False, "error": err}
            return {"ready": True, "active": True, "env": self.env_status}

    def cad_to_csg(self, file_path, options=None):
        with self.lock:
            err = self._start()
            if err:
                return {"ok": False, "error": err}
            self.job += 1
            req = {"cmd": "cad_to_csg", "id": self.job, "file_path": str(file_path), "options": options or {}}
            try:
                self.proc.stdin.write(json.dumps(req) + "\n")
                self.proc.stdin.flush()
                res = self.results.get(timeout=300)
            except (BrokenPipeError, OSError, queue.Empty) as e:
                res = {"id": req["id"], "ok": False, "error": f"Worker communication failure: {e}"}
                self.stop()
            if res and res.get("id") != req["id"]:
                self.stop()
                return {"ok": False, "error": "Mismatched CAD worker response"}
            self.progress = None
            return res or {"ok": False, "error": "No response from CAD worker"}

    def csg_to_cad(self, project, out_path, options=None):
        with self.lock:
            err = self._start()
            if err:
                return {"ok": False, "error": err}
            self.job += 1
            req = {"cmd": "csg_to_cad", "id": self.job, "project": project, "out_path": str(out_path), "options": options or {}}
            try:
                self.proc.stdin.write(json.dumps(req) + "\n")
                self.proc.stdin.flush()
                res = self.results.get(timeout=300)
            except (BrokenPipeError, OSError, queue.Empty) as e:
                res = {"id": req["id"], "ok": False, "error": f"Worker communication failure: {e}"}
                self.stop()
            if res and res.get("id") != req["id"]:
                self.stop()
                return {"ok": False, "error": "Mismatched CAD worker response"}
            self.progress = None
            return res or {"ok": False, "error": "No response from CAD worker"}

    def stop(self):
        self.progress = None
        self.env_status = None
        if self.proc:
            proc = self.proc
            try:
                if sys.platform == "win32":
                    proc.kill()
                else:
                    os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait(timeout=5)
            if getattr(self, "reader_thread", None):
                self.reader_thread.join(timeout=5)
            for pipe in (proc.stdin, proc.stdout):
                if pipe:
                    pipe.close()
            self.proc = None
        if getattr(self, "log_file", None):
            try:
                self.log_file.close()
            except OSError:
                pass
            self.log_file = None


class Handler(BaseHTTPRequestHandler):
    server_version = "OpenMCStudio/" + __version__
    studio = None  # set in serve()

    def log_message(self, fmt, *args):  # keep the console for OpenMC output
        pass

    # ── helpers ──
    def _send(self, code, body, ctype="application/json; charset=utf-8", extra=None):
        data = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _error(self, code, message):
        self._send(code, {"error": message})

    def _host_ok(self):
        host = (self.headers.get("Host") or "").lower()
        return host in {f"127.0.0.1:{self.studio.port}", f"localhost:{self.studio.port}"}

    def _origin_ok(self):
        origin = self.headers.get("Origin")
        return origin is None or origin in {f"http://127.0.0.1:{self.studio.port}", f"http://localhost:{self.studio.port}"}

    def _token_ok(self, query):
        given = self.headers.get("X-Studio-Token") or (query.get("token") or [""])[0]
        return secrets.compare_digest(given.encode(), self.studio.token.encode())

    def _json_body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n < 0 or n > MAX_BODY:
            raise ValueError("request too large")
        body = json.loads(self.rfile.read(n) or b"{}")
        if not isinstance(body, dict):
            raise ValueError("request must be a JSON object")
        return body

    # ── routes ──
    def do_GET(self):
        if not self._host_ok():
            return self._error(403, "Open Studio at http://127.0.0.1 or http://localhost.")
        url = urlparse(self.path)
        q = parse_qs(url.query)
        path = url.path
        if path in ("/", "/index.html"):
            return self._send(200, (STATIC / "index.html").read_bytes(), "text/html; charset=utf-8",
                              {"Referrer-Policy": "no-referrer"})
        if path == "/materials.jsonl":  # the material library (no token: it's the same public data as the page)
            lib = STATIC / "materials.jsonl"
            if not lib.is_file():
                return self._error(404, "No material library")
            return self._send(200, lib.read_bytes(), "application/jsonl; charset=utf-8")
        if path == "/api/ping":
            return self._send(200, {"ok": True, "app": "openmc-studio"})
        if not path.startswith("/api/"):
            return self._error(404, "Not found")
        if not self._token_ok(q):
            return self._error(401, "Missing or wrong token. Start Studio from its launcher.")
        if path == "/api/health":
            return self._send(200, self._health())
        if path == "/api/mcnp-progress":
            return self._send(200, self.studio.mcnp.get_progress() or {})
        if path == "/api/convert/status":
            return self._send(200, self.studio.cad_status())
        if path == "/api/convert/progress":
            return self._send(200, self.studio.cad_progress() or {})
        if path == "/api/cad/capabilities":
            return self._send(200, self.studio.cad_jobs.capabilities())
        m = re.fullmatch(r"/api/cad/jobs/([0-9a-f]{32})(/result)?", path)
        if m:
            try:
                value = self.studio.cad_jobs.result(m[1]) if m[2] else self.studio.cad_jobs.get(m[1])
                return self._send(200, value)
            except KeyError:
                return self._error(404, "No such CAD job")
            except RuntimeError as exc:
                return self._error(409, str(exc))
        if path == "/api/runs":
            return self._send(200, {"runs": self.studio.list_runs()})
        m = re.match(r"^/api/runs/([^/]+)/(stream|results|project|script)$", path)
        if not m:
            return self._error(404, "Not found")
        rid, what = m.groups()
        run_dir = self.studio.run_path(rid)
        if not run_dir:
            return self._error(404, "No such run")
        if what == "stream":
            return self._stream(rid, int((q.get("from") or ["0"])[0]))
        if what == "project":
            return self._send(200, (run_dir / "project.json").read_bytes())
        if what == "script":
            return self._send(200, (run_dir / "model.py").read_bytes(), "text/plain; charset=utf-8")
        try:
            from . import results
            return self._send(200, results.load(run_dir))
        except Exception as e:  # results are best effort; report instead of crashing the page
            return self._error(500, f"Couldn't read results: {e}")

    def do_POST(self):
        if not self._host_ok() or not self._origin_ok():
            return self._error(403, "Cross-origin request refused.")
        url = urlparse(self.path)
        if not self._token_ok(parse_qs(url.query)):
            return self._error(401, "Missing or wrong token.")
        try:
            body = self._json_body()
        except ValueError as e:
            return self._error(400, f"Bad request: {e}")
        if url.path == "/api/cad/jobs":
            import base64
            import binascii
            from .cad.jobs import MAX_INPUT
            try:
                if set(body) - {"filename", "data"}:
                    raise ValueError("Only filename and base64 data are accepted")
                encoded = body.get("data")
                if not isinstance(encoded, str) or len(encoded) > 4 * ((MAX_INPUT + 2) // 3):
                    raise ValueError("Invalid or oversized base64 CAD data")
                data = base64.b64decode(encoded, validate=True)
                job = self.studio.cad_jobs.submit(data, body.get("filename"))
                return self._send(202, job, extra={"Location": f"/api/cad/jobs/{job['id']}"})
            except (ValueError, binascii.Error) as exc:
                return self._error(400, str(exc))
            except RuntimeError as exc:
                return self._error(409, str(exc))
        if url.path == "/api/run":
            script = body.get("script")
            if not isinstance(script, str) or not script.strip():
                return self._error(400, "No script to run.")
            try:
                run = self.studio.start(script, body.get("project") or {}, str(body.get("name") or "model"))
            except RuntimeError as e:
                return self._error(409, str(e))
            return self._send(200, run.meta())
        if url.path == "/api/mcnp-live":
            script = body.get("script")
            if not isinstance(script, str) or not script.strip():
                return self._error(400, "No script.")
            return self._send(200, self.studio.mcnp_live(script, str(body.get("name") or "model"), int(body.get("seq") or 0),
                                                         str(body.get("client") or "")[:64]))
        if url.path == "/api/export-mcnp":
            script = body.get("script")
            if not isinstance(script, str) or not script.strip():
                return self._error(400, "No script to export.")
            return self._send(200, self.studio.export_mcnp(script, body.get("project") or {}, str(body.get("name") or "model")))
        if url.path == "/api/convert/cad-to-csg":
            filename = str(body.get("filename") or "geometry.step")
            raw_data = body.get("data")
            if not raw_data:
                return self._error(400, "No CAD data provided.")
            import base64
            if isinstance(raw_data, str) and raw_data.startswith("data:"):
                _, b64 = raw_data.split(",", 1)
                cad_bytes = base64.b64decode(b64)
            elif isinstance(raw_data, str):
                try:
                    cad_bytes = base64.b64decode(raw_data)
                except Exception:
                    cad_bytes = raw_data.encode("utf-8")
            else:
                cad_bytes = bytes(raw_data)
            res = self.studio.cad_to_csg(cad_bytes, filename, body.get("options"))
            return self._send(200, res)
        if url.path == "/api/convert/csg-to-cad":
            project = body.get("project") or {}
            units = str(body.get("units") or "mm")
            res = self.studio.csg_to_cad(project, units, body.get("options"))
            return self._send(200, res)
        m = re.match(r"^/api/runs/([^/]+)/stop$", url.path)
        if m:
            return self._send(200, {"stopped": self.studio.stop(m.group(1))})
        return self._error(404, "Not found")

    def do_DELETE(self):
        if not self._host_ok() or not self._origin_ok():
            return self._error(403, "Cross-origin request refused.")
        url = urlparse(self.path)
        if not self._token_ok(parse_qs(url.query)):
            return self._error(401, "Missing or wrong token.")
        m = re.fullmatch(r"/api/cad/jobs/([0-9a-f]{32})", url.path)
        if not m:
            return self._error(404, "Not found")
        try:
            return self._send(202, self.studio.cad_jobs.cancel(m[1]))
        except KeyError:
            return self._error(404, "No such CAD job")

    def _health(self):
        xs = os.environ.get("OPENMC_CROSS_SECTIONS", "")
        try:
            import openmc
            version = openmc.__version__
        except Exception as e:
            version = f"not importable ({e})"
        return {"studio": __version__, "openmc": version, "python": sys.version.split()[0],
                "cross_sections": xs, "cross_sections_found": bool(xs) and os.path.isfile(xs),
                "runs_dir": str(self.studio.root)}

    def _stream(self, rid, start):
        run = self.studio.runs.get(rid)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

        def emit(event, data):
            self.wfile.write(f"event: {event}\ndata: {json.dumps(data)}\n\n".encode("utf-8"))
            self.wfile.flush()

        try:
            if run is None:  # a past run from an earlier session: replay its log
                log = self.studio.run_path(rid) / "run.log"
                lines = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
                for i, line in enumerate(lines[start:], start):
                    emit("line", {"n": i, "text": line})
                meta = next((m for m in self.studio.list_runs() if m["id"] == rid), {"id": rid, "status": "unknown"})
                return emit("end", meta)
            i = start
            while True:
                with run.cond:
                    while i >= len(run.lines) and run.status == "running":
                        run.cond.wait(timeout=15)
                        if i >= len(run.lines) and run.status == "running":
                            break
                    batch = run.lines[i:]
                    finished = run.status != "running"
                for line in batch:
                    emit("line", {"n": i, "text": line})
                    i += 1
                if not batch and not finished:
                    self.wfile.write(b": keep-alive\n\n")
                    self.wfile.flush()
                if finished and i >= len(run.lines):
                    return emit("end", run.meta())
        except (BrokenPipeError, ConnectionResetError):
            return


def serve(port, runs_dir, token, open_browser=True):
    studio = Studio(runs_dir, token, port)
    Handler.studio = studio
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    httpd.daemon_threads = True
    url = f"http://127.0.0.1:{port}/?token={token}"
    print(f"OpenMC Studio {__version__} is running.", flush=True)
    print(f"  Open: {url}", flush=True)
    print(f"  Runs are saved in {studio.root}", flush=True)
    print("  Press Ctrl+C here to stop.", flush=True)
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if studio.active and studio.active.status == "running":
            studio.stop(studio.active.id)
        studio.mcnp.stop()
        studio.cad_jobs.close()
        studio.cad.stop()
        httpd.server_close()
        print("OpenMC Studio stopped.", flush=True)
