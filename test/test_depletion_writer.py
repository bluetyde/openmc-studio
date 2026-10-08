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
from openmc_studio import depletion_record, depletion_writer, provenance, results, server as srv  # noqa: E402
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


def two_regions(shares=(0.3, 0.7), power=100.0, steps=(10.0, 20.0), q=200.0):
    """Two burnable regions that split one source rate by shares; each loses exactly the atoms its own power implies."""
    times = [0.0, steps[0], steps[0] + steps[1]]
    regions = []
    for name, share, mass in (("slice A", shares[0], 1.0), ("slice B", shares[1], 3.0)):
        fissions = share * power * sum(steps) * 86400.0 / (q * JOULES_PER_MEV)
        n0 = 1.0e24
        regions.append({"name": name, "cell_ids": [len(regions) + 1], "hm_mass_kg": mass, "power_fraction": [share, share],
                        "hm_atoms": [n0, n0 - fissions * steps[0] / sum(steps), n0 - fissions], "isotopics": {"U235": [1e22, 9e21, 8e21]}})
    return {"times_days": times, "source_rates_w": [power, power], "k": [[1.3, 0.001], [1.29, 0.001], [1.28, 0.001]],
            "fission_q_mev": q, "provenance": {"run": "demo"}, "regions": regions}


class SeveralRegions(unittest.TestCase):
    def test_each_region_gets_its_share_of_the_power_and_its_own_burnup(self):
        rec = build(two_regions())
        a, b = rec["regions"]
        self.assertEqual((a["name"], b["name"]), ("slice A", "slice B"))
        self.assertAlmostEqual(a["power_w"][0], 30.0)
        self.assertAlmostEqual(b["power_w"][1], 70.0)
        # 30 W for 10 d on 1 kg: 3e-5 MW x 10 d / 0.001 t = 0.3 MWd/t; 70 W on 3 kg: 7e-5 x 10 / 0.003 = 0.2333
        self.assertAlmostEqual(a["burnup_mwd_per_tu"][0], 0.3)
        self.assertAlmostEqual(b["burnup_mwd_per_tu"][0], 0.7 / 3.0)
        self.assertAlmostEqual(a["burnup_mwd_per_tu"][1], 0.9)
        # what the regions give up in energy adds up to what the run was given
        total = sum(p * d for r in rec["regions"] for p, d in zip(r["power_w"], rec["time_steps_days"]))
        self.assertAlmostEqual(total, 100.0 * 30.0)
        depletion_record.validate(rec)
        self.assertEqual(sorted(rec["isotopics"]), ["slice A", "slice B"])

    def test_the_inventory_check_is_made_for_each_region(self):
        rec = build(two_regions())
        for name in ("slice A", "slice B"):
            check = rec["provenance"]["checks"][name]["inventory"]
            self.assertAlmostEqual(check["ratio"], 1.0, places=9)
            self.assertTrue(check["ok"])
        # one region's atoms wrong (as if its share were not what was tallied): only that region is flagged
        data = two_regions()
        data["regions"][1]["hm_atoms"] = [1e24, 1e24 - 2 * (1e24 - data["regions"][1]["hm_atoms"][1]), 1e24 - 2 * (1e24 - data["regions"][1]["hm_atoms"][2])]
        rec = build(data)
        self.assertTrue(rec["provenance"]["checks"]["slice A"]["inventory"]["ok"])
        self.assertFalse(rec["provenance"]["checks"]["slice B"]["inventory"]["ok"])
        self.assertEqual(len(rec["provenance"]["notes"]), 1)
        self.assertIn("slice B", rec["provenance"]["notes"][0])

    def test_the_record_says_how_the_power_was_split(self):
        self.assertIn("kappa-fission", build(two_regions())["provenance"]["region_power"])
        self.assertEqual(build(synthetic())["provenance"]["region_power"], "the whole source rate")

    def test_a_single_region_does_not_need_a_share(self):
        self.assertEqual(build(synthetic())["regions"][0]["power_w"], [100.0, 100.0])


class FakeKeff:
    def __init__(self, v):
        self.nominal_value = v


class FakeFilter:
    def __init__(self, bins):
        self.bins = bins


class FakeTally:
    def __init__(self, name, ids, values):
        self.name = name
        self.filters = [FakeFilter(ids)]
        self.mean = __import__("numpy").array(values).reshape(-1, 1, 1)


class FakeStatePoint:
    """Stands in for openmc.StatePoint, keyed by file name: {name: (k, [tallies])}."""
    files = {}

    def __init__(self, path, autolink=True):
        k, tallies = self.files[Path(path).name]
        self.keff = FakeKeff(k)
        self.tallies = dict(enumerate(tallies))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeResults:
    def __init__(self, ks):
        self.ks = ks

    def get_keff(self, time_units="d"):
        import numpy as np
        return np.array([0.0] * len(self.ks)), np.array([[k, 0.001] for k in self.ks])


class PowerShares(unittest.TestCase):
    """_power_shares reads each step's kappa-fission tally from the step's own transport statepoint (openmc.StatePoint stood in for)."""

    def setUp(self):
        import unittest.mock as mock
        self.tmp = Path(tempfile.mkdtemp(prefix="depl-shares-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        import openmc
        patcher = mock.patch.object(openmc, "StatePoint", FakeStatePoint)
        patcher.start()
        self.addCleanup(patcher.stop)
        FakeStatePoint.files = {}

    def put(self, i, k, ids=(1, 2), values=(3.0, 7.0), name=depletion_writer.POWER_TALLY):
        (self.tmp / f"openmc_simulation_n{i}.h5").write_bytes(b"")
        FakeStatePoint.files[f"openmc_simulation_n{i}.h5"] = (k, [FakeTally("other", [9], [1.0]), FakeTally(name, list(ids), list(values))])

    def test_the_share_of_a_material_is_its_tally_over_the_sum_of_the_burnable_ones(self):
        self.put(0, 1.30)
        self.put(1, 1.29, values=(5.0, 5.0))
        shares = depletion_writer._power_shares(self.tmp, ["1", "2"], FakeResults([1.30, 1.29, 1.28]), 2)
        self.assertEqual(shares, {"1": [0.3, 0.5], "2": [0.7, 0.5]})

    def test_a_material_in_the_tally_that_is_not_burnable_takes_no_share(self):
        self.put(0, 1.30, ids=(1, 2, 7), values=(3.0, 7.0, 90.0))
        shares = depletion_writer._power_shares(self.tmp, ["1", "2"], FakeResults([1.30, 1.29]), 1)
        self.assertEqual(shares, {"1": [0.3], "2": [0.7]})

    def test_a_missing_statepoint_is_refused_and_named(self):
        self.put(0, 1.30)
        with self.assertRaises(WriterError) as ctx:
            depletion_writer._power_shares(self.tmp, ["1", "2"], FakeResults([1.30, 1.29, 1.28]), 2)
        self.assertIn("openmc_simulation_n1.h5", str(ctx.exception))

    def test_a_statepoint_without_the_tally_is_refused(self):
        self.put(0, 1.30, name="something else")
        with self.assertRaises(WriterError) as ctx:
            depletion_writer._power_shares(self.tmp, ["1", "2"], FakeResults([1.30, 1.29]), 1)
        self.assertIn("no power-split tally", str(ctx.exception))

    def test_a_statepoint_of_another_solve_is_refused(self):
        self.put(0, 1.31)  # the results file has k = 1.30 for the start of step 1
        with self.assertRaises(WriterError) as ctx:
            depletion_writer._power_shares(self.tmp, ["1", "2"], FakeResults([1.30, 1.29]), 1)
        self.assertIn("not the solve", str(ctx.exception))

    def test_no_power_in_the_burnable_materials_is_refused(self):
        self.put(0, 1.30, values=(0.0, 0.0))
        with self.assertRaises(WriterError):
            depletion_writer._power_shares(self.tmp, ["1", "2"], FakeResults([1.30, 1.29]), 1)

    def test_a_material_the_tally_does_not_hold_is_refused(self):
        self.put(0, 1.30, ids=(1, 5))
        with self.assertRaises(WriterError) as ctx:
            depletion_writer._power_shares(self.tmp, ["1", "2"], FakeResults([1.30, 1.29]), 1)
        self.assertIn("['2']", str(ctx.exception))


SLICES = json.loads((ROOT / "test" / "fixtures" / "depletion" / "slices_run_data.json").read_text())


class RealTwoSliceRun(unittest.TestCase):
    """The numbers of one real run of the pin cut into two burnable slices (test/manual_depletion_slices.py), through build."""

    def test_each_slice_has_its_power_burnup_and_a_passing_inventory_check(self):
        rec = build(SLICES)
        a, b = rec["regions"]
        self.assertEqual((a["name"], b["name"]), ("UO2 3.5%", "UO2 5%"))
        for step in range(2):
            self.assertAlmostEqual(a["power_w"][step] + b["power_w"][step], SLICES["source_rates_w"][step], places=9)
        self.assertGreater(b["power_w"][0] / b["heavy_metal_mass_kg"], a["power_w"][0] / a["heavy_metal_mass_kg"], "the richer slice takes more power per gram")
        for name in (a["name"], b["name"]):
            check = rec["provenance"]["checks"][name]["inventory"]
            self.assertTrue(check["ok"], check)
            self.assertAlmostEqual(check["ratio"], 1.0, delta=0.02)
        self.assertEqual(rec["provenance"]["notes"], [])
        depletion_record.validate(rec)

    def test_a_split_that_ignored_the_tally_would_fail_the_inventory_check(self):
        data = copy.deepcopy(SLICES)
        for reg in data["regions"]:
            reg["power_fraction"] = [0.5, 0.5]
        checks = build(data)["provenance"]["checks"]
        self.assertFalse(all(c["inventory"]["ok"] for c in checks.values()), "a 50/50 split is the wrong power for at least one slice")

    def test_the_committed_record_is_what_build_gives_today(self):
        rec = json.loads((ROOT / "test" / "fixtures" / "depletion" / "slices_record.json").read_text())
        data = dict(copy.deepcopy(SLICES), steps_planned=2, provenance=rec["provenance"] and {k: rec["provenance"][k] for k in ("run", "integrator", "chain_level", "power_density_w_per_g", "particles", "batches", "seed")})
        self.assertEqual(build(data)["id"], rec["id"])


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
    def test_shares_of_the_power_that_do_not_add_up_to_the_source_rate_are_refused(self):
        data = two_regions()
        data["regions"][1]["power_fraction"] = [0.8, 0.8]
        with self.assertRaises(WriterError) as ctx:
            build(data)
        self.assertIn("add up", str(ctx.exception))

    def test_several_regions_without_their_shares_are_refused(self):
        data = synthetic()
        data["regions"].append(dict(data["regions"][0], name="fuel 2"))
        with self.assertRaises(WriterError):
            build(data)

    def test_two_regions_with_one_name_are_refused(self):
        data = two_regions()
        data["regions"][1]["name"] = "slice A"
        with self.assertRaises(WriterError) as ctx:
            build(data)
        self.assertIn("share the name", str(ctx.exception))

    def test_shares_that_do_not_cover_every_step_are_refused(self):
        data = two_regions()
        data["regions"][0]["power_fraction"] = [0.3]
        with self.assertRaises(WriterError):
            build(data)

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


class Partial(unittest.TestCase):
    """A run that was stopped or failed leaves the steps it finished; the record says how far it got."""

    def test_common_steps_is_the_shortest_array(self):
        self.assertEqual(depletion_writer.common_steps([0, 1, 5], [10.0, 10.0], [[1, 0]] * 3), 2)
        self.assertEqual(depletion_writer.common_steps([0, 1, 5], [10.0], [[1, 0]] * 3), 1, "a rate for one step only")
        self.assertEqual(depletion_writer.common_steps([0, 1, 5], [10.0, 10.0], [[1, 0]] * 2), 1, "k for one step only")
        self.assertEqual(depletion_writer.common_steps([0], [], []), 0)

    def test_a_finished_run_is_complete(self):
        data = synthetic()
        data["steps_planned"] = 2
        prov = build(data)["provenance"]
        self.assertEqual((prov["complete"], prov["steps_done"], prov["steps_planned"]), (True, 2, 2))
        self.assertEqual(prov["notes"], [])
        self.assertTrue(build(synthetic())["provenance"]["complete"], "no planned count given: nothing to compare with")

    def test_two_of_five_steps_is_an_incomplete_record_that_says_so(self):
        data = synthetic()
        data["steps_planned"] = 5
        rec = build(data)
        prov = rec["provenance"]
        self.assertEqual((prov["complete"], prov["steps_done"], prov["steps_planned"]), (False, 2, 5))
        self.assertIn("incomplete: 2 of 5 steps finished", prov["notes"])
        self.assertEqual(len(rec["time_steps_days"]), 2)
        depletion_record.validate(rec)


class ForThePage(unittest.TestCase):
    """results._depletion: what the Results page is given for a run that burned fuel."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="depletion-page-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_a_run_that_did_not_burn_has_no_depletion_payload(self):
        self.assertIsNone(results._depletion(self.tmp))

    def test_the_record_and_the_wall_time_are_given(self):
        (self.tmp / "deplete.py").write_text("pass\n")
        rec = build(PIN)
        depletion_record.write(self.tmp, rec)
        (self.tmp / "meta.json").write_text(json.dumps({"started": 1000.0, "ended": 1095.46}))
        out = results._depletion(self.tmp)
        self.assertEqual(out["record"]["id"], rec["id"])
        self.assertIsNone(out["note"])
        self.assertEqual(out["wall_s"], 95.5)

    def test_load_puts_the_depletion_payload_in_the_results_even_with_no_statepoint(self):
        (self.tmp / "deplete.py").write_text("pass" + chr(10))
        depletion_record.write(self.tmp, build(PIN))
        out = results.load(str(self.tmp))
        self.assertEqual(out["depletion"]["record"]["id"], build(PIN)["id"])
        self.assertNotIn("depletion", results.load(str(self.tmp / "nowhere")), "a run folder that burned nothing has no payload")

    def test_without_a_record_the_reason_is_given(self):
        (self.tmp / "deplete.py").write_text("pass\n")
        self.assertEqual(results._depletion(self.tmp)["note"], "No depletion record yet.")
        (self.tmp / "depletion-record.txt").write_text("No depletion record: 2 burnable materials\n")
        self.assertEqual(results._depletion(self.tmp)["note"], "No depletion record: 2 burnable materials")

    def test_a_record_that_does_not_validate_is_reported_not_raised(self):
        (self.tmp / "deplete.py").write_text("pass\n")
        (self.tmp / "depletion.json").write_text("{not json")
        out = results._depletion(self.tmp)
        self.assertIsNone(out["record"])
        self.assertIn("can't be read", out["note"])


class Fixtures(unittest.TestCase):
    def test_the_record_fixture_the_page_tests_use_is_what_build_gives_for_the_run_fixture(self):
        data = dict(copy.deepcopy(PIN), steps_planned=2, provenance={"run": "20261008-000000-depletion-pin", "integrator": "PredictorIntegrator", "chain_level": 3,
                    "power_density_w_per_g": 38, "particles": 2000, "batches": 15, "seed": 12345})
        self.assertEqual(build(data), json.loads((ROOT / "test" / "fixtures" / "depletion" / "pin_record.json").read_text()),
                         "regenerate both with test/regen_depletion_fixtures.py")

    def test_the_fission_products_the_page_charts_are_in_the_record(self):
        iso = json.loads((ROOT / "test" / "fixtures" / "depletion" / "pin_record.json").read_text())["isotopics"]["UO2 3.5%"]
        for nuc in ("U235", "Pu239", "Xe135", "Sm149"):
            self.assertIn(nuc, iso)
        self.assertGreater(iso["Xe135"][-1], 0)


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
