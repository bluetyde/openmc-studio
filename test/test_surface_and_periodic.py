"""Test surface current tally, material filter, and periodic boundary conditions."""
import os
import sys
import shutil
import tempfile
import openmc

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "studio")))
from openmc_studio import results


def test_surface_and_periodic():
    tmpdir = tempfile.mkdtemp(prefix="openmc_test_surf_")
    try:
        # Material
        water = openmc.Material(name="Water")
        water.set_density("g/cm3", 1.0)
        water.add_element("H", 2.0)
        water.add_element("O", 1.0)
        materials = openmc.Materials([water])

        # Periodic unit cell (-10 to +10 cm in x and y, vacuum in z)
        x_min = openmc.XPlane(-10.0, boundary_type="periodic")
        x_max = openmc.XPlane(10.0, boundary_type="periodic")
        x_min.periodic_surface = x_max

        y_min = openmc.YPlane(-10.0, boundary_type="periodic")
        y_max = openmc.YPlane(10.0, boundary_type="periodic")
        y_min.periodic_surface = y_max

        z_min = openmc.ZPlane(-10.0, boundary_type="vacuum")
        z_max = openmc.ZPlane(10.0, boundary_type="vacuum")

        # Dividing surface for surface current tally
        z_mid = openmc.ZPlane(0.0)

        c1 = openmc.Cell(name="Bottom", fill=water, region=+x_min & -x_max & +y_min & -y_max & +z_min & -z_mid)
        c2 = openmc.Cell(name="Top", fill=water, region=+x_min & -x_max & +y_min & -y_max & +z_mid & -z_max)
        geometry = openmc.Geometry([c1, c2])

        settings = openmc.Settings()
        settings.run_mode = "fixed source"
        settings.particles = 500
        settings.batches = 2

        # Source at -5 cm pointing +z
        src = openmc.IndependentSource()
        src.space = openmc.stats.Point((0, 0, -5))
        src.angle = openmc.stats.Monodirectional((0, 0, 1))
        src.energy = openmc.stats.Discrete([2.0e6], [1.0])
        settings.source = [src]

        # 1. Surface current tally across z_mid
        t_surf = openmc.Tally(name="Midplane current")
        t_surf.filters = [openmc.SurfaceFilter([z_mid])]
        t_surf.scores = ["current"]

        # 2. Material filter tally
        t_mat = openmc.Tally(name="Water absorption")
        t_mat.filters = [openmc.MaterialFilter([water])]
        t_mat.scores = ["absorption"]

        tallies = openmc.Tallies([t_surf, t_mat])

        model = openmc.Model(geometry=geometry, materials=materials, settings=settings, tallies=tallies)
        sp_path = model.run(cwd=tmpdir)
        assert os.path.exists(sp_path)

        res = results.load(tmpdir)
        tallies_res = res["tallies"]
        assert len(tallies_res) == 2, f"Expected 2 tallies, got {len(tallies_res)}"

        t1 = next(t for t in tallies_res if t["name"] == "Midplane current")
        assert "SurfaceFilter" in t1["filters"], f"Expected SurfaceFilter in {t1['filters']}"
        assert t1["rows"][0]["score"] == "current"
        assert t1["rows"][0]["mean"] > 0, "Expected positive net current across midplane"
        print(f"Surface current: {t1['rows'][0]['mean']:.5e} +/- {t1['rows'][0]['std']:.5e}")

        t2 = next(t for t in tallies_res if t["name"] == "Water absorption")
        assert "MaterialFilter" in t2["filters"], f"Expected MaterialFilter in {t2['filters']}"
        assert t2["rows"][0]["score"] == "absorption"
        assert t2["rows"][0]["mean"] > 0, "Expected positive absorption in water"
        print(f"Material absorption: {t2['rows'][0]['mean']:.5e} +/- {t2['rows'][0]['std']:.5e}")

        print("PASSED test_surface_and_periodic")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    test_surface_and_periodic()
