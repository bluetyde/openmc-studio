"""A stopped depletion burn, resumed through Studio's own server code, against a burn that was never stopped. Real OpenMC; takes about six minutes.

    node test/generate_depletion_pin.cjs
    OMP_NUM_THREADS=4 python test/manual_depletion_resume.py        (WSL, with OpenMC, nuclear data and a depletion chain)

Uses Studio.start, Studio.stop (the real Stop: SIGTERM to the run's process group) and Studio.resume, in this process, so every step is the code
a user's click reaches. The pin cell, predictor, steps 1, 4 and 10 days, 38 W/g:
  1. a burn that runs to the end, for reference;
  2. the same burn, stopped after its second transport solve: it must leave an incomplete record;
  3. Resume on that run: a new run folder that ends with a complete record of all three steps;
  4. the resumed record against the reference: heavy-metal mass, burnup and the inventory of every listed nuclide agree (relative 1e-6); k is the
     same where the point was not redone and within 3 sigma where it was (a new Monte Carlo solve from a composition that differs in the eighth digit);
  5. the stopped run's folder is byte for byte as it was before the resume, and the new run's record names it;
  6. a second Resume on the finished burn is refused, and so is one on a run without rates.
Exit 0 when all hold.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "studio"))
from openmc_studio import depletion_record, depletion_run, server as srv  # noqa: E402

GEN = ROOT / "test" / "generated" / "depletion_pin"
if not (GEN / "model.py").is_file():
    sys.exit("run: node test/generate_depletion_pin.cjs   first")
if depletion_run.find_chain_file() is None:
    sys.exit(depletion_run.NO_CHAIN)
project = json.loads((GEN / "project.json").read_text())
project["settings"]["depSteps"] = "1, 4, 10"
script = (GEN / "model.py").read_text()
runs = Path(tempfile.mkdtemp(prefix="resume-runs-"))
studio = srv.Studio(runs, "t" * 32, 0)
checks = []


def check(name, ok, detail=""):
    checks.append(ok)
    print(("PASS " if ok else "FAIL ") + name + (": " + detail if detail else ""), flush=True)


def wait(run, until=None, limit=1800):
    t0 = time.time()
    while time.time() - t0 < limit and run.status == "running":
        if until and until():
            return
        time.sleep(0.5)


def tree_hash(folder):
    h = hashlib.sha256()
    for p in sorted(Path(folder).rglob("*")):
        if p.is_file():
            h.update(p.name.encode())
            h.update(p.read_bytes())
    return h.hexdigest()


# 1. the reference
ref_run = studio.start(script, project, "reference")
wait(ref_run)
ref = depletion_record.read(ref_run.path)
check("the reference burn ends complete", ref_run.status == "done" and ref["provenance"]["complete"] is True, f"{ref_run.status}, steps {ref['provenance']['steps_done']} of {ref['provenance']['steps_planned']}")
check("every burn keeps its reaction rates now", "write_rates=True" in (ref_run.path / "deplete.py").read_text())

# 2. stopped after the second transport solve
stopped = studio.start(script, project, "to be stopped")
wait(stopped, until=lambda: (stopped.path / "openmc_simulation_n2.h5").is_file())
time.sleep(1.0)
studio.stop(stopped.id)
wait(stopped)
rec1 = depletion_record.read(stopped.path)
check("the stopped run is stopped and left an incomplete record", stopped.status == "stopped" and rec1["provenance"]["complete"] is False,
      f"{stopped.status}, steps {rec1['provenance']['steps_done']} of {rec1['provenance']['steps_planned']}")
before = tree_hash(stopped.path)

# 3. resume
res_run = studio.resume(stopped.id)
wait(res_run)
check("the resumed run ends", res_run.status == "done", res_run.status + " " + "; ".join(res_run.lines[-3:]))
rec2 = depletion_record.read(res_run.path)
check("the resumed run is a new folder", res_run.path != stopped.path and res_run.id != stopped.id, res_run.id)
check("its record is complete, for all three steps", rec2["provenance"]["complete"] is True and rec2["provenance"]["steps_done"] == 3, f"{rec2['provenance']['steps_done']} steps")
r = rec2["provenance"].get("resumed_from") or {}
check("the record names the run it continued", r.get("run") == stopped.id and r.get("steps_done") == rec1["provenance"]["steps_done"], json.dumps({k: r.get(k) for k in ("run", "steps_done")}))
check("the record carries a note saying so", any(n.startswith("resumed") for n in rec2["provenance"]["notes"]), "; ".join(rec2["provenance"]["notes"]))

# 4. against the reference
a, b = ref["regions"][0], rec2["regions"][0]
check("same heavy-metal mass", abs(a["heavy_metal_mass_kg"] - b["heavy_metal_mass_kg"]) / a["heavy_metal_mass_kg"] < 1e-6, f"{a['heavy_metal_mass_kg']:.9g} and {b['heavy_metal_mass_kg']:.9g} kg")
check("same time steps", ref["time_steps_days"] == rec2["time_steps_days"], str(rec2["time_steps_days"]))
bu = max(abs(x - y) / max(abs(x), 1e-300) for x, y in zip(a["burnup_mwd_per_tu"], b["burnup_mwd_per_tu"]))
check("same burnup at every step", bu < 1e-6, f"largest relative difference {bu:.2e}")
worst, where = 0.0, ""
for nuc, series in ref["isotopics"][a["name"]].items():
    for i, (x, y) in enumerate(zip(series, rec2["isotopics"][b["name"]][nuc])):
        d = abs(x - y) / max(abs(x), 1e-300) if x else abs(y)
        if d > worst:
            worst, where = d, f"{nuc} at point {i}"
check("same inventory of every listed nuclide at every point", worst < 1e-6, f"largest relative difference {worst:.2e} ({where})")
redone = rec1["provenance"]["steps_done"]   # points 0..redone were in the stopped run; later ones are new solves
ok_k = True
detail = []
for i, ((k1, s1), (k2, s2)) in enumerate(zip(ref["k"], rec2["k"])):
    if i <= redone:
        same = abs(k1 - k2) < 1e-6 or (i == redone and abs(k1 - k2) < 3 * max(s1, s2))
    else:
        same = abs(k1 - k2) < 3 * max(s1, s2)
    ok_k &= same
    detail.append(f"{i}: {k1:.5f} / {k2:.5f}")
check("k: identical for the points already made, within 3 sigma for the ones solved again", ok_k, "; ".join(detail))

# 5. the stopped run is untouched
check("the stopped run's folder is byte for byte as it was before the resume", tree_hash(stopped.path) == before)

# 6. refusals
for label, rid in (("a finished burn", res_run.id), ("the reference (also finished)", ref_run.id)):
    try:
        studio.resume(rid)
        check(f"resume of {label} is refused", False, "it was accepted")
    except depletion_run.ResumeRefused as exc:
        check(f"resume of {label} is refused", "nothing to resume" in str(exc), str(exc))
# a run whose results file was cut off (a kill in the middle of a write): refused with the reason, never continued. (A file without reaction rates is
# refused too: test_depletion_resume.py covers it with a stand-in, and test/manual_resume_r0.py measured what OpenMC does with one.)
cut = runs / "20261010-000000-cut"
shutil.copytree(stopped.path, cut)
(cut / "depletion_results.h5").write_bytes((cut / "depletion_results.h5").read_bytes()[:4096])
try:
    studio.resume(cut.name)
    check("resume from a cut-off results file is refused", False, "it was accepted")
except depletion_run.ResumeRefused as exc:
    check("resume from a cut-off results file is refused", "can't be read" in str(exc), str(exc)[:120])

shutil.rmtree(runs, ignore_errors=True)
sys.exit(0 if all(checks) else 1)
