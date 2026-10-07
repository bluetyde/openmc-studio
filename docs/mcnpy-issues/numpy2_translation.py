"""MCNPy and numpy 2: a translated FILL cell whose translation holds numpy floats makes MCNPy send the text np.float64(0.1) to Java.

Needs the MCNPy gateway (port 25333; claim it on a shared machine). Run twice:
    python numpy2_repro.py            # fails with a Java NumberFormatException on numpy >= 2
    python numpy2_repro.py legacy     # works: numpy 1.x style scalar printing
"""
import sys

import numpy as np
import openmc
from mcnpy.translate_mcnp_openmc import openmc_to_mcnp

if "legacy" in sys.argv:
    np.set_printoptions(legacy="1.25")

print("numpy", np.__version__)
m = openmc.Material(name="graphite")
m.set_density("g/cm3", 1.7)
m.add_element("C", 1.0)
big = openmc.Sphere(r=50.0)
inner = openmc.Universe(cells=[openmc.Cell(fill=m, region=-big)])
ball = openmc.Sphere(r=5.0, boundary_type="vacuum")
cell = openmc.Cell(fill=inner, region=-ball)
cell.translation = (0.25, -0.5, 0.125)  # OpenMC stores this as a numpy array of float64
print("translation type:", type(cell.translation), type(cell.translation[0]))
model = openmc.Model(openmc.Geometry([cell]), openmc.Materials([m]))
try:
    deck = openmc_to_mcnp(model.geometry, model.materials, model.settings)
    print("translated OK")
except Exception as exc:  # noqa: BLE001
    print("FAILED:", type(exc).__name__, str(exc)[:200])
