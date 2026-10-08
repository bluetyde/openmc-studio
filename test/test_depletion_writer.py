"""depletion_writer.py: a finished depletion run as depletion.json.

`build` on plain numbers (the arithmetic, the inventory check, the refusals), on the numbers of a real run of the pin cell Studio
generates (test/fixtures/depletion/pin_run_data.json, read from OpenMC's results by `read_run`), and the server hook that writes the
record when a depletion run ends. Reading OpenMC's results file itself is checked by test/manual_depletion_run.py, which runs a real
depletion and takes minutes.

Run: python test/test_depletion_writer.py   (needs OpenMC importable for the nuclide-name test)
"""
import copy
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "studio"))
from openmc_studio import depletion_record, depletion_writer, provenance, server as srv  # noqa: E402
from openmc_studio.depletion_writer import WriterError, build  # noqa: E402

JOULES_PER_MEV = 1.602176634e-13
PIN = json.loads((ROOT / "test" / "fixtures" / "depletion" / "pin_run_data.json").read_text())


def synthetic(power=100.0, steps=(10.0, 20.0), q=200.0, lost_factor=1.0):
    """Two steps at constant power, with exactly the heavy-metal loss the power implies (times lost_factor)."""
    times = [0.0, steps[0], steps[0] + steps[1]]
    energy = sum(power * d * 86400.0 for d in steps)
    fissions = energy / (q * JOULES_PER_MEV)
    n0 = 1.0e24
    return {"times_days": times, "source_rates_w": [power, power], "k": [[1.3, 0.001], [1.29, 0.001], [1.28, 0.001]],
            "fission_q_mev": q, "provenance": {"run": "demo"},
            "regions": [{"name": "fuel", "cell_ids": [1, 2], "hm_mass_kg": 2.0, "hm_atoms": [n0, n0 - 0.4 * fissions * lost_factor, n0 - fissions * lost_factor],
                         "isotopics": {"U235": [1e22, 9e21, 8e21], "Pu239": [0.0, 1e19, 3e19]}}]}


class Arithmetic(unittest.TestCase):
    def test_the_record_has_durations_power_burnup_k_and_isotopics(self):
        rec = build(synthetic())
        self.assertEqual(rec["time_steps_days"], [10.0, 20.0])
        (reg,) = rec["regions"]
        self.assertEqual((reg["name"], reg["cell_ids"], reg["heavy_metal_mass_kg"], reg["power_w"]), ("fuel", [1, 2], 2.0, [100.0, 100.0]))
        # 100 W for 10 d on 2 kg: 1e-4 MW x 10 d / 0.002 t = 0.5 MWd/t; then 20 d more: 1.5
        self.assertAlmostEqual(reg["burnup_mwd_per_tu"][0], 0.5)
        self.assertAlmostEqual(reg["burnup_mwd_per_tu"][1], 1.5)
        self.assertEqual(rec["k"], [[1.3, 0.001], [1.29, 0.001], [1.28, 0.001]])
        self.assertEqual(rec["isotopics"]["fuel"]["Pu239"], [0.0, 1e19, 3e19])
        self.assertEqual(rec["provenance"]["run"], "demo")
        self.assertEqual(rec["provenance"]["units"]["isotopics"], "atoms in the whole region")
        self.assertRegex(rec["id"], "^[0-9a-f]{64}$")
        depletion_record.validate(rec)

    def test_the_inventory_check_is_one_when_the_atoms_lost_match_the_power(self):
        check = build(synthetic())["provenance"]["checks"]["fuel"]["inventory"]
        self.assertAlmostEqual(check["ratio"], 1.0, places=9)
        self.assertTrue(check["ok"])
        self.assertEqual(build(synthetic())["provenance"]["notes"], [])

    def test_a_wrong_power_is_flagged_but_the_record_is_still_written(self):
        rec = build(synthetic(lost_factor=2.0))  # twice the atoms lost for that power: as if the power were doubled
        check = rec["provenance"]["checks"]["fuel"]["inventory"]
        self.assertAlmostEqual(check["ratio"], 2.0, places=9)
        self.assertFalse(check["ok"])
        self.assertEqual(len(rec["provenance"]["notes"]), 1)
        self.assertIn("inventory check", rec["provenance"]["notes"][0])
        self.assertIn("fuel", rec["regions"][0]["name"])

    def test_the_tolerance_is_five_percent(self):
        self.assertTrue(build(synthetic(lost_factor=1.04))["provenance"]["checks"]["fuel"]["inventory"]["ok"])
        self.assertFalse(build(synthetic(lost_factor=1.06))["provenance"]["checks"]["fuel"]["inventory"]["ok"])
        self.assertFalse(build(synthetic(lost_factor=0.94))["provenance"]["checks"]["fuel"]["inventory"]["ok"])

    def test_the_input_is_not_changed(self):
        data = synthetic()
        before = copy.deepcopy(data)
        build(data)
        self.assertEqual(data, before)


class Refusals(unittest.TestCase):
    def test_two_burnable_regions_are_refused_and_the_message_says_why(self):
        data = synthetic()
        data["regions"].append(dict(data["regions"][0], name="fuel 2"))
        with self.assertRaises(WriterError) as ctx:
            build(data)
        self.assertIn("2 burnable materials", str(ctx.exception))
        self.assertIn("power of each", str(ctx.exception))

    def test_no_region_a_wrong_number_of_time_points_and_times_that_do_not_increase(self):
        data = synthetic()
        data["regions"] = []
        with self.assertRaises(WriterError):
            build(data)
        data = synthetic()
        data["times_days"] = [0.0, 10.0]
        with self.assertRaises(WriterError) as ctx:
            build(data)
        self.assertIn("expected 3", str(ctx.exception))
        data = synthetic()
        data["times_days"] = [0.0, 10.0, 10.0]
        with self.assertRaises(WriterError) as ctx:
            build(data)
        self.assertIn("do not increase", str(ctx.exception))


class RealRun(unittest.TestCase):
    """The numbers OpenMC gave for the UO2 pin cell Studio generates (2,000 x 15, predictor, steps 1 and 4 days, chain level 3)."""

    def test_the_pin_makes_a_record_with_the_burnup_power_density_times_time_gives(self):
        rec = build(PIN)
        (reg,) = rec["regions"]
        self.assertEqual(reg["name"], "UO2 3.5%")
        self.assertEqual(reg["cell_ids"], [1])
        self.assertAlmostEqual(reg["heavy_metal_mass_kg"] * 1000, 6.09, places=2)  # grams of heavy metal in the fuel
        # 38 W per gram of heavy metal for 1 and then 5 days in total: 38 and 190 MWd/tU (the power came from the mass, so to rounding)
        self.assertAlmostEqual(reg["burnup_mwd_per_tu"][0], 38.0, places=6)
        self.assertAlmostEqual(reg["burnup_mwd_per_tu"][1], 190.0, places=6)
        self.assertEqual(rec["time_steps_days"], [1.0, 4.0])

    def test_the_inventory_check_agrees_on_the_real_run(self):
        check = build(PIN)["provenance"]["checks"]["UO2 3.5%"]["inventory"]
        self.assertTrue(check["ok"], check)
        self.assertLess(abs(check["ratio"] - 1), 0.02, "observed 1.004 on this run")
        self.assertAlmostEqual(check["fission_q_mev"], 194.4, places=1)

    def test_the_physics_is_in_the_isotopics(self):
        iso = build(PIN)["isotopics"]["UO2 3.5%"]
        self.assertLess(iso["U235"][-1], iso["U235"][0])
        self.assertEqual(iso["Pu239"][0], 0.0)
        self.assertGreater(iso["Pu239"][-1], 0.0)
        self.assertGreater(iso["U236"][-1], iso["U236"][0])

    def test_a_changed_power_changes_the_check_not_the_record_being_written(self):
        data = copy.deepcopy(PIN)
        data["source_rates_w"] = [r * 1.5 for r in data["source_rates_w"]]
        rec = build(data)
        self.assertFalse(rec["provenance"]["checks"]["UO2 3.5%"]["inventory"]["ok"])


class NuclideNames(unittest.TestCase):
    def test_heavy_means_thorium_and_up(self):
        try:
            import openmc  # noqa: F401
        except ImportError:
            self.fail("OpenMC must be importable (run this under WSL with the openmc-mcnp environment)")
        for heavy in ("Th232", "U235", "Pu239", "Am242_m1", "Cm244"):
            self.assertTrue(depletion_writer._heavy(heavy), heavy)
        for light in ("Xe135", "O16", "Zr90", "Sm149", "H1", "Pb208"):
            self.assertFalse(depletion_writer._heavy(light), light)


class FakeRun:
    def __init__(self, path):
        self.path, self.lines = path, []

    def add(self, text):
        self.lines.append(text)


class ServerHook(unittest.TestCase):
    """What the server does when a depletion run ends: write the record, or say why it did not."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="depletion-hook-"))
        provenance.write(self.tmp, "run", {"settings": {"depletion": True}}, files=())
        self.studio = srv.Studio(self.tmp / "runs", "t" * 32, 0)
        self.real = depletion_writer.from_run

    def tearDown(self):
        depletion_writer.from_run = self.real
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_a_written_record_is_named_in_the_log_and_in_provenance(self):
        depletion_writer.from_run = lambda folder: build(PIN)
        run = FakeRun(self.tmp)
        self.studio._depletion_record(run)
        rec = json.loads((self.tmp / "provenance.json").read_text())["depletion_record"]
        self.assertEqual((rec["status"], rec["file"], rec["checks_ok"]), ("written", "depletion.json", True))
        self.assertRegex(rec["id"], "^[0-9a-f]{64}$")
        self.assertEqual(len(run.lines), 1)
        self.assertIn("Depletion record written", run.lines[0])
        self.assertIn(rec["id"][:12], run.lines[0])

    def test_a_check_outside_its_tolerance_is_said_so(self):
        data = copy.deepcopy(PIN)
        data["source_rates_w"] = [r * 2 for r in data["source_rates_w"]]
        depletion_writer.from_run = lambda folder: build(data)
        run = FakeRun(self.tmp)
        self.studio._depletion_record(run)
        self.assertIn("outside its tolerance", run.lines[0])
        self.assertFalse(json.loads((self.tmp / "provenance.json").read_text())["depletion_record"]["checks_ok"])

    def test_a_refusal_is_written_down_and_does_not_raise(self):
        def refuse(folder):
            raise WriterError("2 burnable materials: no record")
        depletion_writer.from_run = refuse
        run = FakeRun(self.tmp)
        self.studio._depletion_record(run)
        self.assertIn("No depletion record: 2 burnable materials", run.lines[0])
        self.assertIn("2 burnable materials", (self.tmp / "depletion-record.txt").read_text())
        rec = json.loads((self.tmp / "provenance.json").read_text())["depletion_record"]
        self.assertEqual(rec["status"], "not written")

    def test_a_crash_in_the_writer_is_also_only_reported(self):
        def crash(folder):
            raise OSError("results file is unreadable")
        depletion_writer.from_run = crash
        run = FakeRun(self.tmp)
        self.studio._depletion_record(run)
        self.assertIn("results file is unreadable", run.lines[0])


if __name__ == "__main__":
    unittest.main()
