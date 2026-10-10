"""R0 of docs/design/depletion-resume-plan.md: what does OpenMC 0.15.3 really do when a depletion is restarted? Real runs on the pin cell Studio generates; takes about ten minutes.

    node test/generate_depletion_pin.cjs
    OMP_NUM_THREADS=4 python test/manual_resume_r0.py        (WSL, with OpenMC, nuclear data and a depletion chain)

Questions, each answered by a run:
  A. Does a run started with write_rates=True keep reaction rates in its results, and how much bigger is the file?
  B. Is a burn that was killed after a step and resumed (prev_results, continue_timesteps=True) IDENTICAL to one that was never interrupted?
  C. What does a restart do when the results were written WITHOUT rates (the default, and what Studio does today)?
The fuel volume is set from the pin's dimensions, not measured, so that two runs of the same model are the same model.
Prints what it finds; exits 0 when it has run to the end (the findings, not a pass or fail, are the result).
"""
import json
import math
import os
from pathlib import Path
import runpy
import shutil
import signal
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "studio"))
from openmc_studio import depletion_run  # noqa: E402

GEN = ROOT / "test" / "generated" / "depletion_pin"
chain = depletion_run.find_chain_file()
STEPS = [1.0, 4.0, 10.0]
HEAD = '''import math, sys, runpy
import openmc, openmc.deplete as dep
ns = runpy.run_path("model.py")
model = ns["model"]
for m in model.materials:
    if m.name.startswith("UO2"):
        m.volume = math.pi * 0.4096 ** 2 * 1.26
'''
FULL = HEAD + '''op = dep.CoupledOperator(model, chain_file=%(chain)r, reduce_chain_level=3)
integ = dep.PredictorIntegrator(op, %(steps)r, power_density=38.0, timestep_units="d")
integ.integrate(write_rates=%(rates)s)
'''
RESUME = HEAD + '''prev = dep.Results("depletion_results.h5")
print("PREV entries", len(prev), "times", list(prev.get_times("d")))
op = dep.CoupledOperator(model, chain_file=%(chain)r, prev_results=prev, reduce_chain_level=3)
integ = dep.PredictorIntegrator(op, %(steps)r, power_density=38.0, timestep_units="d", continue_timesteps=True)
integ.integrate(write_rates=%(rates)s)
'''


def folder(tag):
    d = Path(tempfile.mkdtemp(prefix=f"resume-r0-{tag}-"))
    shutil.copyfile(GEN / "model.py", d / "model.py")
    return d


def run(d, script, timeout=1800):
    (d / "go.py").write_text(script)
    t0 = time.time()
    p = subprocess.run([sys.executable, "-W", "ignore", "go.py"], cwd=d, capture_output=True, text=True, timeout=timeout)
    return p, time.time() - t0


def kill_after(d, script, until):
    (d / "go.py").write_text(script)
    proc = subprocess.Popen([sys.executable, "-W", "ignore", "go.py"], cwd=d, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    deadline = time.time() + 1500
    while time.time() < deadline and not (d / until).is_file() and proc.poll() is None:
        time.sleep(0.5)
    time.sleep(1.0)
    os.killpg(proc.pid, signal.SIGKILL)
    proc.wait()


def read(d):
    import openmc.deplete as dep
    res = dep.Results(str(d / "depletion_results.h5"))
    _, k = res.get_keff(time_units="d")
    nucs = ["U235", "U238", "Pu239", "Xe135"]
    atoms = {n: [float(x) for x in res.get_atoms("1", n, nuc_units="atoms", time_units="d")[1]] for n in nucs}
    rates = [float(r.rates.sum()) if getattr(r, "rates", None) is not None and len(r.rates) else 0.0 for r in res]
    return {"entries": len(res), "times": [float(t) for t in res.get_times("d")], "k": [float(x) for x in k[:, 0]], "atoms": atoms, "rate_sums": rates,
            "bytes": (d / "depletion_results.h5").stat().st_size}


def same(a, b, what):
    n = min(len(a["times"]), len(b["times"]))
    worst = 0.0
    for nuc in a["atoms"]:
        for x, y in zip(a["atoms"][nuc][:n], b["atoms"][nuc][:n]):
            worst = max(worst, abs(x - y) / max(abs(x), 1e-300))
    kd = max(abs(x - y) for x, y in zip(a["k"][:n], b["k"][:n]))
    print(f"   {what}: {n} points compared; largest relative difference in atoms {worst:.3e}; largest difference in k {kd:.3e}")
    return worst, kd


print("chain", chain.name, "; steps", STEPS)
out = {}

# A + reference: never interrupted, rates kept
d_ref = folder("ref")
p, secs = run(d_ref, FULL % {"chain": str(chain), "steps": STEPS, "rates": True})
print(f"A. uninterrupted, write_rates=True: exit {p.returncode} in {secs:.0f} s")
if p.returncode:
    print(p.stdout[-800:], p.stderr[-1500:])
    sys.exit(1)
ref = read(d_ref)
d_plain = folder("plain")
p, secs = run(d_plain, FULL % {"chain": str(chain), "steps": STEPS, "rates": False})
plain = read(d_plain)
print(f"   file size with rates {ref['bytes']} bytes, without {plain['bytes']} bytes; sum of the stored rates per entry: with {[f'{x:.3g}' for x in ref['rate_sums']]}, without {[f'{x:.3g}' for x in plain['rate_sums']]}")
same(ref, plain, "write_rates on or off changes nothing else (the same run)")

# B: killed after the second transport solve, resumed, compared with the reference
d_b = folder("resumed")
kill_after(d_b, FULL % {"chain": str(chain), "steps": STEPS, "rates": True}, "openmc_simulation_n2.h5")
killed = read(d_b)
print(f"B. killed run (rates on): {killed['entries']} entries, times {killed['times']}, stored rates {[f'{x:.3g}' for x in killed['rate_sums']]}")
shutil.copyfile(d_b / "depletion_results.h5", d_b / "killed_results.h5")
p, secs = run(d_b, RESUME % {"chain": str(chain), "steps": STEPS, "rates": True})
print(f"   resume: exit {p.returncode} in {secs:.0f} s")
if p.returncode:
    print(p.stdout[-1000:], p.stderr[-2000:])
else:
    resumed = read(d_b)
    print(f"   resumed run holds {resumed['entries']} entries, times {resumed['times']}")
    same(ref, resumed, "resumed against uninterrupted")
    out["B"] = {"identical_atoms_rel": same(ref, resumed, "(again)")[0]}

# C: killed WITHOUT rates, then resumed
d_c = folder("norates")
kill_after(d_c, FULL % {"chain": str(chain), "steps": STEPS, "rates": False}, "openmc_simulation_n2.h5")
killed_c = read(d_c)
print(f"C. killed run (rates off): {killed_c['entries']} entries, stored rates {[f'{x:.3g}' for x in killed_c['rate_sums']]}")
p, secs = run(d_c, RESUME % {"chain": str(chain), "steps": STEPS, "rates": True})
print(f"   resume from a file with no rates: exit {p.returncode} in {secs:.0f} s")
if p.returncode:
    print("   error text:", (p.stderr.strip().splitlines() or ["(none)"])[-1][:300])
else:
    resumed_c = read(d_c)
    same(ref, resumed_c, "resumed-without-rates against uninterrupted")

for d in (d_ref, d_plain, d_b, d_c):
    shutil.rmtree(d, ignore_errors=True)
sys.exit(0)
