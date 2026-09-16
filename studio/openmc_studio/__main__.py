"""Start the local OpenMC Studio server.

    python -m openmc_studio [--port 8765] [--runs ~/OpenMC-runs] [--no-browser]
"""
import argparse
import os
import secrets

from .server import serve


def main():
    ap = argparse.ArgumentParser(prog="python -m openmc_studio", description="Local OpenMC Studio")
    ap.add_argument("--port", type=int, default=int(os.environ.get("OPENMC_STUDIO_PORT", "8765")))
    ap.add_argument("--runs", default=os.environ.get("OPENMC_STUDIO_RUNS", os.path.expanduser("~/OpenMC-runs")),
                    help="folder for run outputs (default ~/OpenMC-runs)")
    ap.add_argument("--no-browser", action="store_true", help="don't open a browser window")
    ap.add_argument("--exit-with-launcher", action="store_true",
                    help="stop when the process that started Studio goes away (the launcher window was closed)")
    args = ap.parse_args()
    token = os.environ.get("OPENMC_STUDIO_TOKEN") or secrets.token_urlsafe(24)
    if args.exit_with_launcher:
        _watch_parent()
    serve(args.port, args.runs, token, open_browser=not args.no_browser)


def _watch_parent():
    # Closing the Windows launcher kills wsl.exe and the shell that started us, but not this Linux
    # process: it gets re-parented. A changed parent PID is the signal to shut down.
    import signal
    import threading
    import time

    parent = os.getppid()

    def watch():
        while os.getppid() == parent:
            time.sleep(1)
        os.kill(os.getpid(), signal.SIGINT)

    threading.Thread(target=watch, daemon=True).start()


if __name__ == "__main__":
    main()
