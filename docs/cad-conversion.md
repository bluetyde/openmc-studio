# CAD conversion limits

STEP files can be imported as **native parts** (boxes, spheres, capped cylinders
and cones) when every solid is proven to match; see below. General analytical CSG
import (holes, shells, other solids) is a later stage. Earlier versions replaced
solids with bounding boxes or interpreted untrimmed surfaces as complete objects;
those paths are gone and never come back as fallbacks.

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

## Conversion jobs (stage 1)

Conversions run as background jobs so an HTTP request never waits minutes for a
CAD engine. This is infrastructure only: a finished job does **not** import
anything into a project (`can_import_into_studio` is always `false` until the
import stages land). Linux/WSL only.

| Route | Purpose |
|---|---|
| `GET /api/cad/capabilities` | Whether jobs can run here, which modes exist, and whether the engine is *verified* |
| `POST /api/cad/jobs` | `{"mode": "csg-xml", "filename": "part.step", "data": "<base64>"}` or `{"mode": "probe"}`; returns **202** and a `Location` |
| `GET /api/cad/jobs` | Jobs in this session |
| `GET /api/cad/jobs/<id>` | State (`queued`, `running`, `cancelling`, `succeeded`, `failed`, `cancelled`, `timed_out`), progress, error and a short log tail |
| `GET /api/cad/jobs/<id>/result` | The conversion report and OpenMC XML; **409** until the job has succeeded |
| `DELETE /api/cad/jobs/<id>` | Cancel; the worker's whole process group is killed and its scratch deleted |

All routes need the Studio token; POST and DELETE also refuse foreign origins.

**`engine_verified` means a conversion actually ran.** It becomes true only after
a `probe` job builds a drilled block in FreeCAD, converts it with GEOUNED and
finds the hole where it should be. Importable Python modules alone never count.

What a job guarantees:

- One worker at a time, each in its own process group; cancelling or timing out
  kills every descendant, and a crash never affects the next job.
- Inputs are written once, read-only, to a server-generated directory outside
  the checkout (`<runs>/cad-jobs/<id>`). The uploaded filename is kept only as a
  label and never becomes a path.
- Progress and results must name the job they belong to; anything else fails the
  job. A result written after cancellation is discarded.
- Limits: 16 MiB input, 180 s per job, 2 MiB log, 64 MiB of scratch, 128 KiB
  report, 8 MiB XML, 8 queued jobs. Exceeding one fails the job with that reason.
- Finished jobs are kept for an hour, then deleted with their files.
- If the runs folder is inside the checkout, CAD jobs switch off with a reason;
  Studio itself keeps running.

Set `OPENMC_CAD_PYTHON` to the pinned CAD interpreter (see
[setup](../setup/cad/README.md)) before starting Studio.

Tests: `test/test_cad_jobs.py` and `test/test_cad_jobs_http.py` need no CAD engine;
`test/test_cad_jobs_engine.py` runs real conversions and fails, rather than
skips, when `OPENMC_CAD_PYTHON` is not set.

## Importing STEP as native parts (stage 2)

**Convert > Import CAD…** in the local app. The dialog walks through the plan's
workflow; the project doesn't change until the last step.

1. **Engine check.** If the CAD engine hasn't been verified this session, a probe
   job converts a small drilled block first. No probe, no import.
2. **Inspect.** Every solid in the file is listed by its source path, with its
   surfaces and anything that makes it unusable (an open face, an invalid solid).
3. **Import as.** Native parts now. Analytical CSG components are shown but not
   offered until the CSG data model lands.
4. **Preview.** Each solid is *accepted* (with its part), *rejected* (with the
   reason) or *failed* (with the error). Overlapping solids are called out.
5. **Import.** One undoable step. If anything was rejected you must tick the box
   that accepts importing the rest; the omitted solids and their reasons are
   stored with the project and listed in Problems.

**What "accepted" means.** The solid was recognized from its surfaces *and* the
Studio part was rebuilt the way Studio will model it and compared with the
source: bounds, symmetric-difference volume, boundary-to-boundary distance and a
deterministic set of inside/outside probes, within tolerances recorded per solid
(1e-7 of the part's size, never looser than 1e-6 mm). Rejected examples: a 0.01 mm
chamfer, a fillet, a drilled box, a hollow cylinder, a TRISO coating shell, a
0.5 degree parallelepiped, a cylinder with a 1 degree sheared cap, an elliptic
cylinder, a torus, B-spline surfaces. This is sampled evidence within stated
tolerances, not a proof of exact equality.

**Units.** FreeCAD's reader converts whatever the file declares (mm, cm, m, inch)
to millimetres; Studio divides by ten, once. Files written by an independent
non-OpenCASCADE writer are part of the tests for exactly this.

**Materials.** CAD files carry none. Imported parts are stored as Void and marked
*needs material*; Problems reports each one as an error, which blocks runs and
exports, until you pick a material (select the import's group to set them all at
once) or press *Keep as Void* to say the part really is empty space.

**Names and identity.** Parts get fresh Studio IDs every time, so importing a file
twice never collides. Each part remembers its source path (`cadSource`), and the
project keeps an import record (`imports`): file name, SHA-256, adapter version,
accepted and omitted solids. The saved project needs neither the CAD file nor
FreeCAD to reopen.

Tests: `test/test_cad_native_engine.py` (real engine, fails without it),
`test/test_cad_import_browser.cjs` (browser workflow on real engine reports) and
`test/test_cad_import_e2e.cjs` (real browser, server and engine; see its header
for the environment variables).
