"""Rewrites test/fixtures/depletion/pin_run_data.json and pin_record.json from a real depletion of the pin cell Studio generates.

Run only when depletion_writer.read_run changes what it reads (the fixtures are the numbers of one real run, kept so the arithmetic can
be tested without a run). Takes a few minutes; WSL, with OpenMC, nuclear data and a depletion chain:

    node test/generate_depletion_pin.cjs
    OMP_NUM_THREADS=4 python test/regen_depletion_fixtures.py
"""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "studio"))
from openmc_studio import depletion_record, depletion_run, depletion_writer, provenance  # noqa: E402

GEN = ROOT / "test" / "generated" / "depletion_pin"
FIX = ROOT / "test" / "fixtures" / "depletion"
project = json.loads((GEN / "project.json").read_text())
chain = depletion_run.find_chain_file()
work = Path(tempfile.mkdtemp(prefix="depletion-fixture-"))
shutil.copyfile(GEN / "model.py", work / "model.py")
(work / "project.json").write_text(json.dumps(project))
(work / "deplete.py").write_text(depletion_run.script_text(project, work / "model.py", chain))
provenance.write(work, "run", project, files=("model.py", "project.json", "deplete.py"), extra={"depletion": {"chain": depletion_run.chain_record(chain)}})
subprocess.run([sys.executable, "-W", "ignore", "deplete.py"], cwd=work, check=True, capture_output=True)
data = depletion_writer.read_run(work)
(FIX / "pin_run_data.json").write_text(json.dumps(data, indent=1) + "\n")
st = project["settings"]
data["steps_planned"] = len(st["depSteps"].split(","))
data["provenance"] = {"run": "20261008-000000-depletion-pin", "integrator": st["depIntegrator"], "chain_level": st["depReduce"],
                      "power_density_w_per_g": st["depPower"], "particles": st["particles"], "batches": st["batches"], "seed": st["seed"]}
rec = depletion_writer.build(data)
(FIX / "pin_record.json").write_text(json.dumps(rec, indent=1) + "\n")
print("wrote the fixtures; record id", rec["id"][:12], "isotopics:", sorted(rec["isotopics"]["UO2 3.5%"]))
shutil.rmtree(work, ignore_errors=True)
