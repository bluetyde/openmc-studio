"""The pre-run geometry check (studio/openmc_studio/geometry_check.py) must find what it claims to.

Hand-built broken models, each written as a model.py the way Studio's are (a `model` and a
`studio_ids` at module level), then checked through the same command the server runs:

  overlap    two spheres, neither cut out of the other
  gap        a world that doesn't fill the box around a part
  lattice    a lattice with no outer universe, inside a cell larger than the lattice
  rotated    an overlap only visible after a rotated, translated universe fill
  clean      the same shapes done properly: nothing may be reported

Points must find every problem. With OPENMC_CROSS_SECTIONS set, the particle run (openmc -g)
must also report the overlap and the lost particles.

Run with a Python that has openmc:  python test/test_geometry_check.py
"""
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

CHECK = Path(__file__).resolve().parents[1] / "studio" / "openmc_studio" / "geometry_check.py"
HAVE_XS = bool(os.environ.get("OPENMC_CROSS_SECTIONS")) and Path(os.environ.get("OPENMC_CROSS_SECTIONS", "")).exists()

HEAD = """
import openmc
water = openmc.Material(name="water"); water.add_element("H", 2); water.add_element("O", 1); water.set_density("g/cm3", 1.0)
materials = openmc.Materials([water])
walls = [openmc.XPlane(-20, boundary_type="vacuum"), openmc.XPlane(20, boundary_type="vacuum"),
         openmc.YPlane(-20, boundary_type="vacuum"), openmc.YPlane(20, boundary_type="vacuum"),
         openmc.ZPlane(-20, boundary_type="vacuum"), openmc.ZPlane(20, boundary_type="vacuum")]
world = +walls[0] & -walls[1] & +walls[2] & -walls[3] & +walls[4] & -walls[5]
settings = openmc.Settings(); settings.run_mode = "fixed source"; settings.batches = 2; settings.particles = 100
settings.source = openmc.IndependentSource(space=openmc.stats.Box([-15, -15, -15], [15, 15, 15]),
                                           energy=openmc.stats.Discrete([1e6], [1]))
"""
TAIL = """
geometry = openmc.Geometry(root)
model = openmc.Model(geometry=geometry, materials=materials, settings=settings)
studio_ids = {"cell": {c.id: {"kind": "part", "id": c.name or f"c{c.id}"} for c in geometry.get_all_cells().values()}}
"""
MODELS = {
    "overlap": """
a = openmc.Sphere(x0=-3, r=6); b = openmc.Sphere(x0=3, r=6)
ca = openmc.Cell(name="A", fill=water, region=-a); cb = openmc.Cell(name="B", fill=water, region=-b)
rest = openmc.Cell(name="world", region=world & +a & +b)
root = openmc.Universe(cells=[ca, cb, rest])
""",
    "gap": """
s = openmc.Sphere(r=5)
part = openmc.Cell(name="part", fill=water, region=-s)
rest = openmc.Cell(name="world", region=world & +s & +openmc.ZPlane(10))  # nothing below z = 10 outside the sphere
root = openmc.Universe(cells=[part, rest])
""",
    "lattice": """
pin = openmc.Universe(cells=[openmc.Cell(name="pin", fill=water)])
lat = openmc.RectLattice(); lat.lower_left = (-6, -6); lat.pitch = (4, 4); lat.universes = [[pin] * 3] * 3
box = openmc.model.RectangularParallelepiped(-10, 10, -10, 10, -10, 10)
holder = openmc.Cell(name="holder", fill=lat, region=-box)   # the lattice covers only -6..6
rest = openmc.Cell(name="world", region=world & +box)
root = openmc.Universe(cells=[holder, rest])
""",
    "rotated": """
c1 = openmc.ZCylinder(r=2)
inner = openmc.Universe(cells=[openmc.Cell(name="rod", fill=water, region=-c1),
                               openmc.Cell(name="sleeve", fill=water, region=-openmc.ZCylinder(r=3))])  # sleeve not cut
box = openmc.model.RectangularParallelepiped(-8, 8, -8, 8, -8, 8)
holder = openmc.Cell(name="holder", fill=inner, region=-box)
holder.rotation = (90, 0, 0); holder.translation = (2, 0, 0)
rest = openmc.Cell(name="world", region=world & +box)
root = openmc.Universe(cells=[holder, rest])
""",
    "clean": """
a = openmc.Sphere(x0=-3, r=6); b = openmc.Sphere(x0=3, r=6)
ca = openmc.Cell(name="A", fill=water, region=-a); cb = openmc.Cell(name="B", fill=water, region=-b & +a)
pin = openmc.Universe(cells=[openmc.Cell(name="pin", fill=water)])
lat = openmc.RectLattice(); lat.lower_left = (-6, -6); lat.pitch = (4, 4); lat.universes = [[pin] * 3] * 3; lat.outer = pin
box = openmc.model.RectangularParallelepiped(-10, 10, -10, 10, 11, 19)
holder = openmc.Cell(name="holder", fill=lat, region=-box)
rest = openmc.Cell(name="world", region=world & +a & +b & +box)
root = openmc.Universe(cells=[ca, cb, holder, rest])
""",
}


def check(name, particles=0):
    d = Path(tempfile.mkdtemp(prefix=f"geomcheck-{name}-"))
    (d / "model.py").write_text(textwrap.dedent(HEAD + MODELS[name] + TAIL))
    opts = {"world": {"shape": "box", "R": 20}, "points": 40000, "particles": particles}
    env = {**os.environ, "PATH": os.path.dirname(sys.executable) + os.pathsep + os.environ.get("PATH", "")}
    r = subprocess.run([sys.executable, str(CHECK), str(d), json.dumps(opts)], capture_output=True, text=True, env=env, timeout=900)
    assert r.returncode == 0, r.stdout + r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


class Points(unittest.TestCase):
    def test_overlap(self):
        p = check("overlap")["points"]
        self.assertGreater(p["overlaps"], 0, p)
        self.assertEqual(p["gaps"], 0, p)
        ex = p["overlap_examples"][0]
        self.assertEqual(len(ex["cells"]), 2)
        x = ex["p"][0]
        self.assertLess(abs(x), 3.0, "an overlap point lies in the lens between the spheres")

    def test_gap(self):
        p = check("gap")["points"]
        self.assertGreater(p["gaps"], 0, p)
        self.assertEqual(p["overlaps"], 0, p)
        self.assertTrue(all(e["p"][2] < 10 for e in p["gap_examples"]), p["gap_examples"])

    def test_lattice_gap(self):
        p = check("lattice")["points"]
        self.assertGreater(p["gaps"], 0, p)
        self.assertTrue(any(str(e["universe"]).startswith("lattice") for e in p["gap_examples"]), p["gap_examples"])

    def test_overlap_inside_rotated_fill(self):
        p = check("rotated")["points"]
        self.assertGreater(p["overlaps"], 0, p)
        # rod (r=2) about the fill's rotated axis: the local z axis lies along world y after the
        # 90 degree turn about x, and the fill is shifted by +2 in x
        for e in p["overlap_examples"]:
            x, y, z = e["p"]
            self.assertLess((x - 2) ** 2 + z ** 2, 4.0 + 1e-9, e)

    def test_clean(self):
        out = check("clean")
        self.assertEqual((out["points"]["gaps"], out["points"]["overlaps"]), (0, 0), out["points"])
        self.assertTrue(out["cells"], "Studio ids come back so the page can name cells")


@unittest.skipUnless(HAVE_XS, "set OPENMC_CROSS_SECTIONS to run the particle half")
class Particles(unittest.TestCase):
    def test_overlap_found_by_openmc(self):
        t = check("overlap", particles=2000)["transport"]
        self.assertTrue(t["ran"], t)
        self.assertIsNotNone(t["overlap"], t)
        self.assertEqual(len(t["overlap"]["cells"]), 2)

    def test_lost_particles_counted(self):
        t = check("gap", particles=2000)["transport"]
        self.assertTrue(t["ran"], t)
        self.assertGreater(t["lost"], 0, t)

    def test_clean_run(self):
        t = check("clean", particles=1000)["transport"]
        self.assertTrue(t["ran"], t)
        self.assertEqual((t["lost"], t["overlap"]), (0, None), t)


if __name__ == "__main__":
    unittest.main(verbosity=2)
