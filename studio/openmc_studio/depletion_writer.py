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

A run that was stopped or failed after some steps still gets a record of the steps it finished, marked incomplete (provenance.complete,
steps_done, steps_planned): a half-burned fuel is a state someone may want, and the record says plainly how far it got.

One region per burnable material. OpenMC's results file keeps no reaction rates here (the file holds none), so the power of each of
several burnable materials is not in it. model.py's prepare_depletion therefore adds a kappa-fission tally per burnable material, and
the transport statepoint of each step (openmc_simulation_n<step>.h5, the solve at the beginning of that step: its k-eff equals the
results file's, which is checked) gives each material's share of the source rate. That is the beginning-of-step flux of every step: exact
for the predictor, an approximation for the integrators that average several solves. The record says so (provenance.region_power).
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
         "isotopics": "atoms in the whole region", "heavy_metal_mass_kg": "kg, at the start of the run",
         "heavy_metal_atoms_start": "atoms of every nuclide with Z of 90 or more in the whole region, at the start of the run"}


class WriterError(ValueError):
    """The run cannot be made into a record, and the message says why."""


def _ratio(num, den):
    return num / den if den > 0 and math.isfinite(num) and math.isfinite(den) else None


def common_steps(times, rates, k):
    """How many steps all of the arrays cover: a run that was stopped leaves arrays of different lengths."""
    return max(0, min(len(rates), len(times) - 1, len(k) - 1))


def build(data) -> dict:
    """The record for plain numbers.

    data: {"times_days": [t0..tN] (N+1 points, from 0), "source_rates_w": [N], "k": [[k, sigma]] * (N+1), "provenance": {...},
           "fission_q_mev": the fission Q of the fissile nuclides present (MeV), "steps_planned": the number of steps asked for (optional),
           "regions": [{"name", "cell_ids", "hm_mass_kg", "hm_atoms": [N+1], "isotopics": {nuclide: [N+1]},
                        "power_fraction": [N] (the share of the source rate, from the second burnable material on; one region has all of it)}]}"""
    times = [float(t) for t in data["times_days"]]
    rates = [float(r) for r in data["source_rates_w"]]
    n = len(rates)
    if len(times) != n + 1:
        raise WriterError(f"{len(times)} time points for {n} steps: expected {n + 1}")
    if not data["regions"]:
        raise WriterError("no burnable region in the run")
    names = [r["name"] for r in data["regions"]]
    if len(set(names)) != len(names):
        raise WriterError(f"two burnable materials share the name {sorted(n for n in names if names.count(n) > 1)[0]!r}")
    many = len(data["regions"]) > 1
    shares = [[float(x) for x in (reg.get("power_fraction") or [1.0] * n)] for reg in data["regions"]]
    if any(len(sh) != n for sh in shares):
        raise WriterError("a region's power shares do not cover every step")
    if any(abs(sum(sh[i] for sh in shares) - 1.0) > 1e-9 for i in range(n)):
        raise WriterError("the regions' shares of the power do not add up to the source rate")
    durations = [times[i + 1] - times[i] for i in range(n)]
    if any(not d > 0 for d in durations):
        raise WriterError("the time points do not increase")
    regions, isotopics, checks, notes, hm_start = [], {}, {}, [], {}
    for reg, share in zip(data["regions"], shares):
        power = [p * f for p, f in zip(rates, share)]
        regions.append({"name": reg["name"], "cell_ids": [int(c) for c in reg["cell_ids"]], "heavy_metal_mass_kg": float(reg["hm_mass_kg"]),
                        "power_w": power})
        isotopics[reg["name"]] = {k: [float(x) for x in v] for k, v in reg["isotopics"].items()}
        hm_start[reg["name"]] = float(reg["hm_atoms"][0])
        energy_j = sum(p * d * SECONDS_PER_DAY for p, d in zip(power, durations))
        q = float(reg.get("fission_q_mev") or data["fission_q_mev"])
        fissions_by_power = energy_j / (q * JOULES_PER_MEV)
        lost = float(reg["hm_atoms"][0]) - float(reg["hm_atoms"][-1])
        inventory = _ratio(lost, fissions_by_power)
        check = {"ratio": inventory, "meaning": "heavy-metal atoms lost over the fissions power x time implies", "fission_q_mev": q,
                 "tolerance": CHECK_TOLERANCE, "ok": inventory is not None and abs(inventory - 1) <= CHECK_TOLERANCE}
        checks[reg["name"]] = {"inventory": check}
        if not check["ok"]:
            notes.append(f"region {reg['name']}: the inventory check is {inventory!r}, outside 1 +/- {CHECK_TOLERANCE}")
    prov = dict(data.get("provenance") or {})
    prov["units"] = dict(UNITS)
    prov["checks"] = checks
    prov["heavy_metal_atoms_start"] = hm_start  # the whole starting heavy metal, so a reader need not rebuild it from the listed nuclides
    planned = data.get("steps_planned")
    prov["complete"] = planned is None or n >= int(planned)
    prov["steps_done"] = n
    if planned is not None:
        prov["steps_planned"] = int(planned)
    prov["region_power"] = ("the source rate split by each material's kappa-fission tally of the transport solve at the beginning of each step"
                            if many else "the whole source rate")
    prov["notes"] = notes
    if not prov["complete"]:
        prov["notes"].append(f"incomplete: {n} of {int(planned)} steps finished")
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
    n = common_steps(times, rates, k)
    if n < 1:
        raise WriterError("no step finished, so there is nothing to record")
    times, rates, k = times[:n + 1], rates[:n], k[:n + 1]
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
    if not mats:
        raise WriterError("no burnable material in the run")
    shares = _power_shares(folder, mats, results, n) if len(mats) > 1 else {mats[0]: None}
    nuclides = list(results[0].index_nuc)
    heavy = [n for n in nuclides if _heavy(n)]
    wanted = heavy + [n for n in LISTED if n in nuclides and n not in heavy]  # the listed fission products as well as the heavy metal
    regions = []
    for mat_id in mats:
        atoms = {n: results.get_atoms(mat_id, n, nuc_units="atoms", time_units="d")[1][:len(times)] for n in wanted}
        hm_atoms = np.sum([atoms[n] for n in heavy], axis=0)
        mass_g = sum(float(atoms[n][0]) * openmc.data.atomic_mass(n) for n in heavy) / openmc.data.AVOGADRO
        qs = _fission_qs(chain, atoms, heavy)
        if not qs:
            raise WriterError("no nuclide with a fission reaction in the chain is left in the region, so the inventory check has no fission Q")
        name = names.get(str(mat_id), f"material {mat_id}")
        if sum(1 for m in mats if names.get(str(m), f"material {m}") == name) > 1:
            name = f"{name} (material {mat_id})"
        reg = {"name": name, "cell_ids": cells.get(str(mat_id)) or [1], "hm_mass_kg": mass_g / 1000.0, "hm_atoms": hm_atoms.tolist(),
               "isotopics": {n: atoms[n].tolist() for n in LISTED if n in atoms}, "fission_q_mev": sum(qs) / len(qs) / 1e6}
        if shares[mat_id] is not None:
            reg["power_fraction"] = shares[mat_id]
        regions.append(reg)
    return {"times_days": times, "source_rates_w": rates, "k": k.tolist(), "regions": regions,
            "fission_q_mev": regions[0]["fission_q_mev"]}


def _fission_qs(chain, atoms, heavy):
    """The fission Q values (eV) of the nuclides that can fission and are there at the end: U-233, U-235, Pu-239 and Pu-241 when present; when
    none is (a fertile blanket that has bred nothing the chain keeps), whichever heavy nuclide left has a fission reaction in the chain."""
    def qs_of(names):
        return [r.Q for n in names if n in chain.nuclide_dict for r in chain[n].reactions if r.type == "fission"]
    qs = qs_of([n for n in FISSILE if n in atoms and float(atoms[n][-1]) > 0])
    return qs or qs_of([n for n in heavy if float(atoms[n][-1]) > 0])


POWER_TALLY = "Depletion power split (kappa-fission per burnable material)"


def _power_shares(folder, mats, results, n):
    """{material id: [share of the source rate in step 0..n-1]} from the kappa-fission tally in each step's transport statepoint."""
    import openmc

    folder = Path(folder)
    _, k = results.get_keff(time_units="d")
    shares = {m: [] for m in mats}
    for i in range(n):
        path = folder / f"openmc_simulation_n{i}.h5"
        if not path.is_file():
            raise WriterError(f"{len(mats)} burnable materials, and the transport statepoint of step {i + 1} ({path.name}) is missing, so their power cannot be split")
        with openmc.StatePoint(str(path), autolink=False) as sp:
            tally = next((t for t in sp.tallies.values() if t.name == POWER_TALLY), None)
            if tally is None:
                raise WriterError(f"{len(mats)} burnable materials, and {path.name} has no power-split tally (was model.py written by an older Studio?)")
            if abs(sp.keff.nominal_value - float(k[i][0])) > 1e-6:
                raise WriterError(f"{path.name} is not the solve step {i + 1} began with (k-eff {sp.keff.nominal_value:.6f}, the results file has {float(k[i][0]):.6f})")
            ids = [int(b) for b in tally.filters[0].bins]
            kappa = {mid: float(v) for mid, v in zip(ids, tally.mean.ravel())}
        missing = [m for m in mats if int(m) not in kappa]
        total = sum(kappa.get(int(m), 0.0) for m in mats)
        if missing or not total > 0:
            raise WriterError(f"{path.name}: no fission power in the burnable materials {missing or ''}, so the power cannot be split")
        for m in mats:
            shares[m].append(kappa[int(m)] / total)
    return shares


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
    try:
        data["steps_planned"] = len([t for t in str(settings.get("depSteps", "")).split(",") if t.strip()]) or None
    except (TypeError, ValueError):
        data["steps_planned"] = None
    record = build(data)
    depletion_record.write(folder, record)
    return record
