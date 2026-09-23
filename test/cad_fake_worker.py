"""Stand-in CAD worker for the job-lifecycle tests. Never used by Studio itself.

Invoked as: python cad_fake_worker.py BEHAVIOUR [SIDE_DIR]
It runs in the job's private work directory like the real worker, reads the
server's request.json, then misbehaves (or behaves) as asked. SIDE_DIR is a
directory outside the job where the test can observe what happened even after the
job's work directory is deleted.
"""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

behaviour = sys.argv[1]
side = Path(sys.argv[2]) if len(sys.argv) > 2 else None
request = json.loads(Path("request.json").read_text())
job_id, mode = request["id"], request["mode"]


def atomic(name, value):
    tmp = Path(name).with_suffix(".tmp")
    tmp.write_text(json.dumps(value))
    tmp.replace(name)


def ok(**extra):
    if mode == "csg-xml":
        Path("conversion").mkdir(exist_ok=True)
        Path("conversion/geometry.xml").write_text("<geometry><surface id='1' type='sphere' coeffs='0 0 0 1'/>"
                                                   "<cell id='1' material='void' region='-1'/></geometry>")
    atomic("result.json", {"id": job_id, "ok": True, "mode": mode, "xml": "/private/worker/path",
                           "versions": {"fake": "1"}, **extra})


def mark(event):
    if side:
        with open(side / "events.log", "a") as f:
            f.write(f"{event} {job_id} {time.monotonic()}\n")


def spawn_child():
    # A descendant in the worker's process group; it must die with the job.
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])
    (side / f"child-{job_id}.pid").write_text(str(child.pid))


mark("start")
if behaviour == "ok":
    ok()
elif behaviour == "slow-ok":
    time.sleep(0.3)
    ok()
elif behaviour == "segv":
    os.kill(os.getpid(), signal.SIGSEGV)
elif behaviour == "exit3":
    print("something went wrong before any result")
    sys.exit(3)
elif behaviour == "self-fail":
    print("GEOUNED: the solid has no faces")
    atomic("result.json", {"id": job_id, "ok": False, "error": "ValueError: Stage 0 requires exactly one valid closed solid"})
    sys.exit(2)
elif behaviour == "hang":
    spawn_child()
    atomic("progress.json", {"id": job_id, "stage": "decomposing solids"})
    time.sleep(600)
elif behaviour == "stale-result":
    atomic("result.json", {"id": "0" * 32, "ok": True, "mode": mode})
elif behaviour == "stale-progress":
    atomic("progress.json", {"id": "f" * 32, "stage": "someone else's"})
    time.sleep(5)
    ok()
elif behaviour == "wrong-mode":
    atomic("result.json", {"id": job_id, "ok": True, "mode": "probe" if mode != "probe" else "csg-xml"})
elif behaviour == "missing-xml":
    atomic("result.json", {"id": job_id, "ok": True, "mode": mode})
elif behaviour == "log-flood":
    sys.stdout.write("x" * (4 * 1024 * 1024))
    sys.stdout.flush()
    time.sleep(5)
    ok()
elif behaviour == "disk-flood":
    Path("big.bin").write_bytes(b"\0" * (4 * 1024 * 1024))
    time.sleep(5)
    ok()
elif behaviour == "big-result":
    atomic("result.json", {"id": job_id, "ok": True, "mode": mode, "pad": "x" * (200 * 1024)})
elif behaviour == "churn":
    # Atomic rewrites and scratch files as fast as possible, like a busy engine:
    # the supervisor's size scan must not fail the job when a file vanishes under it.
    end = time.monotonic() + 1.5
    n = 0
    while time.monotonic() < end:
        atomic("progress.json", {"id": job_id, "stage": f"step {n}"})
        scratch = Path(f"scratch-{n % 7}.tmp")
        scratch.write_bytes(b"s" * 256)
        scratch.unlink()
        n += 1
    ok(rewrites=n)
elif behaviour == "result-then-wait":
    ok()
    mark("result-written")
    time.sleep(600)
else:
    sys.exit(f"unknown behaviour {behaviour}")
mark("end")
