"""Rewrites test/fixtures/depletion/pin_record.json and slices_record.json from the run-data fixtures beside them, with depletion_writer.build as it is now.
No OpenMC run: the run-data fixtures (pin_run_data.json, slices_run_data.json) are what read_run gave for real runs. Use it when build changes what a record holds;
use test/regen_depletion_fixtures.py (a real run) when read_run changes what it reads.   python test/rebuild_depletion_records.py
"""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "studio"))
from openmc_studio import depletion_writer  # noqa: E402

FIX = ROOT / "test" / "fixtures" / "depletion"
KEYS = ("run", "integrator", "chain_level", "power_density_w_per_g", "particles", "batches", "seed")
for name in ("pin", "slices"):
    old = json.loads((FIX / f"{name}_record.json").read_text())["provenance"]
    data = json.loads((FIX / f"{name}_run_data.json").read_text())
    data["steps_planned"] = len(data["times_days"]) - 1
    data["provenance"] = {k: old[k] for k in KEYS if k in old}
    rec = depletion_writer.build(data)
    (FIX / f"{name}_record.json").write_text(json.dumps(rec, indent=1) + "\n")
    print(name, "id", rec["id"])
