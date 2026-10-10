"""What a depletion run needs from the server: the chain file, the generated deplete.py and a record of the chain.

A project with Settings > Depletion on is run by `python deplete.py`, not `python model.py`. deplete.py is written by
depletion_script.build_script beside model.py in the run folder; it loads model.py (which defines the burnable materials and
prepare_depletion, the function that measures their volumes) and burns the fuel with openmc.deplete. The settings come from the
project, which the page has already checked (prerun_check.py refuses a bad one before a run folder exists).
"""
import hashlib
import json
import os
from pathlib import Path
import shutil

from . import depletion_script

NO_CHAIN = ("Depletion needs a depletion chain file (an XML file of nuclides and their decays), and none was found. Put it next to "
            "the nuclear data in a folder called chains, or set OPENMC_CHAIN_FILE to its path.")


def wants(project):
    """True when the project asks for a depletion run."""
    st = (project or {}).get("settings")
    return isinstance(st, dict) and st.get("depletion") is True


def find_chain_file(environ=None):
    """The chain file this machine uses: OPENMC_CHAIN_FILE, else the chains folder beside the nuclear data folder
    (.../nuclear_data/endfb-viii.0-hdf5/cross_sections.xml finds .../nuclear_data/chains/*.xml). None when there is none."""
    env = os.environ if environ is None else environ
    given = env.get("OPENMC_CHAIN_FILE")
    if given:
        return Path(given) if Path(given).is_file() else None
    xs = env.get("OPENMC_CROSS_SECTIONS")
    if xs:
        folder = Path(xs).resolve().parent.parent / "chains"
        if folder.is_dir():
            found = sorted(folder.glob("*.xml"), key=lambda p: ("pwr" not in p.name, p.name))
            if found:
                return found[0]
    return None


def steps_days(text):
    """The time steps the page writes as '1, 4, 10' as a list of floats."""
    return [float(t) for t in str(text).split(",") if t.strip()]


def script_text(project, model_path, chain_file, resume=False):
    """The text of deplete.py for a project that asks for depletion. Every burn keeps its reaction rates (write_rates), because a burn that
    stops can only be resumed if they are in its results; `resume` continues the burn whose results are beside the script."""
    st = project["settings"]
    return depletion_script.build_script({
        "model_path": str(model_path), "chain_file": str(chain_file), "integrator": st["depIntegrator"],
        "time_steps_days": steps_days(st["depSteps"]), "power_density": float(st["depPower"]),
        "reduce_chain_level": int(st["depReduce"]), "prepare": True, "write_rates": True, "resume": bool(resume)})


def chain_record(chain_file):
    """What the run record keeps about the chain: where it was, how big and which file exactly."""
    h = hashlib.sha256()
    with open(chain_file, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return {"path": str(chain_file), "size": Path(chain_file).stat().st_size, "sha256": h.hexdigest()}


class ResumeRefused(ValueError):
    """A burn that cannot be resumed, and the message says why."""


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def resume_plan(src, chain_file, environ_now=None):
    """Can the depletion run in folder `src` be continued, and from where? Raises ResumeRefused with the reason, else returns
    {"steps_done", "steps_planned", "results_sha256", "files", "warnings"}.

    Refused (each checked, none assumed): not a depletion run; a model.py from before resume existed (prepare_depletion cannot skip the
    volumes); the burn already finished; a results file that cannot be opened; **results without reaction rates** (OpenMC does not refuse
    them: it continues with zero rates and burns without transmutation, wrongly and quietly, measured in test/manual_resume_r0.py);
    another chain file than the one the burn used; time steps that differ from the project's list. Another OpenMC version or another
    nuclear data library only warns: people upgrade, and the new record names it."""
    src = Path(src)
    for name in ("deplete.py", "project.json", "model.py", "depletion_results.h5", "provenance.json"):
        if not (src / name).is_file():
            raise ResumeRefused("this is not a depletion run with results to continue" if name in ("deplete.py", "depletion_results.h5") else f"{name} is missing from the run folder")
    try:
        project = json.loads((src / "project.json").read_text(encoding="utf-8"))
        prov = json.loads((src / "provenance.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ResumeRefused(f"the run's project or provenance record can't be read: {exc}") from exc
    if not wants(project):
        raise ResumeRefused("this run did not ask for depletion")
    if "measure_volumes" not in (src / "model.py").read_text(encoding="utf-8"):
        raise ResumeRefused("this run was made by a Studio from before resume existed: its model.py cannot skip the volume measurement. Start the burn again.")
    if chain_file is None:
        raise ResumeRefused(NO_CHAIN)
    recorded = ((prov.get("depletion") or {}).get("chain") or {}).get("sha256")
    now = chain_record(chain_file)["sha256"]
    if recorded != now:
        raise ResumeRefused("the depletion chain file is not the one this burn used (its SHA-256 differs from the one recorded). A burn with two chains is not one burn.")
    steps = steps_days(project["settings"]["depSteps"])
    try:
        import numpy as np
        import openmc.deplete as dep
        res = dep.Results(str(src / "depletion_results.h5"))
        entries = len(res)
        times = [float(t) for t in res.get_times("d")]
        rates = np.asarray(res[entries - 1].rates, dtype=float)
    except Exception as exc:  # noqa: BLE001  an HDF5 file cut off by a kill, a missing group, anything
        raise ResumeRefused(f"its results file can't be read ({type(exc).__name__}: {exc}). The burn cannot be continued from it.") from exc
    if entries < 1:
        raise ResumeRefused("its results file holds no step")
    if entries >= len(steps) + 1:
        raise ResumeRefused(f"the burn finished all {len(steps)} steps: there is nothing to resume")
    if not (rates.size and float(np.abs(rates).sum()) > 0):
        raise ResumeRefused("its results hold no reaction rates (it was started before Studio kept them). OpenMC would continue from empty rates and burn without "
                            "transmutation, with no error; start the burn again.")
    done = np.diff(times)
    if not np.allclose(done, steps[:len(done)], rtol=1e-9, atol=0):
        raise ResumeRefused("the steps this burn took differ from the time steps in its project, so it is not the same burn")
    warnings = []
    env = (environ_now if environ_now is not None else {}) or {}
    then = prov.get("environment") or {}
    if env:
        if (then.get("openmc") or {}).get("python") != (env.get("openmc") or {}).get("python"):
            warnings.append(f"OpenMC is {(env.get('openmc') or {}).get('python')} now and was {(then.get('openmc') or {}).get('python')} for the first part of this burn")
        if (then.get("nuclear_data") or {}).get("sha256") != (env.get("nuclear_data") or {}).get("sha256"):
            warnings.append("the nuclear data library is not the one the first part of this burn used (its SHA-256 differs)")
    files = ["model.py", "project.json", "depletion_results.h5"] + [f"openmc_simulation_n{i}.h5" for i in range(entries) if (src / f"openmc_simulation_n{i}.h5").is_file()]
    return {"steps_done": entries - 1, "steps_planned": len(steps), "results_sha256": _sha256_file(src / "depletion_results.h5"), "files": files, "warnings": warnings}


def copy_for_resume(src, dst, plan):
    """Copy what a resumed run starts from into its own folder: the model, the project, the results so far and the per-step statepoints of
    the steps it holds. The stopped run's folder is only read."""
    for name in plan["files"]:
        shutil.copyfile(Path(src) / name, Path(dst) / name)
