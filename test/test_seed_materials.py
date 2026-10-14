"""Studio materials as SEED project materials (studio/openmc_studio/seed_materials.py; docs/seed-materials.md).

Reference: SEED's contract (docs/contracts.md section 5 and section 11 rule 4 of the experiment-studio repository), restated below as `check_entry` and the revision rule, and the
fixture project test/fixtures/seed/seed.project.json, which holds what other writers put in a project: a FEED thermal set, an unknown vendor set with `__proto__` and `constructor`
keys, an `openmc.composition` set with fields Studio does not own, and four materials Studio cannot or must not read.

What is held:
  * a Studio material becomes a valid entry (id, revision >= 1, name, sets with a `schema`), refusing ids SEED would refuse and compositions Studio's own parser refuses;
  * importing a project entry and exporting it again unchanged gives the SAME entry (revision included), other sets and unknown keys byte for byte;
  * any change to the name or the composition set takes a strictly greater revision, a change of nothing does not; the other sets never change;
  * a material with no composition set, another version of the set, a unit Studio does not read, or no density is skipped with its reason, never completed by guessing;
  * reading a project is read-only and refuses what is not a seed.project/0.1 file.
Writing `seed.project.json` is not here and not tested: that belongs to SEED's project store.

    python test/test_seed_materials.py
"""
import copy
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "studio"))
from openmc_studio import seed_materials as sm  # noqa: E402

FIXTURE = ROOT / "test" / "fixtures" / "seed" / "seed.project.json"
ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
KEY = re.compile(r"^[a-z][a-z0-9-]*\.[a-z][a-z0-9_.-]*$")


def check_entry(e):
    """SEED contract section 5, material: {id, revision >= 1, name 1..120, sets} with every set an object carrying a `schema` string of 1..80 characters."""
    assert set(e) == {"id", "revision", "name", "sets"}, set(e)
    assert ID.match(e["id"]) and isinstance(e["revision"], int) and e["revision"] >= 1 and 1 <= len(e["name"]) <= 120
    for k, v in e["sets"].items():
        assert KEY.match(k), k
        assert isinstance(v, dict) and isinstance(v["schema"], str) and 1 <= len(v["schema"]) <= 80
    json.dumps(e, allow_nan=False)           # finite numbers only


def fixture():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def studio_material(**kw):
    m = {"id": "m_fuel", "name": "UO2", "color": "#ffaa00", "density": 10.4, "frac": "ao", "comps": "U235:0.031, U238:0.969, O:2", "sab": "", "ref": ""}
    m.update(kw)
    return m


class Composition(unittest.TestCase):
    def test_good_strings(self):
        self.assertEqual(sm.parse_comps("U235:0.03, U238:0.97, O:2"), [{"name": "U235", "fraction": 0.03}, {"name": "U238", "fraction": 0.97}, {"name": "O", "fraction": 2.0}])
        self.assertEqual(sm.parse_comps("Am242_m1 : 1e-3")[0], {"name": "Am242_m1", "fraction": 0.001})
        self.assertEqual(sm.parse_comps(" H:.5 ,, O:1 ")[0]["fraction"], 0.5)

    def test_bad_strings_are_named(self):
        for text, code in (("", "E_PROP_MISSING"), ("U235", "E_SCHEMA_INVALID"), ("u235:1", "E_SCHEMA_INVALID"), ("H:-1", "E_SCHEMA_INVALID"), ("H:0", "E_OUT_OF_DOMAIN"),
                           ("H:1, H:2", "E_SCHEMA_INVALID"), ("Uranium:1", "E_SCHEMA_INVALID"), ("U1234:1", "E_SCHEMA_INVALID"), ("H:nan", "E_SCHEMA_INVALID")):
            with self.assertRaises(sm.MaterialError, msg=text) as cm:
                sm.parse_comps(text)
            self.assertEqual(cm.exception.code, code, text)


class Grammar(unittest.TestCase):
    def test_the_shared_cases(self):
        cases = json.loads((ROOT / "test" / "fixtures" / "seed" / "parse_comps_cases.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(cases), 15)
        for c in cases:
            toks, errs = sm.tokens(c["text"])
            self.assertEqual([[n, a] for n, a in toks], c["tokens"], c["text"])
            self.assertEqual(errs, c["errors"], c["text"])


class ToEntry(unittest.TestCase):
    def test_a_new_material_is_revision_one_and_valid(self):
        e = sm.to_project_entry(studio_material(sab="c_H_in_H2O", ref="PNNL #12"))
        check_entry(e)
        s = e["sets"]["openmc.composition"]
        self.assertEqual((e["revision"], s["schema"], s["units"], s["density"], s["fractionType"], s["sab"]), (1, "openmc.composition/0.1", "g/cm3", 10.4, "ao", "c_H_in_H2O"))
        self.assertEqual(s["source"], {"kind": "sourced", "text": "PNNL #12"})
        self.assertEqual(s["compositionText"], "U235:0.031, U238:0.969, O:2")
        self.assertEqual(sm.to_project_entry(studio_material(ref="my note"))["sets"]["openmc.composition"]["source"]["kind"], "assumed")
        self.assertNotIn("source", sm.to_project_entry(studio_material())["sets"]["openmc.composition"])

    def test_refusals(self):
        for bad, field in ((dict(id="has space"), "/id"), (dict(id="x" * 65), "/id"), (dict(id="-lead"), "/id"), (dict(name="  "), "/name"), (dict(name="n" * 121), "/name"),
                           (dict(density=0), "/density"), (dict(density=float("nan")), "/density"), (dict(density="1"), "/density"), (dict(frac="vo"), "/frac"), (dict(comps="U:x"), "/comps")):
            with self.assertRaises(sm.MaterialError, msg=str(bad)) as cm:
                sm.to_project_entry(studio_material(**bad))
            self.assertEqual(cm.exception.field, field)

    def test_matching_is_by_id_only(self):
        prev = sm.to_project_entry(studio_material())
        with self.assertRaises(sm.MaterialError):
            sm.to_project_entry(studio_material(id="m_other"), prev)


class RoundTrip(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = fixture()
        cls.imp = sm.import_materials(cls.doc)
        cls.by_id = {e["id"]: e for e in cls.doc["materials"]}

    def test_what_is_read_and_what_is_skipped(self):
        self.assertEqual([m["id"] for m in self.imp["materials"]], ["mat-fuel", "mat-water"])
        reasons = {s["id"]: s["code"] for s in self.imp["skipped"]}
        self.assertEqual(reasons, {"mat-thermal-only": "E_PROP_MISSING", "mat-old-schema": "E_SCHEMA_VERSION", "mat-other-writer": "E_UNITS"})
        fuel = self.imp["materials"][0]
        self.assertEqual((fuel["density"], fuel["frac"], fuel["comps"], fuel["name"], fuel["ref"]), (10.4, "ao", "U235:0.031, U238:0.969, O:2", "UO2 fuel 3.1 %", "illustrative PWR-like pellet"))
        self.assertEqual(self.imp["materials"][1]["comps"], "H1:2, O16:1")
        self.assertEqual(self.imp["materials"][1]["sab"], "c_H_in_H2O")

    def test_exporting_what_was_imported_changes_nothing(self):
        for m in self.imp["materials"]:
            prev = sm.restore(m, self.imp["extras"][m["id"]])
            self.assertEqual(sm.canonical(prev), sm.canonical(self.by_id[m["id"]]), "restore() gives back the project's entry")
            again = sm.to_project_entry(m, prev)
            self.assertEqual(again["revision"], self.by_id[m["id"]]["revision"], m["id"])
            self.assertEqual(sm.canonical(again), sm.canonical(self.by_id[m["id"]]), m["id"])
        out = sm.export_entries(self.imp["materials"], self.doc)
        self.assertEqual([e["id"] for e in out], ["mat-fuel", "mat-water"])
        for e in out:
            self.assertEqual(sm.canonical(e), sm.canonical(self.by_id[e["id"]]))

    def test_a_change_takes_a_higher_revision_and_touches_only_the_composition_set(self):
        fuel = copy.deepcopy(self.imp["materials"][0])
        prev = sm.restore(fuel, self.imp["extras"]["mat-fuel"])
        for change, label in (({"density": 10.5}, "density"), ({"comps": "U235:0.04, U238:0.96, O:2"}, "composition"), ({"name": "UO2 fuel 4 %"}, "name"), ({"sab": "c_x"}, "sab"),
                              ({"ref": "another note"}, "source text"), ({"frac": "wo"}, "fraction type")):
            e = sm.to_project_entry({**fuel, **change}, prev)
            check_entry(e)
            self.assertEqual(e["revision"], 4, label)
            for k in ("thermal.conductivity", "vendor.notes"):
                self.assertEqual(sm.canonical(e["sets"][k]), sm.canonical(self.by_id["mat-fuel"]["sets"][k]), f"{label}: {k} is carried exactly")
            owned = e["sets"]["openmc.composition"]
            old = self.by_id["mat-fuel"]["sets"]["openmc.composition"]
            for k in ("conditions", "ranges", "enrichment"):
                self.assertEqual(owned[k], old[k], f"{label}: {k} of the composition set is not Studio's and stays")

    def test_a_kept_source_keeps_its_kind(self):
        fuel = self.imp["materials"][0]
        e = sm.to_project_entry(fuel, sm.restore(fuel, self.imp["extras"]["mat-fuel"]))
        self.assertEqual(e["sets"]["openmc.composition"]["source"]["kind"], "synthetic", "the kind another writer set is not replaced by a guess")

    def test_unknown_keys_survive_through_json_text(self):
        out = sm.export_entries(self.imp["materials"], self.doc)
        text = json.dumps(out)
        back = json.loads(text)
        self.assertEqual(back[0]["sets"]["vendor.notes"]["__proto__"], {"x": 1})
        self.assertEqual(back[0]["sets"]["vendor.notes"]["constructor"], "kept")
        self.assertEqual(back[0]["sets"]["vendor.notes"]["list"], [3, 1, 2])

    def test_the_project_is_not_touched(self):
        before = FIXTURE.read_bytes()
        sm.export_entries(self.imp["materials"], self.doc)
        self.assertEqual(FIXTURE.read_bytes(), before)

    def test_new_ids_start_at_one_and_duplicates_are_refused(self):
        out = sm.export_entries([studio_material(id="m_new")], self.doc)
        self.assertEqual(out[0]["revision"], 1)
        with self.assertRaises(sm.MaterialError):
            sm.export_entries([studio_material(), studio_material()], self.doc)

    def test_components_that_disagree_with_the_text_are_refused(self):
        e = copy.deepcopy(self.by_id["mat-fuel"])
        e["sets"]["openmc.composition"]["components"][0]["fraction"] = 0.5
        with self.assertRaises(sm.MaterialError) as cm:
            sm.from_project_entry(e)
        self.assertTrue(cm.exception.field.endswith("/components"))

    def test_duplicate_ids_in_a_project_are_refused(self):
        d = fixture()
        d["materials"].append(copy.deepcopy(d["materials"][1]))
        with self.assertRaises(sm.MaterialError):
            sm.import_materials(d)


class ReadProject(unittest.TestCase):
    def test_reads_file_or_folder_and_refuses_the_rest(self):
        self.assertEqual(sm.read_project(FIXTURE)["projectId"], "p-0123456789ab")
        self.assertEqual(sm.read_project(FIXTURE.parent)["name"], "Material round trip fixture")
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "other.json").write_text("{}", encoding="utf-8")
            (d / "seed.project.json").write_text("{not json", encoding="utf-8")
            for f, code in (((d / "other.json"), "E_PATH_INVALID"), (d / "missing" / "seed.project.json", "E_NOT_FOUND"), (d / "seed.project.json", "E_SCHEMA_INVALID")):
                with self.assertRaises(sm.MaterialError, msg=str(f)) as cm:
                    sm.read_project(f)
                self.assertEqual(cm.exception.code, code)
            (d / "seed.project.json").write_text(json.dumps({"schema": "seed.project/0.2", "materials": []}), encoding="utf-8")
            with self.assertRaises(sm.MaterialError) as cm:
                sm.read_project(d)
            self.assertEqual(cm.exception.code, "E_SCHEMA_VERSION")
            (d / "seed.project.json").write_text(json.dumps({"schema": "seed.project/0.1"}), encoding="utf-8")
            with self.assertRaises(sm.MaterialError):
                sm.read_project(d)
            big = d / "big"
            big.mkdir()
            (big / "seed.project.json").write_text(" " * (sm.MAX_PROJECT_BYTES + 1), encoding="utf-8")
            with self.assertRaises(sm.MaterialError):
                sm.read_project(big)


class StudioExample(unittest.TestCase):
    def test_the_shipped_example_materials_export_and_come_back_equal(self):
        proj = json.loads((ROOT / "examples" / "triso-particle" / "triso-particle.openmc-studio.json").read_text(encoding="utf-8"))
        entries = sm.export_entries(proj["materials"])
        self.assertEqual(len(entries), len(proj["materials"]))
        doc = {"materials": entries}
        for e in entries:
            check_entry(e)
        back = sm.import_materials(doc)
        self.assertEqual(back["skipped"], [])
        for orig, got in zip(proj["materials"], back["materials"]):
            for k in ("id", "name", "density", "frac", "comps"):
                self.assertEqual(orig[k], got[k], (orig["id"], k))
            self.assertEqual(orig.get("sab", ""), got["sab"])
            self.assertEqual(orig.get("ref", ""), got["ref"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
