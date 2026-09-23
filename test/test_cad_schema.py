"""CAD stage 3: the CSG representation and the XML adapter, without the CAD engine.

- the OpenMC region grammar: precedence (~ over intersection over |), parentheses,
  signs, and refusals (unknown surfaces, unbalanced input, junk, depth, size);
- the XML reader: DTD/entity refusal, size and element limits, unsupported and
  refused (torus) surfaces, bad coefficients, dropped boundary attributes, pruned
  unused surfaces, material/fill/universe refusals;
- surface equations: where openmc is importable, every supported type is compared
  with OpenMC's own evaluate() at random points, so Studio's region answers are
  OpenMC's answers.

Runs anywhere (Windows, WSL, macOS). Run: python test/test_cad_schema.py
"""
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "studio"))
from openmc_studio.cad import schema  # noqa: E402
from openmc_studio.cad.schema import AdapterError, parse_region, read_openmc_xml, region_text  # noqa: E402

IDS = set(range(1, 10))


def xml(surfaces, cells):
    body = "".join(f'<surface id="{i}" type="{t}" coeffs="{c}"{extra}/>' for i, t, c, extra in surfaces)
    body += "".join(f'<cell id="{n + 1}" material="void" name="/x" region="{r}" universe="1"/>' for n, r in enumerate(cells))
    return f"<?xml version='1.0' encoding='UTF-8'?><geometry>{body}</geometry>"


class RegionGrammar(unittest.TestCase):
    def test_intersection_by_juxtaposition(self):
        self.assertEqual(parse_region("((2 4 -3 -1))", IDS),
                         {"op": "and", "args": [{"half": "+", "s": 2}, {"half": "+", "s": 4},
                                                {"half": "-", "s": 3}, {"half": "-", "s": 1}]})

    def test_union_is_weaker_than_intersection(self):
        ast = parse_region("1 -2 | 3", IDS)
        self.assertEqual(ast["op"], "or")
        self.assertEqual(ast["args"][0]["op"], "and")
        self.assertEqual(ast["args"][1], {"half": "+", "s": 3})

    def test_complement_binds_tightest(self):
        ast = parse_region("~1 2", IDS)
        self.assertEqual(ast, {"op": "and", "args": [{"op": "not", "arg": {"half": "+", "s": 1}}, {"half": "+", "s": 2}]})
        ast = parse_region("~(1 | 2) +3", IDS)
        self.assertEqual(ast["args"][0]["arg"]["op"], "or")

    def test_nested_same_operators_flatten(self):
        self.assertEqual(len(parse_region("(1 (2 (3 4)))", IDS)["args"]), 4)
        self.assertEqual(len(parse_region("1 | (2 | (3 | 4))", IDS)["args"]), 4)

    def test_text_round_trip(self):
        for text in ("((2 4 -3 -1))", "1 -2 | 3", "~(1 | 2) +3", "(1 | ~(2 -3)) 4"):
            ast = parse_region(text, IDS)
            self.assertEqual(parse_region(region_text(ast), IDS), ast, text)

    def test_refusals(self):
        for bad, msg in (("", "empty"), ("1 2 )", "unbalanced"), ("(1 2", "unbalanced|ends"), ("1 & 2", "unreadable"),
                         ("1 | | 2", "unexpected"), ("~", "ends"), ("12", "surface 12"), ("1 x 2", "unreadable")):
            with self.subTest(bad=bad):
                with self.assertRaisesRegex(AdapterError, msg):
                    parse_region(bad, IDS)

    def test_depth_and_size_limits(self):
        with self.assertRaisesRegex(AdapterError, "nested too deeply"):
            parse_region("(" * 100 + "1" + ")" * 100, IDS)
        with self.assertRaisesRegex(AdapterError, "too long|too complex"):
            parse_region(" ".join(["1"] * (schema.MAX_TOKENS + 1)), IDS)


class XmlReader(unittest.TestCase):
    def test_reads_geouned_output_and_drops_boundaries(self):
        doc = xml([(1, "z-plane", "1.5", ""), (2, "z-plane", "-1.5", ""), (3, "z-cylinder", "0 0 1.2", ""),
                   (4, "z-cylinder", "0 0 0.7", ' boundary="vacuum"')], ["((2 4 -3 -1))"])
        c = read_openmc_xml(doc)
        self.assertEqual(c["units"], "cm")
        self.assertEqual(len(c["surfaces"]), 4)
        self.assertTrue(all("boundary" not in s for s in c["surfaces"]), "the world owns boundaries")
        self.assertEqual(c["cells"][0]["name"], "x")
        # the annulus: material between r 0.7 and 1.2, the hole empty
        self.assertTrue(schema.component_contains(c, 1.0, 0, 0))
        self.assertFalse(schema.component_contains(c, 0.2, 0, 0))
        self.assertFalse(schema.component_contains(c, 1.0, 0, 2.0))

    def test_unused_surfaces_are_pruned(self):
        c = read_openmc_xml(xml([(1, "sphere", "0 0 0 1", ""), (2, "x-plane", "5", "")], ["-1"]))
        self.assertEqual([s["id"] for s in c["surfaces"]], [1])

    def test_dtd_and_entities_are_refused(self):
        evil = ("<?xml version='1.0'?><!DOCTYPE g [<!ENTITY a 'aaaaaaaaaa'><!ENTITY b '&a;&a;&a;&a;'>]>"
                "<geometry><surface id='1' type='sphere' coeffs='0 0 0 1'/><cell id='1' region='-1'/></geometry>")
        with self.assertRaisesRegex(AdapterError, "DTD or entities"):
            read_openmc_xml(evil)

    def test_limits(self):
        with self.assertRaisesRegex(AdapterError, "too large"):
            read_openmc_xml(b" " * (schema.MAX_XML_BYTES + 1))
        with self.assertRaisesRegex(AdapterError, "well-formed"):
            read_openmc_xml("<geometry><cell")
        with self.assertRaisesRegex(AdapterError, "isn't an OpenMC geometry"):
            read_openmc_xml("<materials/>")

    def test_surface_refusals(self):
        cases = [
            ((1, "x-torus", "0 0 0 5 1 1", ""), "torus"),
            ((1, "spline", "1", ""), "unsupported surface"),
            ((1, "sphere", "0 0 0", ""), "4 finite"),
            ((1, "sphere", "0 0 0 nan", ""), "4 finite"),
            ((1, "sphere", "0 0 0 -1", ""), "non-positive radius"),
            ((1, "plane", "0 0 0 1", ""), "no normal"),
            ((1, "z-cone", "0 0 0 0", ""), "slope"),
            ((1, "quadric", "0 0 0 0 0 0 0 0 0 5", ""), "no terms"),
        ]
        for surface, msg in cases:
            with self.subTest(surface=surface[1]):
                with self.assertRaisesRegex(AdapterError, msg):
                    read_openmc_xml(xml([surface], ["-1"]))

    def test_cell_refusals(self):
        base = [(1, "sphere", "0 0 0 1", "")]
        with self.assertRaisesRegex(AdapterError, "no cells"):
            read_openmc_xml(xml(base, []))
        with self.assertRaisesRegex(AdapterError, "surface 7"):
            read_openmc_xml(xml(base, ["-7"]))
        with self.assertRaisesRegex(AdapterError, "assigned a material"):
            read_openmc_xml(xml(base, ["-1"]).replace('material="void"', 'material="3"'))
        with self.assertRaisesRegex(AdapterError, "universes or fills"):
            read_openmc_xml(xml(base, ["-1"]).replace('universe="1"', 'fill="2"'))
        with self.assertRaisesRegex(AdapterError, "share an id"):
            read_openmc_xml(xml(base + base, ["-1"]))


class SurfaceEquations(unittest.TestCase):
    """Studio's evaluate() must be OpenMC's, sign for sign."""
    SAMPLES = {
        "plane": "0.3 -0.5 0.8 1.2", "x-plane": "0.7", "y-plane": "-1.1", "z-plane": "2.5",
        "sphere": "0.1 -0.2 0.3 1.5", "x-cylinder": "0.2 -0.4 0.9", "y-cylinder": "-0.3 0.5 1.1",
        "z-cylinder": "0.6 0.1 0.8", "x-cone": "0.1 0.2 -0.3 0.4", "y-cone": "-0.2 0.1 0.3 1.7",
        "z-cone": "0.3 -0.1 0.2 0.25",
        "quadric": "0.866896740161730 0.994443376429674 0.138659883408596 0.054391348977741 0.138363908501016 "
                   "-0.677191781839653 -2.836257687166845 3.667535607003433 1.409515771591779 4.430477451754257",
    }

    def test_against_openmc(self):
        try:
            import openmc  # noqa: F401
            import xml.etree.ElementTree as ET
        except ImportError:
            self.skipTest("openmc is not installed here; the WSL/CI run covers this comparison")
        import openmc
        rng = random.Random(7)
        for t, coeffs in self.SAMPLES.items():
            with self.subTest(type=t):
                ours = read_openmc_xml(xml([(1, t, coeffs, "")], ["-1"]))["surfaces"][0]
                el = ET.fromstring(f'<surface id="1" type="{t}" coeffs="{coeffs}"/>')
                theirs = openmc.Surface.from_xml_element(el)
                for _ in range(500):
                    p = tuple(rng.uniform(-4, 4) for _ in range(3))
                    a, b = schema.evaluate(ours, *p), theirs.evaluate(p)
                    self.assertAlmostEqual(a, b, delta=1e-9 * max(1, abs(b)), msg=f"{t} at {p}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
