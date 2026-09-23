"""Disposable job entry point, imported so FreeCAD cannot erase our globals."""
import json
from pathlib import Path
from .geouned_adapter import convert_step


def write_atomic(path, value):
    path = Path(path)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value), encoding="utf-8")
    temporary.replace(path)


def run(job_id):
    def progress(stage):
        write_atomic("progress.json", {"id": job_id, "stage": stage})
    progress("loading")
    report = convert_step("source.step", "conversion", progress=progress)
    report.update(id=job_id, ok=True)
    write_atomic("result.json", report)
    progress("converted")
