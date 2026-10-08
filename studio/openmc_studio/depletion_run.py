"""What a depletion run needs from the server: the chain file, the generated deplete.py and a record of the chain.

A project with Settings > Depletion on is run by `python deplete.py`, not `python model.py`. deplete.py is written by
depletion_script.build_script beside model.py in the run folder; it loads model.py (which defines the burnable materials and
prepare_depletion, the function that measures their volumes) and burns the fuel with openmc.deplete. The settings come from the
project, which the page has already checked (prerun_check.py refuses a bad one before a run folder exists).
"""
import hashlib
import os
from pathlib import Path

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


def script_text(project, model_path, chain_file):
    """The text of deplete.py for a project that asks for depletion."""
    st = project["settings"]
    return depletion_script.build_script({
        "model_path": str(model_path), "chain_file": str(chain_file), "integrator": st["depIntegrator"],
        "time_steps_days": steps_days(st["depSteps"]), "power_density": float(st["depPower"]),
        "reduce_chain_level": int(st["depReduce"]), "prepare": True})


def chain_record(chain_file):
    """What the run record keeps about the chain: where it was, how big and which file exactly."""
    h = hashlib.sha256()
    with open(chain_file, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return {"path": str(chain_file), "size": Path(chain_file).stat().st_size, "sha256": h.hexdigest()}
