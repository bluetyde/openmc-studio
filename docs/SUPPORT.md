# What OpenMC Studio supports

One table per area: what the editor does, what model.py (OpenMC) gets, what the MCNP export does, whether the
round trips (edited model.py / model.mcnp back into Studio) take it back, and the tests that show it. Updated
2026-09-26 (Studio `cf2ad05`, exporter `bfa0d88`).

**Words used:** *yes* = implemented and covered by the named test; *refused* = Studio or the exporter stops with
a message rather than writing something wrong; *untested* = written, but no test checks it; *no* = not there.
MCNP decks are checked by the exporter's validator (MontePy parse, cards read back against the OpenMC model,
sampled geometry comparison). **No deck has been run in real MCNP yet**: the comparison bundle is prepared and
waiting (see the TODO). Plans for what's missing are in [TODO.md](../TODO.md).

Test names: `test/…` is this repository; `exporter tests/…` is
[openmc-mcnp-project](https://github.com/bluetyde/openmc-mcnp-project). `node test/run_all.cjs full` runs them all.

## Geometry

| Feature | Editor / viewport | OpenMC (model.py) | MCNP export | Round trip | Tests |
|---|---|---|---|---|---|
| Sphere, cylinder, box | yes | yes | yes | numbers: yes (a box's faces move together) | `test_frontend_model.js`, `test_generated_models.py`, `test_patch_import.js` |
| Wedge, hexagonal prism, cone, ellipsoid | yes | yes | yes (GQ / planes) | numbers the code tab marks | `test_ellipsoid_primitive.py`, `test_frontend_model.js` |
| Rotations (any angle) | yes | yes (general planes, quadrics) | yes (P / GQ) | untested | exporter `check_export_mcnp.py` (rotated), `test_frontend_model.js` |
| Groups, nested groups, pivots | yes | comments + `groups` dict | `c Group:` comments | n/a | `test_frontend_model.js` |
| Arrays as cells | yes | yes | yes | untested | `test_generated_models.py` (flat twins) |
| Arrays as RectLattice / HexLattice | yes | yes | yes (`LAT=1` / `LAT=2`, `FILL`) | untested | `test_generated_models.py`, `test_hex_lattice.py`, `test_mcnp_group_columns.py` |
| Imported CAD (STEP) as analytic CSG | yes, read-only | yes | yes | no (read-only) | `setup/cad/run_integration.cjs` (17 suites) |
| Imported CAD as a triangulated view | view only | no | no | no | `test_cad_import_browser.cjs` |
| Vacuum / reflective boundaries | yes | yes | yes | n/a | `test_generated_models.py` |
| Periodic / white boundaries | yes | yes | untested | n/a | `test_surface_and_periodic.py` (OpenMC only) |
| Overlap and lost-particle check | yes | uses `openmc -g` | n/a | n/a | `test_geometry_check.py` |

## Materials

| Feature | Editor | OpenMC | MCNP | Round trip | Tests |
|---|---|---|---|---|---|
| Elements / nuclides, weight or atom fractions, density | yes | yes | yes | numbers: yes | `test_patch_import.js`, `test_mcnp_patch_import.js` |
| PNNL compendium library | yes | yes | yes | n/a | `test_frontend_model.js` |
| S(α,β) thermal scattering | yes | yes | yes (`MT`) | n/a | `test_thermal_scattering.py` |
| Temperature | yes | yes | untested | n/a | `test_photon_and_temperature.py` |
| Models with no materials (all void) | yes | yes | yes | n/a | exporter `tests/test_void_model.py` |

## Sources

| Feature | Editor | OpenMC | MCNP | Round trip | Tests |
|---|---|---|---|---|---|
| Point, box, spherical shell, cylinder | yes | yes | yes (`SDEF`) | numbers: yes | exporter `check_export_mcnp.py` |
| Isotropic, monodirectional | yes | yes | yes | yes | exporter `check_export_mcnp.py` |
| Energy: lines, Watt, Maxwell, uniform, Muir | yes | yes | yes (`SP -2/-3/-4`, `L`, `H`) | line numbers: yes | exporter `check_export_mcnp.py` |
| Energy: tabulated (bin probabilities, as `SP D`) | yes (paste SI/SP) | yes, divided by bin width | yes, probabilities after a leading 0 | no | `test_review_deep.js` (sampled in OpenMC), exporter `tests/test_review_semantics.py` |
| Several sources, relative strengths | yes | yes, scaled to sum to 1 | yes (one `SDEF`, `ERG` picks the source) | numbers: yes | `test_dose_page.js`, exporter `check_export_mcnp.py` |
| Box sources mixed with sphere/cylinder sources | yes | yes | **refused** | n/a | exporter `check_export_mcnp.py` |
| Photon sources and transport | yes | yes | yes (`MODE N P`) | n/a | `test_photon_and_temperature.py` |
| Fission treated as capture (fixed source) | yes | yes | yes (`NONU`) | n/a | exporter `check_export_mcnp.py` |
| Eigenvalue runs, Shannon entropy | yes | yes | yes (`KCODE`/`KSRC`; entropy mesh not exported) | n/a | `test_keff_convergence.py`, exporter `check_export_mcnp.py` |

## Tallies

| Feature | Editor | OpenMC | MCNP | Round trip | Tests |
|---|---|---|---|---|---|
| Cell flux and reaction rates | yes | yes | yes (`F4`, `FM`) | numbers: yes | `test_generated_models.py`, exporter `check_export_mcnp.py` |
| Absorption in actinide materials | yes | yes | **refused** (MCNP's -2 excludes fission) | n/a | exporter `check_export_mcnp.py` |
| Parts inside lattices | yes | yes (`CellInstanceFilter`) | yes (chain bins) | n/a | `test_generated_models.py` (rect/hex tally) |
| Energy bins, including a lower edge above 0 | yes | yes | yes (`E`, extra 0-to-first-edge bin) | numbers: yes | `test_review_deep.js`, exporter `tests/test_review_semantics.py` |
| Detector responses (He-3, BF3, B-10, U-235, custom) | yes | yes (`EnergyFunctionFilter`) | yes (`FM`) | n/a | `test_detector_responses.py` |
| Material filter | yes | yes | **refused** by the exporter | n/a | `test_surface_and_periodic.py` (OpenMC only) |
| Surface current, neutron or photon | yes | yes | yes (`F1:N` / `F1:P`, `C`, `FS`) | n/a | `test_generated_models.py`, exporter `tests/test_review_semantics.py` |
| Regular (box) mesh, flux | yes, slice / slab / 3D volume view (Brightest, Surface, Glow) | yes | yes (`FMESH`; MCNP divides by voxel volume) | n/a | `test_mesh_maps.js`, `test_volume_view*.{js,cjs}` |
| Cylindrical mesh, flux | yes, slice and 3D volume view | yes | yes (`FMESH GEOM=CYL`) | n/a | `test_cylindrical_mesh.py`, `test_cylindrical_view.js` |
| Mesh reaction rates | yes | yes | **no** (flux only) | n/a | |
| Effective dose on cells (ICRP-116/-74) | yes | yes (+ volume calculation) | yes (`DE`/`DF`, `SD`, `FM`) | n/a | `test_dose_rates.py` (hand calculation), `test_dose_mcnp.py` |
| Dose on parts inside lattices | yes | yes (per-instance volumes) | yes | n/a | `test_dose_rates.py`, `test_dose_mcnp.py`, exporter `tests/test_dose_export.py` |
| Dose maps (box, cylindrical) | yes | yes | yes (`FMESH` + `DE`/`DF`, `FACTOR`) | n/a | `test_dose_rates.py` |
| Dose with a material filter, detector response or in eigenvalue | **refused** (Problems) | | | | `test_dose_page.js` |
| H*(10) ambient dose | no | | | | |
| `FT` special treatments, pulse height, `FS` segmenting | no | | | | |

## Files and results

| Feature | Status | Tests |
|---|---|---|
| Project file (`.openmc-studio.json`) | yes | `test_frontend_model.js` |
| model.py / model.mcnp carry the project (`@studio-project-v1`) | yes; a saved deck carries the project it was translated from | `test_embed_project.js` |
| Import edited model.py / model.mcnp (numbers Studio marked) | yes; anything else is listed, not applied | `test_patch_import.js`, `test_mcnp_patch_import.js`, `test_review_deep.js` |
| Import a model.py / MCNP deck Studio didn't write | **no** (refused with a message) | `test_patch_import.js` |
| OpenMC XML import | no | |
| Results: k-eff, tables, maps, tracks | yes | `test_results_overlay_browser.cjs`, `test_output_tabs_browser.cjs` |
| Export for ParaView (VTK maps, tracks, STL geometry) | yes | `test_vtk_export.py`, `test_paraview_export.js` |
| STL export of the geometry | yes | `test_stl_export.js` |
| STEP export | yes, primitives only (FreeCAD worker) | `setup/cad/run_integration.cjs` |
| OBJ export | no | |
| provenance.json in every run and MCNP export folder | yes | `test_provenance.py` |

## Platforms

The app (browser page + Python server) runs on Windows (server in WSL), Linux and macOS. CAD import needs the
pinned Linux x86-64 environment (WSL on Windows); native Windows CAD is unsupported and macOS/ARM CAD is not
validated. See [INSTRUCTIONS.md](../INSTRUCTIONS.md) and [setup/cad/README.md](../setup/cad/README.md).
