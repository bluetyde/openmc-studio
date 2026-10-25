"""The torus part, written by Studio and measured by OpenMC (needs OpenMC and nuclear data; run `node test/generate_fixtures.js` first).

Each fixture is a torus 'ring' (a = 10) behind a box 'slab' that wins where they overlap, so OpenMC's stochastic volume of 'ring' is the torus outside |h| < 1.5
along its axis. The closed form is 2 pi a * 2 c b (pi - asin x - x sqrt(1 - x^2)), x = min(h / b, 1). The whole-torus volume 2 pi^2 a b c cannot tell b and c apart;
this one can: b = 2, c = 1 leaves 56.965 cm3 outside the slab, b = 1, c = 2 leaves none.

    python test/test_torus_openmc.py
"""
import contextlib
import io
import math
import os
import runpy
import unittest

import openmc

HERE = os.path.dirname(os.path.abspath(__file__))
A, H = 10.0, 1.5


def outside_slab(b, c, h=H):
    x = min(h / b, 1.0)
    whole = 2 * math.pi ** 2 * A * b * c
    inside = 2 * math.pi * A * 2 * c * b * (math.asin(x) + x * math.sqrt(1 - x * x))
    return whole - inside


def measured(name, lower, upper, samples=4_000_000):
    openmc.reset_auto_ids()
    with contextlib.redirect_stdout(io.StringIO()):
        ns = runpy.run_path(os.path.join(HERE, "generated", name + ".py"), run_name="studio_test")
    model = ns["model"]
    ring = next(c for c in model.geometry.get_all_cells().values() if c.name == "ring")
    import tempfile
    calc = openmc.VolumeCalculation([ring], samples, lower, upper)
    model.settings.volume_calculations = [calc]
    with tempfile.TemporaryDirectory(prefix="studio_torus_") as d:
        model.calculate_volumes(cwd=d, output=False)
        calc.load_results(os.path.join(d, "volume_1.h5"))
    v = calc.volumes[ring.id]
    return v.nominal_value, v.std_dev, model


class TestTorusVolumes(unittest.TestCase):
    def check(self, name, b, c, lower, upper):
        got, sd, _ = measured(name, lower, upper)
        want = outside_slab(b, c)
        self.assertLess(abs(got - want), max(4 * sd, 0.005 * max(want, 1.0)), f"{name}: OpenMC {got:.3f} +/- {sd:.3f}, closed form {want:.3f}")
        return got, want

    def test_z_axis_elliptical_torus(self):
        got, want = self.check("torus_ellip", 2.0, 1.0, (-12, -12, -3), (12, 12, 3))
        self.assertAlmostEqual(want, 56.965, places=2)

    def test_swapping_b_and_c_changes_the_volume_outside_the_slab(self):
        got, want = self.check("torus_swapped", 1.0, 2.0, (-13, -13, -3), (13, 13, 3))
        self.assertLess(want, 1e-9)
        self.assertLess(got, 1.0)                                  # the slab holds the whole shallow torus

    def test_x_axis_torus_has_b_along_x(self):
        got, want = self.check("torus_x", 2.0, 1.0, (-3, -12, -12), (3, 12, 12))
        self.assertAlmostEqual(want, 56.965, places=2)

    def test_the_script_uses_the_matching_openmc_classes(self):
        for name, cls in (("torus_ellip", openmc.ZTorus), ("torus_swapped", openmc.ZTorus), ("torus_x", openmc.XTorus)):
            with contextlib.redirect_stdout(io.StringIO()):
                ns = runpy.run_path(os.path.join(HERE, "generated", name + ".py"), run_name="studio_test")
            tori = [s for s in ns["model"].geometry.get_all_surfaces().values() if isinstance(s, (openmc.XTorus, openmc.YTorus, openmc.ZTorus))]
            self.assertEqual(len(tori), 1)
            self.assertIs(type(tori[0]), cls)
        swapped = [s for s in runpy.run_path(os.path.join(HERE, "generated", "torus_swapped.py"))["model"].geometry.get_all_surfaces().values() if isinstance(s, openmc.ZTorus)][0]
        self.assertEqual((swapped.a, swapped.b, swapped.c), (10.0, 1.0, 2.0))


class TestTorusLattice(unittest.TestCase):
    def test_lattice_and_flat_twin_agree_at_tubes_and_holes(self):
        """Three tori (a = 10, b = 2, c = 1) every 30 cm along x, as a RectLattice and as separate cells."""
        points = [(30 * i + dx, dy, dz) for i in (-1, 0, 1) for dx, dy, dz in
                  ((10, 0, 0), (-10, 0, 0), (0, 10, 1.5), (0, 0, 0), (10, 0, 2.5), (11.5, 0, 0), (5, 5, 0), (7.07, 7.07, 0))]
        for name in ("torus_lattice", "torus_lattice_flat"):
            openmc.reset_auto_ids()
            with contextlib.redirect_stdout(io.StringIO()):
                ns = runpy.run_path(os.path.join(HERE, "generated", name + ".py"), run_name="studio_test")
            geom = ns["model"].geometry
            got = []
            for pt in points:
                found = geom.find(pt)
                fill = found[-1].fill if found else None
                got.append(fill.name if isinstance(fill, openmc.Material) else None)
            if name == "torus_lattice":
                lattice_answer = got
            else:
                self.assertEqual(got, lattice_answer, "lattice and flat twin differ")
        inside = [a is not None for a in lattice_answer]
        self.assertEqual(inside, [True, True, True, False, False, False, False, True] * 3)


if __name__ == "__main__":
    unittest.main()
