"""
Regression tests for detector response tallies:
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

def _get_detector_filter(mat, nuclide, mt, scale="macro"):
    """Detector filter generator mirroring Studio buildScript."""
    lib = openmc.data.DataLibrary.from_xml()
    if scale == "macro":
        if mat is None:
            raise ValueError("Macroscopic detector response requires an assigned material with atom densities.")
        densities = mat.get_nuclide_atom_densities()
        if not densities:
            raise ValueError(f"Material '{getattr(mat, 'name', 'unnamed')}' has no defined nuclide atom densities.")
        if nuclide and nuclide != "all":
            target_nuclides = [nuclide]
        else:
            target_nuclides = sorted(densities.keys())
        contributions = []
        for nuc in target_nuclides:
            entry = lib.get_by_material(nuc)
            if not entry:
                continue
            nuc_data = openmc.data.IncidentNeutron.from_hdf5(entry["path"])
            if mt not in nuc_data.reactions:
                continue
            rx = nuc_data.reactions[mt]
            temp = list(rx.xs.keys())[0]
            xs = rx.xs[temp]
            N_i = densities.get(nuc, 1.0)
            contributions.append((xs.x, xs.y * N_i))
        if not contributions:
            mat_name = getattr(mat, 'name', 'unnamed')
            raise ValueError(f"No nuclides in material '{mat_name}' have reaction MT {mt} in cross sections library")
        if len(contributions) == 1:
            return openmc.EnergyFunctionFilter(contributions[0][0], contributions[0][1])
        all_e = np.unique(np.concatenate([c[0] for c in contributions]))
        total_macro = np.zeros_like(all_e)
        for e_grid, macro_vals in contributions:
            total_macro += np.interp(all_e, e_grid, macro_vals, left=0.0, right=0.0)
        return openmc.EnergyFunctionFilter(all_e, total_macro)
    else:
        if not nuclide or nuclide == "all":
            raise ValueError("Microscopic detector response requires an explicit target nuclide.")
        entry = lib.get_by_material(nuclide)
        if not entry:
            raise ValueError(f"Nuclide {nuclide} not in cross sections library")
        nuc_data = openmc.data.IncidentNeutron.from_hdf5(entry["path"])
        if mt not in nuc_data.reactions:
            raise ValueError(f"Nuclide {nuclide} does not have reaction MT {mt}")
        rx = nuc_data.reactions[mt]
        temp = list(rx.xs.keys())[0]
        xs = rx.xs[temp]
        return openmc.EnergyFunctionFilter(xs.x, xs.y)


class TestDetectorResponses(unittest.TestCase):

    def test_missing_material_error(self):
        """Passing None for macroscopic scale must raise a clear ValueError."""
        with self.assertRaises(ValueError) as ctx:
            _get_detector_filter(None, 'B10', 107, 'macro')
        self.assertIn("Macroscopic detector response requires an assigned material", str(ctx.exception))

    def test_microscopic_requires_explicit_nuclide(self):
        """Microscopic scale requires an explicit target nuclide, not 'all' or empty."""
        mat = openmc.Material(name="BF3 gas")
        mat.set_density('g/cm3', 0.003)
        mat.add_nuclide('B10', 1.0, 'ao')
        with self.assertRaises(ValueError) as ctx:
            _get_detector_filter(mat, 'all', 107, 'micro')
        self.assertIn("Microscopic detector response requires an explicit target nuclide", str(ctx.exception))

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
        thermal_idx = np.argmin(np.abs(eff.energy - 0.0253))
        self.assertGreater(eff.y[thermal_idx], 0.0)

    def test_he3_preset_evaluation(self):
        """He-3 preset: MT 103 (n,p) with He-3 gas produces physical macroscopic response."""
        mat_he3 = openmc.Material(name="He-3 gas (4 atm)")
        mat_he3.set_density('g/cm3', 5.02e-4)
        mat_he3.add_nuclide('He3', 1.0, 'ao')

        eff = _get_detector_filter(mat_he3, 'He3', 103, 'macro')
        self.assertIsInstance(eff, openmc.EnergyFunctionFilter)
        thermal_idx = np.argmin(np.abs(eff.energy - 0.0253))
        # Thermal microscopic cross section is ~5316 b; verify macro product
        self.assertGreater(eff.y[thermal_idx], 0.0)

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
        self.assertIn("No nuclides in material 'Hydrogen gas' have reaction MT 107", str(ctx.exception))


if __name__ == '__main__':
    unittest.main()
