"""Tests for pin power table generation, symmetry folding, alignment checking, and CSV export.

Run: python test/test_pin_power_table.py
"""
import math
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "studio"))
from openmc_studio.pin_power_table import (  # noqa: E402
    TableError,
    build_rows,
    check_alignment,
    csv_cell,
    csv_rows,
    fold_quarter,
    radial_peaking,
)


class TestBuildRows(unittest.TestCase):
    """Test build_rows generation, indexing, coordinates, and masking."""

    def test_build_rows_3x2_hand_values(self):
        """1. build_rows on 3x2 lattice (x fastest) against hand values computed by plain loop."""
        nx = 3
        ny = 2
        pitch_x = 1.26
        pitch_y = 1.30
        x0 = -3.0
        y0 = 2.0
        values = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0]
        sigmas = [1.0, 2.0, 1.5, 2.5, 3.0, 0.5]

        rows = build_rows(
            values, sigmas, nx, ny, pitch_x, pitch_y, x0_cm=x0, y0_cm=y0
        )
        self.assertEqual(len(rows), 6)

        expected_mean = sum(values) / len(values)
        self.assertEqual(expected_mean, 35.0)

        idx = 0
        for iy in range(ny):
            for ix in range(nx):
                row = rows[idx]
                self.assertEqual(row["ix"], ix)
                self.assertEqual(row["iy"], iy)
                exp_x = x0 + (ix + 0.5) * pitch_x
                exp_y = y0 + (iy + 0.5) * pitch_y
                self.assertAlmostEqual(row["x_cm"], exp_x)
                self.assertAlmostEqual(row["y_cm"], exp_y)
                self.assertEqual(row["value"], values[idx])
                self.assertEqual(row["sigma"], sigmas[idx])
                self.assertTrue(row["included"])
                self.assertAlmostEqual(row["relative_power"], values[idx] / expected_mean)
                self.assertAlmostEqual(row["relative_sigma"], sigmas[idx] / expected_mean)
                idx += 1

    def test_masking_guide_tube_and_errors(self):
        """2. Masking removes pin from mean and sets None relative power; all masked and 0 mean error."""
        values = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0]
        sigmas = [1.0, 2.0, 1.5, 2.5, 3.0, 0.5]
        # Guide-tube pin at index 2 (ix=2, iy=0) masked out
        include = [True, True, False, True, True, True]

        rows = build_rows(
            values, sigmas, 3, 2, 1.26, 1.30, x0_cm=-3.0, y0_cm=2.0, include=include
        )
        # Included values: 10, 20, 40, 50, 60 -> sum = 180, mean = 180 / 5 = 36.0
        expected_mean = 36.0
        self.assertFalse(rows[2]["included"])
        self.assertIsNone(rows[2]["relative_power"])
        self.assertIsNone(rows[2]["relative_sigma"])

        for i in [0, 1, 3, 4, 5]:
            self.assertTrue(rows[i]["included"])
            self.assertAlmostEqual(rows[i]["relative_power"], values[i] / expected_mean)
            self.assertAlmostEqual(rows[i]["relative_sigma"], sigmas[i] / expected_mean)

        # All masked -> TableError
        with self.assertRaises(TableError) as cm:
            build_rows(values, sigmas, 3, 2, 1.26, 1.30, include=[False] * 6)
        self.assertIn("include", str(cm.exception))

        # Mean of 0 -> TableError
        with self.assertRaises(TableError) as cm:
            build_rows([0.0] * 6, sigmas, 3, 2, 1.26, 1.30)
        self.assertIn("values", str(cm.exception))

        # Mean of 0 when non-zero pin is masked -> TableError
        with self.assertRaises(TableError) as cm:
            build_rows([0.0, 10.0], [0.1, 0.1], 2, 1, 1.0, 1.0, include=[True, False])
        self.assertIn("values", str(cm.exception))


class TestRadialPeaking(unittest.TestCase):
    """Test radial peaking factor calculation."""

    def test_radial_peaking_largest_included(self):
        """3. Largest included relative power and index; masked huge value ignored; ties to lowest index."""
        values = [10.0, 50.0, 30.0, 20.0]
        sigmas = [1.0, 1.0, 1.0, 1.0]
        rows = build_rows(values, sigmas, 2, 2, 1.0, 1.0)
        # mean = 110 / 4 = 27.5; max is 50.0 / 27.5 at ix=1, iy=0
        peak = radial_peaking(rows)
        self.assertAlmostEqual(peak["max_relative_power"], 50.0 / 27.5)
        self.assertEqual(peak["ix"], 1)
        self.assertEqual(peak["iy"], 0)
        self.assertEqual(peak["n_used"], 4)

    def test_radial_peaking_masked_huge_ignored(self):
        """Masked pin with huge value is ignored."""
        values = [10.0, 99999.0, 30.0, 20.0]
        sigmas = [1.0, 1.0, 1.0, 1.0]
        include = [True, False, True, True]
        rows = build_rows(values, sigmas, 2, 2, 1.0, 1.0, include=include)
        # Included: idx 0 (val 10), idx 2 (val 30, ix=0, iy=1), idx 3 (val 20)
        # Mean = 60 / 3 = 20.0; max is 30 / 20 = 1.5 at ix=0, iy=1
        peak = radial_peaking(rows)
        self.assertAlmostEqual(peak["max_relative_power"], 1.5)
        self.assertEqual(peak["ix"], 0)
        self.assertEqual(peak["iy"], 1)
        self.assertEqual(peak["n_used"], 3)

    def test_radial_peaking_ties_lowest_index(self):
        """Ties select the lowest index."""
        values = [20.0, 50.0, 50.0, 10.0]  # indices 1 and 2 tied at max value
        sigmas = [1.0, 1.0, 1.0, 1.0]
        rows = build_rows(values, sigmas, 2, 2, 1.0, 1.0)
        peak = radial_peaking(rows)
        self.assertEqual(peak["ix"], 1)
        self.assertEqual(peak["iy"], 0)  # index 1 (ix=1, iy=0) rather than index 2 (ix=0, iy=1)
        self.assertEqual(peak["n_used"], 4)

    def test_radial_peaking_multiple_ties(self):
        """Multiple ties at indices 0, 1, 2 select index 0."""
        values = [100.0, 100.0, 100.0, 10.0]
        sigmas = [1.0, 1.0, 1.0, 1.0]
        rows = build_rows(values, sigmas, 2, 2, 1.0, 1.0)
        peak = radial_peaking(rows)
        self.assertEqual(peak["ix"], 0)
        self.assertEqual(peak["iy"], 0)
        self.assertEqual(peak["n_used"], 4)

    def test_radial_peaking_no_included_rows_error(self):
        """No included row -> TableError."""
        rows = [
            {"ix": 0, "iy": 0, "included": False, "relative_power": None},
            {"ix": 1, "iy": 0, "included": False, "relative_power": None},
        ]
        with self.assertRaises(TableError) as cm:
            radial_peaking(rows)
        self.assertIn("rows", str(cm.exception))


class TestFoldQuarter(unittest.TestCase):
    """Test folding symmetric cores into quarter core."""

    def test_fold_quarter_symmetric_4x4(self):
        """4. 4x4 lattice with perfect four-fold symmetry: max_dev=0, n_members=4, power=group."""
        nx, ny = 4, 4
        # Four groups for 4x4:
        # group (0, 0): (0,0), (3,0), (0,3), (3,3) -> val 10.0
        # group (1, 0): (1,0), (2,0), (1,3), (2,3) -> val 20.0
        # group (0, 1): (0,1), (3,1), (0,2), (3,2) -> val 30.0
        # group (1, 1): (1,1), (2,1), (1,2), (2,2) -> val 40.0
        values = [0.0] * 16
        sigmas = [1.0] * 16
        group_map = {
            (0, 0): 10.0,
            (1, 0): 20.0,
            (0, 1): 30.0,
            (1, 1): 40.0,
        }
        for (qix, qiy), val in group_map.items():
            for px, py in [(qix, qiy), (3 - qix, qiy), (qix, 3 - qiy), (3 - qix, 3 - qiy)]:
                values[px + nx * py] = val

        rows = build_rows(values, sigmas, nx, ny, 1.26, 1.26)
        q_rows = fold_quarter(rows, nx, ny)

        # ceil(4/2) = 2; quarter has 2x2 = 4 pins
        self.assertEqual(len(q_rows), 4)
        for qr in q_rows:
            self.assertEqual(qr["n_members"], 4)
            self.assertAlmostEqual(qr["max_deviation"], 0.0)
            # The folded relative power must equal any member's relative power
            member_row = rows[qr["ix"] + nx * qr["iy"]]
            self.assertAlmostEqual(qr["relative_power"], member_row["relative_power"])

    def test_fold_quarter_5x5_membership_and_order(self):
        """5x5 lattice: corner has 4, edge has 2, centre has 1; quarter has 9 pins in order."""
        nx, ny = 5, 5
        values = [10.0] * 25
        sigmas = [1.0] * 25
        rows = build_rows(values, sigmas, nx, ny, 1.26, 1.26)
        q_rows = fold_quarter(rows, nx, ny)

        # ceil(5/2) = 3; quarter has 3x3 = 9 pins in index order (ix fastest)
        self.assertEqual(len(q_rows), 9)
        expected_indices = [(0, 0), (1, 0), (2, 0), (0, 1), (1, 1), (2, 1), (0, 2), (1, 2), (2, 2)]
        for i, (exp_ix, exp_iy) in enumerate(expected_indices):
            self.assertEqual(q_rows[i]["ix"], exp_ix)
            self.assertEqual(q_rows[i]["iy"], exp_iy)

        # Corner pin (0, 0) has 4 members
        self.assertEqual(q_rows[0]["n_members"], 4)
        # Edge pin on centreline: (2, 0) has 2 members ((2,0) and (2,4))
        self.assertEqual(q_rows[2]["n_members"], 2)
        # Edge pin on centreline: (0, 2) has 2 members ((0,2) and (4,2))
        self.assertEqual(q_rows[6]["n_members"], 2)
        # Centre pin (2, 2) has 1 member
        self.assertEqual(q_rows[8]["n_members"], 1)

    def test_fold_quarter_asymmetric_4x4_hand_values(self):
        """Asymmetric 4x4: max_deviation and relative_sigma equal hand values."""
        nx, ny = 4, 4
        values = [20.0] * 16
        sigmas = [1.0] * 16

        # In group (0, 0): (0,0), (3,0), (0,3), (3,3)
        # Give distinct values and sigmas
        values[0 + 4 * 0] = 10.0
        sigmas[0 + 4 * 0] = 1.0

        values[3 + 4 * 0] = 12.0
        sigmas[3 + 4 * 0] = 2.0

        values[0 + 4 * 3] = 14.0
        sigmas[0 + 4 * 3] = 3.0

        values[3 + 4 * 3] = 16.0
        sigmas[3 + 4 * 3] = 4.0

        rows = build_rows(values, sigmas, nx, ny, 1.0, 1.0)
        q_rows = fold_quarter(rows, nx, ny)

        # Quarter pin (0, 0)
        q0 = q_rows[0]
        self.assertEqual(q0["ix"], 0)
        self.assertEqual(q0["iy"], 0)
        self.assertEqual(q0["n_members"], 4)

        # Lattice mean
        lat_mean = sum(values) / 16.0
        # Member relative powers and sigmas
        m_powers = [10.0 / lat_mean, 12.0 / lat_mean, 14.0 / lat_mean, 16.0 / lat_mean]
        m_sigmas = [1.0 / lat_mean, 2.0 / lat_mean, 3.0 / lat_mean, 4.0 / lat_mean]

        hand_rel_power = sum(m_powers) / 4.0
        hand_rel_sigma = math.sqrt(sum(s ** 2 for s in m_sigmas)) / 4.0
        hand_max_dev = max(abs(p - hand_rel_power) for p in m_powers) / hand_rel_power

        self.assertAlmostEqual(q0["relative_power"], hand_rel_power)
        self.assertAlmostEqual(q0["relative_sigma"], hand_rel_sigma)
        self.assertAlmostEqual(q0["max_deviation"], hand_max_dev)

    def test_fold_quarter_masking(self):
        """Masked member is excluded (fewer members); all members masked gives None entries."""
        nx, ny = 4, 4
        values = [20.0] * 16
        sigmas = [1.0] * 16

        # In group (0, 0), mask out (3, 3)
        include = [True] * 16
        include[3 + 4 * 3] = False

        # In group (1, 1), mask out all 4 members: (1,1), (2,1), (1,2), (2,2)
        for px, py in [(1, 1), (2, 1), (1, 2), (2, 2)]:
            include[px + 4 * py] = False

        rows = build_rows(values, sigmas, nx, ny, 1.0, 1.0, include=include)
        q_rows = fold_quarter(rows, nx, ny)

        # q_rows[0] is (0, 0): 3 members remaining
        self.assertEqual(q_rows[0]["n_members"], 3)
        self.assertIsNotNone(q_rows[0]["relative_power"])
        self.assertIsNotNone(q_rows[0]["relative_sigma"])
        self.assertIsNotNone(q_rows[0]["max_deviation"])

        # q_rows[3] is (1, 1): all 4 members masked
        self.assertEqual(q_rows[3]["n_members"], 0)
        self.assertIsNone(q_rows[3]["relative_power"])
        self.assertIsNone(q_rows[3]["relative_sigma"])
        self.assertIsNone(q_rows[3]["max_deviation"])

    def test_fold_quarter_rectangular_3x4(self):
        """Rectangular lattice (3x4): odd nx, even ny."""
        nx, ny = 3, 4
        values = [10.0] * 12
        sigmas = [1.0] * 12
        rows = build_rows(values, sigmas, nx, ny, 1.26, 1.30)
        q_rows = fold_quarter(rows, nx, ny)

        # ceil(3/2) = 2, ceil(4/2) = 2 -> 4 quarter pins
        self.assertEqual(len(q_rows), 4)
        # (0, 0): (0,0), (2,0), (0,3), (2,3) -> 4 members
        self.assertEqual(q_rows[0]["n_members"], 4)
        # (1, 0): (1,0), (1,0), (1,3), (1,3) -> 2 members (ix=1 on centreline)
        self.assertEqual(q_rows[1]["n_members"], 2)
        # (0, 1): (0,1), (2,1), (0,2), (2,2) -> 4 members
        self.assertEqual(q_rows[2]["n_members"], 4)
        # (1, 1): (1,1), (1,1), (1,2), (1,2) -> 2 members
        self.assertEqual(q_rows[3]["n_members"], 2)

    def test_fold_quarter_1x1_single_pin(self):
        """1x1 lattice: ceil(1/2) = 1, exactly 1 quarter pin with 1 member."""
        rows = build_rows([15.0], [1.5], 1, 1, 1.0, 1.0)
        q_rows = fold_quarter(rows, 1, 1)
        self.assertEqual(len(q_rows), 1)
        self.assertEqual(q_rows[0]["ix"], 0)
        self.assertEqual(q_rows[0]["iy"], 0)
        self.assertEqual(q_rows[0]["n_members"], 1)
        self.assertAlmostEqual(q_rows[0]["relative_power"], 1.0)
        self.assertAlmostEqual(q_rows[0]["relative_sigma"], 0.1)
        self.assertEqual(q_rows[0]["max_deviation"], 0.0)


class TestCheckAlignment(unittest.TestCase):
    """Test check_alignment mesh and lattice validation."""

    def test_check_alignment_cases(self):
        """5. Aligned 17x17 lattice gives []; 16x16 gives mesh-dims; 2% wider gives mesh-pitch; 0.5 pitch offset gives mesh-offset; 1 pitch offset aligned."""
        # Aligned 17x17 lattice with pitch 1.26
        # Mesh from -10.71 to 10.71, 17x17, lattice lower-left -10.71
        findings = check_alignment(
            (-10.71, -10.71),
            (10.71, 10.71),
            (17, 17),
            (-10.71, -10.71),
            (1.26, 1.26),
            (17, 17),
        )
        self.assertEqual(findings, [])

        # 16x16 over the same box gives mesh-dims finding
        f_dims = check_alignment(
            (-10.71, -10.71),
            (10.71, 10.71),
            (16, 16),
            (-10.71, -10.71),
            (1.26, 1.26),
            (17, 17),
        )
        dims_findings = [f for f in f_dims if f["code"] == "mesh-dims"]
        self.assertEqual(len(dims_findings), 1)
        self.assertEqual(dims_findings[0]["level"], "error")
        self.assertIn("16", dims_findings[0]["message"])
        self.assertIn("17", dims_findings[0]["message"])

        # Isolated mesh-dims (matching cell pitch 1.26 over a 16x16 box)
        f_isolated_dims = check_alignment(
            (-10.71, -10.71),
            (9.45, 9.45),
            (16, 16),
            (-10.71, -10.71),
            (1.26, 1.26),
            (17, 17),
        )
        self.assertEqual([f["code"] for f in f_isolated_dims], ["mesh-dims"])

        # Mesh box 2 percent too wide: width = 21.42 * 1.02 = 21.8484
        # upper-right = -10.71 + 21.8484 = 11.1384
        f_pitch = check_alignment(
            (-10.71, -10.71),
            (11.1384, 11.1384),
            (17, 17),
            (-10.71, -10.71),
            (1.26, 1.26),
            (17, 17),
        )
        self.assertEqual(len(f_pitch), 2)
        for f in f_pitch:
            self.assertEqual(f["level"], "error")
            self.assertEqual(f["code"], "mesh-pitch")

        # Mesh shifted by half a pitch (0.63 cm in x and y)
        f_offset = check_alignment(
            (-10.71 + 0.63, -10.71 + 0.63),
            (10.71 + 0.63, 10.71 + 0.63),
            (17, 17),
            (-10.71, -10.71),
            (1.26, 1.26),
            (17, 17),
        )
        self.assertEqual(len(f_offset), 2)
        for f in f_offset:
            self.assertEqual(f["level"], "error")
            self.assertEqual(f["code"], "mesh-offset")

        # Shift of exactly one pitch is aligned
        f_one_pitch = check_alignment(
            (-10.71 + 1.26, -10.71 + 1.26),
            (10.71 + 1.26, 10.71 + 1.26),
            (17, 17),
            (-10.71, -10.71),
            (1.26, 1.26),
            (17, 17),
        )
        self.assertEqual(f_one_pitch, [])

    def test_check_alignment_single_axis_and_negative_offset(self):
        """Single-axis mismatch produces exactly one finding; negative offsets handled correctly."""
        # Pitch mismatch along x only (width = 21.42 * 1.02 = 21.8484, height = 21.42)
        f_x_pitch = check_alignment(
            (-10.71, -10.71),
            (11.1384, 10.71),
            (17, 17),
            (-10.71, -10.71),
            (1.26, 1.26),
            (17, 17),
        )
        self.assertEqual(len(f_x_pitch), 1)
        self.assertEqual(f_x_pitch[0]["code"], "mesh-pitch")
        self.assertIn("along x", f_x_pitch[0]["message"])

        # Offset along y only with negative displacement (-0.5 pitch)
        f_y_offset = check_alignment(
            (-10.71, -10.71 - 0.63),
            (10.71, 10.71 - 0.63),
            (17, 17),
            (-10.71, -10.71),
            (1.26, 1.26),
            (17, 17),
        )
        self.assertEqual(len(f_y_offset), 1)
        self.assertEqual(f_y_offset[0]["code"], "mesh-offset")
        self.assertIn("along y", f_y_offset[0]["message"])

        # Negative shift of exactly 2 pitches is aligned
        f_neg_2_pitches = check_alignment(
            (-10.71 - 2.52, -10.71 - 2.52),
            (10.71 - 2.52, 10.71 - 2.52),
            (17, 17),
            (-10.71, -10.71),
            (1.26, 1.26),
            (17, 17),
        )
        self.assertEqual(f_neg_2_pitches, [])


class TestCsvSanitization(unittest.TestCase):
    """Test csv_cell and csv_rows protection against formula injection."""

    def test_csv_cell_formula_injection(self):
        """6. csv_cell prefixes single quote for =, +, -, @, \\t, \\r."""
        self.assertEqual(csv_cell("=SUM(A1)"), "'=SUM(A1)")
        self.assertEqual(csv_cell("+1"), "'+1")
        self.assertEqual(csv_cell("-1"), "'-1")
        self.assertEqual(csv_cell("@x"), "'@x")
        self.assertEqual(csv_cell("\tx"), "'\tx")
        self.assertEqual(csv_cell("\rx"), "'\rx")

    def test_csv_cell_unchanged_cases(self):
        """Normal, empty, space-led, and quote-led strings unchanged."""
        self.assertEqual(csv_cell("normal"), "normal")
        self.assertEqual(csv_cell(""), "")
        self.assertEqual(csv_cell(" =x"), " =x")
        self.assertEqual(csv_cell("'x"), "'x")

    def test_csv_cell_non_str_and_none(self):
        """Numbers and booleans unchanged and same type; None gives empty string."""
        self.assertEqual(csv_cell(-1.5), -1.5)
        self.assertIsInstance(csv_cell(-1.5), float)

        self.assertEqual(csv_cell(3), 3)
        self.assertIsInstance(csv_cell(3), int)

        self.assertEqual(csv_cell(True), True)
        self.assertIsInstance(csv_cell(True), bool)

        self.assertEqual(csv_cell(None), "")

    def test_csv_rows_header_and_data(self):
        """csv_rows exact header, masked pin gives empty strings, negative number preserved."""
        values = [10.0, 20.0]
        sigmas = [1.0, 2.0]
        rows = build_rows(
            values, sigmas, 2, 1, 1.26, 1.26, x0_cm=-3.0, y0_cm=-2.0, include=[True, False]
        )
        table = csv_rows(rows)

        expected_header = [
            "ix",
            "iy",
            "x_cm",
            "y_cm",
            "value",
            "sigma",
            "included",
            "relative_power",
            "relative_sigma",
        ]
        self.assertEqual(table[0], expected_header)
        self.assertEqual(len(table), 3)

        # Row 1 (included)
        row1 = table[1]
        self.assertEqual(row1[0], 0)
        self.assertEqual(row1[1], 0)
        self.assertLess(row1[2], 0)  # negative number stays negative number
        self.assertIsInstance(row1[2], float)
        self.assertTrue(row1[6])
        self.assertIsInstance(row1[7], float)
        self.assertIsInstance(row1[8], float)

        # Row 2 (masked)
        row2 = table[2]
        self.assertEqual(row2[0], 1)
        self.assertEqual(row2[1], 0)
        self.assertFalse(row2[6])
        self.assertEqual(row2[7], "")
        self.assertEqual(row2[8], "")


class TestBadInputs(unittest.TestCase):
    """7 & 8. Every kind of bad input raises TableError naming the argument (Rule 10)."""

    def test_bad_lengths_and_empty(self):
        """Lists of wrong length."""
        with self.assertRaises(TableError) as cm:
            build_rows([1.0], [0.1], 2, 2, 1.0, 1.0)
        self.assertIn("values", str(cm.exception))

        with self.assertRaises(TableError) as cm:
            build_rows([1.0] * 4, [0.1], 2, 2, 1.0, 1.0)
        self.assertIn("sigmas", str(cm.exception))

        with self.assertRaises(TableError) as cm:
            build_rows([1.0] * 4, [0.1] * 4, 2, 2, 1.0, 1.0, include=[True])
        self.assertIn("include", str(cm.exception))

    def test_bad_numeric_values(self):
        """nan, inf, bool entries, negative values and sigmas."""
        # nan in values
        with self.assertRaises(TableError) as cm:
            build_rows([float("nan"), 1.0], [0.1, 0.1], 2, 1, 1.0, 1.0)
        self.assertIn("values", str(cm.exception))

        # inf in sigmas
        with self.assertRaises(TableError) as cm:
            build_rows([1.0, 1.0], [float("inf"), 0.1], 2, 1, 1.0, 1.0)
        self.assertIn("sigmas", str(cm.exception))

        # bool in values
        with self.assertRaises(TableError) as cm:
            build_rows([True, 1.0], [0.1, 0.1], 2, 1, 1.0, 1.0)
        self.assertIn("values", str(cm.exception))

        # bool in sigmas
        with self.assertRaises(TableError) as cm:
            build_rows([1.0, 1.0], [False, 0.1], 2, 1, 1.0, 1.0)
        self.assertIn("sigmas", str(cm.exception))

        # negative value
        with self.assertRaises(TableError) as cm:
            build_rows([-1.0, 1.0], [0.1, 0.1], 2, 1, 1.0, 1.0)
        self.assertIn("values", str(cm.exception))

        # negative sigma
        with self.assertRaises(TableError) as cm:
            build_rows([1.0, 1.0], [-0.1, 0.1], 2, 1, 1.0, 1.0)
        self.assertIn("sigmas", str(cm.exception))

    def test_bad_nx_ny_pitch_coords(self):
        """nx of 0 or bool, ny of 0 or bool, pitch <= 0, x0/y0 non-finite."""
        # nx 0
        with self.assertRaises(TableError) as cm:
            build_rows([1.0], [0.1], 0, 1, 1.0, 1.0)
        self.assertIn("nx", str(cm.exception))

        # nx bool
        with self.assertRaises(TableError) as cm:
            build_rows([1.0], [0.1], True, 1, 1.0, 1.0)
        self.assertIn("nx", str(cm.exception))

        # ny 0
        with self.assertRaises(TableError) as cm:
            build_rows([1.0], [0.1], 1, 0, 1.0, 1.0)
        self.assertIn("ny", str(cm.exception))

        # ny bool
        with self.assertRaises(TableError) as cm:
            build_rows([1.0], [0.1], 1, False, 1.0, 1.0)
        self.assertIn("ny", str(cm.exception))

        # pitch_x 0
        with self.assertRaises(TableError) as cm:
            build_rows([1.0], [0.1], 1, 1, 0.0, 1.0)
        self.assertIn("pitch_x_cm", str(cm.exception))

        # pitch_y bool
        with self.assertRaises(TableError) as cm:
            build_rows([1.0], [0.1], 1, 1, 1.0, True)
        self.assertIn("pitch_y_cm", str(cm.exception))

        # x0_cm inf
        with self.assertRaises(TableError) as cm:
            build_rows([1.0], [0.1], 1, 1, 1.0, 1.0, x0_cm=float("inf"))
        self.assertIn("x0_cm", str(cm.exception))

        # y0_cm bool
        with self.assertRaises(TableError) as cm:
            build_rows([1.0], [0.1], 1, 1, 1.0, 1.0, y0_cm=True)
        self.assertIn("y0_cm", str(cm.exception))

    def test_bad_include(self):
        """include of wrong type or containing non-bool."""
        with self.assertRaises(TableError) as cm:
            build_rows([1.0], [0.1], 1, 1, 1.0, 1.0, include="not-a-list")
        self.assertIn("include", str(cm.exception))

        with self.assertRaises(TableError) as cm:
            build_rows([1.0], [0.1], 1, 1, 1.0, 1.0, include=[1])
        self.assertIn("include", str(cm.exception))

    def test_bad_radial_peaking(self):
        """radial_peaking with bad rows."""
        with self.assertRaises(TableError) as cm:
            radial_peaking("not-a-list")
        self.assertIn("rows", str(cm.exception))

        with self.assertRaises(TableError) as cm:
            radial_peaking([])
        self.assertIn("rows", str(cm.exception))

        with self.assertRaises(TableError) as cm:
            radial_peaking(["not-a-dict"])
        self.assertIn("rows", str(cm.exception))

        with self.assertRaises(TableError) as cm:
            radial_peaking([{"ix": 0, "iy": 0, "included": True, "relative_power": float("nan")}])
        self.assertIn("rows", str(cm.exception))

    def test_bad_fold_quarter(self):
        """fold_quarter with wrong number of rows, wrong order, or invalid nx/ny."""
        rows = [
            {"ix": 0, "iy": 0, "included": True, "relative_power": 1.0, "relative_sigma": 0.1},
        ]
        with self.assertRaises(TableError) as cm:
            fold_quarter(rows, 2, 2)
        self.assertIn("rows", str(cm.exception))

        # Out of index order
        bad_order_rows = [
            {"ix": 1, "iy": 0, "included": True, "relative_power": 1.0, "relative_sigma": 0.1},
            {"ix": 0, "iy": 0, "included": True, "relative_power": 1.0, "relative_sigma": 0.1},
        ]
        with self.assertRaises(TableError) as cm:
            fold_quarter(bad_order_rows, 2, 1)
        self.assertIn("rows", str(cm.exception))

        with self.assertRaises(TableError) as cm:
            fold_quarter(rows, 0, 1)
        self.assertIn("nx", str(cm.exception))

        with self.assertRaises(TableError) as cm:
            fold_quarter(rows, 1, True)
        self.assertIn("ny", str(cm.exception))

    def test_bad_check_alignment(self):
        """check_alignment with pairs of wrong size, dims of 0, tol_cm <= 0."""
        # Pair wrong size
        with self.assertRaises(TableError) as cm:
            check_alignment((0.0,), (1.0, 1.0), (1, 1), (0.0, 0.0), (1.0, 1.0), (1, 1))
        self.assertIn("mesh_lower_left_cm", str(cm.exception))

        with self.assertRaises(TableError) as cm:
            check_alignment((0.0, 0.0), (1.0, 1.0, 1.0), (1, 1), (0.0, 0.0), (1.0, 1.0), (1, 1))
        self.assertIn("mesh_upper_right_cm", str(cm.exception))

        # Dims of 0
        with self.assertRaises(TableError) as cm:
            check_alignment((0.0, 0.0), (1.0, 1.0), (0, 1), (0.0, 0.0), (1.0, 1.0), (1, 1))
        self.assertIn("mesh_dims", str(cm.exception))

        with self.assertRaises(TableError) as cm:
            check_alignment((0.0, 0.0), (1.0, 1.0), (1, 1), (0.0, 0.0), (1.0, 1.0), (1, 0))
        self.assertIn("lattice_dims", str(cm.exception))

        # Pitch <= 0
        with self.assertRaises(TableError) as cm:
            check_alignment((0.0, 0.0), (1.0, 1.0), (1, 1), (0.0, 0.0), (0.0, 1.0), (1, 1))
        self.assertIn("pitch_cm", str(cm.exception))

        # tol_cm 0
        with self.assertRaises(TableError) as cm:
            check_alignment((0.0, 0.0), (1.0, 1.0), (1, 1), (0.0, 0.0), (1.0, 1.0), (1, 1), tol_cm=0.0)
        self.assertIn("tol_cm", str(cm.exception))

        # upper_right <= lower_left
        with self.assertRaises(TableError) as cm:
            check_alignment((1.0, 0.0), (0.5, 1.0), (1, 1), (0.0, 0.0), (1.0, 1.0), (1, 1))
        self.assertIn("mesh_upper_right_cm", str(cm.exception))

    def test_bad_csv_rows(self):
        """csv_rows with non-list or missing keys."""
        with self.assertRaises(TableError) as cm:
            csv_rows("not-a-list")
        self.assertIn("rows", str(cm.exception))

        with self.assertRaises(TableError) as cm:
            csv_rows([{"ix": 0}])
        self.assertIn("rows", str(cm.exception))


if __name__ == "__main__":
    unittest.main(verbosity=2)
