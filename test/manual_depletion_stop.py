"""A depletion that is stopped part way still leaves a record of the steps it finished, marked incomplete. Real OpenMC; takes a few minutes.

    node test/generate_depletion_pin.cjs
    OMP_NUM_THREADS=4 python test/manual_depletion_stop.py     (WSL)

Runs the pin with three steps, kills the burn once the second transport solve has been written, then asks depletion_writer.from_run for the
record as the server does for a stopped run. Checks: a record exists and validates, it says 1 or 2 of 3 steps, the burnup of the steps it holds
is still power density x time, and no step it was not given appears.
"""
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "studio"))
from openmc_studio import depletion_record, depletion_run, depletion_writer, provenance  # noqa: E402

GEN = ROOT / "test" / "generated" / "depletion_pin"
project = json.loads((GEN / "project.json").read_text())
project["settings"]["depSteps"] = "1, 4, 10"
chain = depletion_run.find_chain_file()
work = Path(tempfile.mkdtemp(prefix="depletion-stop-"))
shutil.copyfile(GEN / "model.py", work / "model.py")
(work / "project.json").write_text(json.dumps(project))
(work / "deplete.py").write_text(depletion_run.script_text(project, work / "model.py", chain))
provenance.write(work, "run", project, files=("model.py", "project.json", "deplete.py"), extra={"depletion": {"chain": depletion_run.chain_record(chain)}})
proc = subprocess.Popen([sys.executable, "-W", "ignore", "deplete.py"], cwd=work, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
deadline = time.time() + 900
while time.time() < deadline and not (work / "openmc_simulation_n2.h5").is_file() and proc.poll() is None:
    time.sleep(1)
time.sleep(2)
os.killpg(proc.pid, signal.SIGKILL)
proc.wait()
print(f"killed after {time.time() - (deadline - 900):.0f} s; files: {sorted(p.name for p in work.glob('*.h5'))}")
try:
    rec = depletion_writer.from_run(work)
except Exception as exc:  # noqa: BLE001
    print("FAIL: no record:", type(exc).__name__, exc)
    sys.exit(1)
prov = rec["provenance"]
ok = []
for name, good, detail in (
        ("the record validates and reads back", depletion_record.read(work)["id"] == rec["id"], rec["id"][:12]),
        ("it says it is incomplete", prov["complete"] is False and prov["steps_planned"] == 3 and 1 <= prov["steps_done"] <= 2, f"{prov['steps_done']} of {prov['steps_planned']} steps"),
        ("its burnup is still 38 W/g x time", all(abs(b - 38.0 * d) < 1e-6 for b, d in zip(rec["regions"][0]["burnup_mwd_per_tu"], [1.0, 5.0])), str(rec["regions"][0]["burnup_mwd_per_tu"])),
        ("it has one more k and inventory point than steps", len(rec["k"]) == len(rec["time_steps_days"]) + 1, f"{len(rec['k'])} k points for {len(rec['time_steps_days'])} steps"),
        ("the note says how far it got", any("incomplete" in n for n in prov["notes"]), "; ".join(prov["notes"]))):
    ok.append(good)
    print(("PASS " if good else "FAIL ") + name + ": " + detail)
shutil.rmtree(work, ignore_errors=True)
sys.exit(0 if all(ok) else 1)
