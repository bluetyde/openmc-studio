"""Tests for openmc_studio.material_assistant.

Covers:
- Constants cross-check against openmc.data atomic masses and natural abundances.
- Mass conservation across multiple enrichments, densities, and soluble boron concentrations.
- Uranium dioxide stoichiometry, U-235 mass share, and pure U-235 boundary behavior.
- Uranium dioxide scaling with percent of theoretical density and theoretical density.
- Uranium dioxide published-fact check (uranium mass share and heavy metal + oxygen atom density).
- Borated water stoichiometry, light/heavy water limits, and intermediate deuterium fractions.
- Borated water soluble boron ppm definition, B-10 isotopic share, and mass conservation.
- Determinism of function results given identical arguments.
- Comprehensive MaterialError input validation and argument naming across all parameters.
"""
import math
from pathlib import Path
import sys
import unittest

import openmc.data

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "studio"))

from openmc_studio.material_assistant import (  # noqa: E402
    ATOMIC_MASSES,
    NATURAL_ABUNDANCES,
    MaterialError,
    borated_water,
    uranium_dioxide,
)


class TestMaterialAssistantConstants(unittest.TestCase):
    def test_constants_cross_check(self):
        """1. Constants cross-check: atomic masses and boron abundances match openmc.data."""
        for nuclide, mass in ATOMIC_MASSES.items():
            with self.subTest(nuclide=nuclide):
                expected_mass = openmc.data.atomic_mass(nuclide)
                rel_diff = abs(mass - expected_mass) / expected_mass
                self.assertLess(
                    rel_diff,
                    1e-9,
                    f"Atomic mass for {nuclide} ({mass}) differs from openmc.data ({expected_mass})",
                )

        b10_expected = openmc.data.NATURAL_ABUNDANCE["B10"]
        b11_expected = openmc.data.NATURAL_ABUNDANCE["B11"]
        self.assertAlmostEqual(NATURAL_ABUNDANCES["B10"], b10_expected, delta=1e-9)
        self.assertAlmostEqual(NATURAL_ABUNDANCES["B11"], b11_expected, delta=1e-9)


class TestUraniumDioxide(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_masses = {n: openmc.data.atomic_mass(n) for n in ("U235", "U238", "O16")}
        cls.n_a = 6.02214076e23

    def test_mass_conservation(self):
        """2. Mass conservation: mass fractions sum to 1 within 1e-12; density matches within 1e-12 relative."""
        enrichments = (0.711, 3.0, 4.95, 100.0)
        percent_tds = (95.0, 100.0)
        td = 10.96

        for enr in enrichments:
            for ptd in percent_tds:
                with self.subTest(enrichment=enr, percent_td=ptd):
                    res = uranium_dioxide(enr, ptd, td)
                    sum_mf = sum(res["mass_fractions"].values())
                    self.assertAlmostEqual(sum_mf, 1.0, delta=1e-12)

                    density = res["density_g_cm3"]
                    ad = res["atom_density_per_b_cm"]
                    reconstructed_density = (
                        sum(ad[n] * self.test_masses[n] for n in ad) / self.n_a * 1e24
                    )
                    rel_density_diff = abs(reconstructed_density - density) / density
                    self.assertLess(
                        rel_density_diff,
                        1e-12,
                        f"Density reconstruction failed for enr={enr}, ptd={ptd}",
                    )

    def test_stoichiometry_and_enrichment(self):
        """3. Stoichiometry: O-16 atoms are 2x U atoms; U-235 mass share matches enrichment; U-238 is 0.0 at 100%."""
        for enr in (0.711, 3.0, 4.95, 100.0):
            with self.subTest(enrichment=enr):
                res = uranium_dioxide(enr, 95.0, 10.96)
                ad = res["atom_density_per_b_cm"]
                u_atoms = ad["U235"] + ad["U238"]
                self.assertAlmostEqual(ad["O16"], 2.0 * u_atoms, delta=2.0 * u_atoms * 1e-12)

                m5 = ad["U235"] * self.test_masses["U235"]
                m8 = ad["U238"] * self.test_masses["U238"]
                u_mass_share = m5 / (m5 + m8)
                self.assertAlmostEqual(u_mass_share, enr / 100.0, delta=1e-12)

        res100 = uranium_dioxide(100.0, 95.0, 10.96)
        self.assertEqual(res100["mass_fractions"]["U238"], 0.0)
        self.assertEqual(res100["atom_density_per_b_cm"]["U238"], 0.0)

    def test_scaling(self):
        """4. Scaling: doubling percent_td doubles density and atom densities; linear with theoretical density."""
        res_50 = uranium_dioxide(3.2, 50.0, 10.96)
        res_100 = uranium_dioxide(3.2, 100.0, 10.96)

        self.assertAlmostEqual(res_100["density_g_cm3"], 2.0 * res_50["density_g_cm3"], delta=1e-12)
        for nuclide in ("U235", "U238", "O16"):
            self.assertAlmostEqual(
                res_100["atom_density_per_b_cm"][nuclide],
                2.0 * res_50["atom_density_per_b_cm"][nuclide],
                delta=1e-12,
            )
            self.assertEqual(res_100["mass_fractions"][nuclide], res_50["mass_fractions"][nuclide])

        # Atom densities scale linearly with theoretical_density_g_cm3
        res_td1 = uranium_dioxide(3.2, 95.0, 10.0)
        res_td2 = uranium_dioxide(3.2, 95.0, 20.0)
        self.assertAlmostEqual(res_td2["density_g_cm3"], 2.0 * res_td1["density_g_cm3"], delta=1e-12)
        for nuclide in ("U235", "U238", "O16"):
            self.assertAlmostEqual(
                res_td2["atom_density_per_b_cm"][nuclide],
                2.0 * res_td1["atom_density_per_b_cm"][nuclide],
                delta=1e-12,
            )
            self.assertEqual(res_td2["mass_fractions"][nuclide], res_td1["mass_fractions"][nuclide])

    def test_published_facts(self):
        """5. Published-fact check: natural U mass share near 0.8815; total atom density near 0.0696."""
        res = uranium_dioxide(0.711, 95.0, 10.96)
        u_mass_frac = res["mass_fractions"]["U235"] + res["mass_fractions"]["U238"]
        self.assertAlmostEqual(u_mass_frac, 0.8815, delta=2e-4)

        total_ad = sum(res["atom_density_per_b_cm"].values())
        ref_atom_density = 3.0 * (10.412 * 6.02214076e23 / 270.03 * 1e-24)
        self.assertAlmostEqual(total_ad, 0.0696, delta=0.0696 * 0.01)
        self.assertAlmostEqual(total_ad, ref_atom_density, delta=ref_atom_density * 0.01)


class TestBoratedWater(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_masses = {n: openmc.data.atomic_mass(n) for n in ("H1", "H2", "O16", "B10", "B11")}
        cls.n_a = 6.02214076e23

    def test_water_stoichiometry_and_deuterium(self):
        """6. Borated water: stoichiometry at 0 ppm, pure heavy water, and 50/50 H/D mixture."""
        # boron_ppm = 0 and deuterium_fraction = 0
        res_light = borated_water(0, 1.0, deuterium_fraction=0.0)
        expected_h1_mf = 2.0 * 1.008 / 18.015
        self.assertAlmostEqual(res_light["mass_fractions"]["H1"], expected_h1_mf, delta=1e-3)
        self.assertEqual(res_light["mass_fractions"]["B10"], 0.0)
        self.assertEqual(res_light["mass_fractions"]["B11"], 0.0)
        self.assertEqual(res_light["mass_fractions"]["H2"], 0.0)
        self.assertEqual(res_light["atom_density_per_b_cm"]["B10"], 0.0)
        self.assertEqual(res_light["atom_density_per_b_cm"]["B11"], 0.0)
        self.assertEqual(res_light["atom_density_per_b_cm"]["H2"], 0.0)

        h_to_o_ratio = (
            res_light["atom_density_per_b_cm"]["H1"] / res_light["atom_density_per_b_cm"]["O16"]
        )
        self.assertAlmostEqual(h_to_o_ratio, 2.0, delta=2.0 * 1e-12)

        # deuterium_fraction = 1
        res_heavy = borated_water(0, 1.0, deuterium_fraction=1.0)
        self.assertEqual(res_heavy["mass_fractions"]["H1"], 0.0)
        self.assertEqual(res_heavy["atom_density_per_b_cm"]["H1"], 0.0)
        expected_h2_mf = 2.0 * 2.014 / 20.028
        self.assertAlmostEqual(res_heavy["mass_fractions"]["H2"], expected_h2_mf, delta=1e-3)

        # deuterium_fraction = 0.5
        res_half = borated_water(0, 1.0, deuterium_fraction=0.5)
        ad_h1 = res_half["atom_density_per_b_cm"]["H1"]
        ad_h2 = res_half["atom_density_per_b_cm"]["H2"]
        self.assertAlmostEqual(ad_h2, ad_h1, delta=ad_h1 * 1e-12)

    def test_ppm_definition_and_b10_abundance(self):
        """7. Boron ppm definition, B-10 isotopic share, and mass conservation."""
        for ppm in (0, 1, 700, 2500):
            with self.subTest(ppm=ppm):
                res = borated_water(ppm, 0.998)
                b_mf = res["mass_fractions"]["B10"] + res["mass_fractions"]["B11"]
                self.assertAlmostEqual(b_mf, ppm * 1e-6, delta=1e-15)

                sum_mf = sum(res["mass_fractions"].values())
                self.assertAlmostEqual(sum_mf, 1.0, delta=1e-12)

                ad = res["atom_density_per_b_cm"]
                reconstructed_density = (
                    sum(ad[n] * self.test_masses[n] for n in ad) / self.n_a * 1e24
                )
                rel_diff = abs(reconstructed_density - res["density_g_cm3"]) / res["density_g_cm3"]
                self.assertLess(rel_diff, 1e-12)

        # B-10 atom share among boron equals b10_atom_fraction
        test_cases = [
            (None, openmc.data.NATURAL_ABUNDANCE["B10"]),
            (0.5, 0.5),
            (1.0, 1.0),
        ]
        for b10_arg, expected_share in test_cases:
            with self.subTest(b10_atom_fraction=b10_arg):
                if b10_arg is None:
                    res = borated_water(1000, 0.998)
                else:
                    res = borated_water(1000, 0.998, b10_atom_fraction=b10_arg)
                ad = res["atom_density_per_b_cm"]
                b10_share = ad["B10"] / (ad["B10"] + ad["B11"])
                self.assertAlmostEqual(b10_share, expected_share, delta=1e-12)


class TestDeterminism(unittest.TestCase):
    def test_determinism(self):
        """8. Determinism: two calls with the same arguments return equal dicts."""
        u1 = uranium_dioxide(4.5, 95.0, 10.96)
        u2 = uranium_dioxide(4.5, 95.0, 10.96)
        self.assertEqual(u1, u2)

        b1 = borated_water(1200, 0.997, 0.05, 0.25)
        b2 = borated_water(1200, 0.997, 0.05, 0.25)
        self.assertEqual(b1, b2)


class TestValidation(unittest.TestCase):
    def test_uranium_dioxide_invalid_inputs(self):
        """9 & 10. Uranium dioxide input validation and MaterialError argument naming."""
        generic_bads = (
            True,
            False,
            "bad_string",
            None,
            float("nan"),
            float("inf"),
            float("-inf"),
        )

        # enrichment_wt_pct
        for bad_val in generic_bads + (0, 0.0, -1, -5.0, 100.001, 150.0):
            with self.subTest(enrichment_bad=bad_val):
                with self.assertRaises(MaterialError) as cm:
                    uranium_dioxide(bad_val, 95.0, 10.96)
                self.assertIn("enrichment_wt_pct", str(cm.exception))

        # percent_td
        for bad_val in generic_bads + (0, 0.0, -1, -10.0, 100.001, 120.0):
            with self.subTest(percent_td_bad=bad_val):
                with self.assertRaises(MaterialError) as cm:
                    uranium_dioxide(4.5, bad_val, 10.96)
                self.assertIn("percent_td", str(cm.exception))

        # theoretical_density_g_cm3
        for bad_val in generic_bads + (0, 0.0, -0.01, -10.96):
            with self.subTest(theoretical_density_bad=bad_val):
                with self.assertRaises(MaterialError) as cm:
                    uranium_dioxide(4.5, 95.0, bad_val)
                self.assertIn("theoretical_density_g_cm3", str(cm.exception))

    def test_borated_water_invalid_inputs(self):
        """9 & 10. Borated water input validation and MaterialError argument naming."""
        generic_bads = (
            True,
            False,
            "bad_string",
            None,
            float("nan"),
            float("inf"),
            float("-inf"),
        )

        # boron_ppm
        for bad_val in generic_bads + (-0.01, -100.0, 1e6, 1e6 + 1):
            with self.subTest(boron_ppm_bad=bad_val):
                with self.assertRaises(MaterialError) as cm:
                    borated_water(bad_val, 1.0)
                self.assertIn("boron_ppm", str(cm.exception))

        # solution_density_g_cm3
        for bad_val in generic_bads + (0, 0.0, -0.01, -1.0):
            with self.subTest(solution_density_bad=bad_val):
                with self.assertRaises(MaterialError) as cm:
                    borated_water(1000, bad_val)
                self.assertIn("solution_density_g_cm3", str(cm.exception))

        # deuterium_fraction
        for bad_val in generic_bads + (-0.01, -1.0, 1.001, 2.0):
            with self.subTest(deuterium_fraction_bad=bad_val):
                with self.assertRaises(MaterialError) as cm:
                    borated_water(1000, 1.0, deuterium_fraction=bad_val)
                self.assertIn("deuterium_fraction", str(cm.exception))

        # b10_atom_fraction
        for bad_val in generic_bads + (-0.01, -1.0, 1.001, 2.0):
            with self.subTest(b10_atom_fraction_bad=bad_val):
                with self.assertRaises(MaterialError) as cm:
                    borated_water(1000, 1.0, b10_atom_fraction=bad_val)
                self.assertIn("b10_atom_fraction", str(cm.exception))

    def test_missing_arguments_raise_type_error(self):
        """Missing required arguments raise plain TypeError from Python."""
        with self.assertRaises(TypeError):
            uranium_dioxide()  # type: ignore[call-arg]

        with self.assertRaises(TypeError):
            uranium_dioxide(4.5)  # type: ignore[call-arg]

        with self.assertRaises(TypeError):
            uranium_dioxide(4.5, 95.0)  # type: ignore[call-arg]

        with self.assertRaises(TypeError):
            borated_water()  # type: ignore[call-arg]

        with self.assertRaises(TypeError):
            borated_water(1000)  # type: ignore[call-arg]


if __name__ == "__main__":
    unittest.main(verbosity=2)
