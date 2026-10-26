"""Private runtime entry point. No host conda/Python discovery or shell profiles."""
import argparse
import json
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import sys
import xml.etree.ElementTree as ET

PREFIX = Path("/opt/openmc")
CORE = PREFIX / "conda/envs/openmc-mcnp"
CAD = PREFIX / "conda/envs/openmc-cad"


def nuclear_files(directory):
    """Require portable, complete data references contained in the data folder."""
    directory = directory.resolve()
    xml = directory / "cross_sections.xml"
    tree = ET.parse(xml)
    if tree.find("directory") is not None:
        raise ValueError("Nuclear data XML must use relative paths without a directory override")
    found = []
    for library in tree.findall("library"):
        relative = Path(library.attrib["path"])
        target = (directory / relative).resolve()
        if relative.is_absolute() or not target.is_relative_to(directory):
            raise ValueError(f"Non-portable nuclear data path: {relative}")
        if not target.is_file() or target.stat().st_size == 0:
            raise ValueError(f"Missing or empty nuclear data: {relative}")
        found.append(target)
    if not found:
        raise ValueError("Nuclear data index is empty")
    return found


def environment(package, token="", port=8765):
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("CONDA", "PYTHON", "OPENMC", "LD_"))}
    env.update(PATH=f"{CORE}/bin:/usr/bin:/bin", HOME="/home/studio", LANG="C.UTF-8",
               PYTHONDONTWRITEBYTECODE="1", PYTHONNOUSERSITE="1",
               PYTHONPATH=str(package / "app/studio"),
               OPENMC_MCNP_PROJECT=str(PREFIX / "exporter"),
               OPENMC_CAD_PYTHON=str(CAD / "bin/python"),
               OPENMC_CROSS_SECTIONS=str(package / "nuclear_data/cross_sections.xml"),
               OPENMC_STUDIO_RUNS=str(package / "results"),
               OPENMC_STUDIO_TOKEN=token, OPENMC_STUDIO_PORT=str(port),
               QT_QPA_PLATFORM="offscreen", OMP_NUM_THREADS=str(min(8, os.cpu_count() or 1)))
    return env


def verify(package):
    files = nuclear_files(package / "nuclear_data")
    env = environment(package)
    subprocess.run([str(CORE / "bin/python"), "-c",
                    "import openmc, openmc_mcnp_adapter, h5py; print('OpenMC', openmc.__version__)"],
                   env=env, check=True, timeout=60)
    subprocess.run([str(CORE / "bin/java"), "-version"], env=env, check=True, timeout=20)
    subprocess.run([str(CAD / "bin/python"), "-c",
                    "from openmc_studio.cad.geouned_adapter import configure_runtime; "
                    "configure_runtime(); import FreeCAD, Part, geouned; print('CAD imports OK')"],
                   env=env, check=True, timeout=90)
    if not (PREFIX / "exporter/LICENSE").is_file():
        raise ValueError("Bundled exporter is missing")
    print(json.dumps({"runtime": (PREFIX / "runtime-id").read_text().strip(),
                      "nuclear_libraries": len(files), "status": "ready"}))


def pid_path(token):
    if not re.fullmatch(r"[a-f0-9]{32}", token):
        raise ValueError("Invalid launch token")
    return Path("/run") / ("openmc-studio-" + token + ".pid")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=("verify", "start", "stop"))
    p.add_argument("package", type=Path)
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--token", default="")
    a = p.parse_args()
    package = a.package.resolve()
    if a.action == "verify":
        verify(package)
        return
    pidfile = pid_path(a.token)
    if a.action == "stop":
        if pidfile.exists():
            pid = int(pidfile.read_text())
            try:
                environ = Path(f"/proc/{pid}/environ").read_bytes().split(b"\0")
                if ("OPENMC_STUDIO_TOKEN=" + a.token).encode() in environ:
                    os.kill(pid, signal.SIGINT)
            except ProcessLookupError:
                pass
            except FileNotFoundError:
                pass
            pidfile.unlink(missing_ok=True)
        return
    if not 1024 <= a.port <= 65535:
        raise ValueError("Port must be between 1024 and 65535")
    nuclear_files(package / "nuclear_data")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", a.port))
    for name in ("projects", "results", "logs"):
        (package / name).mkdir(exist_ok=True)
    pidfile.write_text(str(os.getpid()))
    os.chdir(package / "app/studio")
    os.execve(CORE / "bin/python", [str(CORE / "bin/python"), "-m", "openmc_studio",
              "--port", str(a.port), "--runs", str(package / "results"), "--no-browser",
              "--exit-with-launcher"], environment(package, a.token, a.port))


if __name__ == "__main__":
    main()
