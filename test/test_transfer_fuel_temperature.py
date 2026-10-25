"""SEED's return transfer `fuel-temperature` (studio/openmc_studio/transfer.py): a fuel temperature into the material temperature of an OpenMC Studio project.
Pure Python, no OpenMC needed. Every refusal has a good twin that differs only in the one thing refused (the negative control), the mapping is absolute and
deterministic, and nothing in the project changes except the named materials' temperature.

    python test/test_transfer_fuel_temperature.py
"""
import copy
import json
import math
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "studio"))
from openmc_studio import transfer  # noqa: E402

EXAMPLE = os.path.join(ROOT, "examples", "triso-particle", "triso-particle.openmc-studio.json")
with open(EXAMPLE, encoding="utf-8", newline="") as f:
    TEXT = f.read()


def recipe(**over):
    r = {"schema": "seed.transfer-recipe/0.2", "recipeId": "pt-1", "proposedBy": {"kind": "agent", "name": "x"}, "proposedAt": "2026-10-25T00:00:00Z",
         "source": {"runId": "r1", "resultsSha256": "0" * 64, "quantity": "fuel_temperature", "dataSha256": "1" * 64, "unit": "K", "dimension": "temperature",
                    "normalization": "none", "revisionPins": []},
         "target": {"app": "openmc-studio", "artifact": "project", "revision": "2" * 64, "field": "fuel-temperature"},
         "units": {"to": "K"}, "normalization": {"kind": "none", "origin": "absolute"},
         "mapping": {"spatial": {"meaning": "volume-mean", "materials": [{"material": "triso_m0", "region": "kernel"}]},
                     "time": {"kind": "steady"}, "extrapolation": "refused"},
         "tolerance": {"conservation": 0.01, "fixedBefore": "mapping"}}
    for k, v in over.items():
        r[k] = v
    return r


def table(rows, unit="K", extra_cols=()):
    cols = [{"name": "region", "unit": "", "role": "label"}, {"name": "T", "unit": unit, "role": "value"}, *extra_cols]
    return {"schema": "seed.quantity-data/0.2", "quantity": "fuel_temperature", "kind": "table", "unit": unit, "columns": cols, "rows": rows}


def scalar(value, unit="K", **extra):
    return {"schema": "seed.quantity-data/0.2", "quantity": "fuel_temperature", "kind": "scalar", "unit": unit, "value": value, **extra}


def request(rec=None, data=None, content=TEXT):
    return {"schema": "seed.transfer-request/0.2", "recipe": rec or recipe(), "recipeDigest": "d" * 64,
            "source": {"data": data or table([["kernel", 900.0]])}, "target": {"artifact": "project", "revision": "2" * 64, "content": content}}


def good(rec=None, data=None, content=TEXT):
    r = transfer.transfer(request(rec, data, content))
    assert r["ok"], r
    return r


def temps(content):
    return {m["id"]: m.get("temperature") for m in json.loads(content)["materials"]}


class Good(unittest.TestCase):
    def test_sets_the_named_material_to_the_absolute_value(self):
        r = good()
        self.assertEqual(temps(r["output"]["content"]), {"triso_m0": 900, "triso_m1": None, "triso_m2": None, "triso_m3": None, "triso_m4": None})
        self.assertEqual(r["checks"]["applied"][0]["temperatureK"], 900.0)
        self.assertEqual(r["checks"]["meaning"], "volume-mean")

    def test_value_is_used_as_given_not_normalized_or_rescaled(self):
        for v in (250.0, 293.6, 873.15, 1200.0, 2500.0):
            self.assertEqual(temps(good(data=table([["kernel", v]]))["output"]["content"])["triso_m0"], v if v != int(v) else int(v))

    def test_only_the_named_materials_change(self):
        before, after = json.loads(TEXT), json.loads(good()["output"]["content"])
        for m in after["materials"]:
            if m["id"] == "triso_m0":
                del m["temperature"]         # the example predates the field, so the transfer adds the key
        self.assertEqual(before, after)

    def test_two_materials_from_a_table_and_a_scalar_for_one(self):
        rec = recipe(mapping={"spatial": {"meaning": "volume-mean", "materials": [{"material": "triso_m0", "region": "a"}, {"material": "triso_m3", "region": "b"}]},
                              "time": {"kind": "steady"}, "extrapolation": "refused"})
        t = temps(good(rec, table([["a", 800.0], ["b", 650.5], ["unused", 2000.0]]))["output"]["content"])
        self.assertEqual((t["triso_m0"], t["triso_m3"], t["triso_m1"]), (800, 650.5, None))
        rec1 = recipe(mapping={"spatial": {"meaning": "volume-mean", "materials": [{"material": "triso_m0"}]}, "time": {"kind": "steady"}, "extrapolation": "refused"})
        self.assertEqual(temps(good(rec1, scalar(1000.0, std=5.0))["output"]["content"])["triso_m0"], 1000)

    def test_deterministic_and_idempotent(self):
        a, b = good()["output"]["content"], good()["output"]["content"]
        self.assertEqual(a, b)
        again = good(content=a)["output"]["content"]
        self.assertEqual(again, a, "mapping the same value onto the result changes nothing")

    def test_the_text_is_studios_own_format(self):
        r = good()
        self.assertFalse(r["checks"]["reformatted"], "the example is in Studio's format, so only the temperature line differs")
        import difflib
        d = [l for l in difflib.unified_diff(TEXT.splitlines(), r["output"]["content"].splitlines(), lineterm="", n=0) if l[:1] in "+-" and l[:3] not in ("+++", "---")]
        self.assertEqual(len(d), 3, d)         # the example has no temperature key: the last line of the material gains a comma and a temperature line follows
        self.assertTrue(d[0].startswith("-") and d[1] == d[0][1:].join(["+", ","]) and d[2] == '+      "temperature": 900', d)
        self.assertEqual(r["output"]["content"].endswith("\n"), TEXT.endswith("\n"))
        # the example round-trips through the writer byte for byte
        self.assertEqual(transfer.studio_json(json.loads(TEXT)) + "\n", TEXT)

    def test_a_previous_temperature_is_replaced_and_reported(self):
        p = json.loads(TEXT)
        p["materials"][0]["temperature"] = 600
        r = good(content=transfer.studio_json(p))
        self.assertEqual(r["checks"]["applied"][0]["previousK"], 600)
        self.assertEqual(temps(r["output"]["content"])["triso_m0"], 900)

    def test_std_is_recorded_and_not_used(self):
        std = {"name": "T_std", "unit": "K", "role": "std", "of": "T"}
        r = good(data=table([["kernel", 900.0, 12.0]], extra_cols=[std]))
        self.assertEqual(r["checks"]["applied"][0]["sourceStdK"], 12.0)
        self.assertEqual(temps(r["output"]["content"])["triso_m0"], 900)

    def test_the_reply_comes_through_the_runner_command(self):
        env = dict(os.environ, PYTHONPATH=os.path.join(ROOT, "studio"))
        p = subprocess.run([sys.executable, "-m", "openmc_studio.headless", "transfer"], input=json.dumps(request()).encode(), capture_output=True, env=env, timeout=60)
        self.assertEqual(p.returncode, 0)
        reply = json.loads(p.stdout.decode().strip().splitlines()[-1])
        self.assertTrue(reply["ok"]); self.assertEqual(reply["output"]["content"], good()["output"]["content"])
        for bad in (b"not json", b"{\"x\":1}", b"{\"a\": NaN}"):
            p = subprocess.run([sys.executable, "-m", "openmc_studio.headless", "transfer"], input=bad, capture_output=True, env=env, timeout=60)
            self.assertEqual(p.returncode, 0, "every answer is exit 0")
            self.assertFalse(json.loads(p.stdout.decode().strip().splitlines()[-1])["ok"])


class Refusals(unittest.TestCase):
    def refused(self, code, rec=None, data=None, content=TEXT, field=None):
        r = transfer.transfer(request(rec, data, content))
        self.assertFalse(r["ok"], f"expected {code}, got an accepted transfer")
        self.assertEqual(r["errors"][0]["code"], code, r["errors"])
        self.assertTrue(r["errors"][0]["message"])
        if field:
            self.assertIn(field, r["errors"][0]["field"])
        return r

    def with_source(self, **over):
        rec = recipe(); rec["source"] = {**rec["source"], **over}; return rec

    # --- wrong unit or dimension ---
    def test_celsius_is_refused_and_kelvin_is_the_control(self):
        self.refused("E_UNITS", self.with_source(unit="degC"), field="/source/unit")
        self.refused("E_UNITS", data=table([["kernel", 900.0]], unit="degC"), field="/unit")
        good()

    def test_wrong_dimension_is_refused(self):
        for dim in ("power", "length", "energy", None):
            self.refused("E_UNITS", self.with_source(dimension=dim), field="/source/dimension")
        good(self.with_source(dimension="temperature"))

    def test_scalar_in_another_unit_and_units_to_are_refused(self):
        rec = recipe(mapping={"spatial": {"meaning": "volume-mean", "materials": [{"material": "triso_m0"}]}, "time": {"kind": "steady"}, "extrapolation": "refused"})
        self.refused("E_UNITS", rec, scalar(900.0, unit="degC"), field="/source/data/unit")
        good(rec, scalar(900.0))
        r = recipe(); r["units"] = {"to": "degC"}
        self.refused("E_UNITS", r, field="/units/to")

    # --- a normalization claim ---
    def test_a_normalization_claim_is_refused(self):
        for kind in ("total-power", "source-rate", "per-source-particle"):
            r = recipe(); r["normalization"] = {"kind": kind, "value": {"value": 1, "unit": "W"}, "origin": "x"}
            self.refused("E_UNITS", r, field="/normalization/kind")
        r = recipe(); r["normalization"] = {"kind": "none", "origin": "absolute"}
        good(r)

    # --- coverage ---
    def test_a_material_without_a_row_is_refused_and_the_row_is_the_control(self):
        self.refused("E_COVERAGE", data=table([["other", 900.0]]))
        self.refused("E_COVERAGE", data=table([]))
        good(data=table([["kernel", 900.0], ["other", 100.0]]))     # an unused row is ignored (and so is its value, out of range as it is)

    def test_one_of_two_materials_uncovered_refuses_the_whole_transfer(self):
        rec = recipe(mapping={"spatial": {"meaning": "volume-mean", "materials": [{"material": "triso_m0", "region": "a"}, {"material": "triso_m3", "region": "b"}]},
                              "time": {"kind": "steady"}, "extrapolation": "refused"})
        r = self.refused("E_COVERAGE", rec, table([["a", 800.0]]), field="materials/1")
        self.assertEqual(len(r["errors"]), 1)
        good(rec, table([["a", 800.0], ["b", 900.0]]))

    def test_a_region_twice_and_a_material_twice_and_an_unknown_material(self):
        self.refused("E_SCHEMA_INVALID", data=table([["kernel", 900.0], ["kernel", 950.0]]))
        r = recipe(); r["mapping"]["spatial"]["materials"] = [{"material": "triso_m0", "region": "kernel"}, {"material": "triso_m0", "region": "kernel"}]
        self.refused("E_RECIPE_INVALID", r)
        r = recipe(); r["mapping"]["spatial"]["materials"] = [{"material": "no_such", "region": "kernel"}]
        self.refused("E_RECIPE_INVALID", r, field="materials/0/material")

    # --- range the cross-section data supports ---
    def test_outside_250_to_2500_K_is_refused_at_both_ends_with_the_edges_accepted(self):
        for v in (249.999, 2500.001, 0.0, -10.0, 1e9):
            r = self.refused("E_TEMPERATURE_RANGE", data=table([["kernel", v]]))
            self.assertIn("250 K to 2500 K", r["errors"][0]["message"])
        for v in (250.0, 2500.0):
            good(data=table([["kernel", v]]))

    def test_a_thermal_scattering_table_narrows_the_range(self):
        p = json.loads(TEXT); p["materials"][0]["sab"] = "c_U_in_UO2"
        content = transfer.studio_json(p) + "\n"
        r = self.refused("E_TEMPERATURE_RANGE", data=table([["kernel", 1300.0]]), content=content)
        self.assertIn("296 K to 1200 K", r["errors"][0]["message"])
        self.refused("E_TEMPERATURE_RANGE", data=table([["kernel", 280.0]]), content=content)
        good(data=table([["kernel", 1200.0]]), content=content)
        p["materials"][0]["sab"] = "c_Unknown_table"
        self.refused("E_TEMPERATURE_RANGE", data=table([["kernel", 900.0]]), content=transfer.studio_json(p) + "\n")

    def test_the_recipe_range_can_only_narrow(self):
        r = recipe(applicability={"range": {"min": 500, "max": 1500}, "note": "x"})
        self.refused("E_TEMPERATURE_RANGE", r, table([["kernel", 400.0]]))
        self.refused("E_TEMPERATURE_RANGE", r, table([["kernel", 1600.0]]))
        good(r, table([["kernel", 1000.0]]))
        wide = recipe(applicability={"range": {"min": 0, "max": 9000}})
        self.refused("E_TEMPERATURE_RANGE", wide, table([["kernel", 3000.0]]))

    # --- finite ---
    def test_non_finite_and_non_numbers_are_refused_with_a_number_as_the_control(self):
        for bad in (float("nan"), float("inf"), -float("inf"), None, "900", True, [900]):
            self.refused("E_NUMERIC", data=table([["kernel", bad]]))
        self.refused("E_NUMERIC", data=table([["kernel", 900.0, float("nan")]], extra_cols=[{"name": "s", "unit": "K", "role": "std", "of": "T"}]))
        good(data=table([["kernel", 900.0]]))

    # --- the rest of the contract ---
    def test_only_the_volume_mean_meaning_is_taken(self):
        for meaning in ("effective-doppler", None, "centerline"):
            r = recipe(); r["mapping"]["spatial"]["meaning"] = meaning
            self.refused("E_UNSUPPORTED", r, field="meaning")

    def test_steady_only_and_extrapolation_refused_and_strict_keys(self):
        r = recipe(); r["mapping"]["time"] = {"kind": "series"}
        self.refused("E_UNSUPPORTED", r)
        r = recipe(); r["mapping"]["extrapolation"] = "allowed"
        self.refused("E_RECIPE_INVALID", r)
        r = recipe(); r["mapping"]["spatial"]["zones"] = []
        self.refused("E_RECIPE_INVALID", r, field="/zones")
        r = recipe(); r["target"]["field"] = "heating-to-pin"
        self.refused("E_UNSUPPORTED", r)
        r = recipe(); r["target"]["app"] = "feed"
        self.refused("E_RECIPE_INVALID", r)

    def test_a_bad_target_or_request_is_refused(self):
        self.refused("E_SCHEMA_INVALID", content="not json")
        self.refused("E_SCHEMA_INVALID", content=json.dumps({"hello": 1}))
        self.refused("E_SCHEMA_INVALID", content='{"materials": [], "settings": {"a": NaN}}')
        self.assertEqual(transfer.transfer({"schema": "other"})["errors"][0]["code"], "E_SCHEMA_INVALID")
        self.assertEqual(transfer.transfer([])["errors"][0]["code"], "E_SCHEMA_INVALID")

    def test_a_refusal_never_returns_a_project(self):
        r = transfer.transfer(request(data=table([["kernel", 5.0]])))
        self.assertNotIn("output", r)


class Writer(unittest.TestCase):
    def test_numbers_are_written_as_javascript_writes_them(self):
        want = {1: "1", 0.5: "0.5", 1e-7: "1e-7", 5e-7: "5e-7", 1e21: "1e+21", 1.5e21: "1.5e+21", 0.000001: "0.000001", 12345.678: "12345.678", -0.0005: "-0.0005",
                2.5e-10: "2.5e-10", 100.0: "100", 1e300: "1e+300", 0.1 + 0.2: "0.30000000000000004", 123456789012345680000.0: "123456789012345680000", 0.0: "0"}
        for v, w in want.items():
            self.assertEqual(transfer.js_number(v), w, v)
        with self.assertRaises(ValueError):
            transfer.js_number(float("nan"))

    def test_nested_structures_are_written_like_json_stringify(self):
        v = {"a": [], "b": {}, "c": [1, {"d": None}], "e": "é\n\"", "f": [True, False]}
        self.assertEqual(transfer.studio_json(v), '{\n  "a": [],\n  "b": {},\n  "c": [\n    1,\n    {\n      "d": null\n    }\n  ],\n  "e": "é\\n\\"",\n  "f": [\n    true,\n    false\n  ]\n}')


if __name__ == "__main__":
    unittest.main()
