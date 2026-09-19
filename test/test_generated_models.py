"""Runs the model.py files OpenMC Studio writes (test/generated/, from `node test/generate_fixtures.js`).

- every generated model.py compiles and builds its model (this is what caught the Python 3.11 f-string bug)
- lattice fixtures give the same material as their cell-by-cell twin at random points
- the fixed-source fixtures run in OpenMC without lost particles
- detector responses: macro / micro = the He-3 atom density; the current leaving a sphere is positive

Needs OpenMC and nuclear data (OPENMC_CROSS_SECTIONS). Run from the repo root:
    node test/generate_fixtures.js
    python test/test_generated_models.py
"""
import contextlib
import glob
import io
import os
import random
import runpy
import shutil
import tempfile
import unittest

import numpy as np
import openmc

HERE = os.path.dirname(os.path.abspath(__file__))
GEN = os.path.join(HERE, "generated")
FILES = sorted(glob.glob(os.path.join(GEN, "*.py")))


def load(path):
    openmc.reset_auto_ids()
    with contextlib.redirect_stdout(io.StringIO()):
        return runpy.run_path(path, run_name="studio_test")


def material_at(geometry, point):
    found = geometry.find(point)
    fill = found[-1].fill if found else None
    return fill.name if isinstance(fill, openmc.Material) else None


def run(path):
    """Run a generated model in a temporary folder; returns (namespace, {tally name: mean array})."""
    ns = load(path)
    tmp = tempfile.mkdtemp(prefix="studio_gen_")
    cwd = os.getcwd()
    try:
        os.chdir(tmp)
        with contextlib.redirect_stdout(io.StringIO()):
            sp_path = ns["model"].run(output=False)  # OpenMC stops with an error after too many lost particles
        with openmc.StatePoint(sp_path) as sp:
            return ns, {t.name: t.mean.copy() for t in sp.tallies.values()}
    finally:
        os.chdir(cwd)
        shutil.rmtree(tmp, ignore_errors=True)


def run_full(path):
    """Like run(), but returns {tally name: (mean, std_dev)}."""
    ns = load(path)
    tmp = tempfile.mkdtemp(prefix="studio_gen_")
    cwd = os.getcwd()
    try:
        os.chdir(tmp)
        with contextlib.redirect_stdout(io.StringIO()):
            sp_path = ns["model"].run(output=False)
        with openmc.StatePoint(sp_path) as sp:
            return {t.name: (t.mean.copy(), t.std_dev.copy()) for t in sp.tallies.values()}
    finally:
        os.chdir(cwd)
        shutil.rmtree(tmp, ignore_errors=True)


@unittest.skipUnless(FILES, "no generated models: run `node test/generate_fixtures.js` first")
class GeneratedModels(unittest.TestCase):
    def test_builds(self):
        for path in FILES:
            with self.subTest(os.path.basename(path)):
                ns = load(path)
                self.assertIsInstance(ns["model"], openmc.Model)
                ns["model"].geometry.get_all_cells()

    def test_lattice_matches_cell_by_cell(self):
        pairs = [f for f in FILES if not f.endswith("_flat.py") and os.path.exists(f.replace(".py", "_flat.py"))]
        self.assertTrue(pairs)
        for path in pairs:
            with self.subTest(os.path.basename(path)):
                g_lat = load(path)["model"].geometry
                g_flat = load(path.replace(".py", "_flat.py"))["model"].geometry
                self.assertTrue(g_lat.get_all_lattices(), "the fixture should have become a lattice")
                self.assertFalse(g_flat.get_all_lattices(), "the flat twin should have no lattice")
                lo, hi = g_flat.bounding_box
                rng = random.Random(1)
                bad = []
                for _ in range(20000):
                    p = tuple(rng.uniform(lo[k], hi[k]) for k in range(3))
                    a, b = material_at(g_lat, p), material_at(g_flat, p)
                    if a != b:
                        bad.append((p, a, b))
                self.assertFalse(bad, f"{len(bad)} of 20000 points differ, e.g. {bad[:3]}")

    def test_runs(self):
        for name in ("rect_array.py", "hex_array_y.py", "hex_array_x.py", "surface_current.py"):
            with self.subTest(name):
                ns, means = run(os.path.join(GEN, name))
                for mean in means.values():
                    self.assertTrue(np.all(np.isfinite(mean)))
                    self.assertGreater(mean.sum(), 0)

    def test_lattice_part_tallies(self):
        """A tally on parts inside a lattice (CellInstanceFilter bins) equals the same tally on the cell-by-cell
        twin (CellFilter), bin by bin, within Monte Carlo noise."""
        for name, tally in (("rect_tally", "t_rods"), ("hex_tally", "t_pins")):
            with self.subTest(name):
                (m1, s1), (m2, s2) = run_full(os.path.join(GEN, f"{name}.py"))[tally], run_full(os.path.join(GEN, f"{name}_flat.py"))[tally]
                self.assertEqual(m1.shape, m2.shape)
                self.assertTrue(np.all(m1 > 0), "every bin scored")
                z = np.abs(m1 - m2) / np.sqrt(s1 ** 2 + s2 ** 2)
                self.assertTrue(np.all(z < 4), f"lattice vs cell-by-cell differ by {z.max():.1f} sigma: {m1.ravel()} vs {m2.ravel()}")

    def test_detector_responses(self):
        ns, means = run(os.path.join(GEN, "detectors.py"))
        macro, micro = means["t_he3_macro"].sum(), means["t_he3_micro"].sum()
        he3 = next(m for m in ns["materials"] if m.name == "He-3 gas")
        n_he3 = he3.get_nuclide_atom_densities()["He3"]
        self.assertGreater(macro, 0)
        self.assertAlmostEqual(macro / micro / n_he3, 1.0, places=6)
        self.assertGreater(means["t_bf3_macro"].sum(), 0)
        tallies = {t.name: t for t in ns["tallies"]}
        self.assertEqual(ns["detector_responses"][tallies["t_he3_macro"].id],
                         {"material": he3.id, "nuclide": "He3", "mt": 103, "scale": "macro"})


if __name__ == "__main__":
    unittest.main()
