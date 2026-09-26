"""Dose tallies from Studio to MCNP, end to end (plans/dose-rates-plan.md, stage 3).

The `dose_tank` fixture (test/generate_fixtures.js) has a detector sphere cut by a lead plug listed above it,
so its volume is neither a sphere's nor something MCNP can compute itself (the cell is neither polyhedral nor
rotationally symmetric). The test:
  1. runs model.py as a Studio run does: OpenMC's volume calculation, then transport; dose.json has the volume;
  2. prepares the export the way Studio's MCNP worker does (mcnp_worker.dose_description on the MCNP twin);
     its volume must be the SAME number as the run's (same cells, boxes, samples and seed), so the deck's SD
     card and Studio's results divide by one volume;
  3. exports the deck and checks SD, the rate factor (FM, FACTOR), F4:P for the photon dose, DE/DF equal to
     model.py's own padded tables, and that the deck validates.

Needs OpenMC with nuclear data, OPENMC_MCNP_PROJECT (the companion exporter) and the MCNPy gateway (port 25333;
claim it where agents share a machine). Run `node test/generate_fixtures.js` first.
Run: python test/test_dose_mcnp.py
"""
import contextlib
import io
import json
import os
import re
import runpy
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import openmc

ROOT = Path(__file__).resolve().parents[1]
GEN = ROOT / "test" / "generated"
EXP = os.environ.get("OPENMC_MCNP_PROJECT")
sys.path.insert(0, str(ROOT / "studio"))
if EXP:
    sys.path.insert(0, str(Path(EXP) / "src"))


def numbers(deck, head):
    lines = deck.splitlines()
    i = next(k for k, l in enumerate(lines) if l.split()[:1] == [head])
    words = lines[i].split()[1:]
    for l in lines[i + 1:]:
        if not l.startswith("     "):
            break
        words += l.split()
    return [float(w) for w in words if re.fullmatch(r"[-+0-9.eE]+", w)]


class DoseToMcnp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not EXP:
            raise RuntimeError("set OPENMC_MCNP_PROJECT to the companion exporter; this test never skips")
        from openmc_studio.mcnp_worker import dose_description
        from export_mcnp import export
        # 1. the Studio run
        cls.run_dir = Path(tempfile.mkdtemp(prefix="dose-tank-run-"))
        shutil.copy(GEN / "dose_tank.py", cls.run_dir / "model.py")
        r = subprocess.run([sys.executable, "model.py"], cwd=cls.run_dir, capture_output=True, text=True, timeout=1800)
        if r.returncode:
            raise RuntimeError(r.stdout[-3000:] + r.stderr[-3000:])
        cls.run_info = json.loads((cls.run_dir / "dose.json").read_text())
        # 2. the export, prepared as mcnp_worker does it
        cls.exp = Path(tempfile.mkdtemp(prefix="dose-tank-mcnp-"))
        shutil.copy(GEN / "dose_tank_mcnp.py", cls.exp / "model.py")
        cwd = os.getcwd()
        try:
            os.chdir(cls.exp)
            openmc.reset_auto_ids()
            with contextlib.redirect_stdout(io.StringIO()):
                cls.ns = runpy.run_path(str(cls.exp / "model.py"), run_name="studio_export")
                cls.ns["model"].export_to_model_xml(str(cls.exp / "model.xml"))
            cls.dose = dose_description(cls.ns, str(cls.exp))
            with contextlib.redirect_stdout(io.StringIO()):
                cls.report = export(str(cls.exp / "model.xml"), str(cls.exp / "deck"), "tank", samples=5000, dose=cls.dose)
        finally:
            os.chdir(cwd)
        cls.deck = Path(cls.report["runnable"]).read_text()

    def test_export_and_run_use_the_same_volume(self):
        self.assertEqual(len(self.run_info["volumes"]), 1)
        self.assertEqual(self.dose["volumes"], self.run_info["volumes"], "same cells, boxes, samples and seed")
        v = next(iter(self.run_info["volumes"].values()))[0]
        self.assertLess(v, 4 / 3 * 3.141592653589793 * 27 * 0.95, "the plug cuts the sphere: not a plain sphere")
        for n in (4, 14):
            self.assertEqual(numbers(self.deck, f"SD{n}"), [v])

    def test_deck_validates(self):
        self.assertTrue(self.report["ok"], self.report.get("validation", "")[-2000:])

    def test_cards(self):
        d, factor = self.deck, 5e7 * 3600e-12
        self.assertRegex(d, r"(?m)^F4:N \d+$")
        self.assertRegex(d, r"(?m)^F14:P \d+$")
        self.assertRegex(d, r"(?m)^FC4 Detector dose: neutron effective dose, Sv/h \(ICRP116 AP\)$")
        self.assertRegex(d, r"(?m)^FMESH24:N GEOM=XYZ")
        self.assertRegex(d, r"(?m)^FC24 Dose map: neutron effective dose map, Sv/h \(ICRP74 ISO\)$")
        self.assertAlmostEqual(numbers(d, "FM4")[0], factor, delta=factor * 1e-12)
        self.assertRegex(d, r"(?m)^     FACTOR=" + re.escape(repr(factor)) + "$")

    def test_tables_match_model_py(self):
        tallies = {t.name: t for t in self.ns["model"].tallies}
        for n, name in ((4, "Detector dose [neutron dose]"), (14, "Detector dose [photon dose]"), (24, "Dose map [neutron dose]")):
            f = tallies[name].filters[-1]
            self.assertEqual(numbers(self.deck, f"DF{n}"), [float(y) for y in f.y], name)
            de = numbers(self.deck, f"DE{n}")
            self.assertEqual(len(de), len(f.energy))
            for a, b in zip(de, f.energy):
                self.assertAlmostEqual(a, b / 1e6, delta=b / 1e6 * 1e-11)


class DoseInLatticeToMcnp(unittest.TestCase):
    """Dose on parts inside a lattice (fixture dose_lattice): the deck tallies each part as a lattice chain bin
    (unit cell < lattice cell[i j k] < filled cell) and its SD card carries that one element's volume, the same
    number the Studio run divides by (keyed "cell/instance")."""

    @classmethod
    def setUpClass(cls):
        if not EXP:
            raise RuntimeError("set OPENMC_MCNP_PROJECT to the companion exporter; this test never skips")
        from openmc_studio.mcnp_worker import dose_description
        from export_mcnp import export
        cls.run_dir = Path(tempfile.mkdtemp(prefix="dose-lattice-run-"))
        shutil.copy(GEN / "dose_lattice.py", cls.run_dir / "model.py")
        r = subprocess.run([sys.executable, "model.py"], cwd=cls.run_dir, capture_output=True, text=True, timeout=1800)
        if r.returncode:
            raise RuntimeError(r.stdout[-3000:] + r.stderr[-3000:])
        cls.run_info = json.loads((cls.run_dir / "dose.json").read_text())
        cls.exp = Path(tempfile.mkdtemp(prefix="dose-lattice-mcnp-"))
        shutil.copy(GEN / "dose_lattice_mcnp.py", cls.exp / "model.py")
        cwd = os.getcwd()
        try:
            os.chdir(cls.exp)
            openmc.reset_auto_ids()
            with contextlib.redirect_stdout(io.StringIO()):
                cls.ns = runpy.run_path(str(cls.exp / "model.py"), run_name="studio_export")
                cls.ns["model"].export_to_model_xml(str(cls.exp / "model.xml"))
            cls.dose = dose_description(cls.ns, str(cls.exp))
            with contextlib.redirect_stdout(io.StringIO()):
                cls.report = export(str(cls.exp / "model.xml"), str(cls.exp / "deck"), "lat", samples=5000, dose=cls.dose)
        finally:
            os.chdir(cwd)
        cls.deck = Path(cls.report["runnable"]).read_text()

    def test_export_and_run_use_the_same_volumes(self):
        self.assertEqual(self.dose["volumes"], self.run_info["volumes"])
        self.assertEqual(sum("/" in k for k in self.run_info["volumes"]), 2, self.run_info["volumes"])
        self.assertEqual(sorted(self.run_info["labels"].values()), ["rod_0_0", "rod_2_1"], "lattice parts carry their names")

    def test_chain_bins_and_their_volumes(self):
        f4 = next(l for l in self.deck.splitlines() if l.startswith("F4:N"))
        self.assertEqual(f4.count("<"), 4, f4)  # two lattice parts, each (unit < lattice[i j k] < filled cell)
        order = [k for k in self.run_info["volumes"]]  # CellInstanceFilter order: rod_0_0, rod_2_1, probe
        self.assertEqual(numbers(self.deck, "SD4"), [self.run_info["volumes"][k][0] for k in order])

    def test_deck_validates(self):
        self.assertTrue(self.report["ok"], self.report.get("validation", "")[-2000:])


if __name__ == "__main__":
    unittest.main(verbosity=2)
