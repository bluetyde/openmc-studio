"""Mandatory real-engine stage-0 check; missing dependencies fail, never skip.

Run with the dedicated CAD Python and --output outside the repository. Each
fixture uses a fresh subprocess; logs, STEP, XML and JSON evidence are retained.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "studio"))
sys.path.insert(0, str(ROOT / "test" / "fixtures" / "cad"))
CASES = ("drilled_block", "annular_cylinder", "drilled_block_rotated", "annular_cylinder_rotated")


def check_case(name, directory):
    # FreeCAD initialization modifies __main__ globals; keep verifier imports local.
    import json
    import math
    import random
    import xml.etree.ElementTree as ET
    from openmc_studio.cad.geouned_adapter import configure_runtime, convert_step
    configure_runtime()
    import FreeCAD as App
    import Part
    import openmc
    from generate import make_fixture

    shape, expected_volume, probes = make_fixture(name)
    source = directory / "source.step"
    shape.exportStep(str(source))
    report = convert_step(source, directory / "conversion")
    if not math.isclose(shape.Volume, expected_volume, rel_tol=1e-9):
        raise ValueError("Fixture volume differs from analytical formula")
    restored = Part.read(str(source))
    if not math.isclose(restored.Volume, expected_volume, rel_tol=1e-8):
        raise ValueError("STEP roundtrip changed fixture volume")
    # This parser is exclusively for our generated fixtures, not an upload API.
    tree = ET.parse(report["xml"])
    surfaces = {int(e.attrib["id"]): openmc.Surface.from_xml_element(e)
                for e in tree.findall("surface")}
    cells = tree.findall("cell")
    if len(cells) != 1:
        raise ValueError(f"Expected one solid region with void generation off, got {len(cells)}")
    region = openmc.Region.from_expression(cells[0].attrib["region"], surfaces)

    def contains(point_mm):
        return tuple(x / 10 for x in point_mm) in region

    for point, expected in probes:
        if contains(point) != expected:
            raise ValueError(f"Hole/material probe failed at {point}")
    # Uniform samples in a padded box also test the exterior and cap boundaries.
    bounds = restored.BoundBox
    lows = [getattr(bounds, k) - 1 for k in ("XMin", "YMin", "ZMin")]
    highs = [getattr(bounds, k) + 1 for k in ("XMax", "YMax", "ZMax")]
    rng = random.Random(20260923)
    count, occupied = 20000, 0
    for _ in range(count):
        point = tuple(rng.uniform(a, b) for a, b in zip(lows, highs))
        expected = restored.isInside(App.Vector(*point), 1e-7, False)
        actual = contains(point)
        if actual != expected:
            raise ValueError(f"CAD/XML containment mismatch at {point}")
        occupied += actual
    box_volume = math.prod(b - a for a, b in zip(lows, highs))
    fraction = occupied / count
    sampled_volume = box_volume * fraction
    sigma = box_volume * math.sqrt(fraction * (1 - fraction) / count)
    if abs(sampled_volume - expected_volume) > 6 * sigma:
        raise ValueError("XML sampled volume differs from analytical volume")
    report.update(case=name, ok=True, point_checks=count, explicit_probes=len(probes),
                  seed=20260923, analytic_volume_cm3=expected_volume / 1000,
                  sampled_volume_cm3=sampled_volume / 1000, volume_sigma_cm3=sigma / 1000,
                  xml_cells=len(cells), xml_surfaces=len(surfaces))
    (directory / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--case", choices=CASES, help=argparse.SUPPRESS)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.is_relative_to(ROOT):
        parser.error("Output must be outside the repository")
    if args.case:
        check_case(args.case, output)
        return
    output.mkdir(parents=True, exist_ok=False)
    results = []
    for case in CASES:
        directory = output / case
        directory.mkdir()
        with (directory / "conversion.log").open("w") as log:
            try:
                run = subprocess.run([sys.executable, str(Path(__file__).resolve()),
                                      "--output", str(directory), "--case", case],
                                     cwd=directory, stdout=log, stderr=subprocess.STDOUT, timeout=180)
                if run.returncode:
                    raise RuntimeError(f"Conversion exited {run.returncode}; see {directory / 'conversion.log'}")
                results.append(json.loads((directory / "report.json").read_text()))
            except (subprocess.TimeoutExpired, RuntimeError) as exc:
                results.append({"case": case, "ok": False, "error": str(exc)})
        print(f"{case}: {'PASS' if results[-1]['ok'] else 'FAIL'}", flush=True)
    report = {"ok": all(r["ok"] for r in results), "cases": results,
              "can_import_into_studio": False}
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    if not report["ok"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
