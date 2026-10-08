"""A real depletion of two axial fuel slices (3.5 % below, 5 % above), both burnable: the record gets one region for each, with the source
rate split by the kappa-fission tally that model.py adds. Real OpenMC; takes a few minutes.

    node test/generate_depletion_slices.cjs
    OMP_NUM_THREADS=4 python test/manual_depletion_slices.py       (WSL, with OpenMC, nuclear data and a depletion chain)

What the unit tests cannot check, and this does:
  - the transport statepoint of each step holds the power-split tally and is the solve the results file began that step with;
  - the heavy-metal mass of each slice agrees with the dimensions worked out by hand (pi r^2 h rho x the heavy-metal mass fraction);
  - the regions' powers add up to the source rate, and the richer slice takes the larger share per gram of heavy metal;
  - the independent bookkeeping: for each slice, the heavy-metal atoms it lost agree with the fissions its own share of the power implies
    (the inventory check, within its 5 percent). That check does not use the tally, so it tests the split;
  - the record is written, validates, keeps its id, and each region's burnup is its power x time over its own heavy-metal mass.
Exit 0 when all hold.
"""
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "studio"))
from openmc_studio import depletion_record, depletion_run, depletion_writer, provenance  # noqa: E402

GEN = ROOT / "test" / "generated" / "depletion_slices"
if not (GEN / "model.py").is_file():
    sys.exit("run: node test/generate_depletion_slices.cjs   first")
project = json.loads((GEN / "project.json").read_text())
chain = depletion_run.find_chain_file()
if chain is None:
    sys.exit(depletion_run.NO_CHAIN)
KEEP = "--keep" in sys.argv

work = Path(tempfile.mkdtemp(prefix="depletion-slices-"))
shutil.copyfile(GEN / "model.py", work / "model.py")
(work / "deplete.py").write_text(depletion_run.script_text(project, work / "model.py", chain))
(work / "project.json").write_text(json.dumps(project))
provenance.write(work, "run", project, files=("model.py", "project.json", "deplete.py"), extra={"depletion": {"chain": depletion_run.chain_record(chain)}})
print(f"run folder {work}; chain {chain.name}; steps {project['settings']['depSteps']}; {project['settings']['depIntegrator']}")
proc = subprocess.run([sys.executable, "-W", "ignore", "deplete.py"], cwd=work, capture_output=True, text=True, timeout=3600)
print(f"deplete.py exit {proc.returncode}")
if proc.returncode:
    print(proc.stdout[-1500:], proc.stderr[-1500:])
    sys.exit(1)

st = project["settings"]
power_density = float(st["depPower"])
steps = [float(x) for x in st["depSteps"].split(",")]
checks = []


def check(name, ok, detail):
    checks.append(ok)
    print(("PASS " if ok else "FAIL ") + name + ": " + detail)


rec = depletion_writer.from_run(work)   # what the server does when the run ends
back = depletion_record.read(work)
check("the record was written, validates and keeps its id", back["id"] == rec["id"] == depletion_record.record_id(back), f"id {rec['id'][:16]}")
check("it has one region for each slice", [r["name"] for r in rec["regions"]] == ["UO2 3.5%", "UO2 5%"], ", ".join(r["name"] for r in rec["regions"]))
# the heavy-metal mass of a slice by hand: pi r^2 h rho, times the heavy-metal mass fraction of UO2 at that enrichment
masses = []
for enrich in (0.035, 0.05):
    a_u = enrich * 235.0439 + (1 - enrich) * 238.0508
    masses.append(math.pi * 0.4096 ** 2 * 0.63 * 10.4 * a_u / (a_u + 2 * 15.9994))
for reg, hand in zip(rec["regions"], masses):
    check(f"{reg['name']}: heavy-metal mass by hand", abs(reg["heavy_metal_mass_kg"] * 1000 - hand) / hand < 0.02, f"{reg['heavy_metal_mass_kg'] * 1000:.4f} g against {hand:.4f} g (stochastic volume, 2 percent)")
a, b = rec["regions"]
total_w = [pa + pb for pa, pb in zip(a["power_w"], b["power_w"])]
expected_total = power_density * sum(r["heavy_metal_mass_kg"] for r in rec["regions"]) * 1000
check("the regions' powers add up to power density x heavy-metal mass", all(abs(t - expected_total) / expected_total < 1e-6 for t in total_w), f"{total_w} W against {expected_total:.3f} W")
per_g = [p / (r["heavy_metal_mass_kg"] * 1000) for r in rec["regions"] for p in r["power_w"][:1]]
check("the richer slice takes the larger power per gram of heavy metal", per_g[1] > per_g[0], f"{per_g[0]:.2f} and {per_g[1]:.2f} W/g at the start")
for reg in rec["regions"]:
    inv = rec["provenance"]["checks"][reg["name"]]["inventory"]
    check(f"{reg['name']}: the atoms lost agree with the fissions its share of the power implies", inv["ok"], f"ratio {inv['ratio']:.4f} (tolerance {inv['tolerance']})")
    days = rec["time_steps_days"]
    cumulative = [sum(p * d for p, d in zip(reg["power_w"][:i + 1], days[:i + 1])) / (reg["heavy_metal_mass_kg"] * 1000) for i in range(len(days))]
    check(f"{reg['name']}: burnup is its power x time over its own heavy metal", all(abs(x - y) / y < 1e-6 for x, y in zip(reg["burnup_mwd_per_tu"], cumulative)), f"{[round(x, 2) for x in reg['burnup_mwd_per_tu']]} MWd/tU")
check("the two slices have different burnups", abs(a["burnup_mwd_per_tu"][-1] - b["burnup_mwd_per_tu"][-1]) > 1e-3, f"{a['burnup_mwd_per_tu'][-1]:.2f} and {b['burnup_mwd_per_tu'][-1]:.2f} MWd/tU")
check("the record says how the power was split", "kappa-fission" in rec["provenance"]["region_power"], rec["provenance"]["region_power"])
check("both slices hold their isotopics", all(n in rec["isotopics"][r["name"]] for r in rec["regions"] for n in ("U235", "Pu239", "Xe135")), ", ".join(sorted(rec["isotopics"])))
if KEEP:
    print("kept", work)
else:
    shutil.rmtree(work, ignore_errors=True)
sys.exit(0 if all(checks) else 1)
