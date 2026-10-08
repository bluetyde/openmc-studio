"""depletion.json: hand-off record of burnup arithmetic and power history for fuel performance.

Provides burnup arithmetic, oxide basis conversion, record construction,
validation against schema 'studio.depletion/0.1', and reading/writing
the depletion.json hand-off record.
"""
import hashlib
import json
import math
from pathlib import Path

SCHEMA = "studio.depletion/0.1"
TOP_LEVEL_KEYS = {"schema", "id", "time_steps_days", "regions", "k", "isotopics", "provenance"}
REGION_KEYS = {"name", "cell_ids", "heavy_metal_mass_kg", "power_w", "burnup_mwd_per_tu"}


class RecordError(ValueError):
    """Raised for any invalid depletion record or burnup input."""
    pass


def burnup_mwd_per_tu(time_steps_days, power_w, heavy_metal_mass_kg) -> list[float]:
    """Cumulative burnup in MWd/tU at the end of each time step."""
    if not isinstance(time_steps_days, list):
        raise RecordError("time_steps_days: expected list")
    if len(time_steps_days) == 0:
        raise RecordError("time_steps_days: list must not be empty")
    for i, d in enumerate(time_steps_days):
        if not isinstance(d, (int, float)) or isinstance(d, bool):
            raise RecordError(f"time_steps_days[{i}]: expected number, got {type(d).__name__}")
        if not math.isfinite(d):
            raise RecordError(f"time_steps_days[{i}]: expected finite number, got {d}")
        if d <= 0:
            raise RecordError(f"time_steps_days[{i}]: duration must be > 0, got {d}")

    if not isinstance(power_w, list):
        raise RecordError("power_w: expected list")
    if len(power_w) != len(time_steps_days):
        raise RecordError(f"power_w: length {len(power_w)}, expected {len(time_steps_days)}")
    for i, p in enumerate(power_w):
        if not isinstance(p, (int, float)) or isinstance(p, bool):
            raise RecordError(f"power_w[{i}]: expected number, got {type(p).__name__}")
        if not math.isfinite(p):
            raise RecordError(f"power_w[{i}]: expected finite number, got {p}")
        if p < 0:
            raise RecordError(f"power_w[{i}]: power must be >= 0, got {p}")

    if not isinstance(heavy_metal_mass_kg, (int, float)) or isinstance(heavy_metal_mass_kg, bool):
        raise RecordError(f"heavy_metal_mass_kg: expected number, got {type(heavy_metal_mass_kg).__name__}")
    if not math.isfinite(heavy_metal_mass_kg):
        raise RecordError(f"heavy_metal_mass_kg: expected finite number, got {heavy_metal_mass_kg}")
    if heavy_metal_mass_kg <= 0:
        raise RecordError(f"heavy_metal_mass_kg: mass must be > 0, got {heavy_metal_mass_kg}")

    hm_tonnes = float(heavy_metal_mass_kg) / 1000.0
    cum_mwd = 0.0
    burnup = []
    for d, p in zip(time_steps_days, power_w):
        cum_mwd += (float(p) / 1e6) * float(d)
        burnup.append(float(cum_mwd / hm_tonnes))
    return burnup


def to_oxide_basis(burnup, hm_mass_fraction_of_oxide):
    """Convert burnup from MWd/tU to MWd per tonne of oxide fuel using fraction f."""
    f = hm_mass_fraction_of_oxide
    if not isinstance(f, (int, float)) or isinstance(f, bool) or not math.isfinite(f) or not (0 < f <= 1):
        raise RecordError(f"hm_mass_fraction_of_oxide: expected finite number in (0, 1], got {f}")

    if isinstance(burnup, bool):
        raise RecordError("burnup: expected number or list of numbers, got bool")
    if isinstance(burnup, (int, float)):
        if not math.isfinite(burnup):
            raise RecordError(f"burnup: expected finite number, got {burnup}")
        return burnup * f
    if isinstance(burnup, list):
        res = []
        for i, b in enumerate(burnup):
            if not isinstance(b, (int, float)) or isinstance(b, bool) or not math.isfinite(b):
                raise RecordError(f"burnup[{i}]: expected finite number, got {b}")
            res.append(b * f)
        return res
    raise RecordError(f"burnup: expected number or list of numbers, got {type(burnup).__name__}")


def record_id(record) -> str:
    """The id of a record: the SHA-256 of its canonical JSON (sorted keys, no spaces) with the id itself left out. Two records
    with the same numbers have the same id, and any change to a number changes it. FEED's case names a burnup by this id."""
    body = {k: v for k, v in record.items() if k != "id"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def validate(record) -> None:
    """Validate a depletion record against the studio.depletion/0.1 schema."""
    if not isinstance(record, dict):
        raise RecordError("record: expected object")

    for k in record:
        if k not in TOP_LEVEL_KEYS:
            raise RecordError(f"{k}: unknown top-level key")

    if "schema" not in record:
        raise RecordError("schema: missing required key")
    if record["schema"] != SCHEMA:
        raise RecordError(f"schema: expected {SCHEMA!r}, got {record['schema']!r}")
    if "id" in record and record["id"] != record_id(record):
        raise RecordError("id: does not match the record (it was changed after the id was made)")

    if "time_steps_days" not in record:
        raise RecordError("time_steps_days: missing required key")
    ts = record["time_steps_days"]
    if not isinstance(ts, list):
        raise RecordError("time_steps_days: expected list")
    if len(ts) == 0:
        raise RecordError("time_steps_days: list must not be empty")
    for i, d in enumerate(ts):
        if not isinstance(d, (int, float)) or isinstance(d, bool):
            raise RecordError(f"time_steps_days[{i}]: expected number, got {type(d).__name__}")
        if not math.isfinite(d):
            raise RecordError(f"time_steps_days[{i}]: expected finite number, got {d}")
        if d <= 0:
            raise RecordError(f"time_steps_days[{i}]: duration must be > 0, got {d}")
    n = len(ts)

    if "regions" not in record:
        raise RecordError("regions: missing required key")
    regs = record["regions"]
    if not isinstance(regs, list):
        raise RecordError("regions: expected list")
    if len(regs) == 0:
        raise RecordError("regions: list must not be empty")

    seen_names = set()
    for i, r in enumerate(regs):
        if not isinstance(r, dict):
            raise RecordError(f"regions[{i}]: expected object")
        for k_r in r:
            if k_r not in REGION_KEYS:
                raise RecordError(f"regions[{i}].{k_r}: unknown key")
        for k_r in ("name", "cell_ids", "heavy_metal_mass_kg", "power_w", "burnup_mwd_per_tu"):
            if k_r not in r:
                raise RecordError(f"regions[{i}].{k_r}: missing required key")

        name = r["name"]
        if not isinstance(name, str) or len(name) == 0:
            raise RecordError(f"regions[{i}].name: must be a non-empty string")
        if name in seen_names:
            raise RecordError(f"regions[{i}].name: duplicate region name {name!r}")
        seen_names.add(name)

        cids = r["cell_ids"]
        if not isinstance(cids, list):
            raise RecordError(f"regions[{i}].cell_ids: expected list")
        if len(cids) == 0:
            raise RecordError(f"regions[{i}].cell_ids: list must not be empty")
        seen_cids = set()
        for j, cid in enumerate(cids):
            if not isinstance(cid, int) or isinstance(cid, bool):
                raise RecordError(f"regions[{i}].cell_ids[{j}]: expected integer, got {type(cid).__name__}")
            if cid < 1:
                raise RecordError(f"regions[{i}].cell_ids[{j}]: cell id must be >= 1, got {cid}")
            if cid in seen_cids:
                raise RecordError(f"regions[{i}].cell_ids[{j}]: duplicate cell id {cid}")
            seen_cids.add(cid)

        mass = r["heavy_metal_mass_kg"]
        if not isinstance(mass, (int, float)) or isinstance(mass, bool):
            raise RecordError(f"regions[{i}].heavy_metal_mass_kg: expected number, got {type(mass).__name__}")
        if not math.isfinite(mass):
            raise RecordError(f"regions[{i}].heavy_metal_mass_kg: expected finite number, got {mass}")
        if mass <= 0:
            raise RecordError(f"regions[{i}].heavy_metal_mass_kg: mass must be > 0, got {mass}")

        pw = r["power_w"]
        if not isinstance(pw, list):
            raise RecordError(f"regions[{i}].power_w: expected list")
        if len(pw) != n:
            raise RecordError(f"regions[{i}].power_w: length {len(pw)}, expected {n}")
        for j, p in enumerate(pw):
            if not isinstance(p, (int, float)) or isinstance(p, bool):
                raise RecordError(f"regions[{i}].power_w[{j}]: expected number, got {type(p).__name__}")
            if not math.isfinite(p):
                raise RecordError(f"regions[{i}].power_w[{j}]: expected finite number, got {p}")
            if p < 0:
                raise RecordError(f"regions[{i}].power_w[{j}]: power must be >= 0, got {p}")

        bu = r["burnup_mwd_per_tu"]
        if not isinstance(bu, list):
            raise RecordError(f"regions[{i}].burnup_mwd_per_tu: expected list")
        if len(bu) != n:
            raise RecordError(f"regions[{i}].burnup_mwd_per_tu: length {len(bu)}, expected {n}")
        for j, b in enumerate(bu):
            if not isinstance(b, (int, float)) or isinstance(b, bool):
                raise RecordError(f"regions[{i}].burnup_mwd_per_tu[{j}]: expected number, got {type(b).__name__}")
            if not math.isfinite(b):
                raise RecordError(f"regions[{i}].burnup_mwd_per_tu[{j}]: expected finite number, got {b}")
            if b < 0:
                raise RecordError(f"regions[{i}].burnup_mwd_per_tu[{j}]: burnup must be >= 0, got {b}")
            if j > 0 and b < bu[j - 1]:
                raise RecordError(f"regions[{i}].burnup_mwd_per_tu[{j}]: burnup must be non-decreasing, got {b} < {bu[j - 1]}")

        # Consistency rule
        hm_tonnes = float(mass) / 1000.0
        cum_mwd = 0.0
        for j in range(n):
            cum_mwd += (float(pw[j]) / 1e6) * float(ts[j])
            expected_bu = cum_mwd / hm_tonnes
            if not math.isclose(bu[j], expected_bu, rel_tol=1e-9, abs_tol=1e-12):
                raise RecordError(
                    f"regions[{i}].burnup_mwd_per_tu[{j}]: burnup {bu[j]} inconsistent with power history (expected {expected_bu})"
                )

    if "k" in record:
        k_val = record["k"]
        if not isinstance(k_val, list):
            raise RecordError("k: expected list")
        if len(k_val) != n + 1:
            raise RecordError(f"k: length {len(k_val)}, expected {n + 1}")
        for j, pair in enumerate(k_val):
            if not isinstance(pair, list) or len(pair) != 2:
                raise RecordError(f"k[{j}]: expected pair [value, sigma] of length 2")
            val, sig = pair[0], pair[1]
            if not isinstance(val, (int, float)) or isinstance(val, bool) or not math.isfinite(val) or val <= 0:
                raise RecordError(f"k[{j}][0]: value must be finite number > 0, got {val}")
            if not isinstance(sig, (int, float)) or isinstance(sig, bool) or not math.isfinite(sig) or sig < 0:
                raise RecordError(f"k[{j}][1]: sigma must be finite number >= 0, got {sig}")

    if "isotopics" in record:
        iso = record["isotopics"]
        if not isinstance(iso, dict):
            raise RecordError("isotopics: expected object")
        for rname, nuclides in iso.items():
            if rname not in seen_names:
                raise RecordError(f"isotopics.{rname}: unknown region {rname!r}")
            if not isinstance(nuclides, dict):
                raise RecordError(f"isotopics.{rname}: expected object")
            for nuc, vals in nuclides.items():
                if not isinstance(nuc, str) or len(nuc) == 0:
                    raise RecordError(f"isotopics.{rname}: nuclide name must be a non-empty string")
                if not isinstance(vals, list):
                    raise RecordError(f"isotopics.{rname}.{nuc}: expected list")
                if len(vals) != n + 1:
                    raise RecordError(f"isotopics.{rname}.{nuc}: length {len(vals)}, expected {n + 1}")
                for j, v in enumerate(vals):
                    if not isinstance(v, (int, float)) or isinstance(v, bool):
                        raise RecordError(f"isotopics.{rname}.{nuc}[{j}]: expected number, got {type(v).__name__}")
                    if not math.isfinite(v):
                        raise RecordError(f"isotopics.{rname}.{nuc}[{j}]: expected finite number, got {v}")
                    if v < 0:
                        raise RecordError(f"isotopics.{rname}.{nuc}[{j}]: amount must be >= 0, got {v}")

    if "provenance" not in record:
        raise RecordError("provenance: missing required key")
    if not isinstance(record["provenance"], dict):
        raise RecordError(f"provenance: expected object, got {type(record['provenance']).__name__}")


def build_record(time_steps_days, regions, k=None, isotopics=None, provenance=None) -> dict:
    """Construct and validate a depletion record, calculating burnup for each region."""
    if not isinstance(regions, list):
        raise RecordError("regions: expected list")
    built_regions = []
    for i, r in enumerate(regions):
        if not isinstance(r, dict):
            raise RecordError(f"regions[{i}]: expected object")
        reg = dict(r)
        if "power_w" not in reg:
            raise RecordError(f"regions[{i}].power_w: missing required key")
        if "heavy_metal_mass_kg" not in reg:
            raise RecordError(f"regions[{i}].heavy_metal_mass_kg: missing required key")
        bu = burnup_mwd_per_tu(time_steps_days, reg["power_w"], reg["heavy_metal_mass_kg"])
        reg["burnup_mwd_per_tu"] = bu
        built_regions.append(reg)

    record = {
        "schema": SCHEMA,
        "time_steps_days": time_steps_days,
        "regions": built_regions,
    }
    if k is not None:
        record["k"] = k
    if isotopics is not None:
        record["isotopics"] = isotopics
    record["provenance"] = {} if provenance is None else provenance
    validate(record)
    record = dict(record, id=record_id(record))
    validate(record)
    return record


def write(folder, record) -> Path:
    """Validate and write record to <folder>/depletion.json."""
    validate(record)
    folder_path = Path(folder)
    if not folder_path.is_dir():
        raise FileNotFoundError(f"Directory not found: {folder_path}")
    target = folder_path / "depletion.json"
    content = json.dumps(record, indent=1) + "\n"
    target.write_bytes(content.encode("utf-8"))
    return target


def read(folder) -> dict:
    """Read and validate <folder>/depletion.json."""
    target = Path(folder) / "depletion.json"
    if not target.is_file():
        raise FileNotFoundError(f"File not found: {target}")
    try:
        raw = target.read_bytes()
        text = raw.decode("utf-8")
        data = json.loads(text)
    except (json.JSONDecodeError, UnicodeDecodeError) as err:
        raise RecordError(f"depletion.json: not valid JSON ({err})") from err
    validate(data)
    return data
