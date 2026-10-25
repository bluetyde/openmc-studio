"""The first wall read from a PLOW-style record, written by Studio and measured by OpenMC (needs OpenMC and nuclear data; run `node test/generate_fixtures.js` first).

firstwall_ring is the cone stack the reader writes in exact mode for a 120-point Miller D (R0 200 cm, a 60 cm, kappa 1.7, delta 0.33) with a 5 cm wall. OpenMC's stochastic volume of the
plasma cells and of the wall cells (the wall cones plus the left cones of the plasma boundary, which are the wall on the inboard side) is compared with the volume the polygon turns through
(V = pi * closed integral of R^2 dZ) and with its mitre offset by 5 cm, both computed here independently of the page.

    python test/test_first_wall_openmc.py
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
R0, A, KAPPA, DELTA, WALL, POINTS = 200.0, 60.0, 1.7, 0.33, 5.0, 120


def polygon():
    s = math.asin(DELTA)
    pts = []
    for i in range(POINTS):
        t = 2 * math.pi * i / POINTS
        u = t + s * math.sin(t)
        pts.append((R0 + A * math.cos(u), KAPPA * A * math.sin(t)))
    return pts


def offset(pts, d):
    n = len(pts)
    nrm = []
    for i, a in enumerate(pts):
        b = pts[(i + 1) % n]
        dr, dz = b[0] - a[0], b[1] - a[1]
        ln = math.hypot(dr, dz)
        nrm.append((dz / ln, -dr / ln))
    out = []
    for i, p in enumerate(pts):
        m, q = nrm[i - 1], nrm[i]
        k = 1 + m[0] * q[0] + m[1] * q[1]
        out.append((p[0] + d * (m[0] + q[0]) / k, p[1] + d * (m[1] + q[1]) / k))
    return out


def revolve_volume(pts):
    v = 0.0
    n = len(pts)
    for i in range(n):
        a, b = pts[i], pts[(i + 1) % n]
        v += (a[0] * a[0] + a[0] * b[0] + b[0] * b[0]) / 3 * (b[1] - a[1])
    return math.pi * v


def measured(samples=6_000_000):
    openmc.reset_auto_ids()
    with contextlib.redirect_stdout(io.StringIO()):
        ns = runpy.run_path(os.path.join(HERE, "generated", "firstwall_ring.py"), run_name="studio_test")
    model = ns["model"]
    cells = {c.name: c for c in model.geometry.get_all_cells().values()}
    chosen = {n: c for n, c in cells.items() if n.startswith(("D_plasma", "D_wall", "D_left_0"))}
    calc = openmc.VolumeCalculation(list(chosen.values()), samples, (-290, -290, -125), (290, 290, 125))
    model.settings.volume_calculations = [calc]
    with tempfile.TemporaryDirectory(prefix="studio_firstwall_") as d:
        model.calculate_volumes(cwd=d, output=False)
        calc.load_results(os.path.join(d, "volume_1.h5"))
    got = {"plasma": [0.0, 0.0], "wall": [0.0, 0.0]}
    for n, c in chosen.items():
        v = calc.volumes[c.id]
        k = "plasma" if n.startswith("D_plasma") else "wall"
        got[k][0] += v.nominal_value
        got[k][1] += v.std_dev ** 2
    return {k: (a, math.sqrt(b)) for k, (a, b) in got.items()}


class TestFirstWallRing(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.vol = measured()

    def test_plasma_volume_is_the_polygons_volume_of_revolution(self):
        want = revolve_volume(polygon())
        got, sd = self.vol["plasma"]
        self.assertLess(abs(got / want - 1), max(4 * sd / want, 0.003), f"OpenMC {got:.4g} +/- {sd:.2g} cm3, polygon {want:.4g} cm3")

    def test_wall_volume_is_the_offset_polygon_minus_the_plasma(self):
        want = revolve_volume(offset(polygon(), WALL)) - revolve_volume(polygon())
        got, sd = self.vol["wall"]
        self.assertLess(abs(got / want - 1), max(4 * sd / want, 0.01), f"OpenMC {got:.4g} +/- {sd:.2g} cm3, offset polygon {want:.4g} cm3")


if __name__ == "__main__":
    unittest.main()
