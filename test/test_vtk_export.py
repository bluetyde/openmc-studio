"""VTK export for ParaView (studio/openmc_studio/vtk_export.py), checked with VTK's own reader.

1. A small OpenMC model runs here: a water box with an off-centre source, a 6 x 5 x 4 regular mesh tally
   with two energy bins, a 3 x 4 x 2 cylindrical mesh tally, and particle tracks.
2. export_run() writes the VTK files.
3. The expected value of every voxel is looked up independently with Tally.get_values() by mesh index
   (not by reshaping arrays, which is the part most likely to be wrong).
4. A second Python that has the `vtk` package (OPENMC_CAD_PYTHON, the pinned CAD env) reads the files with
   vtkStructuredPointsReader / vtkStructuredGridReader / vtkPolyDataReader and compares: dimensions, origin,
   spacing, point positions, every array value, track points and energies.

Needs OpenMC with nuclear data (OPENMC_CROSS_SECTIONS) and OPENMC_CAD_PYTHON. Fails, never skips, without them.
Run: python test/test_vtk_export.py
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import openmc

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "studio"))
from openmc_studio import vtk_export  # noqa: E402

READER = r'''
import json, sys
import numpy as np
from vtkmodules.vtkIOLegacy import vtkStructuredPointsReader, vtkStructuredGridReader, vtkPolyDataReader
from vtkmodules.util.numpy_support import vtk_to_numpy
out = {}
d = sys.argv[1]
def arrays(data):
    cd = data.GetCellData() if data.GetCellData().GetNumberOfArrays() else data.GetPointData()
    return {cd.GetArrayName(i): vtk_to_numpy(cd.GetArray(i)).tolist() for i in range(cd.GetNumberOfArrays())}
r = vtkStructuredPointsReader(); r.SetFileName(d + "/rect.vtk"); r.ReadAllScalarsOn(); r.Update(); g = r.GetOutput()
out["rect"] = {"dims": list(g.GetDimensions()), "origin": list(g.GetOrigin()), "spacing": list(g.GetSpacing()),
               "arrays": arrays(g)}
r = vtkStructuredGridReader(); r.SetFileName(d + "/cyl.vtk"); r.ReadAllScalarsOn(); r.Update(); g = r.GetOutput()
e = g.GetExtent()
out["cyl"] = {"dims": [e[1] - e[0] + 1, e[3] - e[2] + 1, e[5] - e[4] + 1], "points": vtk_to_numpy(g.GetPoints().GetData()).tolist(), "arrays": arrays(g)}
r = vtkPolyDataReader(); r.SetFileName(d + "/tracks.vtk"); r.ReadAllScalarsOn(); r.Update(); g = r.GetOutput()
lines = g.GetLines(); ids = []
lines.InitTraversal()
from vtkmodules.vtkCommonCore import vtkIdList
l = vtkIdList()
while lines.GetNextCell(l):
    ids.append([l.GetId(i) for i in range(l.GetNumberOfIds())])
out["tracks"] = {"points": vtk_to_numpy(g.GetPoints().GetData()).tolist(), "lines": ids,
                 "arrays": {g.GetPointData().GetArrayName(i): vtk_to_numpy(g.GetPointData().GetArray(i)).tolist()
                            for i in range(g.GetPointData().GetNumberOfArrays())}}
print(json.dumps(out))
'''


def build_and_run(work):
    openmc.reset_auto_ids()
    water = openmc.Material(name="water")
    water.add_element("H", 2)
    water.add_element("O", 1)
    water.set_density("g/cm3", 1.0)
    box = openmc.model.RectangularParallelepiped(-15, 15, -15, 15, -15, 15, boundary_type="vacuum")
    geometry = openmc.Geometry([openmc.Cell(fill=water, region=-box)])
    s = openmc.Settings()
    s.run_mode, s.batches, s.particles, s.seed = "fixed source", 2, 800, 11
    s.source = openmc.IndependentSource(space=openmc.stats.Point((4, -3, 2)), energy=openmc.stats.Discrete([2e6], [1]))
    s.max_tracks = 5
    rect = openmc.RegularMesh(name="rect")
    rect.dimension, rect.lower_left, rect.upper_right = (6, 5, 4), (-15, -12.5, -10), (15, 12.5, 10)
    cyl = openmc.CylindricalMesh(r_grid=[0, 3, 7, 12], phi_grid=np.linspace(0, 2 * np.pi, 5), z_grid=[-8, 0, 8],
                                 origin=(1, 0, 0), name="cyl")
    t1 = openmc.Tally(name="rect")
    t1.filters = [openmc.EnergyFilter([0, 1.0, 2e7]), openmc.MeshFilter(rect)]  # energy BEFORE mesh on purpose
    t1.scores = ["flux"]
    t2 = openmc.Tally(name="cyl")
    t2.filters = [openmc.MeshFilter(cyl)]
    t2.scores = ["flux", "absorption"]
    model = openmc.Model(geometry, openmc.Materials([water]), s, openmc.Tallies([t1, t2]))
    cwd = os.getcwd()
    try:
        os.chdir(work)
        model.run(output=False, tracks=True)
    finally:
        os.chdir(cwd)


def expected(work):
    """Per-voxel expectations by mesh index, independent of the exporter's reshaping."""
    sp = openmc.StatePoint(sorted(Path(work).glob("statepoint.*.h5"))[-1])
    t1, t2 = sp.get_tally(name="rect"), sp.get_tally(name="cyl")
    mf1 = t1.find_filter(openmc.MeshFilter)
    ef = t1.find_filter(openmc.EnergyFilter)
    nx, ny, nz = mf1.mesh.dimension
    vol = np.prod((np.array(mf1.mesh.upper_right) - mf1.mesh.lower_left) / mf1.mesh.dimension)
    rect = {"flux_mean_E0": [], "flux_mean_E1": [], "flux_mean": [], "flux_std_dev": []}
    for k in range(nz):
        for j in range(ny):
            for i in range(nx):  # VTK cell order: x fastest
                vals = [float(t1.get_values(scores=["flux"], filters=[openmc.EnergyFilter, openmc.MeshFilter],
                                            filter_bins=[(tuple(ef.bins[e]),), ((i + 1, j + 1, k + 1),)]).ravel()[0])
                        for e in range(2)]
                sd = [float(t1.get_values(scores=["flux"], filters=[openmc.EnergyFilter, openmc.MeshFilter],
                                          filter_bins=[(tuple(ef.bins[e]),), ((i + 1, j + 1, k + 1),)],
                                          value="std_dev").ravel()[0]) for e in range(2)]
                rect["flux_mean_E0"].append(vals[0] / vol)
                rect["flux_mean_E1"].append(vals[1] / vol)
                rect["flux_mean"].append(sum(vals) / vol)
                rect["flux_std_dev"].append(float(np.sqrt(sd[0] ** 2 + sd[1] ** 2)) / vol)
    m2 = t2.find_filter(openmc.MeshFilter).mesh
    r, phi, z = np.array(m2.r_grid), np.array(m2.phi_grid), np.array(m2.z_grid)
    cyl = {"absorption_mean": []}
    for k in range(len(z) - 1):
        for j in range(len(phi) - 1):
            for i in range(len(r) - 1):
                v = 0.5 * (r[i + 1] ** 2 - r[i] ** 2) * (phi[j + 1] - phi[j]) * (z[k + 1] - z[k])
                a = float(t2.get_values(scores=["absorption"], filters=[openmc.MeshFilter],
                                        filter_bins=[((i + 1, j + 1, k + 1),)]).ravel()[0])
                cyl["absorption_mean"].append(a / v)
    tracks = openmc.Tracks(str(Path(work) / "tracks.h5"))
    first = next(pt for tr in tracks for pt in tr.particle_tracks if len(pt.states) >= 2)
    n_lines = sum(1 for tr in tracks for pt in tr.particle_tracks if len(pt.states) >= 2)
    return {"rect": rect, "cyl": cyl, "origin": list(mf1.mesh.lower_left), "dims": [nx, ny, nz],
            "cyl_first_points": [[1 + r[0] * np.cos(phi[0]), 0 + r[0] * np.sin(phi[0]), z[0]],
                                 [1 + r[1] * np.cos(phi[0]), r[1] * np.sin(phi[0]), z[0]],
                                 [1 + r[0], 0, z[0]]],
            "cyl_point_after_r": [1 + r[0] * np.cos(phi[1]), r[0] * np.sin(phi[1]), z[0]],
            "cyl_point_row1": [1 + r[1] * np.cos(phi[1]), r[1] * np.sin(phi[1]), z[0]],
            "track0": {"x": first.states["r"]["x"].tolist(), "E": first.states["E"].tolist()}, "n_lines": n_lines}


class VtkExport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cad = os.environ.get("OPENMC_CAD_PYTHON")
        if not cad:
            raise RuntimeError("OPENMC_CAD_PYTHON must name a Python with the vtk package; this test never skips")
        cls.work = tempfile.mkdtemp(prefix="studio-vtk-")
        build_and_run(cls.work)
        cls.manifest = vtk_export.export_run(cls.work, Path(cls.work) / "vtk", stl={"geometry_Water.stl": b"solid x\nendsolid x\n"})
        cls.exp = expected(cls.work)
        reader = Path(cls.work) / "read_vtk.py"
        reader.write_text(READER)
        r = subprocess.run([cad, str(reader), str(Path(cls.work) / "vtk")], capture_output=True, text=True, timeout=300)
        if r.returncode:
            raise RuntimeError("VTK reader failed:\n" + r.stdout[-2000:] + r.stderr[-3000:])
        cls.got = json.loads(r.stdout.strip().splitlines()[-1])

    def test_manifest_and_readme(self):
        names = [f["file"] for f in self.manifest["files"]]
        self.assertEqual(names, ["rect.vtk", "cyl.vtk", "tracks.vtk", "geometry_Water.stl"])
        readme = (Path(self.work) / "vtk" / "README.txt").read_text()
        self.assertIn("per source particle, per cm^3", readme)
        self.assertIn("rect.vtk (mesh tally \"rect\", 120 voxels)", readme)

    def test_regular_mesh_grid(self):
        g = self.got["rect"]
        self.assertEqual(g["dims"], [7, 6, 5])  # points = cells + 1
        np.testing.assert_allclose(g["origin"], self.exp["origin"])
        np.testing.assert_allclose(g["spacing"], [5, 5, 5])

    def test_regular_mesh_values_every_voxel(self):
        g = self.got["rect"]["arrays"]
        for name, want in self.exp["rect"].items():
            with self.subTest(name):
                np.testing.assert_allclose(g[name], want, rtol=1e-12, atol=0)
        self.assertGreater(np.count_nonzero(g["flux_mean"]), 60, "the map is not all zeros")
        # the peak is in the source's voxel: (4, -3, 2) is voxel (3, 1, 2)
        self.assertEqual(int(np.argmax(g["flux_mean"])), 3 + 6 * (1 + 5 * 2))
        rel = np.array(g["flux_rel_err"]); m = np.array(g["flux_mean"]); s = np.array(g["flux_std_dev"])
        np.testing.assert_allclose(rel[m > 0], s[m > 0] / m[m > 0], rtol=1e-12)

    def test_cylindrical_mesh(self):
        g = self.got["cyl"]
        self.assertEqual(g["dims"], [4, 5, 3])
        pts = np.array(g["points"])
        np.testing.assert_allclose(pts[1], self.exp["cyl_first_points"][1], atol=1e-12)      # r fastest
        np.testing.assert_allclose(pts[4], self.exp["cyl_point_after_r"], atol=1e-12)        # then phi
        np.testing.assert_allclose(pts[5], self.exp["cyl_point_row1"], atol=1e-12)
        np.testing.assert_allclose(g["arrays"]["absorption_mean"], self.exp["cyl"]["absorption_mean"], rtol=1e-12)
        self.assertIn("flux_mean", g["arrays"])

    def test_tracks(self):
        g = self.got["tracks"]
        self.assertEqual(len(g["lines"]), self.exp["n_lines"])
        pts = np.array(g["points"])
        first = g["lines"][0]
        np.testing.assert_allclose(pts[first, 0], self.exp["track0"]["x"])
        np.testing.assert_allclose(np.array(g["arrays"]["energy_eV"])[first], self.exp["track0"]["E"])
        self.assertEqual(set(g["arrays"]["particle"]), {0})  # neutrons only in this run


if __name__ == "__main__":
    unittest.main(verbosity=2)
