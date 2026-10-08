"""A real pin-resolved mesh tally read as a pin map: does the table put the hot pin where it is, with the power it has?

A 4 x 4 lattice of UO2 pins in water, one pin at lattice position (ix 3, iy 1) enriched to 5 percent among 3 percent ones, reflective box. Two tallies:
a 4 x 4 x 1 mesh tally of kappa-fission, one mesh cell to a pin, and a material-filter tally of the same score for the hot pin's own material.
Checks: results._tally gives the mesh payload, pin_power_view.analyse peaks at (3, 1), the pin's centre is where the geometry put it, and the hot
pin's mesh value equals the material tally of its own material (the only place that material is). Real OpenMC; about a minute.

    OMP_NUM_THREADS=4 python test/manual_pin_power.py        (WSL, with OpenMC and nuclear data)
"""
import math
from pathlib import Path
import shutil
import sys
import tempfile

import openmc

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "studio"))
from openmc_studio import pin_power_view, results  # noqa: E402

PITCH, R_FUEL, N = 1.26, 0.4096, 4
HOT = (3, 1)


def uo2(name, enrich, mid):
    m = openmc.Material(name=name, material_id=mid)
    m.add_nuclide("U235", enrich / 100.0)  # atom fractions: only the contrast between the pins matters here
    m.add_nuclide("U238", 1 - enrich / 100.0)
    m.add_element("O", 2.0)
    m.set_density("g/cm3", 10.4)
    return m


work = Path(tempfile.mkdtemp(prefix="pin-power-"))
fuel, hot, water = uo2("fuel 3%", 3.0, 1), uo2("hot 5%", 5.0, 2), openmc.Material(name="water", material_id=3)
water.add_element("H", 2.0); water.add_element("O", 1.0); water.set_density("g/cm3", 0.74); water.add_s_alpha_beta("c_H_in_H2O")


def pin_universe(mat, uid):
    cyl = openmc.ZCylinder(r=R_FUEL)
    return openmc.Universe(universe_id=uid, cells=[openmc.Cell(fill=mat, region=-cyl), openmc.Cell(fill=water, region=+cyl)])


u_fuel, u_hot = pin_universe(fuel, 10), pin_universe(hot, 11)
lat = openmc.RectLattice()
lat.lower_left = (0.0, 0.0)
lat.pitch = (PITCH, PITCH)
rows = [[u_fuel] * N for _ in range(N)]
rows[N - 1 - HOT[1]][HOT[0]] = u_hot  # RectLattice.universes is listed top row (largest y) first
lat.universes = rows
size = N * PITCH
box = [openmc.XPlane(0.0, boundary_type="reflective"), openmc.XPlane(size, boundary_type="reflective"),
       openmc.YPlane(0.0, boundary_type="reflective"), openmc.YPlane(size, boundary_type="reflective"),
       openmc.ZPlane(-1.0, boundary_type="reflective"), openmc.ZPlane(1.0, boundary_type="reflective")]
cell = openmc.Cell(fill=lat, region=+box[0] & -box[1] & +box[2] & -box[3] & +box[4] & -box[5])
msh = openmc.RegularMesh()
msh.dimension = (N, N, 1)
msh.lower_left = (0.0, 0.0, -1.0)
msh.upper_right = (size, size, 1.0)
t_mesh = openmc.Tally(name="Pin power"); t_mesh.filters = [openmc.MeshFilter(msh)]; t_mesh.scores = ["kappa-fission"]
t_mat = openmc.Tally(name="hot material"); t_mat.filters = [openmc.MaterialFilter([hot])]; t_mat.scores = ["kappa-fission"]
st = openmc.Settings(); st.particles = 4000; st.batches = 40; st.inactive = 10; st.seed = 3
st.source = openmc.IndependentSource(space=openmc.stats.Box((0, 0, -1), (size, size, 1)))
model = openmc.Model(openmc.Geometry([cell]), openmc.Materials([fuel, hot, water]), st, openmc.Tallies([t_mesh, t_mat]))
sp_path = model.run(cwd=str(work), output=False)

with openmc.StatePoint(str(sp_path)) as sp:
    payload = results._tally(sp.get_tally(name="Pin power"), {}, {}, openmc)
    hot_tally = float(sp.get_tally(name="hot material").mean.ravel()[0])
a = pin_power_view.analyse(payload)
checks = []


def check(name, ok, detail):
    checks.append(ok)
    print(("PASS " if ok else "FAIL ") + name + ": " + detail)


peak = a["peak"]
check("the peak is the enriched pin", (peak["ix"], peak["iy"]) == HOT, f"peak at ({peak['ix']}, {peak['iy']}), relative power {peak['relative_power']:.3f}")
row = a["rows"][HOT[0] + N * HOT[1]]
check("its centre is where the geometry put it", math.isclose(row["x_cm"], (HOT[0] + 0.5) * PITCH) and math.isclose(row["y_cm"], (HOT[1] + 0.5) * PITCH), f"({row['x_cm']:.3f}, {row['y_cm']:.3f}) cm")
check("its mesh value is the tally of its own material", math.isclose(row["value"], hot_tally, rel_tol=1e-9), f"{row['value']:.6e} against {hot_tally:.6e}")
others = [r["relative_power"] for r in a["rows"] if (r["ix"], r["iy"]) != HOT]
check("the 3 percent pins sit below the mean and the 5 percent pin above it", max(others) < peak["relative_power"] and peak["relative_power"] > 1.0 > min(others),
      f"others {min(others):.3f} to {max(others):.3f}")
check("the layout is not symmetric, and the view says so", not a["symmetry"]["within_noise"], f"max z {a['symmetry']['max_z']:.1f}")
check("the mean of the relative powers is 1", math.isclose(sum(others) + peak["relative_power"], N * N, rel_tol=1e-9), f"sum {sum(others) + peak['relative_power']:.6f}")
shutil.rmtree(work, ignore_errors=True)
sys.exit(0 if all(checks) else 1)
