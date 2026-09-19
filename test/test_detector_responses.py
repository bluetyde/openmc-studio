"""
Regression tests for detector response tallies, run against the helper OpenMC Studio writes into model.py:
1. Validates B-10 preset reaction MT 107 and He-3 preset reaction MT 103.
2. Validates multi-nuclide material composition order invariance on shared energy grids.
3. Validates error handling for missing detector materials and invalid nuclides.
"""
import os
import sys
import unittest
import numpy as np

# Ensure OPENMC_CROSS_SECTIONS is set for nuclear data lookups if present
if 'OPENMC_CROSS_SECTIONS' not in os.environ:
    wsl_xs = '/root/nuclear_data/endfb-viii.0-hdf5/cross_sections.xml'
    if os.path.exists(wsl_xs):
        os.environ['OPENMC_CROSS_SECTIONS'] = wsl_xs

import openmc
import openmc.data

HERE = os.path.dirname(os.path.abspath(__file__))
GENERATED = os.path.join(HERE, "generated", "detectors.py")


def _load_studio_helper():
    """The _get_detector_filter that OpenMC Studio writes into model.py, taken from a generated model
    (node test/generate_fixtures.js), so these tests check Studio's real output rather than a copy."""
    import ast
    if not os.path.exists(GENERATED):
        raise unittest.SkipTest("run `node test/generate_fixtures.js` first")
    with open(GENERATED, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_get_detector_filter")
    ns = {"openmc": openmc, "np": np}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), GENERATED, "exec"), ns)
    return ns["_get_detector_filter"]


_get_detector_filter = None


def setUpModule():
    global _get_detector_filter
    _get_detector_filter = _load_studio_helper()


class TestDetectorResponses(unittest.TestCase):

    def test_missing_material_error(self):
        """Passing None for macroscopic scale must raise a clear ValueError."""
        with self.assertRaises(ValueError) as ctx:
            _get_detector_filter(None, 'B10', 107, 'macro')
        self.assertIn("needs a detector material", str(ctx.exception))

    def test_microscopic_requires_explicit_nuclide(self):
        """Microscopic scale requires an explicit target nuclide, not 'all' or empty."""
        mat = openmc.Material(name="BF3 gas")
        mat.set_density('g/cm3', 0.003)
        mat.add_nuclide('B10', 1.0, 'ao')
        with self.assertRaises(ValueError) as ctx:
            _get_detector_filter(mat, 'all', 107, 'micro')
        self.assertIn("needs one target nuclide", str(ctx.exception))

    def test_b10_preset_evaluation(self):
        """B-10 preset: MT 107 (n,a) with B-10 material produces physical macroscopic response."""
        mat_b10 = openmc.Material(name="B-10 enriched BF3 gas")
        mat_b10.set_density('g/cm3', 2.68e-3)
        mat_b10.add_nuclide('B10', 0.96, 'ao')
        mat_b10.add_nuclide('B11', 0.04, 'ao')
        mat_b10.add_element('F', 3.0, 'ao')

        eff = _get_detector_filter(mat_b10, 'B10', 107, 'macro')
        self.assertIsInstance(eff, openmc.EnergyFunctionFilter)
        self.assertTrue(len(eff.energy) > 100)
        # Verify thermal cross section value at ~0.0253 eV (3837 barns * N_B10)
        # About 3840 b at 0.0253 eV, times the B-10 atom density
        n_b10 = mat_b10.get_nuclide_atom_densities()["B10"]
        self.assertAlmostEqual(np.interp(0.0253, eff.energy, eff.y) / n_b10 / 3840.0, 1.0, delta=0.02)

    def test_he3_preset_evaluation(self):
        """He-3 preset: MT 103 (n,p) with He-3 gas produces physical macroscopic response."""
        mat_he3 = openmc.Material(name="He-3 gas (4 atm)")
        mat_he3.set_density('g/cm3', 5.02e-4)
        mat_he3.add_nuclide('He3', 1.0, 'ao')

        eff = _get_detector_filter(mat_he3, 'He3', 103, 'macro')
        self.assertIsInstance(eff, openmc.EnergyFunctionFilter)
        # About 5316 b at 0.0253 eV, times the He-3 atom density
        n_he3 = mat_he3.get_nuclide_atom_densities()["He3"]
        self.assertAlmostEqual(np.interp(0.0253, eff.energy, eff.y) / n_he3 / 5316.0, 1.0, delta=0.02)

    def test_composition_order_invariance(self):
        """Permuting the composition text/entry order must yield identical macroscopic response."""
        # Material 1: B10 first, then B11, then F19
        mat1 = openmc.Material(name="BF3 Gas Order 1")
        mat1.set_density('g/cm3', 0.0028)
        mat1.add_nuclide('B10', 0.20, 'ao')
        mat1.add_nuclide('B11', 0.80, 'ao')
        mat1.add_element('F', 3.0, 'ao')

        # Material 2: F19 first, then B11, then B10
        mat2 = openmc.Material(name="BF3 Gas Order 2")
        mat2.set_density('g/cm3', 0.0028)
        mat2.add_element('F', 3.0, 'ao')
        mat2.add_nuclide('B11', 0.80, 'ao')
        mat2.add_nuclide('B10', 0.20, 'ao')

        eff1 = _get_detector_filter(mat1, 'all', 107, 'macro')
        eff2 = _get_detector_filter(mat2, 'all', 107, 'macro')

        self.assertEqual(len(eff1.energy), len(eff2.energy))
        np.testing.assert_allclose(eff1.energy, eff2.energy, rtol=1e-12)
        np.testing.assert_allclose(eff1.y, eff2.y, rtol=1e-12)

    def test_nuclide_without_reaction_error(self):
        """Selecting a reaction not present in the material's nuclides raises a clear ValueError."""
        mat_h = openmc.Material(name="Hydrogen gas")
        mat_h.set_density('g/cm3', 8.9e-5)
        mat_h.add_nuclide('H1', 1.0, 'ao')

        with self.assertRaises(ValueError) as ctx:
            _get_detector_filter(mat_h, 'all', 107, 'macro')
        self.assertIn("No nuclide in material 'Hydrogen gas' has reaction MT 107", str(ctx.exception))


if __name__ == '__main__':  # python test/test_detector_responses.py (after node test/generate_fixtures.js)
    unittest.main()
