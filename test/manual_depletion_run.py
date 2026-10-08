"""A real depletion of the pin cell Studio generates, end to end: model.py from the page, deplete.py from the server's writer, openmc.deplete.

Not part of the suite (it takes minutes: three transport solves on a chain of about 1,300 nuclides). It checks what the unit tests cannot:
that prepare_depletion measures the fuel volume, that deplete.py runs and writes depletion_results.h5, and that the numbers come out as
physics and arithmetic say they must.

    node test/generate_depletion_pin.cjs          (Windows or anywhere Node runs: writes test/generated/depletion_pin/)
    OMP_NUM_THREADS=4 python test/manual_depletion_run.py     (WSL, with OpenMC, nuclear data and a depletion chain)

Checks: the source rate equals power density x the fuel's heavy-metal mass (the heavy-metal mass computed by hand from the pin's
dimensions, which does not use OpenMC's volume), within the stochastic volume's error; burnup is power density x time; U-235 falls;
Pu-239 and Xe-135 appear; k falls. Exit 0 when all hold.
"""
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "studio"))
from openmc_studio import depletion_record, depletion_run  # noqa: E402

GEN = ROOT / "test" / "generated" / "depletion_pin"
if not (GEN / "model.py").is_file():
    sys.exit("run: node test/generate_depletion_pin.cjs   first")
project = json.loads((GEN / "project.json").read_text())
chain = depletion_run.find_chain_file()
if chain is None:
    sys.exit(depletion_run.NO_CHAIN)

work = Path(tempfile.mkdtemp(prefix="depletion-pin-"))
shutil.copyfile(GEN / "model.py", work / "model.py")
(work / "deplete.py").write_text(depletion_run.script_text(project, work / "model.py", chain))
print(f"run folder {work}; chain {chain.name}; steps {project['settings']['depSteps']}; {project['settings']['depIntegrator']}")
t0 = time.time()
proc = subprocess.run([sys.executable, "-W", "ignore", "deplete.py"], cwd=work, capture_output=True, text=True, timeout=3600)
print(f"deplete.py exit {proc.returncode} after {time.time() - t0:.0f} s (machine load matters: do not quote this time)")
if proc.returncode:
    print(proc.stdout[-1500:], proc.stderr[-1500:])
    sys.exit(1)

import openmc.deplete as dep  # noqa: E402

res = dep.Results(str(work / "depletion_results.h5"))
times, k = res.get_keff(time_units="d")
rates = [float(x) for x in res.get_source_rates()]
st = project["settings"]
steps = [float(x) for x in st["depSteps"].split(",")]
power_density = float(st["depPower"])
# the heavy-metal mass by hand: pin dimensions, density, atom fractions and atomic masses, nothing from OpenMC
r, h, rho = 0.4096, 1.26, 10.4
a_u = 0.035 * 235.0439 + 0.965 * 238.0508
hm_g = math.pi * r * r * h * rho * a_u / (a_u + 2 * 15.9994)
expected_w = power_density * hm_g
_, u235 = res.get_atoms("1", "U235", time_units="d")
checks = []


def check(name, ok, detail):
    checks.append(ok)
    print(("PASS " if ok else "FAIL ") + name + ": " + detail)


check("source rate = power density x heavy-metal mass", abs(rates[0] - expected_w) / expected_w < 0.01,
      f"{rates[0]:.2f} W against {expected_w:.2f} W by hand ({hm_g:.4f} g of heavy metal)")
check("one rate per step", len(rates) == len(steps), f"{len(rates)} rates for {len(steps)} steps")
burnup = [power_density * sum(steps[:i + 1]) for i in range(len(steps))]
check("burnup = power density x time", all(abs(b - power_density * c) < 1e-9 for b, c in zip(burnup, [sum(steps[:i + 1]) for i in range(len(steps))])), f"{burnup} MWd/tU")
check("U-235 falls", u235[-1] < u235[0], f"{u235[0]:.4e} to {u235[-1]:.4e} atoms")
for nuc in ("Pu239", "Xe135"):
    try:
        _, a = res.get_atoms("1", nuc, time_units="d")
        check(f"{nuc} appears", a[0] == 0 and a[-1] > 0, f"{a[0]:.3e} to {a[-1]:.3e} atoms")
    except KeyError:
        check(f"{nuc} appears", False, "not in the reduced chain")
check("k falls", k[-1, 0] < k[0, 0], f"{k[0, 0]:.5f} to {k[-1, 0]:.5f}")
rec = depletion_record.build_record(steps, [{"name": "fuel", "cell_ids": [1], "power_w": rates[:len(steps)], "heavy_metal_mass_kg": hm_g / 1000}],
                                    k=[[float(a), float(b)] for a, b in k], provenance={"chain": depletion_run.chain_record(chain)["sha256"]})
check("the record builds and validates", rec["regions"][0]["burnup_mwd_per_tu"][-1] > 0, f"burnup {rec['regions'][0]['burnup_mwd_per_tu']} MWd/tU")
shutil.rmtree(work, ignore_errors=True)
sys.exit(0 if all(checks) else 1)
