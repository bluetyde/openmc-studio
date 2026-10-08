"""Rewrites test/fixtures/material_assistant/cases.json from studio/openmc_studio/material_assistant.py: the golden cases the page's JavaScript port is held to
(test/test_material_assistant_page.js). Run when the module's arithmetic changes:  python test/regen_material_assistant_cases.py
`python test/regen_material_assistant_cases.py --check` fails if the file is not what the module gives now (the Python test runs it that way).
"""
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "studio"))
from openmc_studio import material_assistant as ma  # noqa: E402

UO2 = [[3.5, 95.0, 10.96], [0.71, 100.0, 10.5], [100.0, 100.0, 10.0], [5.0, 60.0, 10.9], [19.75, 98.5, 10.0], [1e-3, 50.0, 1.0],
       [0.0, 95.0, 10.0], [101.0, 95.0, 10.0], [3.5, 0.0, 10.0], [3.5, 100.5, 10.0], [3.5, 95.0, 0.0], [3.5, 95.0, -1.0], [3.5, 95.0, None], [None, 95.0, 10.0]]
WATER = [[0.0, 1.0], [1000.0, 0.7], [2500.0, 0.75, 0.0, 0.5], [500.0, 1.1, 1.0, 0.1982], [0.0, 1.0, 0.5], [999999.0, 1.0], [1000.0, 0.7, 0.0, 0.0], [1000.0, 0.7, 0.0, 1.0],
         [1e6, 1.0], [-1.0, 1.0], [100.0, 0.0], [100.0, 1.0, 1.5], [100.0, 1.0, 0.0, -0.1], [100.0, None], [None, 1.0]]


def case(fn, args):
    try:
        out = getattr(ma, fn)(*[float("nan") if a is None else a for a in args])
        return {"fn": fn, "args": args, "expect": out}
    except ma.MaterialError as exc:
        return {"fn": fn, "args": args, "error_arg": re.match(r"Argument '([a-z0-9_]+)'", str(exc)).group(1)}


def cases():
    return [case("uranium_dioxide", a) for a in UO2] + [case("borated_water", a) for a in WATER]


if __name__ == "__main__":
    target = ROOT / "test" / "fixtures" / "material_assistant" / "cases.json"
    text = json.dumps(cases(), indent=1) + "\n"
    if "--check" in sys.argv:
        sys.exit(0 if target.read_text() == text else "cases.json is not what material_assistant gives now: run test/regen_material_assistant_cases.py")
    target.write_text(text)
    print("wrote", len(cases()), "cases")
