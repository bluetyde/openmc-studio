"""A Studio torus in the MCNP deck: written as a TX/TY/TZ card and compared with OpenMC point by point.

The exporter (OPENMC_MCNP_PROJECT, src/torus_cards.py) hands MCNPy a stand-in sphere and rewrites its card, because MCNPy itself cannot translate an OpenMC torus.
Generate the fixtures first (`node test/generate_fixtures.js`); needs the MCNPy gateway (port 25333: claim it first where agents share a machine).

    python test/test_torus_mcnp.py
"""
import contextlib
import io
import os
import re
import runpy
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(os.environ["OPENMC_MCNP_PROJECT"]) / "src"))
import openmc  # noqa: E402
from export_mcnp import translate  # noqa: E402
from remediate_deck import remediate  # noqa: E402
from validate_deck import validate_deck  # noqa: E402

HERE = Path(__file__).parent / "generated"


def deck_of(name):
    openmc.reset_auto_ids()
    ns = runpy.run_path(str(HERE / f"{name}_mcnp.py"), run_name="test_export")
    model, ids = ns["model"], ns["studio_ids"]
    with tempfile.TemporaryDirectory(prefix="studio_torus_mcnp_") as folder:
        base, out = Path(folder) / "raw.mcnp", Path(folder) / "ready.mcnp"
        with contextlib.redirect_stdout(io.StringIO()):
            translate(model, str(base))
            remediate(str(base), model, str(out), detector_responses=ns.get("detector_responses"), studio_ids=ids)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ok = validate_deck(str(out), model=model, geometry_samples=6000)
        return out.read_text(), ok, buf.getvalue()


class TorusDeck(unittest.TestCase):
    def check(self, name, card, values, compared=True):
        deck, ok, report = deck_of(name)
        self.assertTrue(ok, report[-1200:])
        self.assertRegex(deck, rf"(?m)^\d+ {card} {values}$")
        self.assertNotRegex(deck, r"(?m)^\d+ SO? .*77\d\d\.0$", "no stand-in sphere (radius 7778, 7779, ...) is left in the deck")
        if compared:
            self.assertNotIn("no sampled point fell in it", report, "the torus cell is compared, not skipped")
        return deck

    def test_z_axis_elliptical_torus(self):
        self.check("torus_ellip", "TZ", r"0 0 0 10\.0 2\.0 1\.0")

    def test_x_axis_torus(self):
        self.check("torus_x", "TX", r"0 0 0 10\.0 2\.0 1\.0")

    def test_the_swapped_minor_radii_are_written_swapped(self):
        # the slab part holds all of this shallow torus, so its cell gets no sample points; the card itself shows the order
        self.check("torus_swapped", "TZ", r"0 0 0 10\.0 1\.0 2\.0", compared=False)

    def test_three_tori_in_a_lattice_are_one_surface(self):
        deck = self.check("torus_lattice", "TZ", r"0 0 0 10\.0 2\.0 1\.0")
        self.assertEqual(len(re.findall(r"(?m)^\d+ TZ ", deck)), 1, "the lattice element is one torus surface used three times")


if __name__ == "__main__":
    unittest.main(verbosity=2)
