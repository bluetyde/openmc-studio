"""Hexagonal lattices (LAT=2) in imported MCNP decks, checked against the manual's index order and nothing else.

Each deck is written here from the manual's rules (MCNP 6.3.0 p. 290 and the example on p. 766): the element across the
first listed face is [1,0,0], across the third [0,1,0], across the fifth [-1,1,0], and the fill list runs i fastest,
then j, then k. Every element holds a universe whose two halves (either side of a plane through the element's own
centre) are different materials, so a wrong index order, pitch, centre, level or shift of the universe's own
coordinates changes the material somewhere. The expected material at a point is worked out here, with no OpenMC
and no lattice code: the nearest element centre (a hexagon is the region nearer to its centre than to any other)
and which half of it the point is in. The imported geometry (Studio's flat cells, as the report lists them) is
compared at thousands of random points.

Also: the exported fixture deck (a hex lattice Studio wrote) must agree with its cell-by-cell twin, and the decks
this can't read are refused with the reason.

Needs OpenMC with nuclear data (OPENMC_CROSS_SECTIONS) and openmc_mcnp_adapter. Run: python test/test_mcnp_hex.py
"""
import math
import random
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "test" / "fixtures" / "mcnp"
sys.path.insert(0, str(ROOT / "studio"))
from openmc_studio import mcnp_hex, mcnp_import  # noqa: E402

RAD = 4.4  # default width of the filled cylinder: inside the area a 5-ring-wide fill range covers
MATS = {1: "1001.80c 1", 2: "8016.80c 1", 3: "6012.80c 1", 4: "26056.80c 1"}


def unit(deg):
    return (math.cos(math.radians(deg)), math.sin(math.radians(deg)))


def deck_text(a1=30.0, turn=60.0, pitch=3.0, centre=(0.0, 0.0), dz=None, zc=0.0, zup=True, rng_ij=(-2, 2, -2, 2), ks=(0, 0),
              shift=(0.0, 0.0, 0.0), fill_of=None, bad=None, rad=RAD):
    """A deck with one hexagonal lattice. a1 is the direction of the step to [1,0,0], turn the angle from it to the
    step to [0,1,0] (+60 or -60). dz makes it 3D (with the base planes listed up, then down unless zup is False)."""
    a2 = a1 + turn
    t1, t2 = unit(a1), unit(a2)
    n5 = (t2[0] - t1[0], t2[1] - t1[1])
    normals = [t1, (-t1[0], -t1[1]), t2, (-t2[0], -t2[1]), n5, (-n5[0], -n5[1])]
    if bad == "swap5":
        normals[4], normals[5] = normals[5], normals[4]
    if bad == "turned":
        normals = [(math.cos(math.radians(15) + math.atan2(n[1], n[0])), math.sin(math.radians(15) + math.atan2(n[1], n[0]))) for n in normals]
    i1, i2, j1, j2 = rng_ij
    k1, k2 = ks
    lines = ["hex lattice test"]
    face = " ".join(f"-{s}" for s in range(1, 7)) + ((" -7 8" if zup else " 7 -8") if dz else "")
    ids = []
    for k in range(k1, k2 + 1):
        for j in range(j1, j2 + 1):
            for i in range(i1, i2 + 1):
                ids.append(fill_of(i, j, k) if fill_of else 20 + (2 * i + 3 * j + k) % 4)
    fill = f"FILL={i1}:{i2} {j1}:{j2} {k1}:{k2}"
    lines.append(f"1 0 -90 -91 92 FILL=5 ({shift[0]} {shift[1]} {shift[2]}) IMP:N=1")
    lines.append("2 0 90:91:-92 IMP:N=0")
    lines.append(f"10 0 {face} U=5 LAT=2 {fill}")
    for n in range(0, len(ids), 12):
        lines.append("     " + " ".join(str(v) for v in ids[n:n + 12]))
    for c in range(4):
        # the half of the universe beyond the plane through the element's own centre is one material, the rest another
        lines.append(f"{100 + 2 * c} {1 + c} -1.0 -95 61 U={20 + c} IMP:N=1")
        lines.append(f"{101 + 2 * c} {1 + (c + 1) % 4} -1.0 -95 -61 U={20 + c} IMP:N=1")
    lines.append("")
    for s, (n, ) in enumerate([(n,) for n in normals], 1):
        d = n[0] * centre[0] + n[1] * centre[1] + pitch / 2
        lines.append(f"{s} P {n[0]!r} {n[1]!r} 0 {d!r}")
    if dz:
        up, dn = zc + dz / 2, zc - dz / 2
        lines.append(f"7 PZ {up}" if zup else f"7 PZ {dn}")
        lines.append(f"8 PZ {dn}" if zup else f"8 PZ {up}")
    lines += [f"90 C/Z {shift[0]} {shift[1]} {rad}", "91 PZ 12", "92 PZ -12", "95 SO 60", f"61 PX {centre[0]}", ""]
    lines += [f"M{m} {text}" for m, text in MATS.items()] + ["MODE N", "NPS 10"]
    return "\n".join(lines) + "\n", dict(a1=a1, turn=turn, pitch=pitch, centre=centre, dz=dz, zc=zc, zup=zup, rng=rng_ij, ks=ks, shift=shift, rad=rad)


def centres(spec):
    """Element centre of [i,j,k] in the filled cell's coordinates, by the manual's rule."""
    t1, t2 = unit(spec["a1"]), unit(spec["a1"] + spec["turn"])
    p = spec["pitch"]
    zs = (spec["dz"] or 0.0) * (1 if spec["zup"] else -1)
    sx, sy, sz = spec["shift"]
    return lambda i, j, k: (sx + p * (i * t1[0] + j * t2[0]), sy + p * (i * t1[1] + j * t2[1]), sz + k * zs)


def material_at(rep, pt):
    """The imported geometry's material (MCNP number) at a point, from the report's cells."""
    x, y, z = (np.array([v]) for v in pt)
    hits = []
    for comp in rep["components"]:
        surfs = {s["id"]: s for s in comp["surfaces"]}
        for cell in comp["cells"]:
            if mcnp_import.region_eval(cell["region"], surfs, x, y, z, {})[0]:
                hits.append(cell["material_mcnp"])
    return hits


class IndexOrder(unittest.TestCase):
    def check(self, text, spec, seed=1, n=3000):
        d = Path(tempfile.mkdtemp(prefix="mcnp-hex-"))
        deck = d / "deck.mcnp"
        deck.write_text(text)
        rep = mcnp_import.import_deck(deck)
        self.assertTrue(rep["check"]["agree"] == rep["check"]["points"] > 0)
        where = centres(spec)
        i1, i2, j1, j2 = spec["rng"]
        k1, k2 = spec["ks"]
        ids = [int(v) for line in text.splitlines() if line.startswith("     ") for v in line.split()]
        fill = {}
        it = iter(ids)
        for k in range(k1, k2 + 1):
            for j in range(j1, j2 + 1):
                for i in range(i1, i2 + 1):
                    fill[(i, j, k)] = next(it)
        flat = [(i, j) for i in range(i1, i2 + 1) for j in range(j1, j2 + 1)]
        rng = random.Random(seed)
        circum = spec["pitch"] / math.sqrt(3)
        checked, bad, examples = 0, 0, []
        for _ in range(n):
            x, y = rng.uniform(-spec["rad"], spec["rad"]) + spec["shift"][0], rng.uniform(-spec["rad"], spec["rad"]) + spec["shift"][1]
            z = rng.uniform(-11.5, 11.5)
            if math.hypot(x - spec["shift"][0], y - spec["shift"][1]) >= spec["rad"] - 1e-6:
                continue
            (i, j) = min(flat, key=lambda ij: math.hypot(x - where(ij[0], ij[1], 0)[0], y - where(ij[0], ij[1], 0)[1]))
            k = min(range(k1, k2 + 1), key=lambda kk: abs(z - where(0, 0, kk)[2]))
            cx, cy, cz = where(i, j, k)
            if spec["dz"] and abs(z - cz) >= abs(spec["dz"]) / 2 - 1e-6:
                continue
            if math.hypot(x - cx, y - cy) > circum - 1e-6 or abs(x - cx) < 1e-6:
                continue  # outside the hexagon of the nearest listed element, or on the plane that splits its universe
            u = fill[(i, j, k)] - 20
            want = 1 + u if (x - cx) > 0 else 1 + (u + 1) % 4
            checked += 1
            got = material_at(rep, (x, y, z))
            if got != [want]:
                bad += 1
                if len(examples) < 4:
                    examples.append(((round(x, 3), round(y, 3), round(z, 3)), (i, j, k), want, got))
        self.assertGreater(checked, n // 5, "too few points were usable")
        self.assertEqual(bad, 0, f"{bad} of {checked} points differ from the manual's index order, e.g. {examples}")
        return rep

    def test_y_orientation_2d(self):
        text, spec = deck_text(a1=30.0, turn=60.0)
        self.check(text, spec)

    def test_x_orientation_2d(self):
        text, spec = deck_text(a1=0.0, turn=60.0)
        self.check(text, spec)

    def test_first_step_towards_minus_x(self):
        text, spec = deck_text(a1=180.0, turn=60.0)
        self.check(text, spec)

    def test_second_step_turns_the_other_way(self):
        text, spec = deck_text(a1=0.0, turn=-60.0)
        self.check(text, spec)

    def test_first_step_along_y(self):
        text, spec = deck_text(a1=90.0, turn=60.0)
        self.check(text, spec)

    def test_a_range_that_isnt_centred(self):
        text, spec = deck_text(a1=30.0, rng_ij=(-1, 2, -1, 1), rad=2.5)
        self.check(text, spec)

    def test_centre_off_the_origin_and_fill_translation(self):
        text, spec = deck_text(a1=0.0, centre=(0.7, -0.4), shift=(1.5, -2.0, 0.0))
        self.check(text, spec)

    def test_three_dimensional_levels(self):
        text, spec = deck_text(a1=30.0, dz=4.0, zc=0.5, ks=(-1, 1), rng_ij=(-1, 1, -1, 1), shift=(0.0, 0.0, 1.0), rad=2.5)
        self.check(text, spec)

    def test_three_dimensional_with_the_levels_listed_downward(self):
        text, spec = deck_text(a1=0.0, dz=4.0, zup=False, ks=(-1, 1), rng_ij=(-1, 1, -1, 1), rad=2.5)
        self.check(text, spec)


class Fixture(unittest.TestCase):
    def test_exported_deck_matches_its_cell_by_cell_twin(self):
        """hex_array.mcnp is the 'hex_array_y' project exported by Studio; the twin lays out every pin by hand."""
        twin = ROOT / "test" / "generated" / "hex_array_y_flat.py"
        if not twin.is_file():
            self.skipTest("run `node test/generate_fixtures.js` first")
        import runpy
        import openmc
        openmc.reset_auto_ids()
        geom = runpy.run_path(str(twin))["model"].geometry
        rep = mcnp_import.import_deck(FIX / "hex_array.mcnp")
        b = rep["bounds_cm"]
        rng = np.random.default_rng(5)
        pts = np.array(b[:3]) + (np.array(b[3:]) - np.array(b[:3])) * rng.random((3000, 3))
        # the twin's materials by name; the deck's by MCNP number (1 water, 2 iron)
        bad, seen = 0, set()
        for p in pts:
            cell = geom.find(tuple(p))
            m = cell[-1].fill if cell else None
            want = {"Water": 1, "Iron": 2}.get(getattr(m, "name", None))
            got = material_at(rep, tuple(p))
            got = got[0] if len(got) == 1 else (None if not got else "many")
            seen.add(got)
            if got != want:
                bad += 1
        self.assertEqual(bad, 0, f"{bad} of {len(pts)} points differ from the cell-by-cell twin")
        self.assertIn(2, seen)


class Refusals(unittest.TestCase):
    def reason(self, text):
        d = Path(tempfile.mkdtemp(prefix="mcnp-hex-bad-"))
        (d / "deck.mcnp").write_text(text)
        with self.assertRaises(mcnp_import.Refused) as cm:
            mcnp_import.import_deck(d / "deck.mcnp")
        return str(cm.exception)

    def test_hexagon_turned_to_neither_axis(self):
        text, _ = deck_text(bad="turned")
        self.assertIn("neither the x nor the y axis", self.reason(text))

    def test_faces_in_the_wrong_order(self):
        text, _ = deck_text(bad="swap5")
        self.assertIn("fifth face", self.reason(text))

    def test_not_a_regular_hexagon(self):
        text, _ = deck_text()
        text = text.replace("3 P ", "3 P ", 1)
        lines = text.split("\n")
        k = next(n for n, ln in enumerate(lines) if ln.startswith("3 P "))
        parts = lines[k].split()
        parts[-1] = repr(float(parts[-1]) + 0.4)
        lines[k] = " ".join(parts)
        self.assertIn("isn't regular", self.reason("\n".join(lines)))

    def test_fill_count_must_match_the_range(self):
        text, _ = deck_text()
        lines = text.split("\n")
        k = next(n for n, ln in enumerate(lines) if ln.startswith("     "))
        lines[k] = lines[k].rsplit(" ", 1)[0]
        self.assertIn("universes for an index range", self.reason("\n".join(lines)))

    def test_a_curved_face(self):
        text, _ = deck_text()
        lines = text.split("\n")
        k = next(n for n, ln in enumerate(lines) if ln.startswith("2 P "))
        lines[k] = "2 SO 4"
        self.assertIn("isn't a plane", self.reason("\n".join(lines)))

    def test_prepare_leaves_a_deck_without_hex_alone(self):
        text = (FIX / "aperture_block.mcnp").read_text()
        self.assertEqual(mcnp_hex.prepare(text), (text, []))


if __name__ == "__main__":
    unittest.main()
