"""Rewrites test/fixtures/pin_power/analysis.json: pin_power_view.analyse of a 4 x 3 mesh (hot pin at ix 3, iy 1, one pin that scored nothing, two
axial layers), the way the server sends it. The page test draws this. Run when pin_power_view's output changes:  python test/regen_pin_power_fixture.py
"""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "studio"))
from openmc_studio import pin_power_view  # noqa: E402

v0 = [1.00, 1.02, 0.98, 1.01, 0.99, 1.00, 0.0, 1.50, 1.01, 0.97, 1.03, 1.00]
v0[7] = 1.50
v1 = [x * 0.9 for x in v0]
tally = {"name": "Pin power", "kind": "mesh", "mesh_type": "regular", "dims": [4, 3, 2], "lower": [0.0, 0.0, 0.0], "upper": [5.04, 3.78, 2.0],
         "scores": ["kappa-fission", "fission"], "values": {"kappa-fission": v0 + v1, "fission": v1 + v0},
         "std": {"kappa-fission": [0.01 * x for x in v0 + v1], "fission": [0.01 * x for x in v1 + v0]}}
a = pin_power_view.analyse(tally, "kappa-fission", 0)
a["csv"] = pin_power_view.csv_text(a)
(ROOT / "test" / "fixtures" / "pin_power" / "analysis.json").write_text(json.dumps(a, indent=1) + "\n")
(ROOT / "test" / "fixtures" / "pin_power" / "tally.json").write_text(json.dumps(tally, indent=1) + "\n")
print("hot pin", a["peak"], "symmetry", a["symmetry"]["within_noise"])
