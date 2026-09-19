"""Test eigenvalue k_eff batch convergence and Shannon entropy extraction."""
import os
import sys
import shutil
import tempfile
import openmc

# Add studio to sys.path so we can import results
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "studio")))
from openmc_studio import results


def test_keff_and_entropy_extraction():
    tmpdir = tempfile.mkdtemp(prefix="openmc_test_keff_")
    try:
        # Fissile fuel sphere (Godiva-like enriched Uranium)
        u235 = openmc.Material(name="HEU")
        u235.set_density("g/cm3", 18.74)
        u235.add_nuclide("U235", 0.93)
        u235.add_nuclide("U238", 0.07)
        materials = openmc.Materials([u235])

        sphere = openmc.Sphere(r=8.74, boundary_type="vacuum")
        cell = openmc.Cell(name="Core", fill=u235, region=-sphere)
        geometry = openmc.Geometry([cell])

        # Eigenvalue settings
        settings = openmc.Settings()
        settings.run_mode = "eigenvalue"
        settings.particles = 1000
        settings.batches = 5
        settings.inactive = 2
        settings.seed = 42

        # Initial source box
        settings.source = openmc.IndependentSource(space=openmc.stats.Box([-5, -5, -5], [5, 5, 5]))

        # Shannon entropy mesh
        entropy_mesh = openmc.RegularMesh(name="Shannon entropy mesh")
        entropy_mesh.dimension = [5, 5, 5]
        entropy_mesh.lower_left = [-9, -9, -9]
        entropy_mesh.upper_right = [9, 9, 9]
        settings.entropy_mesh = entropy_mesh

        model = openmc.Model(geometry=geometry, materials=materials, settings=settings)
        sp_path = model.run(cwd=tmpdir)
        assert os.path.exists(sp_path), f"Statepoint not found at {sp_path}"

        # Load with OpenMC Studio results loader
        res = results.load(tmpdir)
        summary = res["summary"]
        assert summary is not None, "Results summary is None"
        print("Extracted summary:", summary)

        assert summary["run_mode"] == "eigenvalue", f"Expected eigenvalue, got {summary['run_mode']}"
        assert summary["batches"] == 5, f"Expected 5 batches, got {summary['batches']}"
        assert summary["inactive"] == 2, f"Expected 2 inactive batches, got {summary['inactive']}"

        assert "k_generation" in summary, "k_generation missing from summary"
        assert len(summary["k_generation"]) == 5, f"Expected 5 k_generation values, got {len(summary['k_generation'])}"

        assert "entropy" in summary, "entropy missing from summary"
        assert len(summary["entropy"]) == 5, f"Expected 5 entropy values, got {len(summary['entropy'])}"

        assert "keff" in summary and summary["keff"] is not None, "keff missing from summary"
        print(f"Final k_eff = {summary['keff'][0]:.5f} +/- {summary['keff'][1]:.5f}")
        print(f"k_generation across batches: {summary['k_generation']}")
        print(f"Shannon entropy across batches: {summary['entropy']}")

        print("PASSED test_keff_and_entropy_extraction")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    test_keff_and_entropy_extraction()
