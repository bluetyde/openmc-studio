import unittest
import tempfile
import numpy as np
import openmc
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "studio"))
from openmc_studio import results

class TestEllipsoidPrimitive(unittest.TestCase):
    def test_ellipsoid_quadric_simulation(self):
        mat = openmc.Material(name='water')
        mat.set_density('g/cm3', 1.0)
        mat.add_nuclide('H1', 2.0)
        mat.add_nuclide('O16', 1.0)
        materials = openmc.Materials([mat])

        # Ellipsoid semi-axes and center
        a, b, c = 2.0, 3.0, 4.0
        x0, y0, z0 = 0.5, -0.5, 1.0

        A = 1.0 / (a * a)
        B = 1.0 / (b * b)
        C = 1.0 / (c * c)
        G = -2.0 * x0 / (a * a)
        H = -2.0 * y0 / (b * b)
        J = -2.0 * z0 / (c * c)
        K = (x0 * x0) / (a * a) + (y0 * y0) / (b * b) + (z0 * z0) / (c * c) - 1.0

        ellip_surf = openmc.Quadric(a=A, b=B, c=C, g=G, h=H, j=J, k=K, boundary_type='vacuum')
        cell_ellip = openmc.Cell(name='ellipsoid_body', fill=mat, region=-ellip_surf)
        geom = openmc.Geometry([cell_ellip])

        tally = openmc.Tally(name='ellip_flux')
        tally.filters = [openmc.CellFilter([cell_ellip])]
        tally.scores = ['flux']
        tallies = openmc.Tallies([tally])

        settings = openmc.Settings()
        settings.particles = 100
        settings.batches = 5
        settings.inactive = 0
        settings.run_mode = 'fixed source'
        settings.source = openmc.IndependentSource(space=openmc.stats.Point((x0, y0, z0)))

        model = openmc.Model(geometry=geom, materials=materials, settings=settings, tallies=tallies)
        with tempfile.TemporaryDirectory(prefix='studio_test_') as run_dir:
            model.run(output=False, cwd=run_dir)
            res = results.load(run_dir)
            t_data = next((t for t in res["tallies"] if t["name"] == "ellip_flux"), None)
            self.assertIsNotNone(t_data, "Ellipsoid tally should exist")
            self.assertEqual(len(t_data["rows"]), 1)
            flux = t_data["rows"][0]["mean"]
            self.assertGreater(flux, 0.0)

if __name__ == '__main__':
    unittest.main()
