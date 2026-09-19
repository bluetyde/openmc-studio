"""Test coupled photon transport and material temperature execution in OpenMC."""
import os
import shutil
import tempfile
import openmc


def test_photon_and_temperature_simulation():
    tmpdir = tempfile.mkdtemp(prefix="openmc_test_photon_")
    try:
        # Define materials with temperature
        lead = openmc.Material(name="Lead")
        lead.set_density("g/cm3", 11.34)
        lead.add_element("Pb", 1.0)
        lead.temperature = 300.0

        water = openmc.Material(name="Water")
        water.set_density("g/cm3", 1.0)
        water.add_element("H", 2.0)
        water.add_element("O", 1.0)
        water.temperature = 350.0

        materials = openmc.Materials([lead, water])

        # Geometry
        s_inner = openmc.Sphere(r=10.0)
        s_outer = openmc.Sphere(r=20.0, boundary_type="vacuum")

        c_inner = openmc.Cell(name="Inner", fill=water, region=-s_inner)
        c_outer = openmc.Cell(name="Outer", fill=lead, region=+s_inner & -s_outer)
        geometry = openmc.Geometry([c_inner, c_outer])

        # Settings with coupled photon transport, cutoff, and temperature
        settings = openmc.Settings()
        settings.run_mode = "fixed source"
        settings.particles = 500
        settings.batches = 2
        settings.photon_transport = True
        settings.cutoff = {"energy_photon": 1000.0}
        settings.temperature = {"default": 293.6, "method": "interpolation"}

        # Source with photons
        src = openmc.IndependentSource()
        src.particle = "photon"
        src.space = openmc.stats.Point((0, 0, 0))
        src.energy = openmc.stats.Discrete([662000.0], [1.0])  # Cs-137 gamma (662 keV)
        settings.source = [src]

        # Tallies with ParticleFilter
        tally = openmc.Tally(name="Gamma flux")
        tally.filters = [openmc.CellFilter([c_inner, c_outer]), openmc.ParticleFilter(["photon"])]
        tally.scores = ["flux"]
        tallies = openmc.Tallies([tally])

        model = openmc.Model(geometry=geometry, materials=materials, settings=settings, tallies=tallies)
        sp_path = model.run(cwd=tmpdir)

        assert os.path.exists(sp_path), f"Statepoint file not created at {sp_path}"

        with openmc.StatePoint(sp_path) as sp:
            assert bool(sp.photon_transport) is True
            t_out = sp.get_tally(name="Gamma flux")
            mean = t_out.mean
            print(f"Photon simulation successful! Tally mean shape: {mean.shape}, flux: {mean.flatten()}")
            assert mean.shape[0] == 2, f"Expected 2 cells, got {mean.shape[0]}"
            assert (mean > 0).any(), "Expected non-zero gamma flux"

        print("PASSED test_photon_and_temperature_simulation")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    test_photon_and_temperature_simulation()
