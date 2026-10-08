"""depletion_writer.py: a finished depletion run as the depletion.json hand-off record.

`build(data)` is the arithmetic and the checks on plain numbers (no OpenMC import): the durations of the steps, the power each region
had, its burnup (depletion_record's own arithmetic) and two bookkeeping checks. `from_run(folder)` reads a run folder that deplete.py
filled (depletion_results.h5, summary.h5, project.json, provenance.json) with openmc.deplete.Results and hands `build` what it needs.

Units in the record: time steps in days; power in W; burnup in MWd per tonne of initial heavy metal (heavy metal: every nuclide with
Z of 90 or more, so thorium and up); isotopics in atoms in the whole region (not per volume), at the start of the run and after
each step; k with its standard deviation. The record stays on a heavy-metal basis: converting to oxide is the consumer's job.

One bookkeeping check goes in the record's provenance, a ratio that should be 1, with its tolerance and a note when it is not:
  inventory:  the fissions the heavy-metal atoms lost imply (a fission removes one heavy atom; a capture only changes which heavy
              atom it is) against the fissions the power implies (power x time over the fission Q of the fissile nuclides present,
              from the chain). The Q differs by a few percent between nuclides, so the tolerance is 5 percent: it catches a power or a
              unit that is wrong, not a 1 percent error.
A failed check does not stop the record: the record says so, and a reader decides.

One burnable region per record. OpenMC's results file keeps no reaction rates here (the file holds none), so the power of a run
with two or more burnable materials cannot be split between them and no record is written for it; the run itself is unaffected.
"""
import json
import math
from pathlib import Path

from . import depletion_record

SECONDS_PER_DAY = 86400.0
CHECK_TOLERANCE = 0.05
FISSILE = ("U233", "U235", "Pu239", "Pu241")
JOULES_PER_MEV = 1.602176634e-13
LISTED = ("U234", "U235", "U236", "U238", "Np237", "Np239", "Pu238", "Pu239", "Pu240", "Pu241", "Pu242", "Am241", "Am243",
          "Cm242", "Cm244", "Xe135", "Sm149")
UNITS = {"time_steps_days": "days", "power_w": "W", "burnup_mwd_per_tu": "MWd per tonne of initial heavy metal",
         "isotopics": "atoms in the whole region", "heavy_metal_mass_kg": "kg, at the start of the run"}


class WriterError(ValueError):
    """The run cannot be made into a record, and the message says why."""


def _ratio(num, den):
    return num / den if den > 0 and math.isfinite(num) and math.isfinite(den) else None


def build(data) -> dict:
    """The record for plain numbers.

    data: {"times_days": [t0..tN] (N+1 points, from 0), "source_rates_w": [N], "k": [[k, sigma]] * (N+1), "provenance": {...},
           "fission_q_mev": the fission Q of the fissile nuclides present (MeV),
           "regions": [{"name", "cell_ids", "hm_mass_kg", "hm_atoms": [N+1], "isotopics": {nuclide: [N+1]}}]}"""
    times = [float(t) for t in data["times_days"]]
    rates = [float(r) for r in data["source_rates_w"]]
    n = len(rates)
    if len(times) != n + 1:
        raise WriterError(f"{len(times)} time points for {n} steps: expected {n + 1}")
    if not data["regions"]:
        raise WriterError("no burnable region in the run")
    if len(data["regions"]) > 1:
        raise WriterError(f"{len(data['regions'])} burnable materials: OpenMC's results do not keep the power of each, so no record is written")
    durations = [times[i + 1] - times[i] for i in range(n)]
    if any(not d > 0 for d in durations):
        raise WriterError("the time points do not increase")
    reg = data["regions"][0]
    regions = [{"name": reg["name"], "cell_ids": [int(c) for c in reg["cell_ids"]], "heavy_metal_mass_kg": float(reg["hm_mass_kg"]),
                "power_w": list(rates)}]
    isotopics = {reg["name"]: {k: [float(x) for x in v] for k, v in reg["isotopics"].items()}}
    energy_j = sum(p * d * SECONDS_PER_DAY for p, d in zip(rates, durations))
    fissions_by_power = energy_j / (float(data["fission_q_mev"]) * JOULES_PER_MEV)
    lost = float(reg["hm_atoms"][0]) - float(reg["hm_atoms"][-1])
    inventory = _ratio(lost, fissions_by_power)
    check = {"ratio": inventory, "meaning": "heavy-metal atoms lost over the fissions power x time implies", "fission_q_mev": float(data["fission_q_mev"]),
             "tolerance": CHECK_TOLERANCE, "ok": inventory is not None and abs(inventory - 1) <= CHECK_TOLERANCE}
    prov = dict(data.get("provenance") or {})
    prov["units"] = dict(UNITS)
    prov["checks"] = {reg["name"]: {"inventory": check}}
    prov["region_power"] = "the whole source rate"
    prov["notes"] = [] if check["ok"] else [f"region {reg['name']}: the inventory check is {inventory!r}, outside 1 +/- {CHECK_TOLERANCE}"]
    return depletion_record.build_record(durations, regions, k=[[float(a), float(b)] for a, b in data["k"]], isotopics=isotopics,
                                         provenance=prov)


def _heavy(nuclide):
    """True for thorium and heavier: the nuclide name's element has Z of 90 or more."""
    import openmc.data
    name = "".join(ch for ch in nuclide if ch.isalpha() or ch == "_")
    name = name.split("_")[0]
    return openmc.data.ATOMIC_NUMBER.get(name, 0) >= 90 if hasattr(openmc.data, "ATOMIC_NUMBER") else False


def read_run(folder, cells=None, names=None):
    """The numbers `build` wants, from a run folder. `cells` ({material id: [cell ids]}) and `names` ({material id: name}) replace what
    summary.h5 would give (for runs that have no summary, such as a test)."""
    import numpy as np
    import openmc
    import openmc.data
    import openmc.deplete as dep

    folder = Path(folder)
    results = dep.Results(str(folder / "depletion_results.h5"))
    times = [float(t) for t in results.get_times("d")]
    _, k = results.get_keff(time_units="d")
    rates = [float(x) for x in results.get_source_rates()]
    if cells is None or names is None:
        summary = openmc.Summary(str(folder / "summary.h5"))
        cells, names = dict(cells or {}), dict(names or {})
        for c in summary.geometry.get_all_cells().values():
            fill = c.fill
            if isinstance(fill, openmc.Material):
                cells.setdefault(str(fill.id), []).append(c.id)
        for m in summary.materials:
            names.setdefault(str(m.id), m.name or f"material {m.id}")
    chain = dep.Chain.from_xml(_chain_path(folder))
    mats = list(results[0].index_mat)
    if len(mats) != 1:
        raise WriterError(f"{len(mats)} burnable materials: OpenMC's results do not keep the power of each, so no record is written")
    mat_id = mats[0]
    nuclides = list(results[0].index_nuc)
    heavy = [n for n in nuclides if _heavy(n)]
    atoms = {n: results.get_atoms(mat_id, n, nuc_units="atoms", time_units="d")[1] for n in heavy}
    hm_atoms = np.sum([atoms[n] for n in heavy], axis=0)
    mass_g = sum(float(atoms[n][0]) * openmc.data.atomic_mass(n) for n in heavy) / openmc.data.AVOGADRO
    present = [n for n in FISSILE if n in atoms and float(atoms[n][-1]) > 0]
    qs = [r.Q for n in present for r in chain[n].reactions if r.type == "fission"]
    if not qs:
        raise WriterError("no fissile nuclide (U-233, U-235, Pu-239, Pu-241) in the run, so the inventory check has no fission Q")
    regions = [{"name": names.get(str(mat_id), f"material {mat_id}"), "cell_ids": cells.get(str(mat_id)) or [1],
                "hm_mass_kg": mass_g / 1000.0, "hm_atoms": hm_atoms.tolist(),
                "isotopics": {n: atoms[n].tolist() for n in LISTED if n in atoms}}]
    return {"times_days": times, "source_rates_w": rates, "k": k.tolist(), "regions": regions,
            "fission_q_mev": sum(qs) / len(qs) / 1e6}


def _chain_path(folder):
    rec = json.loads((Path(folder) / "provenance.json").read_text(encoding="utf-8"))
    return rec["depletion"]["chain"]["path"]


def from_run(folder, **overrides):
    """Read a finished depletion run, build its record and write <folder>/depletion.json. Returns the record."""
    folder = Path(folder)
    data = read_run(folder, **overrides)
    prov = json.loads((folder / "provenance.json").read_text(encoding="utf-8"))
    settings = prov.get("settings") or {}
    data["provenance"] = {"run": folder.name, "environment": prov.get("environment"), "chain": (prov.get("depletion") or {}).get("chain"),
                          "integrator": settings.get("depIntegrator"), "chain_level": settings.get("depReduce"),
                          "power_density_w_per_g": settings.get("depPower"), "particles": settings.get("particles"),
                          "batches": settings.get("batches"), "seed": settings.get("seed"),
                          "files": prov.get("files")}
    record = build(data)
    depletion_record.write(folder, record)
    return record
