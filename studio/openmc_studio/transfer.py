"""The receiving end of SEED's return transfers: a fuel temperature into an OpenMC Studio project.

    python -m openmc_studio.headless transfer          (a seed.transfer-request/0.2 on stdin, one reply on stdout)

Field `fuel-temperature`. What it sets: the **material temperature** (`Material.temperature` in OpenMC, the "Temperature" field of a Studio
material, in kelvin) of the named project materials, and nothing else. It applies to every part that uses the material: Studio has no per-cell
temperature, and one material has one temperature, so a temperature that varies along the fuel needs one material per axial zone.

What the number must be: the **volume-mean temperature of the fuel region** the material fills, in kelvin, absolute (not normalized, not a
change, not Celsius). It is NOT an effective Doppler temperature: Studio does not turn one into the other, and a sender that has an effective
temperature must say so in the recipe (`mapping.spatial.meaning`), which makes this field refuse it. The temperature is used as given for the
cross sections (OpenMC interpolates between the library's temperatures); the mapping is a pure function of (recipe, source data, target input)
with no randomness, and the reply is the whole new project text, written the way Studio writes it (JSON.stringify(project, null, 2); a final
newline is kept if the input had one), so equal inputs give byte-identical outputs. model.py is not part of the reply: SEED regenerates
it from the new project text with Studio's own generator, as it does at every validate and run.

Refusals (each with a code, the field and a message; the reply carries all it found up to 20, never a partial project):
  E_SCHEMA_INVALID    the request, the source data or the target project is not what it says
  E_RECIPE_INVALID    the recipe lacks a part, has an unknown key, or names a material the project does not have
  E_UNSUPPORTED       another field, a time series, an effective Doppler temperature
  E_UNITS             not kelvin or not the temperature dimension, or a normalization claimed (a temperature is absolute)
  E_COVERAGE          a mapped material has no row in the source (nothing is extrapolated or defaulted)
  E_NUMERIC           a value that is not a finite number
  E_TEMPERATURE_RANGE a value outside what the cross-section data supports (250 K to 2500 K for ENDF/B-VIII.0 neutron data, narrower for a
                      material with a thermal scattering table; the recipe's applicability range can only narrow it)
"""
import json
import math
from decimal import Decimal

REQUEST_SCHEMA = "seed.transfer-request/0.2"
RECIPE_SCHEMA = "seed.transfer-recipe/0.2"
FIELD = "fuel-temperature"
APP = "openmc-studio"
MEANING = "volume-mean"

# Temperatures (K) the ENDF/B-VIII.0 HDF5 library holds, read from the files in /root/nuclear_data/endfb-viii.0-hdf5 (2026-10-25):
# every neutron file has 250, 294, 600, 900, 1200 and 2500 K, so an interpolating run can use 250 K to 2500 K. The thermal scattering tables
# are narrower; a name not listed here is refused (its range is not known), not guessed.
NEUTRON_RANGE = (250.0, 2500.0)
THERMAL_RANGE = {
    "c_U_in_UO2": (296.0, 1200.0),
    "c_O_in_UO2": (296.0, 1200.0),
    "c_Graphite": (296.0, 2000.0),
    "c_H_in_H2O": (284.0, 800.0),
}

DESCRIPTION = {
    "field": FIELD,
    "accepts": [{"dimension": "temperature", "normalization": "none"}],
    "parameters": {
        "sets": "the material temperature (Material.temperature, K) of each project material named in mapping.spatial.materials; every part with that material gets it. Studio has no per-cell temperature",
        "means": "the volume-mean fuel temperature of the region the material fills, absolute, in K; not an effective Doppler temperature (recipe mapping.spatial.meaning must be 'volume-mean')",
        "spatial": "meaning ('volume-mean'), materials [{material: a project material id, region: the source row label (omit for a scalar source with one material)}], columns? {region, value}",
        "source": "a scalar (one material) or a table with one row per region: a label column, one value column in K (the std column, if any, is recorded, not used)",
        "units": "units.to and the source unit are K; normalization.kind is none",
        "range": {"neutronDataK": list(NEUTRON_RANGE), "thermalScatteringK": {k: list(v) for k, v in THERMAL_RANGE.items()}, "library": "ENDF/B-VIII.0"},
        "time": "steady only",
        "produces": "the new project text; model.py is regenerated from it by SEED",
    },
}

SPATIAL_KEYS = {"meaning", "materials", "columns"}
COLUMN_KEYS = {"region", "value"}


def _refuse(code, field, message):
    return {"ok": False, "errors": [{"code": code, "field": field, "message": message}]}


def _is_obj(x):
    return isinstance(x, dict)


def _finite(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _nonempty(x):
    return isinstance(x, str) and x.strip() != ""


# ---- Studio's JSON text: JSON.stringify(project, null, 2) ----------------------------------------------------------------------

def js_number(v):
    """A number the way JavaScript's Number.prototype.toString writes it (ECMAScript Number::toString), so a file Studio wrote is reproduced exactly."""
    if isinstance(v, bool):
        raise TypeError("bool is not a number")
    if isinstance(v, int):
        if abs(v) < 10 ** 21:
            return str(v)
        v = float(v)
    if not math.isfinite(v):
        raise ValueError("not finite")
    if v == 0:
        return "0"
    sign = "-" if v < 0 else ""
    _, digs, exp = Decimal(repr(abs(v))).as_tuple()       # repr gives the shortest digits that round-trip, which is what JavaScript uses
    digits = "".join(map(str, digs))
    stripped = digits.rstrip("0")
    exp += len(digits) - len(stripped)
    digits = stripped or "0"
    k = len(digits)
    n = k + exp                                           # the decimal point sits after n digits
    if k <= n <= 21:
        out = digits + "0" * (n - k)
    elif 0 < n <= 21:
        out = digits[:n] + "." + digits[n:]
    elif -6 < n <= 0:
        out = "0." + "0" * (-n) + digits
    else:
        e = n - 1
        out = digits[0] + ("." + digits[1:] if k > 1 else "") + "e" + ("+" if e >= 0 else "-") + str(abs(e))
    return sign + out


def studio_json(value, indent=0):
    """JSON.stringify(value, null, 2), for the types a project holds."""
    pad, pad1 = "  " * indent, "  " * (indent + 1)
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, (int, float)):
        return js_number(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        if not value:
            return "[]"
        return "[\n" + ",\n".join(pad1 + studio_json(v, indent + 1) for v in value) + "\n" + pad + "]"
    if isinstance(value, dict):
        if not value:
            return "{}"
        return "{\n" + ",\n".join(pad1 + json.dumps(str(k), ensure_ascii=False) + ": " + studio_json(v, indent + 1) for k, v in value.items()) + "\n" + pad + "}"
    raise TypeError(f"cannot write {type(value).__name__}")


def _no_constant(name):
    raise ValueError(f"{name} is not valid JSON")


def _loads(text):
    return json.loads(text, parse_constant=_no_constant)


# ---- the mapping ---------------------------------------------------------------------------------------------------------------

def _allowed_range(material, recipe):
    """(lo, hi, why) for one project material, or an error string when its thermal scattering table's range is not known."""
    lo, hi = NEUTRON_RANGE
    why = ["ENDF/B-VIII.0 neutron data " + _fmt_range(lo, hi)]
    sab = material.get("sab")
    names = [s for s in str(sab).replace(",", " ").split()] if sab else []
    for name in names:
        if name not in THERMAL_RANGE:
            return None, None, f"the thermal scattering table {name} of material {material.get('name') or material.get('id')} has no known temperature range, so no temperature is accepted for it"
        a, b = THERMAL_RANGE[name]
        lo, hi = max(lo, a), min(hi, b)
        why.append(f"{name} {_fmt_range(a, b)}")
    app = recipe.get("applicability")
    rng = app.get("range") if _is_obj(app) else None
    if _is_obj(rng):
        if _finite(rng.get("min")):
            lo = max(lo, float(rng["min"]))
        if _finite(rng.get("max")):
            hi = min(hi, float(rng["max"]))
        why.append("the recipe's applicability range")
    return lo, hi, "; ".join(why)


def _fmt_range(lo, hi):
    return f"{js_number(lo)} K to {js_number(hi)} K"


def transfer(request):
    """The whole mapping. `request` is the parsed seed.transfer-request/0.2. Returns {"ok": True, "output": {"content"}, "checks"} or a refusal."""
    if not _is_obj(request) or request.get("schema") != REQUEST_SCHEMA:
        return _refuse("E_SCHEMA_INVALID", "/schema", f"not a {REQUEST_SCHEMA} request")
    recipe = request.get("recipe")
    if not _is_obj(recipe) or recipe.get("schema") != RECIPE_SCHEMA or not _nonempty(recipe.get("recipeId")):
        return _refuse("E_RECIPE_INVALID", "/recipe", f"not a {RECIPE_SCHEMA} recipe with a recipe id")
    target = recipe.get("target")
    if not _is_obj(target) or target.get("app") != APP:
        return _refuse("E_RECIPE_INVALID", "/recipe/target/app", f"the recipe's target is not {APP}")
    if target.get("field") != FIELD:
        return _refuse("E_UNSUPPORTED", "/recipe/target/field", f"{APP} accepts {FIELD}; {target.get('field')!r} is not accepted here")
    rs, norm, mapping, units = recipe.get("source"), recipe.get("normalization"), recipe.get("mapping"), recipe.get("units")
    if not (_is_obj(rs) and _is_obj(norm) and _is_obj(mapping) and _is_obj(units)):
        return _refuse("E_RECIPE_INVALID", "/recipe", "the recipe lacks source, units, normalization or mapping")

    # units, dimension, normalization: a temperature is absolute, in kelvin
    if rs.get("dimension") != "temperature":
        return _refuse("E_UNITS", "/recipe/source/dimension", f"the source's dimension is {rs.get('dimension')!r}; a fuel temperature must be 'temperature'")
    if rs.get("unit") != "K":
        return _refuse("E_UNITS", "/recipe/source/unit", f"the source's unit is {rs.get('unit')!r}; a fuel temperature must be in K (not degC)")
    if units.get("to") != "K":
        return _refuse("E_UNITS", "/recipe/units/to", "units.to must be K: the material temperature is set in kelvin")
    if norm.get("kind") != "none":
        return _refuse("E_UNITS", "/recipe/normalization/kind", f"a temperature is absolute; the normalization {norm.get('kind')!r} would rescale it and is refused")
    time = mapping.get("time")
    if not _is_obj(time) or time.get("kind") != "steady":
        return _refuse("E_UNSUPPORTED", "/recipe/mapping/time/kind", "only a steady transfer is accepted: one temperature per material, not a history")
    if mapping.get("extrapolation") != "refused":
        return _refuse("E_RECIPE_INVALID", "/recipe/mapping/extrapolation", "extrapolation must be refused; nothing is extrapolated or defaulted")

    # spatial vocabulary: strict, so a mistyped key is a refusal and not a silent default
    sp = mapping.get("spatial")
    if not _is_obj(sp):
        return _refuse("E_RECIPE_INVALID", "/recipe/mapping/spatial", "mapping.spatial is missing")
    for k in sp:
        if k not in SPATIAL_KEYS:
            return _refuse("E_RECIPE_INVALID", f"/recipe/mapping/spatial/{k}", f"unknown key {k}; this field reads meaning, materials, columns")
    if sp.get("meaning") != MEANING:
        return _refuse("E_UNSUPPORTED", "/recipe/mapping/spatial/meaning", f"this field takes the {MEANING} fuel temperature; {sp.get('meaning')!r} (for example an effective Doppler temperature) is not converted here")
    cols = sp.get("columns", {})
    if not _is_obj(cols) or any(k not in COLUMN_KEYS or not _nonempty(v) for k, v in cols.items()):
        return _refuse("E_RECIPE_INVALID", "/recipe/mapping/spatial/columns", "columns names region or value, each a column name")
    wanted = sp.get("materials")
    if not isinstance(wanted, list) or not wanted:
        return _refuse("E_RECIPE_INVALID", "/recipe/mapping/spatial/materials", "name at least one project material")
    seen_materials = set()
    for i, w in enumerate(wanted):
        if not _is_obj(w) or set(w) - {"material", "region"} or not _nonempty(w.get("material")) or (w.get("region") is not None and not _nonempty(w.get("region"))):
            return _refuse("E_RECIPE_INVALID", f"/recipe/mapping/spatial/materials/{i}", "each entry is {material, region?}: a project material id and the source row label")
        if w["material"] in seen_materials:
            return _refuse("E_RECIPE_INVALID", f"/recipe/mapping/spatial/materials/{i}/material", f"material {w['material']} is named twice; one material has one temperature")
        seen_materials.add(w["material"])

    # the target project
    t0 = request.get("target")
    if not _is_obj(t0) or not isinstance(t0.get("content"), str):
        return _refuse("E_SCHEMA_INVALID", "/target/content", "the request carries no target project text")
    try:
        project = _loads(t0["content"])
    except ValueError:
        return _refuse("E_SCHEMA_INVALID", "/target/content", "the target project is not JSON")
    if not _is_obj(project) or not isinstance(project.get("materials"), list) or not _is_obj(project.get("settings")):
        return _refuse("E_SCHEMA_INVALID", "/target/content", "the target is not an OpenMC Studio project (no materials list or settings)")
    by_id = {}
    for m in project["materials"]:
        if _is_obj(m) and isinstance(m.get("id"), str):
            by_id[m["id"]] = m
    errors = []
    for i, w in enumerate(wanted):
        if w["material"] not in by_id:
            errors.append({"code": "E_RECIPE_INVALID", "field": f"/recipe/mapping/spatial/materials/{i}/material", "message": f"the project has no material {w['material']!r}"})
    if errors:
        return {"ok": False, "errors": errors}

    # the source
    src = request.get("source")
    data = src.get("data") if _is_obj(src) else None
    if not _is_obj(data) or data.get("kind") not in ("scalar", "table"):
        return _refuse("E_SCHEMA_INVALID", "/source/data", "the source is neither a scalar nor a table")
    if data.get("quantity") != rs.get("quantity"):
        return _refuse("E_RECIPE_INVALID", "/source/data/quantity", f"the data is {data.get('quantity')!r} but the recipe was approved for {rs.get('quantity')!r}")
    if data.get("unit") != "K" and data["kind"] == "scalar":
        return _refuse("E_UNITS", "/source/data/unit", f"the data's unit is {data.get('unit')!r}, not K")
    values = {}                                    # region -> (value, std or None)
    if data["kind"] == "scalar":
        if len(wanted) != 1 or wanted[0].get("region") is not None:
            return _refuse("E_RECIPE_INVALID", "/recipe/mapping/spatial/materials", "a scalar source gives one temperature: name exactly one material and no region")
        values[None] = (data.get("value"), data.get("std"))
    else:
        columns, rows = data.get("columns"), data.get("rows")
        if not isinstance(columns, list) or not isinstance(rows, list):
            return _refuse("E_SCHEMA_INVALID", "/source/data", "a table needs columns and rows")
        names = set()
        for i, c in enumerate(columns):
            if not (_is_obj(c) and _nonempty(c.get("name")) and isinstance(c.get("unit"), str) and isinstance(c.get("role"), str)):
                return _refuse("E_SCHEMA_INVALID", f"/source/data/columns/{i}", "each column needs a name, a unit and a role")
            if c["name"] in names:
                return _refuse("E_SCHEMA_INVALID", f"/source/data/columns/{i}/name", f"column name {c['name']} appears twice; the table must say which column is meant")
            names.add(c["name"])
        idx = {c["name"]: i for i, c in enumerate(columns)}
        i_reg = idx.get(cols.get("region", "region"), -1)
        if i_reg < 0 or columns[i_reg]["role"] != "label":
            return _refuse("E_COVERAGE", "/source/data/columns", "no label column names the region (default name: region)")
        if "value" in cols:
            i_val = idx.get(cols["value"], -1)
        else:
            vs = [i for i, c in enumerate(columns) if c["role"] == "value"]
            if len(vs) != 1:
                return _refuse("E_RECIPE_INVALID", "/recipe/mapping/spatial/columns/value", "the table has no value column" if not vs else "the table has several value columns; name the one to map in columns.value")
            i_val = vs[0]
        if i_val < 0 or columns[i_val]["role"] != "value":
            return _refuse("E_RECIPE_INVALID", "/recipe/mapping/spatial/columns/value", "the named value column is not in the table")
        if columns[i_val]["unit"] != "K":
            return _refuse("E_UNITS", f"/source/data/columns/{i_val}/unit", f"the table's value is in {columns[i_val]['unit']!r}, not K")
        stds = [i for i, c in enumerate(columns) if c["role"] == "std" and c.get("of") == columns[i_val]["name"]]
        if len(stds) > 1:
            return _refuse("E_SCHEMA_INVALID", "/source/data/columns", f"{len(stds)} std columns name {columns[i_val]['name']}; exactly one uncertainty per value")
        i_std = stds[0] if stds else -1
        if i_std >= 0 and columns[i_std]["unit"] != "K":
            return _refuse("E_UNITS", f"/source/data/columns/{i_std}/unit", "the std column has a different unit from its value")
        for r, row in enumerate(rows):
            if not isinstance(row, list) or len(row) != len(columns):
                return _refuse("E_SCHEMA_INVALID", f"/source/data/rows/{r}", "a row must have one cell per column")
            label = row[i_reg]
            label = ",".join(label) if isinstance(label, list) and all(isinstance(x, str) for x in label) else label
            if not isinstance(label, str):
                return _refuse("E_SCHEMA_INVALID", f"/source/data/rows/{r}", "the region cell must be a string or a list of strings")
            if label in values:
                return _refuse("E_SCHEMA_INVALID", f"/source/data/rows/{r}", f"region {label!r} appears twice; one region has one temperature")
            values[label] = (row[i_val], row[i_std] if i_std >= 0 else None)

    # one entry per mapped material: covered, finite, inside the range the data supports
    applied = []
    for i, w in enumerate(wanted):
        region = w.get("region")
        field = f"/recipe/mapping/spatial/materials/{i}"
        if region not in values:
            errors.append({"code": "E_COVERAGE", "field": field, "message": f"the source has no row for region {region!r} (material {w['material']}); nothing is extrapolated or defaulted"})
            continue
        v, sd = values[region]
        if not _finite(v):
            errors.append({"code": "E_NUMERIC", "field": field, "message": f"the temperature for {w['material']} is {v!r}, not a finite number"})
            continue
        if sd is not None and not (_finite(sd) and sd >= 0):
            errors.append({"code": "E_NUMERIC", "field": field, "message": f"the standard deviation for {w['material']} is {sd!r}, not a finite non-negative number"})
            continue
        material = by_id[w["material"]]
        lo, hi, why = _allowed_range(material, recipe)
        if lo is None:
            errors.append({"code": "E_TEMPERATURE_RANGE", "field": field, "message": why})
            continue
        if not (lo <= v <= hi):
            errors.append({"code": "E_TEMPERATURE_RANGE", "field": field, "message": f"{js_number(v)} K for {w['material']} is outside {_fmt_range(lo, hi)} ({why}); it is refused, not clamped"})
            continue
        applied.append((material, w["material"], region, float(v), sd, lo, hi))
    if errors:
        return {"ok": False, "errors": errors[:20]}

    checks_applied = []
    for material, mid, region, v, sd, lo, hi in applied:
        before = material.get("temperature")
        material["temperature"] = int(v) if v == int(v) and abs(v) < 1e15 else v
        checks_applied.append({"material": mid, "region": region, "temperatureK": v, "previousK": before, "sourceStdK": sd, "rangeK": [lo, hi]})
    original = t0["content"]
    tail = "\n" if original.endswith("\n") else ""
    try:
        content = studio_json(project) + tail
    except (TypeError, ValueError) as exc:
        return _refuse("E_SCHEMA_INVALID", "/target/content", f"the target project cannot be written back: {exc}")
    return {"ok": True, "output": {"content": content},
            "checks": {"applied": checks_applied, "meaning": MEANING, "sets": "Material.temperature (K)",
                       "reformatted": studio_json(_loads(original)) + tail != original}}
