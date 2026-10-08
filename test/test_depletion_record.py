"""Tests for studio/openmc_studio/depletion_record.py.

Validates burnup arithmetic, oxide basis conversion, record construction,
validation against schema 'studio.depletion/0.1', and reading/writing
the depletion.json hand-off record.

Run with:  python test/test_depletion_record.py
"""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "studio"))

from openmc_studio.depletion_record import (  # noqa: E402
    RecordError,
    burnup_mwd_per_tu,
    to_oxide_basis,
    build_record,
    record_id,
    validate,
    write,
    read,
)


class TestDepletionRecord(unittest.TestCase):
    """Test suite for depletion record creation, validation, and serialization."""

    def _base_record(self):
        """Construct a fresh valid record according to the worked example."""
        return {
            "schema": "studio.depletion/0.1",
            "time_steps_days": [10, 20, 30],
            "regions": [{
                "name": "fuel",
                "cell_ids": [1],
                "heavy_metal_mass_kg": 2.0,
                "power_w": [1000, 2000, 1500],
                "burnup_mwd_per_tu": [5.0, 25.0, 47.5],
            }],
            "k": [[1.30, 0.001], [1.29, 0.001], [1.28, 0.001], [1.27, 0.001]],
            "provenance": {"written": "2026-10-07T12:00:00+00:00"},
        }

    def test_worked_example(self):
        """Worked example: exact numbers from the specification."""
        steps = [10, 20, 30]
        power = [1000, 2000, 1500]
        mass = 2.0
        burnup = burnup_mwd_per_tu(steps, power, mass)
        expected_burnup = [5.0, 25.0, 47.5]
        self.assertEqual(len(burnup), 3)
        for b, exp in zip(burnup, expected_burnup):
            self.assertAlmostEqual(b, exp, delta=1e-12)

        example_record = {
            "schema": "studio.depletion/0.1",
            "time_steps_days": [10, 20, 30],
            "regions": [{
                "name": "fuel",
                "cell_ids": [1],
                "heavy_metal_mass_kg": 2.0,
                "power_w": [1000, 2000, 1500],
                "burnup_mwd_per_tu": [5.0, 25.0, 47.5],
            }],
            "k": [[1.30, 0.001], [1.29, 0.001], [1.28, 0.001], [1.27, 0.001]],
            "provenance": {"written": "2026-10-07T12:00:00+00:00"},
        }

        built = build_record(
            [10, 20, 30],
            [{"name": "fuel", "cell_ids": [1], "heavy_metal_mass_kg": 2.0, "power_w": [1000, 2000, 1500]}],
            k=[[1.30, 0.001], [1.29, 0.001], [1.28, 0.001], [1.27, 0.001]],
            provenance={"written": "2026-10-07T12:00:00+00:00"},
        )
        self.assertEqual(built, dict(example_record, id=record_id(example_record)))
        validate(example_record)  # a record with no id is still valid (older writers)

    def test_second_region_independent_loop(self):
        """Second region with different mass and power computed independently by a loop."""
        steps = [10.0, 20.0, 30.0]
        r1 = {"name": "fuel1", "cell_ids": [1], "heavy_metal_mass_kg": 2.0, "power_w": [1000.0, 2000.0, 1500.0]}
        r2 = {"name": "fuel2", "cell_ids": [2, 3], "heavy_metal_mass_kg": 4.0, "power_w": [2500.0, 3000.0, 1000.0]}

        cum_energy = 0.0
        expected_bu2 = []
        for dt, p in zip(steps, r2["power_w"]):
            cum_energy += (p / 1e6) * dt
            expected_bu2.append(cum_energy / (r2["heavy_metal_mass_kg"] / 1000.0))

        record = build_record(steps, [r1, r2])
        self.assertEqual(len(record["regions"]), 2)
        bu2 = record["regions"][1]["burnup_mwd_per_tu"]
        for b, exp in zip(bu2, expected_bu2):
            self.assertAlmostEqual(b, exp, delta=1e-12)
        validate(record)

    def test_to_oxide_basis(self):
        """Conversion to oxide basis: number in/out, list in/out, f bounds and bad inputs."""
        out_num = to_oxide_basis(100, 0.8)
        self.assertAlmostEqual(out_num, 80.0, delta=1e-12)
        self.assertIsInstance(out_num, (int, float))

        out_list = to_oxide_basis([100, 200], 0.8)
        self.assertIsInstance(out_list, list)
        self.assertEqual(len(out_list), 2)
        self.assertAlmostEqual(out_list[0], 80.0, delta=1e-12)
        self.assertAlmostEqual(out_list[1], 160.0, delta=1e-12)

        for bad_f in [0, 0.0, 1.2, float("nan"), True]:
            with self.assertRaises(RecordError) as ctx:
                to_oxide_basis(100, bad_f)
            self.assertTrue(str(ctx.exception).startswith("hm_mass_fraction_of_oxide:"))

        self.assertAlmostEqual(to_oxide_basis(100, 1), 100.0, delta=1e-12)
        self.assertAlmostEqual(to_oxide_basis(100, 1.0), 100.0, delta=1e-12)

    def test_validation_rules(self):
        """Every validation rule broken individually asserting RecordError at the right path."""
        # 1. Wrong schema
        rec = self._base_record()
        rec["schema"] = "other.schema/0.1"
        with self.assertRaises(RecordError) as ctx:
            validate(rec)
        self.assertTrue(str(ctx.exception).startswith("schema:"))

        # 2. Unknown top-level key
        rec = self._base_record()
        rec["extra_key"] = "unexpected"
        with self.assertRaises(RecordError) as ctx:
            validate(rec)
        self.assertTrue(str(ctx.exception).startswith("extra_key:"))

        # 3. time_steps_days empty
        rec = self._base_record()
        rec["time_steps_days"] = []
        with self.assertRaises(RecordError) as ctx:
            validate(rec)
        self.assertTrue(str(ctx.exception).startswith("time_steps_days:"))

        # 4. time_steps_days with 0
        rec = self._base_record()
        rec["time_steps_days"] = [0, 20, 30]
        with self.assertRaises(RecordError) as ctx:
            validate(rec)
        self.assertTrue(str(ctx.exception).startswith("time_steps_days[0]:"))

        # 5. time_steps_days negative
        rec = self._base_record()
        rec["time_steps_days"] = [-10, 20, 30]
        with self.assertRaises(RecordError) as ctx:
            validate(rec)
        self.assertTrue(str(ctx.exception).startswith("time_steps_days[0]:"))

        # 6. time_steps_days nan
        rec = self._base_record()
        rec["time_steps_days"] = [float("nan"), 20, 30]
        with self.assertRaises(RecordError) as ctx:
            validate(rec)
        self.assertTrue(str(ctx.exception).startswith("time_steps_days[0]:"))

        # 7. time_steps_days a bool
        rec = self._base_record()
        rec["time_steps_days"] = [True, 20, 30]
        with self.assertRaises(RecordError) as ctx:
            validate(rec)
        self.assertTrue(str(ctx.exception).startswith("time_steps_days[0]:"))

        # 8. Duplicate region name
        rec = self._base_record()
        rec["regions"].append(copy.deepcopy(rec["regions"][0]))
        with self.assertRaises(RecordError) as ctx:
            validate(rec)
        self.assertTrue(str(ctx.exception).startswith("regions[1].name:"))

        # 9. Empty region name
        rec = self._base_record()
        rec["regions"][0]["name"] = ""
        with self.assertRaises(RecordError) as ctx:
            validate(rec)
        self.assertTrue(str(ctx.exception).startswith("regions[0].name:"))

        # 10. cell_ids empty
        rec = self._base_record()
        rec["regions"][0]["cell_ids"] = []
        with self.assertRaises(RecordError) as ctx:
            validate(rec)
        self.assertTrue(str(ctx.exception).startswith("regions[0].cell_ids:"))

        # 11. cell_ids duplicated
        rec = self._base_record()
        rec["regions"][0]["cell_ids"] = [1, 1]
        with self.assertRaises(RecordError) as ctx:
            validate(rec)
        self.assertTrue(str(ctx.exception).startswith("regions[0].cell_ids[1]:"))

        # 12. cell_ids 0
        rec = self._base_record()
        rec["regions"][0]["cell_ids"] = [0]
        with self.assertRaises(RecordError) as ctx:
            validate(rec)
        self.assertTrue(str(ctx.exception).startswith("regions[0].cell_ids[0]:"))

        # 13. cell_ids a bool
        rec = self._base_record()
        rec["regions"][0]["cell_ids"] = [True]
        with self.assertRaises(RecordError) as ctx:
            validate(rec)
        self.assertTrue(str(ctx.exception).startswith("regions[0].cell_ids[0]:"))

        # 14. mass 0
        rec = self._base_record()
        rec["regions"][0]["heavy_metal_mass_kg"] = 0
        with self.assertRaises(RecordError) as ctx:
            validate(rec)
        self.assertTrue(str(ctx.exception).startswith("regions[0].heavy_metal_mass_kg:"))

        # 15. mass negative
        rec = self._base_record()
        rec["regions"][0]["heavy_metal_mass_kg"] = -2.0
        with self.assertRaises(RecordError) as ctx:
            validate(rec)
        self.assertTrue(str(ctx.exception).startswith("regions[0].heavy_metal_mass_kg:"))

        # 16. mass nan
        rec = self._base_record()
        rec["regions"][0]["heavy_metal_mass_kg"] = float("nan")
        with self.assertRaises(RecordError) as ctx:
            validate(rec)
        self.assertTrue(str(ctx.exception).startswith("regions[0].heavy_metal_mass_kg:"))

        # 17. power_w wrong length
        rec = self._base_record()
        rec["regions"][0]["power_w"] = [1000, 2000]
        with self.assertRaises(RecordError) as ctx:
            validate(rec)
        self.assertTrue(str(ctx.exception).startswith("regions[0].power_w:"))

        # 18. power_w negative
        rec = self._base_record()
        rec["regions"][0]["power_w"] = [-1000, 2000, 1500]
        with self.assertRaises(RecordError) as ctx:
            validate(rec)
        self.assertTrue(str(ctx.exception).startswith("regions[0].power_w[0]:"))

        # 19. power_w bool
        rec = self._base_record()
        rec["regions"][0]["power_w"] = [True, 2000, 1500]
        with self.assertRaises(RecordError) as ctx:
            validate(rec)
        self.assertTrue(str(ctx.exception).startswith("regions[0].power_w[0]:"))

        # 20. burnup_mwd_per_tu wrong length
        rec = self._base_record()
        rec["regions"][0]["burnup_mwd_per_tu"] = [5.0, 25.0]
        with self.assertRaises(RecordError) as ctx:
            validate(rec)
        self.assertTrue(str(ctx.exception).startswith("regions[0].burnup_mwd_per_tu:"))

        # 21. burnup_mwd_per_tu decreasing
        rec = self._base_record()
        rec["regions"][0]["burnup_mwd_per_tu"] = [25.0, 5.0, 47.5]
        with self.assertRaises(RecordError) as ctx:
            validate(rec)
        self.assertTrue(str(ctx.exception).startswith("regions[0].burnup_mwd_per_tu[1]:"))

        # 22. burnup_mwd_per_tu negative
        rec = self._base_record()
        rec["regions"][0]["burnup_mwd_per_tu"] = [-5.0, 25.0, 47.5]
        with self.assertRaises(RecordError) as ctx:
            validate(rec)
        self.assertTrue(str(ctx.exception).startswith("regions[0].burnup_mwd_per_tu[0]:"))

        # 23. burnup disagrees with power history by 1 part in 1e6
        rec = self._base_record()
        rec["regions"][0]["burnup_mwd_per_tu"] = [5.0 * (1 + 1e-6), 25.0, 47.5]
        with self.assertRaises(RecordError) as ctx:
            validate(rec)
        self.assertTrue(str(ctx.exception).startswith("regions[0].burnup_mwd_per_tu[0]:"))

        # 24. k wrong length
        rec = self._base_record()
        rec["k"] = [[1.30, 0.001], [1.29, 0.001]]
        with self.assertRaises(RecordError) as ctx:
            validate(rec)
        self.assertTrue(str(ctx.exception).startswith("k:"))

        # 25. k a pair of the wrong size
        rec = self._base_record()
        rec["k"][0] = [1.30]
        with self.assertRaises(RecordError) as ctx:
            validate(rec)
        self.assertTrue(str(ctx.exception).startswith("k[0]:"))

        # 26. k value 0
        rec = self._base_record()
        rec["k"][0] = [0.0, 0.001]
        with self.assertRaises(RecordError) as ctx:
            validate(rec)
        self.assertTrue(str(ctx.exception).startswith("k[0][0]:"))

        # 27. k negative sigma
        rec = self._base_record()
        rec["k"][0] = [1.30, -0.001]
        with self.assertRaises(RecordError) as ctx:
            validate(rec)
        self.assertTrue(str(ctx.exception).startswith("k[0][1]:"))

        # 28. isotopics naming a region that does not exist
        rec = self._base_record()
        rec["isotopics"] = {"ghost_region": {"U235": [1e20, 9e19, 8e19, 7e19]}}
        with self.assertRaises(RecordError) as ctx:
            validate(rec)
        self.assertTrue(str(ctx.exception).startswith("isotopics.ghost_region:"))

        # 29. isotopics a list of the wrong length
        rec = self._base_record()
        rec["isotopics"] = {"fuel": {"U235": [1e20, 9e19, 8e19]}}
        with self.assertRaises(RecordError) as ctx:
            validate(rec)
        self.assertTrue(str(ctx.exception).startswith("isotopics.fuel.U235:"))

        # 30. isotopics a negative amount
        rec = self._base_record()
        rec["isotopics"] = {"fuel": {"U235": [-1.0, 9e19, 8e19, 7e19]}}
        with self.assertRaises(RecordError) as ctx:
            validate(rec)
        self.assertTrue(str(ctx.exception).startswith("isotopics.fuel.U235[0]:"))

        # 31. provenance missing
        rec = self._base_record()
        del rec["provenance"]
        with self.assertRaises(RecordError) as ctx:
            validate(rec)
        self.assertTrue(str(ctx.exception).startswith("provenance:"))

        # 32. provenance a list
        rec = self._base_record()
        rec["provenance"] = ["not", "an", "object"]
        with self.assertRaises(RecordError) as ctx:
            validate(rec)
        self.assertTrue(str(ctx.exception).startswith("provenance:"))

    def test_round_trip_and_io(self):
        """Round trip serialization and I/O error handling."""
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td)
            rec = self._base_record()

            # write then read returns an equal record
            target = write(folder, rec)
            self.assertEqual(target, folder / "depletion.json")
            self.assertTrue(target.is_file())

            # the file ends with a newline and contains no carriage return
            raw = target.read_bytes()
            self.assertTrue(raw.endswith(b"\n"))
            self.assertNotIn(b"\r", raw)

            read_back = read(folder)
            self.assertEqual(read_back, rec)

            # writing an invalid record raises RecordError and leaves no file
            sub_bad = folder / "bad_run"
            sub_bad.mkdir()
            bad_rec = copy.deepcopy(rec)
            bad_rec["schema"] = "invalid"
            with self.assertRaises(RecordError):
                write(sub_bad, bad_rec)
            self.assertFalse((sub_bad / "depletion.json").exists())

            # read of invalid JSON text raises RecordError
            sub_corrupt = folder / "corrupt_run"
            sub_corrupt.mkdir()
            (sub_corrupt / "depletion.json").write_bytes(b"{not valid json")
            with self.assertRaises(RecordError) as ctx:
                read(sub_corrupt)
            self.assertTrue(str(ctx.exception).startswith("depletion.json: not valid JSON"))

            # read in an empty folder raises FileNotFoundError
            sub_empty = folder / "empty_run"
            sub_empty.mkdir()
            with self.assertRaises(FileNotFoundError):
                read(sub_empty)

            # writing into a folder that does not exist raises OSError
            non_existent = folder / "does_not_exist"
            with self.assertRaises(OSError):
                write(non_existent, rec)

    def test_bad_inputs_arithmetic_and_builder(self):
        """Exercise bad inputs to burnup_mwd_per_tu, to_oxide_basis, and build_record."""
        # burnup_mwd_per_tu bad inputs
        with self.assertRaises(RecordError):
            burnup_mwd_per_tu("not_a_list", [1000], 2.0)
        with self.assertRaises(RecordError):
            burnup_mwd_per_tu([], [], 2.0)
        with self.assertRaises(RecordError):
            burnup_mwd_per_tu([10], "not_a_list", 2.0)
        with self.assertRaises(RecordError):
            burnup_mwd_per_tu([10], [1000, 2000], 2.0)
        with self.assertRaises(RecordError):
            burnup_mwd_per_tu([10], [-1000], 2.0)
        with self.assertRaises(RecordError):
            burnup_mwd_per_tu([10], [1000], 0)
        with self.assertRaises(RecordError):
            burnup_mwd_per_tu([10], [1000], -1.0)
        with self.assertRaises(RecordError):
            burnup_mwd_per_tu([10], [1000], True)

        # to_oxide_basis bad inputs
        with self.assertRaises(RecordError):
            to_oxide_basis(True, 0.8)
        with self.assertRaises(RecordError):
            to_oxide_basis("100", 0.8)
        with self.assertRaises(RecordError):
            to_oxide_basis([100, "200"], 0.8)
        with self.assertRaises(RecordError):
            to_oxide_basis([100, True], 0.8)

        # build_record bad inputs
        with self.assertRaises(RecordError):
            build_record([10], "not_a_list")
        with self.assertRaises(RecordError):
            build_record([10], ["not_a_dict"])
        with self.assertRaises(RecordError):
            build_record([10], [{"name": "fuel", "cell_ids": [1], "heavy_metal_mass_kg": 2.0}])

    def test_additional_edge_cases(self):
        """Zero power steps, zero burnup, zero sigma k, and malformed structures."""
        # Zero power step (burnup remains constant)
        steps = [10, 20]
        power = [1000, 0]
        mass = 2.0
        bu = burnup_mwd_per_tu(steps, power, mass)
        self.assertEqual(len(bu), 2)
        self.assertAlmostEqual(bu[0], 5.0, delta=1e-12)
        self.assertAlmostEqual(bu[1], 5.0, delta=1e-12)
        rec_zero_power = build_record(steps, [{"name": "fuel", "cell_ids": [1], "heavy_metal_mass_kg": mass, "power_w": power}])
        validate(rec_zero_power)

        # Zero sigma in k is allowed
        rec_zero_sigma = self._base_record()
        rec_zero_sigma["k"][0] = [1.30, 0.0]
        validate(rec_zero_sigma)

        # Record is not a dict
        with self.assertRaises(RecordError) as ctx:
            validate(["not", "a", "dict"])
        self.assertTrue(str(ctx.exception).startswith("record:"))

        # Unknown key inside a region
        rec_extra = self._base_record()
        rec_extra["regions"][0]["unexpected"] = "bad"
        with self.assertRaises(RecordError) as ctx:
            validate(rec_extra)
        self.assertTrue(str(ctx.exception).startswith("regions[0].unexpected:"))

        # Missing required key inside a region
        rec_missing = self._base_record()
        del rec_missing["regions"][0]["cell_ids"]
        with self.assertRaises(RecordError) as ctx:
            validate(rec_missing)
        self.assertTrue(str(ctx.exception).startswith("regions[0].cell_ids:"))

        # Float cell_id
        rec_float_cid = self._base_record()
        rec_float_cid["regions"][0]["cell_ids"] = [1.5]
        with self.assertRaises(RecordError) as ctx:
            validate(rec_float_cid)
        self.assertTrue(str(ctx.exception).startswith("regions[0].cell_ids[0]:"))

        # Non-dict isotopics
        rec_bad_iso = self._base_record()
        rec_bad_iso["isotopics"] = ["not", "a", "dict"]
        with self.assertRaises(RecordError) as ctx:
            validate(rec_bad_iso)
        self.assertTrue(str(ctx.exception).startswith("isotopics:"))

        # Empty nuclide name in isotopics
        rec_empty_nuc = self._base_record()
        rec_empty_nuc["isotopics"] = {"fuel": {"": [1.0, 1.0, 1.0, 1.0]}}
        with self.assertRaises(RecordError) as ctx:
            validate(rec_empty_nuc)
        self.assertTrue(str(ctx.exception).startswith("isotopics.fuel:"))


class TestRecordId(unittest.TestCase):
    """The id FEED's case names a burnup by: a hash of the record's own content."""

    def make(self, power=1000, k=1.3):
        return build_record([10, 20], [{"name": "fuel", "cell_ids": [1], "heavy_metal_mass_kg": 2.0, "power_w": [power, power]}],
                            k=[[k, 0.001], [k - 0.01, 0.001], [k - 0.02, 0.001]], provenance={"note": "x"})

    def test_every_built_record_has_an_id_that_validate_accepts(self):
        rec = self.make()
        self.assertRegex(rec["id"], "^[0-9a-f]{64}$")
        self.assertEqual(rec["id"], record_id(rec))
        validate(rec)

    def test_the_same_numbers_give_the_same_id_and_a_changed_number_a_different_one(self):
        self.assertEqual(self.make()["id"], self.make()["id"])
        self.assertNotEqual(self.make()["id"], self.make(power=1001)["id"])
        self.assertNotEqual(self.make()["id"], self.make(k=1.31)["id"])

    def test_the_id_does_not_depend_on_key_order_or_on_the_id_itself(self):
        rec = self.make()
        shuffled = dict(reversed(list(rec.items())))
        self.assertEqual(record_id(shuffled), rec["id"])
        self.assertEqual(record_id({k: v for k, v in rec.items() if k != "id"}), rec["id"])

    def test_a_record_changed_after_its_id_was_made_is_refused(self):
        rec = self.make()
        rec["provenance"] = {"note": "edited"}
        with self.assertRaises(RecordError) as ctx:
            validate(rec)
        self.assertIn("id", str(ctx.exception))

    def test_the_id_survives_writing_and_reading(self):
        import tempfile
        rec = self.make()
        with tempfile.TemporaryDirectory(prefix="depl-id-") as tmp:
            write(tmp, rec)
            self.assertEqual(read(tmp)["id"], rec["id"])


def canonical_from_tokens(text):
    """The id's canonical text built from the tokens as the file prints them (sorted keys, no spaces, top-level id left out), the way FEED's
    reader does it in JavaScript, which cannot re-print a float the way Python does. If the writer changes how it prints numbers or
    escapes, this and record_id part ways and the test below fails here first."""
    pos = 0

    def ws():
        nonlocal pos
        while text[pos] in " \t\n\r":
            pos += 1

    def string():
        nonlocal pos
        start = pos
        pos += 1
        while text[pos] != '"':
            pos += 2 if text[pos] == chr(92) else 1
        pos += 1
        return text[start:pos]

    def value(top):
        nonlocal pos
        ws()
        c = text[pos]
        if c == "{":
            pos += 1
            members = []
            ws()
            if text[pos] == "}":
                pos += 1
                return "{}"
            while True:
                ws()
                key = string()
                ws()
                pos += 1
                val = value(False)
                if not (top and json.loads(key) == "id"):
                    members.append((json.loads(key), key + ":" + val))
                ws()
                end = text[pos]
                pos += 1
                if end == "}":
                    break
            return "{" + ",".join(m for _, m in sorted(members)) + "}"
        if c == "[":
            pos += 1
            items = []
            ws()
            if text[pos] == "]":
                pos += 1
                return "[]"
            while True:
                items.append(value(False))
                ws()
                end = text[pos]
                pos += 1
                if end == "]":
                    break
            return "[" + ",".join(items) + "]"
        if c == '"':
            return string()
        start = pos
        while text[pos] not in ",]} \t\n\r":
            pos += 1
        return text[start:pos]

    return value(True)


class TestIdFormatIsPinned(unittest.TestCase):
    """FEED's reader recomputes the id from the file's own text; these keep Studio's writer from drifting away from that."""

    def test_the_committed_real_record_has_the_id_FEED_checks(self):
        text = (ROOT / "test" / "fixtures" / "depletion" / "pin_record.json").read_text(encoding="utf-8")
        self.assertEqual(hashlib.sha256(canonical_from_tokens(text).encode("utf-8")).hexdigest(), json.loads(text)["id"])
        # Also pinned as a literal. (FEED holds a copy of the earlier version of this file, id adde6fb2..., made before provenance gained heavy_metal_atoms_start; it stays a valid record.)
        self.assertEqual(json.loads(text)["id"], "ac9478238ca221e145a9c15604e264e9c0318e41d868111a34e0d830a4359995")

    def test_a_written_file_with_awkward_numbers_and_names_has_the_token_id(self):
        rec = build_record([1.0, 2.5e-05], [{"name": "f\u00fcel \"1\"", "cell_ids": [1], "heavy_metal_mass_kg": 2.0, "power_w": [1000, 1e-05]}],
                           k=[[1.0, 0.001], [0.99, 0.001], [0.98, 1e-05]], provenance={"note": "caf\u00e9"})
        with tempfile.TemporaryDirectory(prefix="depl-tok-") as tmp:
            write(tmp, rec)
            text = (Path(tmp) / "depletion.json").read_text(encoding="utf-8")
        self.assertIn("1e-05", text)
        self.assertIn("1.0", text)
        self.assertEqual(hashlib.sha256(canonical_from_tokens(text).encode("utf-8")).hexdigest(), rec["id"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
