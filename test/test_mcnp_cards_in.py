"""Unit tests for openmc_studio.mcnp_cards_in.

Stdlib only. Tests all rules from 1a to 1g, refusals, and fixtures.
Run: python test/test_mcnp_cards_in.py
"""
import math
import sys
import unittest
from pathlib import Path

# Add studio directory to sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "studio"))

from openmc_studio import mcnp_cards_in  # noqa: E402

FIXTURES_DIR = REPO_ROOT / "test" / "fixtures" / "mcnp"


def make_deck(data_cards, title="Test deck", cells="1 0 -1\n", surfs="1 so 10\n"):
    """Wrap data cards into a valid 3-block MCNP deck."""
    return f"{title}\n{cells}\n{surfs}\n{data_cards}\n"


class TestMcnpCardsIn(unittest.TestCase):

    # ── 1a: Reading the deck ──────────────────────────────────────────────────

    def test_1a_title_skipped(self):
        deck = make_deck("NPS 100", title="A title line with numbers like 12345")
        res = mcnp_cards_in.parse(deck)
        self.assertEqual(res["settings"].get("nps"), 100)
        self.assertEqual(len(res["refused"]), 0)

    def test_1a_message_block_skipped(self):
        deck = "MESSAGE: This is an execution message\nand a continuation of message\n\nTitle line\n1 0 -1\n\n1 so 5\n\nNPS 5000\n"
        res = mcnp_cards_in.parse(deck)
        self.assertEqual(res["settings"].get("nps"), 5000)
        self.assertEqual(len(res["refused"]), 0)

    def test_1a_comment_lines_and_inline_dollar(self):
        data = (
            "c A full comment line\n"
            "   C Indented up to 4 spaces\n"
            "c\n"
            "NPS 10000 $ inline dollar comment\n"
            "SDEF POS=0 0 0 $ inline comment inside card\n"
            "     ERG=14.1 $ another inline comment on continuation\n"
        )
        res = mcnp_cards_in.parse(make_deck(data))
        self.assertEqual(res["settings"]["nps"], 10000)
        self.assertEqual(len(res["sources"]), 1)
        self.assertEqual(res["sources"][0]["lines"], "14.1:1")

    def test_1a_continuation_five_spaces(self):
        data = (
            "SDEF PAR=1\n"
            "     POS=1.0 2.0 3.0\n"
            "     ERG=2.5\n"
        )
        res = mcnp_cards_in.parse(make_deck(data))
        self.assertEqual(len(res["sources"]), 1)
        s = res["sources"][0]
        self.assertEqual(s["x"], 1.0)
        self.assertEqual(s["y"], 2.0)
        self.assertEqual(s["z"], 3.0)
        self.assertEqual(s["lines"], "2.5:1")

    def test_1a_continuation_ampersand(self):
        data = (
            "SDEF PAR=1 &\n"
            "POS=0 0 0 &\n"
            "c comment between ampersand continuations\n"
            "ERG=5.0\n"
        )
        res = mcnp_cards_in.parse(make_deck(data))
        self.assertEqual(len(res["sources"]), 1)
        self.assertEqual(res["sources"][0]["lines"], "5:1")

    def test_1a_tabs_count_as_spaces(self):
        data = "SDEF PAR=1\n\tPOS=0 0 0\n\tERG=14.1\n"
        res = mcnp_cards_in.parse(make_deck(data))
        self.assertEqual(len(res["sources"]), 1)
        self.assertEqual(res["sources"][0]["lines"], "14.1:1")

    def test_1a_card_names_case_preserved_for_refused(self):
        data = "fUnKyCaRd 1 2 3\n"
        res = mcnp_cards_in.parse(make_deck(data))
        self.assertEqual(len(res["refused"]), 1)
        self.assertEqual(res["refused"][0]["card"], "fUnKyCaRd")
        self.assertEqual(res["refused"][0]["reason"], "not imported (Studio has no equivalent yet)")

    # ── 1b: Numeric lists and shortcuts ───────────────────────────────────────

    def test_1b_repeat_shortcut(self):
        data = "KSRC 0 0 0 2R\nKCODE 1000 1.0 30 130\n"
        res = mcnp_cards_in.parse(make_deck(data))
        self.assertEqual(len(res["sources"]), 1)
        self.assertEqual(res["sources"][0]["x"], 0.0)

    def test_1b_linear_interpolation_shortcut(self):
        tokens = ["0.1", "2I", "1.0"]
        expanded = mcnp_cards_in.expand_shortcuts(tokens)
        expected = [0.1, 0.4, 0.7, 1.0]
        self.assertEqual(len(expanded), len(expected))
        for a, b in zip(expanded, expected):
            self.assertAlmostEqual(a, b, delta=1e-12)

    def test_1b_log_interpolation_shortcut(self):
        tokens = ["1e-8", "3LOG", "1e-4"]
        expanded = mcnp_cards_in.expand_shortcuts(tokens)
        expected = [1e-8, 1e-7, 1e-6, 1e-5, 1e-4]
        self.assertEqual(len(expanded), len(expected))
        for a, b in zip(expanded, expected):
            self.assertAlmostEqual(a, b, delta=1e-12 * b)

    def test_1b_unsupported_nj_nm_shortcuts(self):
        data = "E4 1e-8 2J 1e-4\nF4:N 1\n"
        res = mcnp_cards_in.parse(make_deck(data))
        self.assertEqual(len(res["tallies"]), 0)
        self.assertTrue(any(r["card"] == "F4:N" and "the nJ/nM shortcuts aren't imported" in r["reason"] for r in res["refused"]))

    # ── 1c: Cards ignored silently or refused ─────────────────────────────────

    def test_1c_silent_cards(self):
        data = "M1 1001 1\nMT1 lwtr.20t\nMX1 1001\nTR1 0 0 0\n*TR2 0 0 0\nIMP:N 1\nVOL 1.0\nAREA 2.0\nPRINT\nPRDMP 1 2 3\n"
        res = mcnp_cards_in.parse(make_deck(data))
        self.assertEqual(len(res["sources"]), 0)
        self.assertEqual(len(res["tallies"]), 0)
        self.assertEqual(len(res["refused"]), 0)

    def test_1c_unsupported_cards_refused(self):
        data = "WWN1:N 1.0\nRAND 12345\n"
        res = mcnp_cards_in.parse(make_deck(data))
        self.assertEqual(len(res["refused"]), 2)
        cards = [r["card"] for r in res["refused"]]
        self.assertIn("WWN1:N", cards)
        self.assertIn("RAND", cards)
        for r in res["refused"]:
            self.assertEqual(r["reason"], "not imported (Studio has no equivalent yet)")

    # ── 1d: Sources: SDEF with SI/SP ──────────────────────────────────────────

    def test_1d_sdef_particle(self):
        for par, expected in [("1", "neutron"), ("N", "neutron"), ("2", "photon"), ("P", "photon")]:
            data = f"SDEF PAR={par} POS=0 0 0 ERG=1\n"
            res = mcnp_cards_in.parse(make_deck(data))
            self.assertEqual(res["sources"][0]["particle"], expected)

    def test_1d_sdef_unsupported_particle(self):
        data = "SDEF PAR=3 POS=0 0 0 ERG=1\n"
        res = mcnp_cards_in.parse(make_deck(data))
        self.assertEqual(len(res["sources"]), 0)
        self.assertEqual(len(res["refused"]), 1)
        self.assertEqual(res["refused"][0]["card"], "SDEF")

    def test_1d_sdef_wgt(self):
        data = "SDEF WGT=2 POS=0 0 0 ERG=1\n"
        res = mcnp_cards_in.parse(make_deck(data))
        self.assertEqual(len(res["sources"]), 0)
        self.assertEqual(len(res["refused"]), 1)
        self.assertIn("WGT must equal 1", res["refused"][0]["reason"])

    def test_1d_sdef_unknown_keyword(self):
        data = "SDEF CEL=5 POS=0 0 0 ERG=1\n"
        res = mcnp_cards_in.parse(make_deck(data))
        self.assertEqual(len(res["sources"]), 0)
        self.assertEqual(len(res["refused"]), 1)
        self.assertIn("CEL", res["refused"][0]["reason"])

    def test_1d_sdef_second_sdef(self):
        data = "SDEF POS=0 0 0 ERG=1\nSDEF POS=1 1 1 ERG=2\n"
        res = mcnp_cards_in.parse(make_deck(data))
        self.assertEqual(len(res["sources"]), 0)
        self.assertTrue(any(r["card"] == "SDEF" and "second SDEF" in r["reason"] for r in res["refused"]))

    def test_1d_sdef_si_option_s_refused(self):
        data = "SDEF ERG=D1 POS=0 0 0\nSI1 S 1 2\nSP1 0.5 0.5\n"
        res = mcnp_cards_in.parse(make_deck(data))
        self.assertEqual(len(res["sources"]), 0)
        self.assertTrue(any(r["card"] == "SDEF" and "option S" in r["reason"] for r in res["refused"]))

    def test_1d_sdef_space_point(self):
        data = "SDEF POS=1 2 3 ERG=14.1\n"
        res = mcnp_cards_in.parse(make_deck(data))
        s = res["sources"][0]
        self.assertEqual(s["space"], "point")
        self.assertEqual((s["x"], s["y"], s["z"]), (1.0, 2.0, 3.0))

    def test_1d_sdef_space_box(self):
        data = (
            "SDEF X=D1 Y=D2 Z=D3 ERG=1\n"
            "SI1 H -1 1\nSP1 0 1\n"
            "SI2 H -2 2\nSP2 0 1\n"
            "SI3 -3 3\nSP3 D 0 1\n"
        )
        res = mcnp_cards_in.parse(make_deck(data))
        s = res["sources"][0]
        self.assertEqual(s["space"], "box")
        self.assertEqual((s["x0"], s["x1"]), (-1.0, 1.0))
        self.assertEqual((s["y0"], s["y1"]), (-2.0, 2.0))
        self.assertEqual((s["z0"], s["z1"]), (-3.0, 3.0))

    def test_1d_sdef_space_sphere(self):
        data = (
            "SDEF POS=0 0 0 RAD=D1 ERG=1\n"
            "SI1 0 5\n"
            "SP1 -21 2\n"
        )
        res = mcnp_cards_in.parse(make_deck(data))
        s = res["sources"][0]
        self.assertEqual(s["space"], "sphere")
        self.assertEqual(s["rin"], 0.0)
        self.assertEqual(s["r"], 5.0)

    def test_1d_sdef_space_cylinder(self):
        data = (
            "SDEF POS=0 0 10 AXS=0 0 1 RAD=D1 EXT=D2 ERG=1\n"
            "SI1 1 5\n"
            "SP1 -21 1\n"
            "SI2 -10 10\n"
            "SP2 -21 0\n"
        )
        res = mcnp_cards_in.parse(make_deck(data))
        s = res["sources"][0]
        self.assertEqual(s["space"], "cylinder")
        self.assertEqual(s["x"], 0.0)
        self.assertEqual(s["y"], 0.0)
        self.assertEqual(s["z"], 10.0)
        self.assertEqual(s["h"], 20.0)
        self.assertEqual(s["rin"], 1.0)
        self.assertEqual(s["r"], 5.0)

    def test_1d_sdef_direction_mono(self):
        data = "SDEF DIR=1 VEC=0 3 4 ERG=14.1\n"
        res = mcnp_cards_in.parse(make_deck(data))
        s = res["sources"][0]
        self.assertEqual(s["angle"], "mono")
        self.assertAlmostEqual(s["u"], 0.0)
        self.assertAlmostEqual(s["v"], 0.6)
        self.assertAlmostEqual(s["w"], 0.8)

    def test_1d_sdef_direction_refused(self):
        data = "SDEF DIR=2 VEC=0 0 1 ERG=14.1\n"
        res = mcnp_cards_in.parse(make_deck(data))
        self.assertEqual(len(res["sources"]), 0)
        self.assertEqual(len(res["refused"]), 1)

    def test_1d_sdef_energy_missing(self):
        data = "SDEF POS=0 0 0\n"
        res = mcnp_cards_in.parse(make_deck(data))
        s = res["sources"][0]
        self.assertEqual(s["energy"], "lines")
        self.assertEqual(s["lines"], "14:1")
        self.assertTrue(any("ERG missing: MCNP's default 14 MeV" in n for n in res["notes"]))

    def test_1d_sdef_energy_discrete_lines(self):
        data = (
            "SDEF ERG=D1 POS=0 0 0\n"
            "SI1 L 1.1732 1.3325\n"
            "SP1 D 1 1\n"
        )
        res = mcnp_cards_in.parse(make_deck(data))
        s = res["sources"][0]
        self.assertEqual(s["energy"], "lines")
        self.assertEqual(s["lines"], "1.1732:1, 1.3325:1")

    def test_1d_sdef_energy_uniform(self):
        data = (
            "SDEF ERG=D1 POS=0 0 0\n"
            "SI1 H 0.1 2.0\n"
            "SP1 0 1\n"
        )
        res = mcnp_cards_in.parse(make_deck(data))
        s = res["sources"][0]
        self.assertEqual(s["energy"], "uniform")
        self.assertEqual(s["emin"], 0.1)
        self.assertEqual(s["emax"], 2.0)

    def test_1d_sdef_energy_histogram_first_not_zero_refused(self):
        data = (
            "SDEF ERG=D1 POS=0 0 0\n"
            "SI1 H 0.1 1.0 2.0\n"
            "SP1 1 1\n"
        )
        res = mcnp_cards_in.parse(make_deck(data))
        self.assertEqual(len(res["sources"]), 0)
        self.assertTrue(any(r["card"] == "SDEF" and "the first histogram entry must be 0" in r["reason"] for r in res["refused"]))

    def test_1d_sdef_energy_watt(self):
        data = "SDEF ERG=D1 POS=0 0 0\nSP1 -3 0.988 2.249\n"
        res = mcnp_cards_in.parse(make_deck(data))
        s = res["sources"][0]
        self.assertEqual(s["energy"], "watt")
        self.assertEqual(s["wa"], 0.988)
        self.assertEqual(s["wb"], 2.249)

    def test_1d_sdef_energy_maxwell(self):
        data = "SDEF ERG=D1 POS=0 0 0\nSP1 -2 1.2895\n"
        res = mcnp_cards_in.parse(make_deck(data))
        s = res["sources"][0]
        self.assertEqual(s["energy"], "maxwell")
        self.assertEqual(s["theta"], 1.2895)

    def test_1d_sdef_energy_muir(self):
        # b = 14.08 (D-T fusion, mrat = 5.0)
        # a = sqrt(4 * 14.08 * 0.02 / 5) = 0.4746367
        a = math.sqrt(4.0 * 14.08 * (20000.0 / 1e6) / 5.0)
        data = f"SDEF ERG=D1 POS=0 0 0\nSP1 -4 {a} 14.08\n"
        res = mcnp_cards_in.parse(make_deck(data))
        s = res["sources"][0]
        self.assertEqual(s["energy"], "muir")
        self.assertEqual(s["muir_e0"], 14.08)
        self.assertEqual(s["muir_mrat"], 5.0)
        self.assertAlmostEqual(s["muir_kt"], 20000.0, delta=1e-6)

    def test_1d_sdef_energy_muir_dd(self):
        # b = 2.45 (D-D fusion, mrat = 4.0)
        a = math.sqrt(4.0 * 2.45 * (20000.0 / 1e6) / 4.0)
        data = f"SDEF ERG=D1 POS=0 0 0\nSP1 -4 {a} 2.45\n"
        res = mcnp_cards_in.parse(make_deck(data))
        s = res["sources"][0]
        self.assertEqual(s["energy"], "muir")
        self.assertEqual(s["muir_e0"], 2.45)
        self.assertEqual(s["muir_mrat"], 4.0)
        self.assertAlmostEqual(s["muir_kt"], 20000.0, delta=1e-6)

    # ── 1e: Run settings: NPS, KCODE/KSRC, MODE ───────────────────────────────

    def test_1e_nps(self):
        data = "NPS 250000\n"
        res = mcnp_cards_in.parse(make_deck(data))
        self.assertEqual(res["settings"]["nps"], 250000)

    def test_1e_kcode_with_ksrc(self):
        data = "KCODE 5000 1.0 50 150\nKSRC 10 20 30 40 50 60\n"
        res = mcnp_cards_in.parse(make_deck(data))
        st = res["settings"]
        self.assertEqual(st["runMode"], "eigenvalue")
        self.assertEqual(st["particles"], 5000)
        self.assertEqual(st["inactive"], 50)
        self.assertEqual(st["batches"], 150)
        self.assertEqual(len(res["sources"]), 1)
        s = res["sources"][0]
        self.assertEqual((s["x"], s["y"], s["z"]), (10.0, 20.0, 30.0))
        self.assertEqual(s["energy"], "watt")
        self.assertTrue(any("KSRC gave 2 points" in n for n in res["notes"]))

    def test_1e_kcode_without_ksrc(self):
        data = "KCODE 1000\n"
        res = mcnp_cards_in.parse(make_deck(data))
        self.assertEqual(res["settings"]["runMode"], "eigenvalue")
        self.assertEqual(res["settings"]["particles"], 1000)
        self.assertEqual(res["settings"]["inactive"], 30)
        self.assertEqual(res["settings"]["batches"], 130)
        self.assertEqual(len(res["sources"]), 1)
        self.assertEqual((res["sources"][0]["x"], res["sources"][0]["y"], res["sources"][0]["z"]), (0.0, 0.0, 0.0))
        self.assertTrue(any("KCODE without KSRC" in n for n in res["notes"]))

    def test_1e_kcode_refuses_sdef(self):
        data = "KCODE 1000\nSDEF POS=0 0 0 ERG=14.1\n"
        res = mcnp_cards_in.parse(make_deck(data))
        self.assertTrue(any(r["card"] == "SDEF" and "KCODE runs start from KSRC" in r["reason"] for r in res["refused"]))

    def test_1e_mode(self):
        for line, photon, ref in [("MODE N", False, False), ("MODE P", True, False), ("MODE N P", True, False), ("MODE N E", False, True)]:
            res = mcnp_cards_in.parse(make_deck(line))
            self.assertEqual(res["settings"]["photon"], photon)
            if ref:
                self.assertTrue(any(r["card"] == "MODE" and "E" in r["reason"] for r in res["refused"]))

    # ── 1f: Cell tallies: F<n> ────────────────────────────────────────────────

    def test_1f_cell_tally_valid(self):
        data = (
            "F4:N 1 2\n"
            "FC4 Flux in cells 1 and 2\n"
            "E4 0.1 1.0 20.0\n"
            "SD4 1 1\n"
        )
        res = mcnp_cards_in.parse(make_deck(data))
        self.assertEqual(len(res["tallies"]), 1)
        t = res["tallies"][0]
        self.assertEqual(t["kind"], "cell")
        self.assertEqual(t["cells_mcnp"], [1, 2])
        self.assertEqual(t["particle"], "neutron")
        self.assertEqual(t["name"], "Flux in cells 1 and 2")
        self.assertEqual(t["ebins"], "0, 0.1, 1, 20")
        self.assertEqual(t["scores"], ["flux"])

    def test_1f_cell_tally_fm_reactions(self):
        rx_table = [
            ("-1", "total"),
            ("-2", "absorption"),
            ("-6", "fission"),
            ("-6 -7", "nu-fission"),
            ("102", "(n,gamma)"),
            ("103", "(n,p)"),
            ("107", "(n,a)")
        ]
        for rx_code, expected_score in rx_table:
            data = f"F14:N 1\nFM14 (-1 5 {rx_code})\n"
            res = mcnp_cards_in.parse(make_deck(data))
            self.assertEqual(len(res["tallies"]), 1)
            t = res["tallies"][0]
            self.assertEqual(t["scores"], [expected_score])
            self.assertEqual(t["fm_material"], 5)

    def test_1f_cell_tally_unsupported_ending_refused(self):
        for n in [1, 2, 5, 6, 7, 8]:
            data = f"F{n}:N 1\n"
            res = mcnp_cards_in.parse(make_deck(data))
            self.assertEqual(len(res["tallies"]), 0)
            self.assertTrue(any(r["card"] == f"F{n}:N" and "tallies aren't imported" in r["reason"] for r in res["refused"]))

    def test_1f_cell_tally_unsupported_companion_refused(self):
        for comp in ["DE4 1.0", "DF4 1.0", "FT4 RES", "C4 comment", "EM4 1 2"]:
            data = f"F4:N 1\n{comp}\n"
            res = mcnp_cards_in.parse(make_deck(data))
            self.assertEqual(len(res["tallies"]), 0)
            self.assertEqual(len(res["refused"]), 1)
            self.assertEqual(res["refused"][0]["card"], "F4:N")

    def test_1f_cell_tally_two_particles_refused(self):
        data = "F4:N,P 1\n"
        res = mcnp_cards_in.parse(make_deck(data))
        self.assertEqual(len(res["tallies"]), 0)
        self.assertTrue(any(r["card"] == "F4:N,P" for r in res["refused"]))

    def test_1f_cell_tally_invalid_bins_refused(self):
        for bins in ["(1 2)", "1 < 2", "1 T", "1 U=2"]:
            data = f"F4:N {bins}\n"
            res = mcnp_cards_in.parse(make_deck(data))
            self.assertEqual(len(res["tallies"]), 0)
            self.assertEqual(len(res["refused"]), 1)
            self.assertEqual(res["refused"][0]["card"], "F4:N")

    def test_1f_cell_tally_sd_notes(self):
        # Missing SD
        res1 = mcnp_cards_in.parse(make_deck("F4:N 1\n"))
        self.assertTrue(any("F4: MCNP divides by the cell volume" in n for n in res1["notes"]))
        # SD != 1
        res2 = mcnp_cards_in.parse(make_deck("F4:N 1\nSD4 2.5\n"))
        self.assertTrue(any("F4: SD values ignored" in n for n in res2["notes"]))

    # ── 1g: Mesh tallies: FMESH<n> ────────────────────────────────────────────

    def test_1g_fmesh_xyz(self):
        data = (
            "FMESH24:N GEOM=XYZ ORIGIN=-10 -20 -30\n"
            "     IMESH=10 IINTS=20 JMESH=20 JINTS=40 KMESH=30 KINTS=60\n"
            "     EMESH=0.1 1.0\n"
        )
        res = mcnp_cards_in.parse(make_deck(data))
        self.assertEqual(len(res["tallies"]), 1)
        t = res["tallies"][0]
        self.assertEqual(t["kind"], "mesh")
        self.assertEqual((t["nx"], t["ny"], t["nz"]), (20, 40, 60))
        self.assertEqual((t["lx"], t["ly"], t["lz"]), (-10.0, -20.0, -30.0))
        self.assertEqual((t["ux"], t["uy"], t["uz"]), (10.0, 20.0, 30.0))
        self.assertEqual(t["ebins"], "0, 0.1, 1")

    def test_1g_fmesh_cyl(self):
        data = (
            "FMESH14:P GEOM=CYL ORIGIN=0 0 -5\n"
            "     IMESH=10 IINTS=10 JMESH=5 JINTS=10 KMESH=0.5 KINTS=2\n"
        )
        res = mcnp_cards_in.parse(make_deck(data))
        self.assertEqual(len(res["tallies"]), 1)
        t = res["tallies"][0]
        self.assertEqual(t["meshGeom"], "cylindrical")
        self.assertEqual(t["nr"], 10)
        self.assertEqual(t["rmin"], 0.0)
        self.assertEqual(t["rmax"], 10.0)
        self.assertEqual(t["nz"], 10)
        # MCNP 6.3 FMESH note 4: cylindrical JMESH heights are relative to
        # ORIGIN, so this mesh spans z = -5 .. 0 (Studio's z grid is too).
        self.assertEqual(t["zmin"], 0.0)
        self.assertEqual(t["zmax"], 5.0)
        self.assertEqual(t["oz"], -5.0)
        self.assertEqual(t["nphi"], 2)
        self.assertAlmostEqual(t["phimax"], math.pi)

    def test_1g_fmesh_cyl_jmesh_relative_to_origin(self):
        data = (
            "FMESH24 GEOM=CYL ORIGIN=1 2 100\n"
            "     IMESH=4 IINTS=2 JMESH=20 40 JINTS=2 2 KMESH=1 KINTS=4\n"
        )
        t = mcnp_cards_in.parse(make_deck(data))["tallies"][0]
        self.assertEqual((t["ox"], t["oy"], t["oz"]), (1.0, 2.0, 100.0))
        self.assertEqual((t["nz"], t["zmin"], t["zmax"]), (4, 0.0, 40.0))

    # ── One bad card refuses that card only ────────────────────────────────

    def test_bad_nps_refused(self):
        for body in ("NPS abc", "NPS 0", "NPS 2.5", "NPS"):
            res = mcnp_cards_in.parse(make_deck(body + "\n"))
            self.assertNotIn("nps", res["settings"], body)
            self.assertTrue(any(r["card"].upper() == "NPS" for r in res["refused"]), body)

    def test_nps_float_notation_accepted(self):
        res = mcnp_cards_in.parse(make_deck("NPS 1e6\n"))
        self.assertEqual(res["settings"]["nps"], 1000000)

    def test_malformed_tokens_refuse_only_their_card(self):
        data = (
            "NPS 5000\n"
            "F4:N 1\n"
            "E4 R 1 2\n"                     # R with nothing before it
            "F14:N 1\n"
            "E14 0.1 1\n"
            "FMESH34 GEOM=XYZ ORIGIN=0 0 0\n"
            "     IMESH=10 IINTS=0 JMESH=10 JINTS=1 KMESH=10 KINTS=1\n"   # zero intervals
            "FMESH44 GEOM=XYZ ORIGIN=0 0 zz\n"
            "     IMESH=10 JMESH=10 KMESH=10\n"
            "SDEF POS=0 0 1x ERG=1\n"
        )
        res = mcnp_cards_in.parse(make_deck(data))
        self.assertEqual(res["settings"]["nps"], 5000)
        self.assertEqual([t["mcnp_card"] for t in res["tallies"]], ["F14:N"])
        refused = {r["card"].upper() for r in res["refused"]}
        self.assertTrue({"F4:N", "FMESH34", "FMESH44", "SDEF"} <= refused, refused)
        self.assertEqual(res["sources"], [])

    def test_sp_first_value_not_a_number_refused(self):
        data = "SDEF ERG=D1 POS=0 0 0\nSI1 H 0 1\nSP1 abc 1\n"
        res = mcnp_cards_in.parse(make_deck(data))
        self.assertEqual(res["sources"], [])
        self.assertIn({"card": "SDEF", "line": res["refused"][0]["line"],
                       "reason": "SP1 value 'abc' isn't a number"}, res["refused"])

    def test_sp_empty_refused(self):
        data = "SDEF ERG=D1 POS=0 0 0\nSI1 H 0 1\nSP1\n"
        res = mcnp_cards_in.parse(make_deck(data))
        self.assertEqual(res["sources"], [])
        self.assertTrue(any(r["reason"] == "SP1 has no values" for r in res["refused"]), res["refused"])

    def test_kcode_bad_values_refused(self):
        res = mcnp_cards_in.parse(make_deck("KCODE 1000 1.0 x 50\n"))
        self.assertTrue(any(r["card"].upper() == "KCODE" for r in res["refused"]))
        self.assertNotIn("runMode", res["settings"])

    def test_ksrc_without_a_point_refused(self):
        res = mcnp_cards_in.parse(make_deck("KCODE 1000 1.0 10 50\nKSRC 1 2\n"))
        self.assertTrue(any(r["card"].upper() == "KSRC" for r in res["refused"]))
        self.assertEqual(res["sources"], [])

    def test_cell_tally_carries_its_card_name(self):
        res = mcnp_cards_in.parse(make_deck("F4:N 1\nFC4 Core flux\n"))
        t = res["tallies"][0]
        self.assertEqual((t["name"], t["mcnp_card"]), ("Core flux", "F4:N"))

    def test_1g_fmesh_nonuniform_refused(self):
        data = (
            "FMESH4:N GEOM=XYZ ORIGIN=0 0 0\n"
            "     IMESH=5 15 IINTS=5 5 JMESH=10 JINTS=10 KMESH=10 KINTS=10\n"
        )
        # Interval 0..5 has step 1; interval 5..15 has step 2 -> non-uniform!
        res = mcnp_cards_in.parse(make_deck(data))
        self.assertEqual(len(res["tallies"]), 0)
        self.assertTrue(any(r["card"] == "FMESH4:N" and "Studio mesh bins are uniform" in r["reason"] for r in res["refused"]))

    def test_1g_fmesh_unsupported_keyword_refused(self):
        data = "FMESH4:N GEOM=XYZ ORIGIN=0 0 0\n     IMESH=10 IINTS=10 JMESH=10 JINTS=10 KMESH=10 KINTS=10 FACTOR=2\n"
        res = mcnp_cards_in.parse(make_deck(data))
        self.assertEqual(len(res["tallies"]), 0)
        self.assertTrue(any(r["card"] == "FMESH4:N" and "FACTOR" in r["reason"] for r in res["refused"]))

    # ── Self-falsification edge cases (Rule 3) ─────────────────────────────────

    def test_rule3_refused_tally_companion_comes_later(self):
        data = (
            "F4:N 1\n"
            "FC4 Valid Name\n"
            "c Some comment line\n"
            "FM4 0.36\n"
        )
        res = mcnp_cards_in.parse(make_deck(data))
        self.assertEqual(len(res["tallies"]), 0)
        self.assertEqual(len(res["refused"]), 1)
        self.assertEqual(res["refused"][0]["card"], "F4:N")
        self.assertIn("FM4", res["refused"][0]["reason"])

    def test_rule3_dollar_comment_with_ampersand(self):
        data = (
            "SDEF POS=0 0 0 $ comment with & inside it\n"
            "NPS 1000\n"
        )
        res = mcnp_cards_in.parse(make_deck(data))
        self.assertEqual(len(res["sources"]), 1)
        self.assertEqual(res["settings"]["nps"], 1000)

    # ── Real fixtures from Section 4 ──────────────────────────────────────────

    def test_fixture_shielding_demo(self):
        path = FIXTURES_DIR / "shielding_demo.mcnp"
        res = mcnp_cards_in.parse(path.read_text())

        # One point source at (0, 0, 0), neutron, lines: "14.1:1"
        self.assertEqual(len(res["sources"]), 1)
        src = res["sources"][0]
        self.assertEqual(src["space"], "point")
        self.assertEqual((src["x"], src["y"], src["z"]), (0.0, 0.0, 0.0))
        self.assertEqual(src["particle"], "neutron")
        self.assertEqual(src["energy"], "lines")
        self.assertEqual(src["lines"], "14.1:1")

        # settings == {"nps": 100000, "photon": False}
        self.assertEqual(res["settings"]["nps"], 100000)
        self.assertEqual(res["settings"]["photon"], False)

        # Tallies
        t_by_name = {t["name"]: t for t in res["tallies"]}
        self.assertIn("Detector spectrum (flux)", t_by_name)
        f4 = t_by_name["Detector spectrum (flux)"]
        self.assertEqual(f4["kind"], "cell")
        self.assertEqual(f4["cells_mcnp"], [1])
        self.assertEqual(f4["ebins"], "0, 5e-07, 0.1, 20")

        self.assertIn("Detector spectrum ((n,p))", t_by_name)
        f14 = t_by_name["Detector spectrum ((n,p))"]
        self.assertEqual(f14["kind"], "cell")
        self.assertEqual(f14["cells_mcnp"], [1])
        self.assertEqual(f14["scores"], ["(n,p)"])
        self.assertEqual(f14["fm_material"], 3)

        self.assertIn("FMESH24", t_by_name)
        fmesh24 = t_by_name["FMESH24"]
        self.assertEqual(fmesh24["kind"], "mesh")
        self.assertEqual((fmesh24["nx"], fmesh24["ny"], fmesh24["nz"]), (100, 1, 100))
        self.assertEqual((fmesh24["lx"], fmesh24["ly"], fmesh24["lz"]), (-100.0, -5.0, -100.0))
        self.assertEqual((fmesh24["ux"], fmesh24["uy"], fmesh24["uz"]), (100.0, 5.0, 100.0))

        # F34 refused (DE/DF/FM 0.36)
        f34_refused = [r for r in res["refused"] if r["card"] == "F34:N"]
        self.assertEqual(len(f34_refused), 1)

    def test_fixture_aperture_block(self):
        path = FIXTURES_DIR / "aperture_block.mcnp"
        res = mcnp_cards_in.parse(path.read_text())

        # Box source with a tabulated spectrum
        self.assertEqual(len(res["sources"]), 1)
        src = res["sources"][0]
        self.assertEqual(src["space"], "box")
        self.assertEqual((src["x0"], src["x1"]), (-2.5, 2.5))
        self.assertEqual((src["y0"], src["y1"]), (-10.0, 10.0))
        self.assertEqual((src["z0"], src["z1"]), (-62.5, -57.5))
        self.assertEqual(src["energy"], "tabulated")
        edges = [float(x.strip()) for x in src["tab_e"].split(",")]
        probs = [float(x.strip()) for x in src["tab_p"].split(",")]
        self.assertEqual(edges, [0.0, 0.5, 1.0, 2.0, 4.0, 6.0, 8.0, 10.0])
        self.assertEqual(probs, [0.05, 0.1, 0.2, 0.25, 0.2, 0.12, 0.08])

        # NPS
        self.assertEqual(res["settings"]["nps"], 4000)

        # FMESH 4, 14 and 34 imported
        imported_mesh_names = {t["name"] for t in res["tallies"]}
        for name in ["FMESH4", "FMESH14", "FMESH34"]:
            self.assertIn(name, imported_mesh_names)
        fmesh4 = [t for t in res["tallies"] if t["name"] == "FMESH4"][0]
        self.assertEqual(fmesh4["nx"], 56)
        self.assertEqual(fmesh4["lx"], -90.0)
        self.assertEqual(fmesh4["ux"], 90.0)
        self.assertEqual(fmesh4["ny"], 1)
        self.assertEqual(fmesh4["ly"], 18.5)
        self.assertEqual(fmesh4["uy"], 21.5)

        # FMESH24 (the He-3 response, with an FM card) is refused, and says why
        refused = [r for r in res["refused"] if r["card"] == "FMESH24:N"]
        self.assertEqual(len(refused), 1)
        self.assertIn("FM", refused[0]["reason"])

    def test_fixture_outside_features(self):
        path = FIXTURES_DIR / "outside_features.mcnp"
        res = mcnp_cards_in.parse(path.read_text())

        # Point source at origin, 14.1:1
        self.assertEqual(len(res["sources"]), 1)
        src = res["sources"][0]
        self.assertEqual(src["space"], "point")
        self.assertEqual((src["x"], src["y"], src["z"]), (0.0, 0.0, 0.0))
        self.assertEqual(src["lines"], "14.1:1")

        # NPS 1000
        self.assertEqual(res["settings"]["nps"], 1000)

        # F4 cell [1] with missing-SD note
        self.assertEqual(len(res["tallies"]), 1)
        self.assertEqual(res["tallies"][0]["cells_mcnp"], [1])
        self.assertTrue(any("F4: MCNP divides by the cell volume" in n for n in res["notes"]))


if __name__ == "__main__":
    unittest.main()
