"""HTTP server for OpenMC Studio, standard library only.

Security model: the server runs the Python that the page sends it, so it only
listens on 127.0.0.1, checks the Host header (blocks DNS rebinding), rejects
cross-origin POSTs, and requires a per-launch token on every /api call except
/api/ping.
"""
import json
import os
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
MAX_BODY = 5 * 1024 * 1024
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
        """Write model.py, export model.xml, and run openmc-mcnp-project's export_mcnp.py on it."""
        proj = Path(os.environ.get("OPENMC_MCNP_PROJECT", "~/openmc-mcnp-project")).expanduser()
        exporter = proj / "src" / "export_mcnp.py"
        if not exporter.exists():
            return {"ok": False, "error": f"Can't find {exporter}. Clone openmc-mcnp-project to ~/openmc-mcnp-project "
                                          f"or set OPENMC_MCNP_PROJECT to its folder."}
        slug = re.sub(r"[^a-z0-9]+", "-", (name or "model").lower()).strip("-")[:40] or "model"
        folder = self.root / "mcnp-exports" / (time.strftime("%Y%m%d-%H%M%S") + "-" + slug)
        folder.mkdir(parents=True, exist_ok=False)
        (folder / "model.py").write_text(script, encoding="utf-8")
        (folder / "project.json").write_text(json.dumps(project, indent=2), encoding="utf-8")
        env = dict(os.environ, PYTHONUNBUFFERED="1")
        xml = subprocess.run([sys.executable, "model.py", "--export-xml"], cwd=folder, env=env,
                             capture_output=True, text=True, timeout=120)
        if xml.returncode != 0 or not (folder / "model.xml").exists():
            return {"ok": False, "folder": str(folder), "error": "model.py couldn't export model.xml: " + (xml.stderr or xml.stdout)[-2000:]}
        try:
            run = subprocess.run([sys.executable, str(exporter), "model.xml", "--name", slug, "--report", "report.json"],
                                 cwd=folder, env=env, capture_output=True, text=True, timeout=600)
        except subprocess.TimeoutExpired:
            return {"ok": False, "folder": str(folder), "error": "The MCNP export took longer than 10 minutes and was stopped."}
        (folder / "export.log").write_text(run.stdout + run.stderr, encoding="utf-8")
        try:
            report = json.loads((folder / "report.json").read_text())
        except (OSError, ValueError):
            return {"ok": False, "folder": str(folder), "error": "The exporter didn't write a report: " + (run.stderr or run.stdout)[-2000:]}
        deck_path = folder / f"{slug}_runnable.mcnp"
        report.update(folder=str(folder), name=slug,
                      deck=deck_path.read_text() if deck_path.exists() else None)
        report.pop("traceback", None)
        return report

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
        if n > MAX_BODY:
            raise ValueError("request too large")
        return json.loads(self.rfile.read(n) or b"{}")

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
        if path == "/api/ping":
            return self._send(200, {"ok": True, "app": "openmc-studio"})
        if not path.startswith("/api/"):
            return self._error(404, "Not found")
        if not self._token_ok(q):
            return self._error(401, "Missing or wrong token. Start Studio from its launcher.")
        if path == "/api/health":
            return self._send(200, self._health())
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
        if url.path == "/api/run":
            script = body.get("script")
            if not isinstance(script, str) or not script.strip():
                return self._error(400, "No script to run.")
            try:
                run = self.studio.start(script, body.get("project") or {}, str(body.get("name") or "model"))
            except RuntimeError as e:
                return self._error(409, str(e))
            return self._send(200, run.meta())
        if url.path == "/api/export-mcnp":
            script = body.get("script")
            if not isinstance(script, str) or not script.strip():
                return self._error(400, "No script to export.")
            return self._send(200, self.studio.export_mcnp(script, body.get("project") or {}, str(body.get("name") or "model")))
        m = re.match(r"^/api/runs/([^/]+)/stop$", url.path)
        if m:
            return self._send(200, {"stopped": self.studio.stop(m.group(1))})
        return self._error(404, "Not found")

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
        httpd.server_close()
        print("OpenMC Studio stopped.", flush=True)
