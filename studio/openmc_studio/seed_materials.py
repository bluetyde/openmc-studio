"""Studio materials in the form a SEED project holds them (the Studio side of the material round trip; docs/seed-materials.md).

A SEED project (`seed.project.json`, schema `seed.project/0.1`) lists materials as `{id, revision, name, sets}`; a set is `{schema, ...}` named by its consumer. Studio owns
the set `openmc.composition` (schema `openmc.composition/0.1`, below) and carries every other set (`thermal.*`, unknown ones) byte for byte: it never reads, changes or
drops them. This module is pure: it builds and reads those entries and reads a project file; it does NOT write `seed.project.json`, which belongs to SEED's project store
(writer lock, expected revision, canonical-JSON hash). The entries it makes are what that store is handed.

The set, from a Studio material {id, name, density (g/cm3), frac ("ao" | "wo"), comps ("U235:0.03, U238:0.97, O:2"), sab, ref}:

    {"schema": "openmc.composition/0.1", "units": "g/cm3", "density": 10.4, "fractionType": "ao",
     "components": [{"name": "U235", "fraction": 0.03}, ...], "compositionText": "U235:0.03, ...",
     "sab": "c_H_in_H2O", "source": {"kind": "sourced" | "assumed", "text": "..."}}

`components` is the parsed form (same grammar as Studio's own parser: an element symbol with an optional mass number and metastable suffix, a colon, a positive number);
`compositionText` is Studio's string kept as typed, so a round trip gives the same text back. Revisions follow SEED's project-store rule (contracts section 11, rule 4):
the same name and sets keep the revision, any change takes a strictly greater one.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path

SET_NAME = "openmc.composition"
SET_SCHEMA = "openmc.composition/0.1"
PROJECT_SCHEMA = "seed.project/0.1"
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
SET_KEY_RE = re.compile(r"^[a-z][a-z0-9-]*\.[a-z][a-z0-9_.-]*$")
_TOKEN_RE = re.compile(r"^([A-Z][a-z]?)(\d{1,3}(?:_m\d)?)?\s*:\s*([0-9]*\.?[0-9]+(?:[eE][-+]?\d+)?)$")     # Studio's parseComps
MAX_PROJECT_BYTES = 8 * 1024 * 1024


class MaterialError(ValueError):
    """A material or project that cannot be converted; `code` is one of the E_ codes below, `field` a JSON-pointer-like path."""

    def __init__(self, code: str, field: str, message: str):
        super().__init__(f"{code} {field}: {message}")
        self.code, self.field, self.message = code, field, message


def tokens(text) -> tuple[list, list]:
    """The grammar of Studio's own `parseComps` (static/index.html), nothing more: ([(name, fraction)], [unreadable tokens]). test/fixtures/seed/parse_comps_cases.json holds the
    cases both this and the page's parser are run against (test_seed_materials.py, test_seed_materials_parity.js)."""
    out, errs = [], []
    for tok in (t.strip() for t in str(text or "").split(",")):
        if not tok:
            continue
        m = _TOKEN_RE.match(tok)
        if not m:
            errs.append(tok)
            continue
        out.append((m.group(1) + (m.group(2) or ""), float(m.group(3))))
    return out, errs


def parse_comps(text) -> list:
    """Studio's composition string as [{"name", "fraction"}], in the order typed. Refuses a token Studio would not read, a duplicate name and a fraction that is not above zero."""
    toks, errs = tokens(text)
    if errs:
        raise MaterialError("E_SCHEMA_INVALID", "/comps", f"cannot read {errs[0]!r}; each part is Symbol[MassNumber]:fraction, for example U235:0.03")
    out, seen = [], set()
    for name, amt in toks:
        if not (amt > 0 and math.isfinite(amt)):
            raise MaterialError("E_OUT_OF_DOMAIN", "/comps", f"{name} has fraction {amt:g}; it must be above zero")
        if name in seen:
            raise MaterialError("E_SCHEMA_INVALID", "/comps", f"{name} appears twice")
        seen.add(name)
        out.append({"name": name, "fraction": amt})
    if not out:
        raise MaterialError("E_PROP_MISSING", "/comps", "the material has no composition")
    return out


def _norm(obj):
    """Numbers that are whole are written as integers (2 and 2.0 are the same JSON number), recursively."""
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, float) and math.isfinite(obj) and obj.is_integer():
        return int(obj)
    if isinstance(obj, dict):
        return {k: _norm(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_norm(v) for v in obj]
    return obj


def canonical(obj) -> str:
    """Canonical JSON: sorted keys, no spaces, UTF-8 characters kept, whole numbers as integers (the form a hash of a set is taken over here)."""
    return json.dumps(_norm(obj), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def set_sha256(set_obj) -> str:
    return hashlib.sha256(canonical(set_obj).encode("utf-8")).hexdigest()


OWNED = ("schema", "units", "density", "fractionType", "components", "compositionText", "sab", "source")      # the keys Studio writes; any other key of a set is someone else's


def composition_set(material: dict, previous_set: dict | None = None) -> dict:
    """The `openmc.composition` set of a Studio material (id, name, density, frac, comps, sab, ref). With `previous_set` (the project's set of the same material) every key Studio
    does not own (`conditions`, `ranges`, `ref`, an enrichment, anything) is kept exactly; `compositionText` is only written where the previous set had it, and a `source` whose
    text is unchanged is kept as it was (its kind may have been set by someone else)."""
    d = material.get("density")
    if isinstance(d, bool) or not isinstance(d, (int, float)) or not (d > 0 and math.isfinite(d)):
        raise MaterialError("E_UNITS", "/density", f"the density must be a number above zero in g/cm3, got {d!r}")
    frac = material.get("frac")
    if frac not in ("ao", "wo"):
        raise MaterialError("E_UNITS", "/frac", f"the fraction type must be 'ao' or 'wo', got {frac!r}")
    comps = material.get("comps", "")
    new = {"schema": SET_SCHEMA, "units": "g/cm3", "density": float(d), "fractionType": frac, "components": parse_comps(comps)}
    if previous_set is None or "compositionText" in previous_set:
        new["compositionText"] = str(comps)
    sab = material.get("sab") or ""
    if sab:
        new["sab"] = str(sab)
    ref = str(material.get("ref") or "")[:2000]
    prev_source = (previous_set or {}).get("source")
    if ref:
        if isinstance(prev_source, dict) and prev_source.get("text") == ref:
            new["source"] = prev_source
        else:
            new["source"] = {"kind": "sourced" if ref.startswith("PNNL #") else "assumed", "text": ref}
    elif prev_source is not None:
        new["source"] = prev_source
    out = {k: v for k, v in (previous_set or {}).items() if k not in OWNED}
    out.update(new)
    return out


def _check_id(mid) -> str:
    if not isinstance(mid, str) or not ID_RE.match(mid):
        raise MaterialError("E_SCHEMA_INVALID", "/id", f"the material id {mid!r} is not a SEED id (letters, digits, '.', '_' or '-', at most 64, not starting with a symbol); Studio does not rewrite ids")
    return mid


def to_project_entry(material: dict, previous: dict | None = None) -> dict:
    """A Studio material as a project material entry. With `previous` (the project's entry of the same id) the other sets are carried exactly, the name and the composition
    set are replaced, and the revision is the previous one when nothing changed and one more when something did."""
    mid = _check_id(material.get("id"))
    name = str(material.get("name") or "").strip()
    if not 1 <= len(name) <= 120:
        raise MaterialError("E_SCHEMA_INVALID", "/name", "the name must be 1 to 120 characters")
    prev_set = previous.get("sets", {}).get(SET_NAME) if previous else None
    new_set = composition_set(material, prev_set if isinstance(prev_set, dict) else None)
    if previous is None:
        return {"id": mid, "revision": 1, "name": name, "sets": {SET_NAME: new_set}}
    if previous.get("id") != mid:
        raise MaterialError("E_SCHEMA_INVALID", "/id", f"the previous entry is {previous.get('id')!r}, not {mid!r}: matching is by id only")
    sets = {k: v for k, v in previous["sets"].items()}
    unchanged = previous.get("name") == name and canonical(previous["sets"].get(SET_NAME)) == canonical(new_set)
    sets[SET_NAME] = previous["sets"][SET_NAME] if unchanged else new_set          # nothing changed: the set is the project's own text, not a rewrite of it
    return {"id": mid, "revision": int(previous["revision"]) + (0 if unchanged else 1), "name": name, "sets": sets}


def from_project_entry(entry: dict) -> tuple[dict, dict]:
    """(Studio material, extras) from a project entry. extras = {"revision", "otherSets", "compositionSha256"}: what Studio must hand back unchanged when it exports the material
    again (`to_project_entry(material, previous=restore(...))`). A material with no `openmc.composition` set is refused: Studio does not invent a composition."""
    if not isinstance(entry, dict) or not isinstance(entry.get("sets"), dict):
        raise MaterialError("E_SCHEMA_INVALID", "/materials", "not a project material")
    mid = _check_id(entry.get("id"))
    s = entry["sets"].get(SET_NAME)
    if s is None:
        raise MaterialError("E_PROP_MISSING", f"/materials/{mid}/sets/{SET_NAME}", f"the material {mid} has no {SET_NAME} set; Studio cannot make a material from thermal or other sets alone")
    if not isinstance(s, dict) or s.get("schema") != SET_SCHEMA:
        raise MaterialError("E_SCHEMA_VERSION", f"/materials/{mid}/sets/{SET_NAME}/schema", f"expected {SET_SCHEMA!r}, got {s.get('schema') if isinstance(s, dict) else s!r}")
    if s.get("units") != "g/cm3":
        raise MaterialError("E_UNITS", f"/materials/{mid}/sets/{SET_NAME}/units", f"expected 'g/cm3', got {s.get('units')!r}")
    src = s.get("source") if isinstance(s.get("source"), dict) else {}
    text = s.get("compositionText")
    if not isinstance(text, str):
        text = ", ".join(f"{c['name']}:{c['fraction']:g}" for c in s.get("components", []))
    material = {"id": mid, "name": entry.get("name"), "density": s.get("density"), "frac": s.get("fractionType"), "comps": text, "sab": s.get("sab", ""), "ref": src.get("text", "")}
    composition_set(material)          # the same checks as an export: a bad density, fraction type or composition is refused on the way in too
    # the stored components must agree with the text, or the file says two things
    parsed = parse_comps(text)
    if "components" in s and canonical(s["components"]) != canonical(parsed):          # numeric equality: 2 and 2.0 agree
        raise MaterialError("E_SCHEMA_INVALID", f"/materials/{mid}/sets/{SET_NAME}/components", "the components do not match compositionText")
    extras = {"revision": int(entry["revision"]), "name": entry.get("name"), "otherSets": {k: v for k, v in entry["sets"].items() if k != SET_NAME},
              "compositionSet": json.loads(json.dumps(s)), "compositionSha256": set_sha256(s)}
    return material, extras


def restore(material: dict, extras: dict) -> dict:
    """The project entry `to_project_entry` needs as `previous`, rebuilt from what `from_project_entry` returned: the other sets and the composition set exactly as imported."""
    return {"id": material["id"], "revision": extras["revision"], "name": extras["name"], "sets": {**extras["otherSets"], SET_NAME: extras["compositionSet"]}}


def read_project(path) -> dict:
    """Read a `seed.project.json` (or the folder holding it): the manifest as parsed, read-only. At most 8 MB, valid JSON, schema `seed.project/0.1` exactly."""
    p = Path(path)
    if p.is_dir():
        p = p / "seed.project.json"
    if p.name != "seed.project.json":
        raise MaterialError("E_PATH_INVALID", "", "the file must be named seed.project.json")
    if not p.is_file():
        raise MaterialError("E_NOT_FOUND", "", f"{p} does not exist")
    if p.stat().st_size > MAX_PROJECT_BYTES:
        raise MaterialError("E_SCHEMA_INVALID", "", "the project file is larger than 8 MB")
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        raise MaterialError("E_SCHEMA_INVALID", "", f"not valid JSON: {e}") from e
    if not isinstance(doc, dict) or doc.get("schema") != PROJECT_SCHEMA:
        raise MaterialError("E_SCHEMA_VERSION", "/schema", f"expected {PROJECT_SCHEMA!r}, got {doc.get('schema') if isinstance(doc, dict) else doc!r}")
    if not isinstance(doc.get("materials"), list):
        raise MaterialError("E_SCHEMA_INVALID", "/materials", "no materials list")
    return doc


def import_materials(project_doc: dict) -> dict:
    """Every material of a project that Studio can read: {"materials": [studio material ...], "extras": {id: extras}, "skipped": [{"id", "code", "message"}]}. A material with no
    openmc.composition set (or a bad one) is skipped with its reason, never guessed at; ids are unique or the project is refused."""
    out, extras, skipped, seen = [], {}, [], set()
    for i, e in enumerate(project_doc.get("materials", [])):
        mid = e.get("id") if isinstance(e, dict) else None
        if mid in seen:
            raise MaterialError("E_SCHEMA_INVALID", f"/materials/{i}/id", f"duplicate material id {mid!r}")
        seen.add(mid)
        try:
            m, x = from_project_entry(e)
        except MaterialError as err:
            skipped.append({"id": mid, "code": err.code, "message": err.message})
            continue
        out.append(m)
        extras[mid] = x
    return {"materials": out, "extras": extras, "skipped": skipped}


def export_entries(materials: list, previous_doc: dict | None = None, imported: dict | None = None) -> list:
    """Entries for a list of Studio materials. `previous_doc` is the project as read; an id it holds is a new revision of that entry (its other sets carried exactly); a new id is
    revision 1. A project material Studio did not list is not in the output (the caller leaves it alone). `imported` (from import_materials) is accepted for symmetry and unused."""
    prev = {e["id"]: e for e in (previous_doc or {}).get("materials", []) if isinstance(e, dict) and "id" in e}
    ids = [m.get("id") for m in materials]
    if len(set(ids)) != len(ids):
        raise MaterialError("E_SCHEMA_INVALID", "/materials", "duplicate material ids")
    return [to_project_entry(m, prev.get(m.get("id"))) for m in materials]


def main(argv=None) -> int:
    """Command line, one JSON line out (exit 0 ok, 1 refused):
        python -m openmc_studio.seed_materials import PROJECT            the project's materials Studio can read, with what it skipped and why
        python -m openmc_studio.seed_materials export STUDIO.json [--project PROJECT]
                                                                          the entries for the materials of a Studio project file; with --project, new revisions of the ids it holds
    Neither writes a file: the entries are handed to SEED's project store."""
    import argparse
    ap = argparse.ArgumentParser(prog="python -m openmc_studio.seed_materials")
    sub = ap.add_subparsers(dest="verb", required=True)
    a = sub.add_parser("import")
    a.add_argument("project")
    b = sub.add_parser("export")
    b.add_argument("studio")
    b.add_argument("--project", default=None)
    args = ap.parse_args(argv)
    try:
        if args.verb == "import":
            res = import_materials(read_project(args.project))
            print(json.dumps({"ok": True, **res}))
        else:
            studio = json.loads(Path(args.studio).read_text(encoding="utf-8"))
            if not isinstance(studio.get("materials"), list):
                raise MaterialError("E_SCHEMA_INVALID", "/materials", "not an OpenMC Studio project file")
            entries = export_entries(studio["materials"], read_project(args.project) if args.project else None)
            print(json.dumps({"ok": True, "entries": entries}))
    except MaterialError as e:
        print(json.dumps({"ok": False, "code": e.code, "field": e.field, "message": e.message}))
        return 1
    except (OSError, ValueError) as e:
        print(json.dumps({"ok": False, "code": "E_SCHEMA_INVALID", "field": "", "message": str(e)}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
