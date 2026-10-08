"""Rewrites test/fixtures/depletion/slices_run_data.json and slices_record.json from a real two-slice depletion run folder.

Run only when depletion_writer.read_run changes what it reads from the power-split statepoints. Takes a few minutes; WSL.

    node test/generate_depletion_slices.cjs
    OMP_NUM_THREADS=4 python test/manual_depletion_slices.py --keep        (prints the folder it kept)
    python test/regen_depletion_slices_fixtures.py <that folder>
"""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "studio"))
from openmc_studio import depletion_writer  # noqa: E402

FIX = ROOT / "test" / "fixtures" / "depletion"
folder = Path(sys.argv[1])
project = json.loads((folder / "project.json").read_text())
data = depletion_writer.read_run(folder)
(FIX / "slices_run_data.json").write_text(json.dumps(data, indent=1) + "\n")
st = project["settings"]
data["steps_planned"] = len(st["depSteps"].split(","))
data["provenance"] = {"run": "20261008-000000-depletion-slices", "integrator": st["depIntegrator"], "chain_level": st["depReduce"],
                      "power_density_w_per_g": st["depPower"], "particles": st["particles"], "batches": st["batches"], "seed": st["seed"]}
rec = depletion_writer.build(data)
(FIX / "slices_record.json").write_text(json.dumps(rec, indent=1) + "\n")
print("wrote the fixtures; record id", rec["id"][:12], "regions:", [r["name"] for r in rec["regions"]], "shares:", [r["power_w"] for r in rec["regions"]])
