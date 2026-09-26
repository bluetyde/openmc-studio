# Plan: VTK export for ParaView

> **Status (2026-09-25):** done (`studio/openmc_studio/vtk_export.py`, `test/test_vtk_export.py`).

Task H. Studio branch `claude/vtk`. Written 2026-09-25.

Goal: one button saves a finished run's flux maps, particle tracks and geometry as files ParaView (or VisIt)
opens directly, so a professor or colleague can look at the results in a standard tool.

## What we have (checked 2026-09-25)

- OpenMC's `RegularMesh.write_data_to_vtk()` and `Tracks.write_to_vtk()` need the `vtk` Python package, and
  the `openmc-mcnp` environment doesn't have it. Adding `vtk` (a large conda package) to everyone's environment
  for a file writer isn't worth it.
- The legacy VTK file format is plain and documented: a header, the grid, then named arrays. Writing it
  ourselves is about a hundred lines of Python with no new dependency, and every ParaView version reads it.
- Studio already exports geometry as STL (`Export STL…`, tested by `test/test_stl_export.js`); ParaView reads
  STL.
- Each run folder already has the statepoint and, when asked for, `tracks.h5`; `results.py` reads both.

## What the export contains

A zip (or a folder beside the run) named after the run:

- `<tally>.vtk` for each regular mesh tally: `STRUCTURED_POINTS` (origin, voxel size, dimensions),
  `CELL_DATA` arrays per score: `<score>_mean`, `<score>_rel_err`, `<score>_std_dev`; per energy bin when the
  tally has energy bins (`flux_mean_E0`, …). Values per source particle, and per cm³ (divided by the voxel
  volume, like OpenMC's own writer does by default). Dose maps (see the dose plan) export in their own units.
- `<tally>.vtk` for each cylindrical mesh tally: `STRUCTURED_GRID` with the (r, phi, z) points turned into
  x, y, z, so it looks right in ParaView.
- `tracks.vtk` when the run wrote tracks: `POLYDATA` with one polyline per particle and point data `energy_eV`,
  `particle` (neutron/photon) and `track_id`, so ParaView can colour by energy like Studio does.
- `geometry_<material>.stl`, one per material, from the existing STL export, so ParaView colours by material.
  Imported CAD components export their display meshes.
- `README.txt`: what each file is, the units, and four steps to open it in ParaView (open all, Apply, colour
  by `flux_mean`, log scale).

## Where it lives

- Server: `POST /api/runs/<id>/export-vtk` writes the files into `<run>/vtk/` with a new module
  `studio/openmc_studio/vtk_export.py` (reads the statepoint and tracks.h5 with OpenMC, writes legacy VTK),
  and returns the zip for download. The STL files come from the page, which already builds them.
- Page: an "Export for ParaView…" button in the Results tab and in the Export ribbon (next to STL), enabled
  once a run has results.

## Tests

- **Round trip without our own reader**: write a known 3D array (a different value in every voxel, with
  energy bins), then read the file back with VTK's own reader from the `openmc-cad` environment, which has
  VTK 9.7. Dimensions, origin, spacing, array names and every value must match. Same for tracks (points,
  line connectivity, energies) and a cylindrical mesh (point positions).
- **Against OpenMC's writer**: where `vtk` is available (the CAD environment), compare our structured-points
  file with `write_data_to_vtk` for the same mesh: same values.
- The `flux_3d` fixture: export after a real run; the voxel with the highest flux in the VTK file is the
  source's voxel (same check as `test_generated_models.py`).
- Browser: the button is disabled with no results, and a finished run downloads a zip with the expected
  names.

## Risks

- Voxel ordering: OpenMC's mesh index runs x fastest, which is also VTK's order; the round-trip test with
  a distinct value per voxel catches any transposition.
- Large maps: a 1M-voxel map is ~8 MB per array in ASCII; write binary (big-endian, as legacy VTK requires).
- Units: say "per source particle" in the README and the array names, so nobody reads the numbers as absolute.

## Size

Small: one session including tests.
