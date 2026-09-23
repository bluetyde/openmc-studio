# CAD conversion limits

CAD import is unavailable until an adapter can preserve solid geometry and
units. Installing GEOUNED alone does not enable it. Earlier versions replaced
solids with bounding boxes or interpreted untrimmed surfaces as complete
objects; these paths now return an error without changing the project.

The [stage-0 engine spike](../setup/cad/README.md) now performs real single-solid
FreeCAD/GEOUNED conversion and checks holes, units and placement on four fixtures.
It is a command-line development tool; it does not enable browser import.

STEP export requires FreeCAD and Part in the worker's Python environment.
Set `OPENMC_CAD_PYTHON` to that interpreter before starting Studio. Supported
primitives are boxes, spheres, cylinders and cones. Other shapes are rejected
before export; STL remains available for all seven Studio primitives.

STEP exports primitive solids, not the material cells after overlap subtraction.
It does not export materials, sources, tallies, world boundaries or group Boolean
operations. Use a Studio project or generated OpenMC input to preserve those.

Studio lengths are in centimeters. STEP export converts them to millimeters,
including positions, cylinder height and all radii. Cylinder axis and Euler
rotations follow the viewport's frame. The worker checks the STEP unit declaration
and reads the file back to compare bounds and volume before offering a download.
There is no browser STEP fallback: an unavailable or failing CAD worker produces
an error, not a replacement file.

`python test/test_cad_worker_protocol.py` checks rejection, unit conversion,
transforms and worker behavior. Its real FreeCAD test runs only in an interpreter
with FreeCAD and Part installed; an explicit skip is not an export validation.
