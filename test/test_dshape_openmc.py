"""The D-shaped ring, written by Studio and measured by OpenMC (needs OpenMC and nuclear data; run `node test/generate_fixtures.js` first).

dshape_ring is the cone stack the generator writes for R0 = 30, a = 10, kappa = 1.7, delta = 0.33, 48 slabs and a 2 cm wall. OpenMC's stochastic volume of the plasma cells
and of the wall cells (the wall cones plus the left cones of the inner boundary, which are the wall on the inboard side) is compared with the volume the smooth Miller curve
turns through: V = pi * closed integral of R^2 dZ, taken for the curve and for the curve pushed out 2 cm.

    python test/test_dshape_openmc.py
"""
import contextlib
import io
import math
import os
import runpy
import tempfile
import unittest

import openmc

HERE = os.path.dirname(os.path.abspath(__file__))
R0, A, KAPPA, DELTA, WALL = 30.0, 10.0, 1.7, 0.33, 2.0


def curve_volume(d, m=200000):
    s = math.asin(DELTA)
    pts = []
    for i in range(m):
        t = 2 * math.pi * i / m
        u = t + s * math.sin(t)
        dr = -A * math.sin(u) * (1 + s * math.cos(t))
        dz = KAPPA * A * math.cos(t)
        n = math.hypot(dr, dz)
        pts.append((R0 + A * math.cos(u) + d * dz / n, KAPPA * A * math.sin(t) - d * dr / n))
    v = 0.0
    for i in range(m):
        q = pts[(i + 1) % m]
        v += (pts[i][0] ** 2 + q[0] ** 2) / 2 * (q[1] - pts[i][1])
    return math.pi * v


def measured(samples=6_000_000):
    openmc.reset_auto_ids()
    with contextlib.redirect_stdout(io.StringIO()):
        ns = runpy.run_path(os.path.join(HERE, "generated", "dshape_ring.py"), run_name="studio_test")
    model = ns["model"]
    cells = {c.name: c for c in model.geometry.get_all_cells().values()}
    chosen = [c for n, c in cells.items() if n.startswith(("D_plasma", "D_wall", "D_left_0"))]
    calc = openmc.VolumeCalculation(chosen, samples, (-45, -45, -22), (45, 45, 22))
    model.settings.volume_calculations = [calc]
    with tempfile.TemporaryDirectory(prefix="studio_dshape_") as d:
        model.calculate_volumes(cwd=d, output=False)
        calc.load_results(os.path.join(d, "volume_1.h5"))
    got = {"plasma": [0.0, 0.0], "wall": [0.0, 0.0]}
    for n, c in cells.items():
        if c not in chosen:
            continue
        v = calc.volumes[c.id]
        k = "plasma" if n.startswith("D_plasma") else "wall"
        got[k][0] += v.nominal_value
        got[k][1] += v.std_dev ** 2
    return {k: (a, math.sqrt(b)) for k, (a, b) in got.items()}, cells


class TestDShapeRing(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.vol, cls.cells = measured()

    def test_plasma_volume(self):
        want = curve_volume(0.0)
        got, sd = self.vol["plasma"]
        self.assertLess(abs(got / want - 1), max(4 * sd / want, 0.004), f"OpenMC {got:.1f} +/- {sd:.1f}, Miller curve {want:.1f}")

    def test_wall_volume(self):
        want = curve_volume(WALL) - curve_volume(0.0)
        got, sd = self.vol["wall"]
        self.assertLess(abs(got / want - 1), max(4 * sd / want, 0.01), f"OpenMC {got:.1f} +/- {sd:.1f}, Miller curve {want:.1f}")

    def test_the_parts_come_out_as_cone_surfaces(self):
        with contextlib.redirect_stdout(io.StringIO()):
            ns = runpy.run_path(os.path.join(HERE, "generated", "dshape_ring.py"), run_name="studio_test")
        kinds = {type(s).__name__ for s in ns["model"].geometry.get_all_surfaces().values()}
        self.assertTrue(kinds & {"ZCone", "Quadric"}, kinds)


class TestEqualRadiusCone(unittest.TestCase):
    def test_a_cone_with_equal_radii_is_a_cylinder_of_the_right_volume(self):
        openmc.reset_auto_ids()
        with contextlib.redirect_stdout(io.StringIO()):
            ns = runpy.run_path(os.path.join(HERE, "generated", "cone_cylinder.py"), run_name="studio_test")
        model = ns["model"]
        tube = next(c for c in model.geometry.get_all_cells().values() if c.name == "tube")
        calc = openmc.VolumeCalculation([tube], 2_000_000, (-4, -4, -6), (4, 4, 6))
        model.settings.volume_calculations = [calc]
        with tempfile.TemporaryDirectory(prefix="studio_cone_") as d:
            model.calculate_volumes(cwd=d, output=False)
            calc.load_results(os.path.join(d, "volume_1.h5"))
        v = calc.volumes[tube.id]
        want = math.pi * 9 * 10
        self.assertLess(abs(v.nominal_value - want), max(4 * v.std_dev, 0.005 * want), f"OpenMC {v.nominal_value:.2f} +/- {v.std_dev:.2f}, pi r^2 h {want:.2f}")


if __name__ == "__main__":
    unittest.main()
