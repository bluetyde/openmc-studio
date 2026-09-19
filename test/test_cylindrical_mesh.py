import unittest
import numpy as np
import openmc
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "studio"))
from openmc_studio import results

class TestCylindricalMesh(unittest.TestCase):
    def test_cylindrical_mesh_extraction(self):
        mat = openmc.Material(name='water')
        mat.set_density('g/cm3', 1.0)
        mat.add_nuclide('H1', 2.0)
        mat.add_nuclide('O16', 1.0)
        materials = openmc.Materials([mat])

        cyl = openmc.ZCylinder(r=5.0, boundary_type='vacuum')
        z1 = openmc.ZPlane(z0=-5.0, boundary_type='vacuum')
        z2 = openmc.ZPlane(z0=5.0, boundary_type='vacuum')
        cell = openmc.Cell(name='cyl_cell', fill=mat, region=-cyl & +z1 & -z2)
        geom = openmc.Geometry([cell])

        cyl_mesh = openmc.CylindricalMesh(
            r_grid=[0.0, 1.0, 2.5, 5.0],
            phi_grid=[0.0, np.pi, 2*np.pi],
            z_grid=[-5.0, 0.0, 5.0],
            origin=(0.0, 0.0, 0.0)
        )
        mesh_f = openmc.MeshFilter(cyl_mesh)

        tally = openmc.Tally(name='cyl_flux_tally')
        tally.filters = [mesh_f]
        tally.scores = ['flux']
        tallies = openmc.Tallies([tally])

        settings = openmc.Settings()
        settings.particles = 100
        settings.batches = 5
        settings.inactive = 0
        settings.run_mode = 'fixed source'
        settings.source = openmc.IndependentSource(space=openmc.stats.Point((0, 0, 0)))

        model = openmc.Model(geometry=geom, materials=materials, settings=settings, tallies=tallies)
        sp_path = model.run(output=False)

        try:
            res = results.load('.')
            t_data = next((t for t in res["tallies"] if t["name"] == "cyl_flux_tally"), None)
            self.assertIsNotNone(t_data, "Cylindrical tally data should be extracted")
            self.assertEqual(t_data["kind"], "mesh")
            self.assertEqual(t_data["mesh_type"], "cylindrical")
            self.assertEqual(t_data["dims"], [3, 2, 2])
            self.assertEqual(len(t_data["r_grid"]), 4)
            self.assertEqual(len(t_data["phi_grid"]), 3)
            self.assertEqual(len(t_data["z_grid"]), 3)
            self.assertIn("flux", t_data["values"])
            self.assertEqual(len(t_data["values"]["flux"]), 3 * 2 * 2)
            # Ensure non-zero values were recorded
            self.assertTrue(any(v > 0 for v in t_data["values"]["flux"]))
        finally:
            for p in Path('.').glob('*.h5'):
                p.unlink(missing_ok=True)
            for p in Path('.').glob('*.xml'):
                p.unlink(missing_ok=True)

if __name__ == '__main__':
    unittest.main()
