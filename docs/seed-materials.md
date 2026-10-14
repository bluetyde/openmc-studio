# Studio materials in a SEED project

A SEED project (`seed.project.json`, schema `seed.project/0.1`, SEED's `docs/contracts.md` section 5) lists materials as `{id, revision, name, sets}`. A set is `{schema, ...}` named by its consumer, and a set is opaque to everyone but its owner. OpenMC Studio owns the set **`openmc.composition`**. This page is the Studio side of the material round trip that FEED's TODO asks for ("Material round trip with real OpenMC and thermal sets"). Code: `studio/openmc_studio/seed_materials.py`. Tests: `test/test_seed_materials.py`, `test/test_seed_materials_parity.js`.

## What is built, and what is not

| Built | Not built |
|---|---|
| The format of `openmc.composition/0.1` (below) | **Writing `seed.project.json`.** That file belongs to SEED's project store (writer lock `.seed/lock`, `expectedRevision`, canonical-JSON hash of the manifest). Studio produces the entries and reads projects; it does not write the manifest. |
| Studio material to project entry, and back | A button, menu or server route in the Studio page: today the module is a library and a command line |
| The revision rule of SEED's contract (section 11, rule 4) | Reading the set from a model that Studio did not write (any other writer's composition set is read only if it carries the fields below) |
| Other sets carried exactly; unknown keys inside the composition set kept | Thermal sets: Studio never reads or writes them (FEED's) |
| Read-only import of a project (`import_materials`) | A real round trip with SEED's `saveProject` and FEED's importer (needs SEED's side, see below) |

## The set

From a Studio material `{id, name, density (g/cm3), frac ("ao" | "wo"), comps, sab, ref}`:

```json
"openmc.composition": {
  "schema": "openmc.composition/0.1",
  "units": "g/cm3",
  "density": 10.4,
  "fractionType": "ao",
  "components": [{"name": "U235", "fraction": 0.031}, {"name": "U238", "fraction": 0.969}, {"name": "O", "fraction": 2}],
  "compositionText": "U235:0.031, U238:0.969, O:2",
  "sab": "c_H_in_H2O",
  "source": {"kind": "sourced" | "assumed", "text": "PNNL #12"}
}
```

- `components` is the parsed composition: an element symbol with an optional mass number and metastable suffix, a colon, a number above zero (Studio's own grammar; the page's `parseComps` and this parser are run on the same case table, `test/fixtures/seed/parse_comps_cases.json`). Fractions are by atoms or by weight as `fractionType` says; they need not sum to one.
- `compositionText` is the string as typed, so a round trip gives back the same text. It is written only where the previous set had it (a set made by another writer from `components` alone stays without it).
- `source`: the Studio note (`ref`). `sourced` only when the note starts with `PNNL #` (the library Studio ships); everything else is `assumed`. A source whose text did not change keeps the kind that is in the project, even if someone else set it (for example `synthetic`).
- Keys of an existing set that Studio does not own (`conditions`, `ranges`, `ref`, an enrichment, anything) are kept exactly.

## The rules

1. **Matching is by id only.** A Studio id that is not a SEED id (letters, digits, `.`, `_`, `-`, at most 64, not starting with a symbol) is refused (`E_SCHEMA_INVALID /id`); Studio does not rewrite ids.
2. **Revision.** A new id is revision 1. For an id the project already holds: unchanged name and sets keep the revision, any change takes **one more** (SEED requires strictly greater). Changing the composition never touches the other sets, and adding or changing someone else's set is not Studio's to do.
3. **Other sets are carried exactly**, including unknown sets and keys such as `__proto__` and `constructor` (they are data, never evaluated).
4. **Nothing is guessed.** A project material with no `openmc.composition` set (a thermal-only material), another schema version of it, other units, no density, or components that disagree with the text is **skipped with its reason** by the import (`E_PROP_MISSING`, `E_SCHEMA_VERSION`, `E_UNITS`, `E_SCHEMA_INVALID`), never completed.
5. **A project is read, not changed.** `read_project` accepts a file named `seed.project.json` (or its folder), at most 8 MB, valid JSON, schema `seed.project/0.1` exactly.

## Use

```
python -m openmc_studio.seed_materials import PROJECT              # what Studio can read, and what it skipped and why
python -m openmc_studio.seed_materials export STUDIO.json [--project PROJECT]
```

`export` prints the entries as one JSON line (with `--project`, new revisions of the ids the project holds, their other sets carried). It writes no file. The entries are for SEED's project store to merge.

## Who writes the manifest (the open decision)

SEED's `saveProject(dir, manifest, expectedRevision)` owns the write: lock, re-read, `E_STALE_REVISION`, the material revision rule, atomic rename. Two ways:

- **(a) SEED merges.** SEED adds a caller that takes the entries above and applies them through `saveProject`. Studio only produces entries. This is what Studio is built for.
- **(b) Studio writes.** Studio would implement the same lock protocol and hash in Python. Two implementations of one protocol; not done, and not recommended.

That choice is the user's. What is open on SEED's side is not Studio's to build or to edit.

## What was and was not checked

- Checked: the entry shape against the contract's section 5 as restated in the test (a hand copy, not SEED's own schema validator); the revision rule; exact carrying of other sets through a fixture project that holds a FEED thermal set and an unknown set; the shipped example's materials export and come back equal; 20 deliberate breaks of the module are caught (three survived the first run and got tests).
- **Not checked:** SEED's own validator on these entries, SEED's `saveProject` taking them, FEED's importer reading a project that Studio's entries are in (FEED keeps `openmc.composition` exactly and never reads it), and a real OpenMC run on a material that came back from a project. The acceptance case in SEED's plan 02 ("reopening in OpenMC keeps both sets") needs those and is **not** shown here.
