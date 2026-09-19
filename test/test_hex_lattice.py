import unittest
import tempfile
import numpy as np
import openmc
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "studio"))
from openmc_studio import results

class TestHexLattice(unittest.TestCase):
    def test_hex_lattice_simulation(self):
        mat_fuel = openmc.Material(name='fuel')
        mat_fuel.set_density('g/cm3', 10.0)
        mat_fuel.add_nuclide('U235', 1.0)

        mat_mod = openmc.Material(name='water')
        mat_mod.set_density('g/cm3', 1.0)
        mat_mod.add_nuclide('H1', 2.0)
        mat_mod.add_nuclide('O16', 1.0)
        materials = openmc.Materials([mat_fuel, mat_mod])

        cyl = openmc.ZCylinder(r=0.4)
        c_pin = openmc.Cell(name='fuel_pin', fill=mat_fuel, region=-cyl)
        c_cool = openmc.Cell(name='coolant', fill=mat_mod, region=+cyl)
        u_pin = openmc.Universe(name='u_pin', cells=[c_pin, c_cool])

        c_solid = openmc.Cell(name='solid_water', fill=mat_mod)
        u_solid = openmc.Universe(name='u_solid', cells=[c_solid])

        # 3-ring HexLattice (19 positions total: 12 outer, 6 middle, 1 center)
        lat = openmc.HexLattice(name='hex_assembly')
        lat.center = (0.0, 0.0)
        lat.pitch = (1.26,)
        lat.orientation = 'y'
        lat.outer = u_solid

        ring2 = [u_pin] * 12
        ring1 = [u_pin] * 6
        ring0 = [u_solid]  # Central guide tube / water hole
        lat.universes = [ring2, ring1, ring0]

        boundary_cyl = openmc.ZCylinder(r=5.0, boundary_type='vacuum')
        z_top = openmc.ZPlane(z0=10.0, boundary_type='vacuum')
        z_bot = openmc.ZPlane(z0=-10.0, boundary_type='vacuum')

        cell_lat = openmc.Cell(name='core', fill=lat, region=-boundary_cyl & +z_bot & -z_top)
        geom = openmc.Geometry([cell_lat])

        settings = openmc.Settings()
        settings.particles = 100
        settings.batches = 10
        settings.inactive = 2
        settings.run_mode = 'eigenvalue'
        settings.source = openmc.IndependentSource(space=openmc.stats.Point((1.26, 0.0, 0.0)))

        model = openmc.Model(geometry=geom, materials=materials, settings=settings)
        with tempfile.TemporaryDirectory(prefix='studio_test_') as run_dir:
            model.run(output=False, cwd=run_dir)
            res = results.load(run_dir)
            summary = res.get("summary")
            self.assertIsNotNone(summary, "Simulation summary should exist")
            self.assertIn("k_combined", summary)
            k_val = summary["k_combined"][0]
            self.assertGreater(k_val, 0.0)
            self.assertEqual(summary["batches"], 10)

if __name__ == '__main__':
    unittest.main()
