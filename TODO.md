# TODO

What's next for OpenMC Studio, roughly in priority order. Updated 2026-10-07.

**What works today, what is refused and what is planned is in [docs/SUPPORT.md](docs/SUPPORT.md)**, one table
per area with the test behind each entry; start there. This file is the working backlog: open items first,
then the packages, then **Completed** and dated "done" notes, which are history (a later change may have
replaced what they describe; SUPPORT.md is current). Design plans are in [docs/design/](docs/design/).
Run every test with `node test/run_all.cjs [quick|browser|physics|full]` (summary in `test/results/`).

**Packages.** Sections 2 to 5 and the new Nodal and TRISO sections below are *packages*: optional add-ons for users who need them, not part of
the core app (a simple TRIGA or shielding user never sees them). SEED will install them one by one (its plan 11, "Optional add-ons"; manifest
format `seed.component-manifest/0.1`, `docs/runtime-contract.md` in the SEED repo). **On the dev machine every package is installed for now**;
how they are split and installed is decided later, so build features so that a missing package turns off its own tab with a message naming
the package, and nothing else.

## Open items carried over

- **Next up (2026-10-07), in order:**
  1. **Prove the MCNP export in real MCNP**: run the user's MCNP bundle (lattices, lattice tallies, surface
     currents, dose) and compare with OpenMC; waiting on the user's runs. Nothing so far has been checked against an actual MCNP run.
  2. **Small wins from the 2026-10-07 investigation** (private notes kept outside the repo, in the user's plans folder),
     each a day or less: a **figure-of-merit column** on tally tables (1/(R^2 T)); **result-page checks** (section 0 below); a **re-run command**
     over `provenance.json`; a **model-stages guide**; a **Godiva regression case** from `mit-crpg/benchmarks`.
  3. **H\*(10)**: transcribe and check the conversion table (sources found: PNNL-19273; IAEA/Griffith, OSTI XA0053408). The code
     is small (the effective-dose path exists); the work is the sourced, checked table. **Hexagonal lattices in imported decks**
     (`LAT=2`, refused at `mcnp_import.py:207`; the adapter can't read them): Studio's own step, needs MCNP's hex index order, pitch and
     orientation turned into an `openmc.HexLattice`, a fixture and a byte-for-byte check against OpenMC; about 1 to 2 days.
  4. **Nodal core package, P2** (reflector-aware factors; [plan](docs/design/nodal-package-plan.md)); the BEAVRS lesson in RAFT is its first user.
  5. **Shared pre-run check: done (2026-10-07)**: `prerun_check.py` holds the page's errors in Python; `/api/run` refuses a project with errors (422, before any run folder exists) and the headless runner adds them after its own capability checks. Held equal to the page by 73 golden cases (`test/fixtures/prerun/cases.json`, `test_prerun_check_page.js`, `test_prerun_check.py`). **Not covered yet** (page and geometry check only): the rules for imported CAD components and the surface tally of a part inside a lattice; a script that posts no project is not checked.
  6. **Graphs**: lethargy spectrum and 1D line cuts with +/-1 sigma bands (see the backlog below).
  7. **Future: a diff-based export** so that CAD and part edits rebuild only what changed
     ([plan](docs/design/mcnp-diff-export-plan.md); phases 0 to 6, about 6 days to phase 4); hard because one edit (a material, a cell) touches
     several cards that refer to each other, and because of universes and lattices. Stop after phase 3 if edits then take about 1 s.
  **Done, for the record: slow model.mcnp for big imports** ([plan](docs/design/mcnp-import-speed-plan.md)). The 267-cell
  lattice test deck took 23.5 min to export (MCNPy translate 407 s, validate 973 s). Now translate is about 14 s and validate 30 s, all in
  the exporter, byte-identical decks: validate uses `openmc.lib` (`410d9d9`), the world cell is written as `#cell`
  complements (`c765b21`), plain cells' regions are written directly (`f7f78c2`), and MCNPy's own round trips are cut
  (`776bc09`: `fast_add`, `cached_reflection`, a `line_wrap` that cannot loop; deck identical on and off in
  `tests/test_mcnpy_speed_identity.py`). The live model.mcnp tab shows the deck as soon as it is translated and checks it against OpenMC in a
  separate process (H in the plan, merged 2026-10-07: `mcnp_validate.py`, `server.Validator`; a newer deck stops the older check; the Export
  button still validates before it writes).
- **MCNPy issues to report upstream** (found 2026-10-06; nothing sent; details, numbers and runnable examples in
  [docs/mcnpy-issues/](docs/mcnpy-issues/README.md)). MCNPy 0.0.7 is RPI NuCoMP's (MIT, Peter J. Kowal); it is
  **not** on PyPI or public GitHub (source: `github.rpi.edu/NuCoMP/mcnpy`, RPI's GitHub Enterprise server; readable without a login, but
  opening an issue may need an RPI account, so ask the user how they want to reach the authors). Do not confuse it with `sandialabs/mcnpy` or PyPI `mcnpy`, two unrelated projects with the same name.
  Draft the report from the README and send it only when the user says so.
  Running the Java-backed examples (everything except `line_wrap_hang.py`) uses the machine-wide MCNPy port 25333, so post
  `CLAIM: MCNPy` in `messages/openmc.md` first (see `messages/INSTRUCTIONS.md`); the `line_wrap` repro needs no claim.
  Our workarounds are in the exporter: `world_complement.py` (merged, `c765b21`) and `cell_regions.py` (branch
  `claude/direct-cell-cards`; check whether it has merged before relying on it).
  1. **`line_wrap` hangs on a token with no blank longer than the line limit** (a union of 22 terms; 18 is fine). The 128-column
     wrap itself is intended. Standalone, no Java: [`line_wrap_hang.py`](docs/mcnpy-issues/line_wrap_hang.py). Ask for a split
     after `:` or a clear error. Ours: add a guard that wraps MCNPy's own long tokens in the normal translate path too.
  2. **`Deck.add` re-reads all universes through Java for every cell** (O(N^2) calls; the cell-adding stage, "Translating
     Universes and Cells", is 292 of 311 s on the lattice test deck). Verify the per-read call count, then report; examples [`phase_timer.py`](docs/mcnpy-issues/phase_timer.py),
     [`count_rpc.py`](docs/mcnpy-issues/count_rpc.py), [`sample_translate.py`](docs/mcnpy-issues/sample_translate.py),
     [`time_stages.py`](docs/mcnpy-issues/time_stages.py).
- **Flaky test to watch**: `test/test_generated_models.py` failed once in a full run (2026-09-26):
  `model.run()` returned no statepoint. It passed alone and in the next full run; find the cause if it recurs.
- **MontePy upgrade**: 1.1.3 in the env vs 1.5.0 upstream; needs a Python 3.12 env. Not decided. **Pin `montepy==1.1.3`** in the exporter's
  `requirements.txt` and `environment.yml` (both say just `montepy` today; 5 minutes; recommended in the 2026-10-07 investigation).
- **Test thread counts**: Studio's own Python tests run OpenMC with all cores (no `OMP_NUM_THREADS`); upstream advises 2 for its own
  regression tests; only `test_headless.py` sets threads. Decide whether the physics suite should set a count (it would slow a quiet machine).
- **MCNP lattices, remaining**:
  - Rectangular lattices export as `LAT=1`/`FILL` and hexagonal ones as `LAT=2`/`FILL`, and both pass the
    geometry check. Tested: the lattice test deck, a deleted site, 3D and 2D arrays, an outer universe, hex arrays in both
    orientations and with two axial levels.
  - Still open: prove it once in real MCNP. Plot the lattice test deck and a hex deck with lattice index labels
    (manual p. 290), or compare short runs against the cell-by-cell decks.
  - **RPP macrobody element**: done. The `LAT=1` element is one `RPP` card instead of six planes, and
    `geometry_check.py` reads it (its facet order gives the same index directions, manual p. 278, 760).
  - Cell tallies on parts inside a lattice: done in model.py (CellInstanceFilter) and in model.mcnp as
    `(unit < latcell[i j k] < filled cell)` bins (manual p. 452-455). The validator follows each bin through
    the lattice cards and compares it with the OpenMC instance point by point. Still to prove in real MCNP
    like the lattices themselves: compare a short run of `rect_tally_mcnp` against OpenMC.
- **Surface current tallies in MCNP**: done as one F1 + `C 0 1` + `FS` tally per (surface, part) bin; the
  validator checks each FS face and direction against OpenMC at points on the surface. Still open:
  - prove it in real MCNP: run `current_box_mcnp` and compare the FC-tagged bins with OpenMC's t_block;
  - fold the bin and sign into one number with `CM` cosine multipliers (p. 472) once that's confirmed;
  - Problems could warn when a surface tally ticks a part carved out of another ticked part (the export
    refuses it, since OpenMC then counts crossings of the whole surface inside the outer part).
- **He-3 reaction**: confirm with the course which reaction is meant. The pre-lab names (n,alpha) and
  (n,2alpha), MT 107/108, but ENDF/B-VIII.0 He-3 has neither; Studio uses MT 103, He-3(n,p)T.
- **3D view at scale**: time the WebGL 2 BVH view on a few thousand parts; the 10,000-part figure is a
  target, not a measurement. The 128-candidate-per-ray limit tints overflowing pixels magenta.
- **Snap to grid**: re-check that a rotate drag lands on the typed step (e.g. 45°) in the browser.
- **Artifact comments**: the 7 threads on the published copy are addressed but still open; resolve them
  in the artifact view.
- **Name**: "OpenMabc" was floated; not decided.
- **Mac copy**: pull both repos (openmc-studio and openmc-mcnp-project) on the Mac; the exporter changes for
  detector tallies and lattices are on GitHub `main` now.
- **CAD import**: done (all five stages of [the implementation plan](docs/design/cad-import-plan.md); see
  section 5 and `docs/cad-conversion.md`). Still later: IGES and more native shapes.


---

## Active Backlog (Modular Architecture)

### 0. Quality & workflow (from the 2026-10-07 investigation; private notes, not in the repo)
- **Figure of merit** on tally tables: 1/(R^2 T), R the tally's relative error, T the run time (wall time on a shared machine: say so). Hours.
- **Result-page checks for Monte Carlo good practice**, as a separate findings list on the Results page (not Problems, which is rebuilt from the
  model on every edit). Every threshold names its source; where none gives a number it says "could not compare", never a default.
  Particles per cycle (below 200: bias; below 5,000: info; MCNP 6.3 manual 2.8.1/2.8.2); inactive batches (MCNP's minimum-uncertainty skipped-cycle check);
  entropy plateau (no numeric source: "could not compare"); any lost particle (read the run log); label the k uncertainty ("1 sigma, standard
  uncertainty of the mean"). The OpenMC-documentation sources for the last two are **not confirmed** (docs were offline). About 2 days.
- **Re-run command over `provenance.json`**: verify the stored `model.py` / `project.json` hashes, list differences from today's environment
  (the 13 GB library is one hash of `cross_sections.xml`, not its contents), then run through the headless runner. About 1 day.
- **One shared pre-run check**: done, see the order above.
- **Model-stages guide** (materials, parts, source, tally, settings: done / missing) and a **New menu** (Blank, Demo, examples). The findings badge
  and click-to-select already exist (`renderProblems`). 1 day and 1 to 2 days.
- **Godiva regression case** from `mit-crpg/benchmarks` (MIT; `icsbep/heu-met-fast-001`): import its MCNP input into Studio, run in OpenMC, compare
  with the handbook k (to be fetched; the repo stores no reference value), export back to MCNP and diff. No MCNP run needed. About 1 day. C5G7 is multigroup: not Studio's.

### 1. Core Workbench & Measurement Suite
- **3D Caliper & Dimension Measurement Tool**:
  - Interactive distance measurement in the 3D WebGL viewport and 2D slice views.
  - Click two points to measure distance in cm, inspect minimum clearance/gap, check wall thickness, and display coordinate readouts.
- **OBJ Geometry Exporter**: STL export is done (Export STL…, `test/test_stl_export.js`); `.obj` (with material
  groups, for Blender) is still open. Imported CAD exports its display meshes only.
- **Advanced Graphing Suite**:
  - **Lethargy Flux Spectrum**: Plot flux per unit lethargy $\phi(u) = E \cdot \phi(E)$ vs. $\log_{10} E$, presenting the thermal Maxwellian peak, $1/E$ slowing-down resonance region, and fission spectrum on equal footing.
  - **1D Spatial Line Cuts**: Extract 1D radial or axial flux profiles from 2D/3D mesh tallies with shaded $\pm 1\sigma$ Monte Carlo uncertainty bands.
  - **Reaction Rate & Absorption Breakdown**: Interactive pie and stacked bar charts detailing neutron fate (% absorbed in fuel vs moderator vs poison vs leakage).
- **Mesh maps: slabs, 3D and how to look at them** (full plan: [docs/design/mesh-maps-plan.md](docs/design/mesh-maps-plan.md)):
  - A mesh tally is a **slab**: one axis has a single bin, so it looks like a sliver from any other view. The
    bins and corners are already editable in the tally properties; what's missing is saying so.
  - Stage 1: **done** (2026-09-24). Tally properties have a Map control (XY / XZ / YZ slab or 3D box; going 3D
    and back returns the same slab), Thickness for a slab, Resolution for a box, "Centre on the current slice"
    and "Add the other two planes", and a line with the voxel count, voxel size and expected error per voxel
    (scaled from the last run's map of the same name, otherwise sqrt(voxels / histories); on the demo the rough
    guess said 32% and the run measured a 23% median). The million-voxel warning carries the same numbers. The
    viewport says when the map on show is edge-on or the slice is outside it, and the layer list names each
    map's plane and thickness. Tests: `test/test_mesh_maps.js`, `flux_3d` in `test/test_generated_models.py`.
  - Stage 2: **first milestone done** (2026-09-26; plan [docs/design/flux-volume-view-plan.md](docs/design/flux-volume-view-plan.md)).
    In 3D the map toolbar offers Slice / Brightest / Surface (+ level slider) / Hide noisy. `drawVolume3D` marches
    each pixel's ray on its own WebGL2 canvas (R8 3D texture of the log-scaled bytes, NEAREST so values stay
    voxel-exact; depth readback as a texture for occlusion; the cutaway clipped exactly; rays step voxel to voxel,
    so no voxel is skipped, and maps with x + y + z over 4,096 or wider than the GPU's 3D textures fall back to the
    slice with a note) and composites into the overlay; `volumeRayCPU` is the test oracle. Checked live on a 40³
    map of the demo. Tests: `test/test_volume_view_browser.cjs`, `test/test_volume_view.js`. **Extras done**
    (2026-09-26): cylindrical maps in 3D (rays walk cell to cell through the rings, angle half-planes and z planes,
    holes and part turns included; checked against brute force and pixel by pixel on the GPU), **Glow**
    (emission-absorption, strength slider), and half-resolution drawing while the camera moves.
  - Stage 3: functional expansion tallies (`SpatialLegendreFilter`, `ZernikeFilter`, ...) for a smooth flux
    field with real error bars instead of a million voxels. Experiment on the lattice test deck first; MCNP has no
    equivalent, so the export must refuse it with a reason.
  - Stage 4: Gaussian splats for **event clouds** (fission, collision and source sites, track vertices), where
    each splat is one event. Not for mesh tallies: a fitted cloud smooths across material boundaries and is
    hard to read values from.
  - Note on cost: the same histories over 100x more voxels give about 10x the relative error, so a 3D map is a
    statistics decision, not a memory one.
- **VTK export of mesh tallies and geometry**: **done** (2026-09-25). Results > Export for ParaView… (or
  Export > ParaView (VTK)) zips a run's regular and cylindrical mesh tallies as legacy VTK (mean, std dev,
  rel. error, per energy bin; per source particle per cm³), tracks.vtk (energy, particle), one STL per
  material from the run's own project, and a README. `studio/openmc_studio/vtk_export.py` writes VTK itself,
  since OpenMC's writers need the `vtk` package. Tests: `test/test_vtk_export.py` (reads every file back with
  VTK's own readers and compares every voxel with `Tally.get_values`), `test/test_paraview_export.js`.
  Not yet: imported CAD components in the geometry (no STL for them yet).
- **Overlap and lost-particle check before a run**: **done** (2026-09-24). Physics > Check geometry sends
  model.py to the server (`/api/check-geometry`, `studio/openmc_studio/geometry_check.py`), which (1) locates
  100,000 random points in the world through every universe, fill and lattice and reports any point in no
  cell (a gap) or in two (an overlap), and (2) runs 1,000 particles with `openmc -g` (OpenMC's geometry
  debugging) and counts lost particles. Results appear in Problems naming the parts; clicking one moves the
  slice to the spot and marks it. Overlaps, gaps and lost particles block Run until fixed; a geometry edit clears the
  result, and a source, material or physics change clears the particle half. About 5 s on the demo. Studio's own parts can't overlap (higher parts win), so this mainly guards
  lattices, imported CAD and future hand-edited models. Tests: `test/test_geometry_check.py` (broken models:
  overlap, gap, lattice gap, overlap inside a rotated fill; and a clean control), `test/test_mesh_maps.js`.
  Not yet: run it automatically before every Run (it would add ~5 s), or in the 3D view.
- **Source sites and collision points in the viewport**: the OpenMC plotter draws source sites; MCNP's Visual
  Editor draws collision points, surface crossings and tally contributions. Source sites are nearly free since
  tracks already render, and this is the honest version of the splat idea (stage 4 of the mesh plan): each
  point is one event, not a fit.
- **Stochastic Geometry Volumes (`openmc.calculate_volumes`)**:
  - Stochastic ray-tracing volume calculation populating volume $\pm 1\sigma$ directly onto parts/materials for volumetric normalization ($\text{reactions/cm}^3/\text{s}$).
- **Multiple Independent Sources (`SDEF` Multi-Source)**: done in the MCNP export.
  - One SDEF: `ERG=Dn` with `SI n S` picks the source, and `SP n` gives the strengths. Everything else is
    `=FERG=`, with one DS entry per source (manual p. 379-408). The validator reads every source back and
    compares it with OpenMC.
  - Still open: a box source together with a sphere or cylinder source. MCNP's one SDEF card has one volume
    shape, so the export refuses the mix; Problems could warn. Points mix with any one shape.
  - In model.mcnp, clicking source cards only links to a source when there's one source.
- **Physics tab**: source spectrum presets (PuBe, AmBe, Cf-252, D-T, D-D, U-235, Co-60, Cs-137), 1-click detector-response tallies (He-3, BF3, U-235 fission chamber, Cadmium foil activation), and energy-bin presets (2-group, 3-group, 4-group, Cadmium cutoff, 10-decade log, LANL 30-group) are complete. The surface-current tally button, run-mode, photon and fission-neutron toggles, Delete and Clear are in.
- **Tally Segmenting Cards (`FS`)**:
  - Geometric segmentation of cell and surface tallies using secondary dividing surfaces (manual §10.2.4, Examples 33 & 34).
  - The exporter already writes FS for surface currents (to cut a surface down to one part's face); a
    user-facing segmented tally is still to do.

### 2. Package: Reactor Physics & Core Safety
- **Automated Reactivity Coefficient Sweeps**:
  - **Moderator Density / Void Coefficient ($\alpha_v$)**: Parameter sweep of moderator density ($0 \to 100\%$ void) with automated plot of $k_{\text{eff}}$ and derivative $\alpha_v = \partial \rho / \partial v$ in $\text{pcm} / \% \text{void}$.
  - **Doppler Fuel Temperature Coefficient ($\alpha_T$)**: Temperature sweep ($300\text{ K} \to 1800\text{ K}$) using OpenMC Doppler broadening to determine Doppler defect and $\alpha_T = \partial \rho / \partial T$ in $\text{pcm}/\text{K}$.
  - **Pitch-to-Diameter ($p/d$) Ratio Sweep**: Lattice pitch sweep mapping the transition between under-moderated and over-moderated core regimes ($k_\infty$ maximum).
  - **Critical Mass / Dimension Search**: Binary search routine for critical radius, enrichment, or soluble boron concentration to achieve $k_{\text{eff}} = 1.00000$.
    Use a secant that stops within 2 sigma of the target and reports an interval (a tight tolerance chases noise). Needs a ppm knob on a
    material (boron-in-water) first. Boron worth from 2 or 3 runs is the smallest start; 2 to 3 days.
- **Point Kinetics Parameters via Iterated Fission Probability (IFP)**:
  - Calculation and dashboard display of effective delayed neutron fraction $\beta_{\text{eff}}$, delayed group precursors $(\beta_i, \lambda_i)$, and prompt neutron lifetime $\ell_p$ / generation time $\Lambda$.
  - Smallest step: a settings toggle and two numbers on the results page, handed to KIRK and RAFT as JSON; about 2 days plus a check against a known
    value. OpenMC 0.15.3 has IFP; not tried here. Deferred until KIRK or RAFT asks.
- **Core Depletion & Fuel Burnup (`openmc.deplete` & MCNP `BURN`)**:
  - Power history (MW), depletion timesteps (EFPD / MWd/kgHM), and interactive evolution curves for $k_{\text{eff}}$, U-235 consumption, Pu-239 breeding, and fission product equilibrium (Xe-135, Sm-149).
  - MCNP companion `BURN` card export: time steps, power levels, volume tracking (`MATVOL`), and CINDER90 inventory tracking (manual §10.3.3, Example 57).
  - **Hand-off format first, no engine of our own** (FEED and RAFT import it): a schema-versioned `depletion.json` beside a run record with time
    steps (days), power history, k with its sigma, regions (name, OpenMC cell ids, heavy-metal mass), burnup per region and step in MWd/tU,
    optional isotopics, and the run's provenance block. Studio would drive `openmc.deplete`. **FEED answered (2026-10-07)**: OFFBEAT's per-cell `Bu` is
    MWd per tonne of the fuel material, i.e. of oxide for UO2, not of heavy metal. A consumer converts with the uranium mass fraction of the oxide
    (the uranium mass fraction of the oxide: 0.8815 in OFFBEAT's Lassmann burnup model, 0.881 in its `UO2MATPRO` conductivity, which divides by 0.881; oxide burnup = heavy-metal burnup x the factor of the consumer's model); the record stays on heavy metal. FEED's case is one radial slice, so what it can
    take is **one value per axial slice**, written into every fuel cell; write regions as axial slices of the fuel for FEED. The basis is not defined
    for U-ZrH (TRIGA fuel), so FEED would refuse non-oxide fuel. A radial profile would need a burnup-dependent property model first. The plan: [docs/design/depletion-plan.md](docs/design/depletion-plan.md) (D0 feasibility on a UO2 pin first; the record gets an id; the chain file exists at `/root/nuclear_data/chains/chain_endfb80_pwr.xml`, source and licence unrecorded). **Built so far (2026-10-08): D1 to D3** ([plan](docs/design/depletion-plan.md)): Settings > Depletion and a Burnable flag, `deplete.py` run through `/api/run`, `depletion.json` written when a run ends (with a record id, a region per burnable material, incomplete records for stopped runs), a Results section with charts and the estimate. **D4 done on Studio's side (2026-10-08):** FEED's reader reads a Studio record (id format pinned by a test); several burnable materials now give several regions (power split by a kappa-fission tally, checked on a two-slice pin: each slice's inventory check 1.004). **Left:** FEED's case-side import (their M6), depletion in lattices and imported CAD, the headless/SEED path, resume of a stopped burn, a split finer than a material.



### 2b. Package: Nodal Core (PWR-type cores; optional add-on)
Plan: [docs/design/nodal-package-plan.md](docs/design/nodal-package-plan.md). A lattice model gives few-group constants (`openmc.mgxs.Library`), openndm
(MIT; PyPI 0.3.0) solves a coarse 3D core, and the tab shows the nodal k and power map beside OpenMC's k. First user: RAFT's BEAVRS lesson.
- **P0 done (2026-10-07)**: the group-constant path works (infinite assembly within Monte Carlo noise: -76 and +9 pcm). An 8 x 8 core with a water
  reflector is +5,470 pcm (vacuum outside) and +2,350 pcm (reflective); a fuel-only reflective case is -8 pcm. ADFs from infinite lattices change it by under 20 pcm.
  Scripts in `docs/design/nodal-p0/`.
- **Next, P2**: reflector-aware factors or reflector constants from a fuel-and-reflector calculation; then the comparison against OpenMC kept as tests.
  The pass line is the user's to set after seeing the numbers. **No nodal k is shown as an estimate of a core until P2 passes.**
- Then P1 (the solver wrapper; `legendre_order = 0` with P0 correction, `openmc` on PATH, never a physical region as the lattice's `outer`), P3 (the tab),
  P4 (the SEED manifest: add-on `nodal-core`, capabilities `group-constants` and `nodal-solve`, MIT notice), P5 (the RAFT result file).
- For the BEAVRS HZP comparison (RAFT's M8): absolute critical boron and the temperature coefficients need full Monte Carlo; bank and boron worths as
  differences might come from the nodal route, unproven.

### 2c. Package: TRISO & Particle Fuel (eventually; a separate package for people doing TRISO work)
Today: one five-layer particle example (`examples/triso-particle`), no packing. Findings of the 2026-10-07 probe (private notes, not in the repo):
- **Package contents**: a compact or pebble template (radii, packing fraction, count, seed) using `openmc.model.pack_spheres` and `create_triso_lattice`,
  3D and packing-fraction checks (random sequential packing stalls near 0.38), the particle library, volume and fuel-loading numbers. Start OpenMC-only.
- **MCNP export of a packing is not ready, and the template must refuse it with a named message until it is**: MCNPy takes about 2.6 s per particle (20 particles
  about 85 s, 100 particles 302 s; 1,000 would be about 45 min, 10,000 about 7 h if linear); it fails on numpy 2 unless `np.set_printoptions(legacy="1.25")`
  is set (the text `np.float64(...)` reaches Java); and the exporter refuses translated cells inside lattice universes (`lattice_cards.py:351`). Reading the raw deck in MCNP: not run.
- Needs before an MCNP export: exporter support for translated cells in lattice universes, a per-cell speed-up of the same kind as the earlier speed work, and a real MCNP read.
  Weeks, not days. Report the numpy-2 failure upstream only when the user says (with the other MCNPy items).
- Cost of the OpenMC-only template: 3 to 4 days. Build it when TRISO users exist (none confirmed).

### 3. Package: Radiation Protection & Detection Lab
- **Pulse Height Multichannel Analyzer (MCA) Spectrum (`openmc.PulseHeightFilter`)**:
  - Pulse height tally simulating true energy deposition spectra in scintillators and semiconductor detectors (NaI(Tl), HPGe, LaBr3, plastics).
  - Interactive MCA spectrum viewer with linear/log counts vs keV/MeV, photopeak identification, single/double escape peaks, and Compton edge marker.
- **Neutron Capture Multiplicity & Coincidence Counting (`FT CAP`)**:
  - Pulse multiplicity distributions, factorial moments, and coincidence time-gating (`gate predelay width`) on neutron capture absorbers ($^3\text{He}$, $^{10}\text{B}$) for safeguards counters (manual §10.2.5.5–§10.2.5.7, Examples 39 & 40; PRINT Table 118).

- **Dose rates, stage 1: done** (2026-09-25; plan: [docs/design/dose-rates-plan.md](docs/design/dose-rates-plan.md)). A cell tally's
  Dose setting (or the Detector menu's "Dose rate, neutrons" / "neutrons + photons" presets) gives effective dose
  from `openmc.data.dose_coefficients` (ICRP-116 or -74; AP, PA, LLAT, RLAT, ROT, ISO): one tally per particle
  with a log-log `EnergyFunctionFilter`, padded down to the lowest transported energy with the first value so
  low energies count the way MCNP's DE/DF do. model.py runs OpenMC's stochastic volume calculation on each dosed
  cell before the run and writes `dose.json`; results.py divides by the volume and, with Settings > Source
  emission rate, shows µSv/h (mrem/h in imperial), otherwise pSv per source particle, with the volume error in
  the relative error. Test against a hand calculation (point sources in void, `test/test_dose_rates.py`):
  neutron +2.3% ± 2.4%, photon -0.7% ± 2.8%, ICRP-74 ISO -0.1% ± 2.6%; volume 33.514 ± 0.071 vs 33.510 cm³.
  Problems refuses dose in eigenvalue mode, photon dose without photon transport, dose plus a detector response
  and (since 2026-09-25) a material filter. **Found and fixed on the way:** OpenMC multiplies fixed-source tallies by the
  total source strength, so models whose strengths didn't sum to 1 showed tallies scaled by that sum (and
  unlike MCNP). model.py now scales the strengths to sum to 1 before the run.
  **Stage 2 (dose maps): done** (2026-09-25). A mesh tally (regular or cylindrical) with Dose is a dose map:
  results.py sums the particles and divides by each voxel's exact volume, and returns it as an ordinary map
  (score "dose", `unit` Sv/h or pSv/source), so the viewport, Map control, noise line and VTK export work
  unchanged; the colorbar and Results line show µSv/h or mrem/h, the layer is "Dose map". Tested voxel by voxel
  against a numerically integrated point-source fluence (64 box voxels, 4 cylindrical rings, all within 4.5
  sigma, mean deviation unbiased), and the VTK export equals Results value for value. **Found and fixed:** every
  Studio cylindrical mesh tally failed to run: 2π rounded to 12 digits (6.28318530718) is above 2π and OpenMC
  refuses the phi grid; a full circle is now `2 * np.pi` (`test_cylindrical_view.js` asserted the old string).
  **Stage 3 (MCNP): done** (2026-09-25; exporter `8c3b92f`). Dose tallies go to model.mcnp as `F4:N`/`F4:P` or
  `FMESH`, `DE`/`DF` written from model.py's own padded filter (LOG left implicit: MCNP's default, and MontePy
  can't parse the keyword), `SD` with the cell volume from the same OpenMC volume calculation the run does
  (`mcnp_worker.dose_description`; identical numbers, tested on a plug-cut detector MCNP couldn't volume itself),
  and the source rate as `FM` / `FACTOR`. `export_mcnp.py --dose dose.json` exports a run folder. Tests:
  `test/test_dose_mcnp.py`, companion `tests/test_dose_export.py`. **Still open:** run a dose deck in real MCNP and
  compare with Studio; H*(10) (needs a sourced table).
  **Dose on lattice members: done** (2026-09-26). A part inside a RectLattice/HexLattice is a (unit cell, instance)
  bin; its volume is measured in the box around that one part and keyed "cell/instance" in dose.json (with the
  part's name as its label). The MCNP deck tallies it as a chain bin with that volume on SD. Tests:
  `DoseInLattices` in `test/test_dose_rates.py` (volumes vs the shapes; lattice vs flat twin doses agree, rect and
  hex), `DoseInLatticeToMcnp` in `test/test_dose_mcnp.py`, companion `DoseInLattice` in `tests/test_dose_export.py`.
- **Fluence-to-Dose Conversion (ICRP / ANSI)**, original notes:
  - Energy-dependent dose response filters (`openmc.data.dose_coefficients`):
    - **ICRP-74 / ICRP-116**: Effective dose for AP, PA, ISO, and ROT irradiation geometries.
    - **ANSI/ANS-6.1.1-1977**: Standard neutron and gamma flux-to-dose conversion factors.
  - Live readout in physical radiological dose units ($\mu\text{Sv/h}$, $\text{mSv/h}$, $\text{mrem/h}$, $\text{rem/h}$) scaled to source strength ($\text{particles/s}$) and MCNP `DF`/`DE` cards.
- **PNNL Materials Compendium & Cross-Section Explorer**:
  - 1-click standard presets from the PNNL Compendium for structural alloys, shielding concretes, borated polymers, fuels, and control poisons.
  - Interactive microscopic cross-section plot ($\sigma_t, \sigma_\gamma, \sigma_f, \sigma_s$) directly from OpenMC's HDF5 library.
  - **Cheap route**: `openmc.plotter.plot_xs` is built in and needs only the data library we already have. Best
    teaching value per hour on this list: plotting a material with and without its S(a,b) table shows the whole
    thermal-scattering story at a glance (e.g. `c_Be` or `c_Graphite`), as does He-3 (n,p) for a detector.
- **Weight Windows & Importance Maps (`openmc.WeightWindows`)**:
  - Spatial weight window mesh configuration for deep shielding penetration, with 2D/3D importance heatmaps and MCNP `WWG`/`WWP` cards.
  - Order: the figure of merit first (section 0), then MAGIC generation (`openmc.WeightWindowGenerator`; two passes: generate, then load; 3 to 4 days),
    tested on the shielding demo. The test: a windowed run against an analog run of the same model, two seeds each, agreeing within 3 sigma of the
    combined uncertainty, with the FOM gain reported (not run yet). **MCNP export: not supported, and it says so**: MCNP's `WWG` generates its own
    (different) windows, and carrying OpenMC's over needs a `wwinp` writer that cannot be verified without MCNP.
  - Random ray / FW-CADIS: OpenMC 0.15.3 has them (`Settings.random_ray`, `convert_to_multigroup`, `WeightWindowGenerator(method='fw_cadis')`) but they need
    multigroup constants Studio does not make. Deferred.

### 4. Package: Fusion Neutronics
- **Torus & Tokamak Geometry**:
  - Torus primitive (`openmc.ZTorus`, `openmc.XTorus`, `openmc.YTorus` and MCNP `TX`/`TY`/`TZ`) with major radius $R$, minor radius $r$, and analytical 3D raymarching.
  - Parametric elongated D-shaped cross-sections for tokamak first walls, vacuum vessels, and magnetic field coils.
  - Annular / ring plasma sources (`openmc.stats.CylindricalIndependent`).
- **Tritium Breeding Ratio (TBR) Tally**:
  - Automated tally configuration for $(n,\alpha)t$ reaction rates in Li-6 (MT 105) and Li-7 (MT 205) across breeding blanket regions.
- **Spherical Mesh Tallies (`openmc.SphericalMesh`)**:
  - Spherical grid binning ($r, \theta, \phi$) with arbitrary center origin for spherical tokamak chambers and point-source dosimetry.

### 5. Package: Conversion & Interoperability (a "Convert" tab)

- **A Convert tab in the ribbon** gathering everything that crosses a file format, so import/export isn't
  scattered between Export and the file menu: CAD in and out, MCNP in and out, OpenMC scripts and XML in,
  VTK/STL out, and whatever phase-space format we support later. Each entry says what survives the trip and
  what doesn't, since none of these conversions is lossless.
- **Round trips: edit model.py / model.mcnp outside Studio and bring the edits back** (asked for 2026-09-24):
  - **model.py part: done** (2026-09-25). Convert ▸ Import edited model.py… (`importScriptPatch`): regenerates
    the marked script, line-diffs it against the file (common prefix/suffix + LCS), matches each changed line
    to its twin with only the marked numbers free, applies them through `applyEdit` as one Undo step, and logs
    each change by object; new/deleted/rewritten lines and unmarked (computed) numbers are listed as not applied;
    blank lines, CRLF and trailing spaces don't count; unknown studio IDs refuse the file. Tests:
    `test/test_patch_import.js` (9).
  - **model.mcnp part: done** (2026-09-25). The same button takes an edited deck (`planMcnpPatch`): it is lined
    up against the live model.mcnp tab (which must be current), whose editable numbers are read back from
    `annotateMcnp`'s own rendering (`markedMcnp`), so deck numbers map to objects exactly as in-place editing does
    (`@studio-v1` records). Shared core `planLinePatch` with the model.py import. Decks without records, naming
    unknown objects, or a stale tab are refused. Checked live: a density edited in the deck reached the material,
    model.py and the re-translated deck. Tests: `test/test_mcnp_patch_import.js` (7; fixture
    `test/fixtures/mcnp/shielding_demo.*` is a real exported deck and its project). **Next:** the shared record
    format (below) and embedding the whole project.
  - **Import as a patch (first).** Open an edited model.py (then model.mcnp) onto the project it came from.
    Studio regenerates the file from the current project, diffs it against the imported one, and maps each
    changed line to its Studio object and number: model.py through `studio_ids` and Studio's own line map,
    model.mcnp through the `c @studio-v1` records (`docs/studio-ids.md` in the companion). Each change goes
    through the same path as editing a number in place in the code tabs (surface positions and radii,
    densities and compositions, source, tally and run settings), as one Undo step, with a summary.
  - Anything that doesn't map back is listed, never dropped silently: new cells or surfaces, rewritten
    region logic, and numbers Studio derives rather than stores (GQ coefficients of rotated parts,
    lattice-generated, shared or macrobody surfaces; the report says what to change in Studio instead).
  - Refuse when the file came from another project or an older version whose IDs no longer match.
  - **model.py and model.mcnp are interchangeable.** Both point to the same Studio objects, so importing
    either one updates the project and the other file is regenerated from it: edit model.mcnp and the change
    shows up in model.py, and the reverse. Neither file is ever translated straight into the other. Give
    model.py the same `@studio-v1` comment records model.mcnp has (today it has the `studio_ids` table and
    Studio's line map instead), so one record format and one importer serve both files. Numbers that exist
    in only one file (MCNP isotope fractions expanded from an element, GQ for a rotated part, NPS; track
    settings in model.py) can't cross over; the report says what to change instead.
  - **Embedded project: done** (2026-09-25). Saved/copied model.py and the model.mcnp tab's Save end with the
    project as comment lines (`@studio-project-v1`, base64 JSON, 76 per line; MCNP lines under 128 columns;
    over 6 MB it isn't embedded and says so). Export ▸ Open project accepts .py/.mcnp: `openProjectText` restores
    the exact project, then runs the patch import on the file, so edits made after saving come back (no
    fingerprint needed: the file is compared with what the restored project generates). A deck waits for the
    model.mcnp tab to translate first. The live tabs and run folders don't carry the block; the patch import
    ignores it. Tests: `test/test_embed_project.js` (8); a saved model.py with the block runs in OpenMC.
    The server's Export ▸ MCNP input deck carries it too (`server.project_block`, same format; checked by
    decoding the server's block with the page's `readProjectBlock`).
  - **STEP: keep names and materials.** STEP export writes one unnamed compound today, so even part names
    are lost. Write each part as its own named solid (PRODUCT name = the Studio name), put Studio data
    (material, density, id) in the product description, and also write a small sidecar JSON beside the
    .step, since CAD tools that re-save a file often drop the description. On import, use whichever
    survived; otherwise parts stay "needs a material" as now.
  - Tests: an edited radius, density and batch count come back exactly; an unsupported edit is reported;
    a file from another project is refused; STEP export -> import keeps names and materials.
- **Import an MCNP deck: geometry, materials, sources, tallies and run settings done** (2026-09-26; research and converter comparison in
  [docs/design/mcnp-import-research.md](docs/design/mcnp-import-research.md): openmc_mcnp_adapter was exact on every deck it read,
  csg2csg failed on 4 of 6). `mcnp_import.py` flattens universes, lattices and fill transforms into imported-CSG
  cells, checks them against `openmc.lib` at every cell, and builds voxel preview meshes; Convert > Import MCNP
  deck commits them (`commitMcnpImport`). Tests: `test/test_mcnp_import_gate.cjs` (model.py vs the deck in
  OpenMC), `test/test_mcnp_import.py`. The data block is read by `mcnp_cards_in.py` (standard library only): `SDEF` with
  `SI`/`SP` distributions, `NPS`, `KCODE`/`KSRC`, `MODE`, `F4` with `E`/`FM`/`FC`/`SD`, and `FMESH` (rectangular
  and cylindrical); every other card, and any card with a value it can't read, is listed in the Log with the
  reason (tests: `test/test_mcnp_cards_in.py`, `test/test_mcnp_import_physics.js`). **Next:** hexagonal lattices
  (upstream in the adapter, or Studio's own step); `F1`/`F2`/`F5` tallies; tallies on cells repeated in a lattice.
  **Known issue (partly fixed 2026-10-06):** the live model.mcnp tab was unusable on big imports (the lattice test deck, 266
  cells, took 23.5 min). Measured: validate 973 s (OpenMC's Python `Geometry.find` once per sample point; fixed in
  the exporter, now 16-36 s) and MCNPy translate 407 s (about 0.6 s a cell up to 100 cells, steeper beyond). The
  translate cost remains; see the plan for the diff-from-baseline fix.
  Original notes:
  - We already write MCNP decks *and* check them against the OpenMC model point by point. Import closes the
    loop: read a hand-written deck (e.g. a course lab deck) into Studio's scene graph, then run
    the existing geometry check to prove the round trip.
  - Expect gaps: macrobodies, lattices, transforms and repeated structures each need mapping back, and Studio
    parts are shapes rather than raw cells, so some decks will import as geometry we can display but not edit
    as parts. Say so per cell rather than failing the whole file.
- **FreeCAD / GEOUNED CAD import roadmap** (started 2026-09-23):
  - Full architecture, acceptance gates, environment setup and proposed ignore rules:
    [CAD import implementation plan](docs/design/cad-import-plan.md).
  - Two outputs: validated **native editable primitives** through FreeCAD, and **imported analytical CSG
    components** through GEOUNED. General CSG needs a versioned surface/Boolean-region model; it cannot be
    represented by guessed boxes or existing organizational groups. DAGMC remains a separate later path.
  - [x] **Stage 0 — prove the engines:** create an isolated WSL `openmc-cad` environment; convert a drilled
    block and hollow cylinder with real GEOUNED into OpenMC XML. Verify holes, placement and units. Pin the
    tested Python/FreeCAD/OCCT/GEOUNED builds. Recheck upstream's warning recorded on 2026-09-22 about
    incorrect conversion in GEOUNED 1.6.3/1.6.4; evaluate 1.6.2 rather than installing an unqualified latest.
    Delivered: `setup/cad/verify.py`, four real fixture cases (80,000 containment checks plus hole/volume
    checks), input-rejection tests and `setup/cad/locks/linux-64.explicit.txt`. See
    [stage-0 setup and findings](setup/cad/README.md); no browser import or transport readiness implied.
  - [x] **Stage 1 — reliable jobs:** isolated workers, job IDs, progress, cancellation/timeouts, safe temporary
    paths, size limits and diagnostics. Failed or cancelled jobs must not change the project.
    Delivered: `studio/openmc_studio/cad/jobs.py` (one disposable worker process group per job, serialized,
    job-ID-correlated progress/results, atomic files, bounded input/log/disk/report/XML, retention, lock
    against a second Studio), `POST/GET/DELETE /api/cad/jobs` and `GET /api/cad/capabilities`, a real
    `probe` job that must convert a drilled block before `engine_verified` is true, and an explicit job-mode
    allowlist as the adapter contract. Tests: `test/test_cad_jobs.py` (28, lifecycle), `test/test_cad_jobs_http.py`
    (12, real HTTP server) and `test/test_cad_jobs_engine.py` (4, real FreeCAD/GEOUNED; fails, never skips,
    without the engine). Diagnostics are per job (worker's own error plus a bounded log tail); **per-solid**
    diagnostics move to stage 2, which adds the multi-solid STEP inventory they depend on.
  - [x] **Stage 2 — native STEP import:** inventory every solid in a STEP file with per-solid diagnostics
    (validity, closure, surface types, bounds, source names); recognize boxes, spheres, capped cylinders and cones; rebuild and
    compare solids, preserve units/rotations, assign unique IDs and require explicit material mapping.
    Preview omissions before any partial import; commit as one undoable action. Test save/reload.
    Delivered: `cad/read.py` (FreeCAD reader, stable keys for duplicate labels and repeated instances, flat-read
    cross-check), `cad/primitives.py` (support-surface recognition, scale-aware tolerances), `cad/validate.py`
    (rebuild through Studio's own part mapping; bounds, symmetric difference, boundary distances, band-aware point
    probes, all in a local frame), `cad/report.py` (every solid accepted/rejected/failed, overlaps), `inspect` and
    `native` job modes, and **Convert > Import CAD…**: engine probe, inventory, mode choice (CSG shown, disabled at that stage; enabled since),
    preview, explicit partial import, one-step undo, pending materials that block runs until chosen (or Void on
    purpose), import records kept in the project. Tests: `test/test_cad_native_engine.py` (34 FreeCAD-written cases
    + 5 files from an independent non-OCCT writer, units mm/cm/m/inch, 12 near misses, assemblies, teeth check),
    `test/test_cad_import_browser.cjs` (9 workflow checks on real engine reports) and `test/test_cad_import_e2e.cjs`
    (real browser + server + FreeCAD: import, save, reopen). Not done here, by design: wedge/hex-prism/ellipsoid
    recognition (needs its own independent fixtures), a conversion cache with a clear-cache action (stage 5).
  - [x] **Stage 3 — analytical CSG model:** call GEOUNED's real conversion API, parse OpenMC XML as data,
    add versioned surfaces/region trees and preserve source-to-cell identity. Resolve world/void ownership
    and overlaps; never execute generated Python or silently discard unsupported surfaces.
    Delivered: `cad/schema.py` (bounded XML reader refusing DTDs/entities, OpenMC region grammar with depth/size
    limits, 12 surface types, tori refused, boundaries stripped so Studio's world owns them), `cad/csg.py` (the
    `csg` job: each solid converted on its own for an exact one-solid-one-component mapping, then validated with
    Studio's own region evaluator against FreeCAD: band-aware points, cells partition the solid, volume), project
    **schema 2** (`S.csg.components`, newer schemas refused with a reason), exact `model.py` generation (full
    double precision, no priority cutting, world subtracts components), `commitCsgImport` into a new project in
    one undo step, overlapping solids refused at commit, pending materials per cell, MCNP export and the live
    deck off for these projects with the reason. Gate: `test/test_cad_csg_gate.cjs` (real conversions → Studio's
    own import and generation → OpenMC: every one of ~3000 points per case in exactly the right cell, holes in
    the World, for drilled blocks, annuli, rotated variants, a hollow sphere, a TRISO coating shell and a
    four-solid assembly; no Python generated) and `test/test_cad_schema.py` (grammar, XML hardening, and
    Studio's surface equations equal OpenMC's sign for sign). The CSG option in the import dialog and the
    viewport display of components are stage 4.
  - [x] **Stage 4 — Studio integration:** analytical slices, validated 3D preview/picking, materials, cell
    tallies, portable project storage and OpenMC generation. General CSG geometry starts read-only.
    Display meshes are not transport geometry; renderer budget limits must never hide geometry silently.
    Delivered from Claude's draft with Codex validation: CSG dialog, component properties and cell tallies,
    bounded meshes with visible failure notices, cut-cap picking and schema validation. Browser gate
    `test_cad_csg_browser.cjs` passes; `E2E_CAD_MODE=csg test_cad_import_e2e.cjs` exercises real upload,
    conversion, save/reload and an OpenMC geometry-debug run (explicit void fills, 200 histories).
  - [x] **Stage 5 — parity and packaging:** companion MCNP export checks, real engine/browser integration
    CI, clean-machine setup and platform locks. CAD release checks cannot pass through dependency skips.
    Add IGES and further native shapes only after separate geometry-preservation tests.
    Delivered: MCNP export of imported CSG, gated by `test/test_cad_mcnp_parity.cjs` (7 real conversions: deck
    validates with every cell sampled and carries Studio's materials, source and tally; every FreeCAD truth
    point lands in the right MCNP cell, holes included; Studio's `/api/export-mcnp` path too) - after finding
    that the exporter's sampling never reached small rotated cells: Studio now bounds each imported cell with
    its component box, and the exporter (companion `36bba86`) warns for any cell it never sampled. STEP export
    really runs with the CAD environment now (FreeCAD's runtime path and its `__main__` wipe had kept it
    reporting "FreeCAD required"). `setup/cad/run_integration.cjs`: 17 suites, exits 0 only if all ran with
    nothing skipped, 30-minute per-suite timeout. Clean-machine check: the lock installed from an empty package
    cache (1 min 53 s) passes all 17 suites (6.0 min); `test/test_cad_restart_e2e.cjs` checks restart. Platform
    matrix in docs/cad-conversion.md: Linux x86-64 / WSL2 verified; native Windows unsupported; macOS and arm64
    not validated. **CI decision (2026-09-24):** no hosted CI workflow. The integration job runs locally before
    merging CAD work; it needs no accounts or secrets, so anyone who installs the lock env can run it (a hosted
    run would also be unable to fetch the private companion repo on fork pull requests). IGES and further
    native shapes remain later work.
  - [x] **Git policy:** track adapter code, recipes/locks, documentation and small public fixtures. Keep CAD
    engines/environments, user uploads, caches, debug solids, logs and conversion scratch outside Git.
    Add narrow fixture exceptions for IGES/B-Rep and expected XML currently hidden by broad ignores;
    verify ignored and tracked paths with `git check-ignore`. The exact proposed rules are in the plan.
  - **Release gate:** unsupported geometry is reported, never approximated silently; verify boundaries,
    holes, volumes, rotations and mm/cm/inch units against CAD, plus repeated imports and actual OpenMC
    geometry. A matching volume or self-roundtrip alone is insufficient. Full CSG-to-STEP roundtrip and
    MCNP parity must be validated separately from primitive export.
- **DAGMC Direct Accelerated Geometry**:
  - Direct import and visualization of faceted DAGMC `.h5m` surface mesh models.
- **OpenMC Python & XML Importer**:
  - Drag-and-drop parser for existing `model.py` scripts and XML suites (`geometry.xml`, `materials.xml`, `settings.xml`, `tallies.xml`) into OpenMC Studio's scene graph.

### 6. MCNP 6.3 Performance & Geometry Optimizations (Research Analysis)
**No MCNP runs here.** Nothing in this section has been measured: this machine has no MCNP executable, so
every speed claim below is from the manual or from reasoning, never from a timing. Measure before optimising.

- **Direct analytic source sampling (`SP -2`, `SP -3`, `SP -4`)**: **done**. Maxwell, Watt and the Gaussian
  (Muir) fusion spectrum export as closed-form cards from `src/mcnp_cards.py`, instead of histogram tables.
- **Macrobodies**: **`RPP` and `RCC` done**, `HEX` open.
  - `src/lattice_cards.py` writes the `LAT=1` element as one `RPP`; `src/macrobody_cards.py` turns standalone
    boxes into `RPP` and finite cylinders into `RCC`.
  - The gain is **readability and deck style, not speed**: MCNP decomposes every macrobody into ordinary
    surfaces internally (manual p. 271), and the input tip at p. 243 is about simple input, not tracking cost.
  - Left: a `HEX` macrobody for hex-prism parts and hex lattice elements, for the same readability reason.
- **Negative universes (`u=-n`)**: **considered and declined as a default** (decided 2026-09-19, see
  `messages/openmc.md` 13:45). Don't reopen it without the evidence below.
  - The manual (p. 288) promises only that a problem "will run faster", beside a Caution that MCNP cannot
    detect a mistake in this feature: "Extremely wrong answers can be quietly calculated."
  - The "10-25% speedup" is not in the manual. A search of the text found nothing; it needs a citation.
  - Our geometry check cannot catch a wrong `u=-n`: the regions are unchanged, only MCNP's tracking differs.
    Every other MCNP feature we export has a check that fails when we get it wrong. This one would have none.
  - The lattice test model has no cell that qualifies anyway: the aperture spans the full depth of its element and
    touches its faces, and the graphite around it is unbounded.
  - What would change our mind: an opt-in switch, restricted to cells whose bounding box sits strictly inside
    the element with a margin, plus one real MCNP run compared against the same deck without it.
- **Pruning the complement operator (`#`)**: partly done, low priority.
  - `src/macrobody_cards.py` folds de Morgan unions back into a single macrobody sense.
  - Cell complements (`#c`) are untouched. Our decks use `#` only in the graveyard cell, which has `IMP:N=0`,
    so particles die there immediately. The manual's warning (p. 261, tip 2) is about complements that drag
    unneeded surfaces into a cell, which Studio already limits to overlapping bounding boxes.
- **Runtape and print volume (`PRDMP`)**: open, and **not as previously written**. `PRDMP ndp ndm mct ndmp dmmp`
  (manual p. 576-577) takes *intervals*, not switches:
  - `ndm` is how often a dump is written (histories, or minutes if negative). Zero is not "off"; the default is
    every 60 minutes plus one at the end, and the manual gives no way to suppress the final dump.
  - `ndmp` caps how many dumps the runtape keeps, which is the real way to bound its size.
  - `mct = 0` means **no MCTAL file**, the opposite of what an automated run wants if it ever reads tallies
    back; `mct = 1` writes one at the end.
  - Worth setting only when someone actually runs these decks and measures the I/O.

---

## Completed

- **Review fixes (2026-09-19)**:
  - model.py with a detector tally no longer fails on Python 3.11 (backslashes inside an f-string).
  - Detector FM cards come from model.py's `detector_responses` (C = the gas's atom density, or
    1 / atom fraction for microscopic), not from the tally name; -1 (the cell's own density) is gone.
  - Lattices: one shape function for parts and lattice units (every shape works), 3D lattices so units
    sit at the element centre (one-layer arrays off z = 0 were misplaced), top-row-first y order for
    deleted sites, and a check that members are identical and on the grid (else cell by cell, with a
    warning). model.mcnp writes arrays cell by cell; the lattice test deck validates again (87,500 points).
  - Surface current: SurfaceFilter of the part's own surfaces + CellFromFilter (it passed a region before).
  - MCNP previews: Muir source as `SP -4` (no comment inside SDEF), cylindrical FMESH J = z, K = angle.
  - The exporter handles CylindricalMesh (FMESH GEOM=CYL).
  - Problems: periodic boundary needs a box world; surface tallies score current only; detector
    tallies need a material (macro) or nuclide (micro); the "isn't used" note counts arrays and tallies,
    and library materials used only by a detector or array fill aren't auto-removed.
  - model.py groups list their sources again; MCNP group comments turn × ° µ into ASCII.
  - Tests: `node test/generate_fixtures.js` writes Studio's real model.py for fixtures and
    `python test/test_generated_models.py` runs them (lattice vs cell-by-cell at 20,000 points each,
    OpenMC runs, He-3 macro/micro = N). test_detector_responses.py now tests the generated helper.
- **Hexagonal Lattices (`openmc.HexLattice`)**:
  - Hexagonal arrays with flat-to-flat pitch, concentric rings, $x$/$y$ orientation and solid moderator fill.
  - Interactive Hexagonal array tool in editor UI with pitch, rings, and orientation settings.
  - Python `openmc.HexLattice` generation; MCNP `LAT=2`/`FILL` written by openmc-mcnp-project (2026-09-19).
- **Cylindrical Mesh Tallies**:
  - Support for `openmc.CylindricalMesh` ($r, \phi, z$) with custom radial, azimuthal, and axial binning grids and arbitrary spatial origin.
  - Full simulation extraction in `results.py` and 2D canvas annular-sector slice rendering in UI.
  - MCNP export with `FMESH ... GEOM=CYL ORIGIN=... AXS=0 0 1 VEC=1 0 0`.
- **Ellipsoid & Quadric Primitives**:
  - General ellipsoid primitive (`openmc.Quadric`) supporting semi-axes $a, b, c$, arbitrary 3D center, and full 3D Euler rotations.
  - Analytical ray-ellipsoid quadratic intersection in WebGL 2 raymarching fragment shader (`ty == 6`).
  - Exact CPU ray picking and 2D canvas slice cross-section rendering.
  - MCNP: MCNPy translates the openmc.Quadric like other quadrics (not checked separately for ellipsoids).
- **Thermal Neutron Scattering $S(\alpha, \beta)$ Integration**:
  - Full catalog of all 34 ENDF/B-VIII.0 thermal scattering tables with descriptions and MCNP SABID tags.
  - Material Inspector UI with smart dropdown, heuristic "Auto" suggest button, and custom text fallback.
  - Live MCNP Material preview (`M<n>` + companion `MT<n>`) in properties inspector.
  - Model script generation (`mat.add_s_alpha_beta`) and MCNP exporter expansion (`SAB_MCNP_MAP`).
  - Multi-SAB grouping on a single space-separated `MT<m>` card in `remediate_deck.py` per MCNP 6.3 Manual §5.6.2.


- **Coupled Neutron-Photon Transport**:
  - Toggle `settings.photon_transport = True`, energy cutoff (`settings.cutoff = {'energy_photon': ...}`), source particle selection (`neutron`/`photon`), and tally particle filters (`openmc.ParticleFilter`).
  - Automatic `MODE N P` and `F...:P` generation in MCNP export.
- **Material Temperature & Doppler Broadening**:
  - Per-material temperature settings (`mat.temperature = ...`) and project-wide default temperature interpolation (`settings.temperature = {'default': 293.6, 'method': 'interpolation'}`).
- **Criticality & Eigenvalue Convergence Tracking**:
  - Interactive SVG convergence chart for batch-by-batch $k_{\text{eff}}$ with inactive cycle shading, $1\sigma$ band, and Shannon entropy evolution.
  - Shannon entropy mesh toggle and automatic regular grid creation (`settings.entropy_mesh`).
  - Safe extraction of `sp.k_generation`, `sp.n_inactive`, `sp.entropy`, and `sp.k_combined` in `results.py`.
- **Surface Current Tallies & Material Filters**:
  - Added `surface` tally filter with `current` score using `openmc.SurfaceFilter` and MCNP `F1:N`/`F1:P`.
    (Photon current actually exported as `F1:N` until 2026-09-25; tested since: exporter
    `tests/test_review_semantics.py`.)
  - Added material tally filter using `openmc.MaterialFilter` to evaluate reaction rates across distributed cells.
    OpenMC only: the MCNP exporter refuses a `MaterialFilter`, and dose tallies refuse it in Problems.
- **Boundary Conditions (Periodic & White)**:
  - Supported `periodic` and `white` boundary types with automatic pairing of opposing planar surfaces (`.periodic_surface = ...`).
- **Fusion Plasma Source (`openmc.stats.muir`)**:
  - Supported Muir fusion neutron spectra for D-T ($14.08\text{ MeV}$) and D-D ($2.45\text{ MeV}$) with ion temperature Doppler broadening ($kT_{\text{ion}}$ in eV).
- **Virtual Detector Response Quality (B-10 & Multi-Nuclide)**:
  - B-10 preset mapped to $(n,\alpha)$ [MT 107] with auto-detection of boron/BF3 media and UI override.
  - (The MCNP side was wrong until the 2026-09-19 review fixes above.)
  - Multi-nuclide custom detector responses with $N_i$-weighted cross-section interpolation across all constituent nuclides on a unified energy grid, invariant to composition text order.
- **3D Dense Raymarching BVH Acceleration**:
  - Primitive intersection filtering at BVH leaf nodes prior to stack insertion; increased candidate budget from 96 to 128 with visual overflow diagnostic tint.
  - test_bvh_dense_ray.py models this logic in Python; it doesn't run the shader.
- **Automated Regression Test Suite**:
  - `test_frontend_model.js`: verifies data model, script generation, and MCNP cards.
  - `test_bvh_dense_ray.py`: verifies 3D raymarching with 140 parts along a ray line.
  - `test_detector_responses.py`: verifies physics accuracy against ENDF/B-VIII.0 cross sections in OpenMC 0.15.3.
  - `test_photon_and_temperature.py`: verifies coupled photon simulation and temperature broadening.
  - `test_keff_convergence.py`: verifies eigenvalue convergence extraction and Shannon entropy.
  - `test_surface_and_periodic.py`: verifies surface current tallies, material tallies, and periodic unit cells.

- **MCNP Translation Progress & Refresh**:
  - Real-time stage tracking (`@@PROGRESS` events) across all 8 MCNPy translation stages with timing display.
  - Manual **Refresh** button on `model.mcnp` toolbar.
  - Viewport overlay **Clear** button and automatic overlay reset on run switching.
- **EnergyFunctionFilter MCNP Export**:
  - Translated virtual detector response tallies using `openmc.EnergyFunctionFilter` into standard MCNP `FM` multiplier cards.
- **Array Tool & RectLattice Export**:
  - Native `openmc.RectLattice` in model.py with unit universes and oriented tilted surfaces, reducing code from >1000 lines down to ~216 lines. MCNP `LAT=1`/`FILL` written by openmc-mcnp-project (2026-09-19).
  - Support for missing/deleted array lattice elements using solid moderator universes.
  - Automatic host moderator material detection and UI selector.
- **He-3 Proportional Counter Detector Response**:
  - Unperturbed virtual detector response tallies with `openmc.EnergyFunctionFilter` and MCNP `FM` multiplier cards.
- **3D WebGL 2 Raymarching with BVH**:
  - Data textures and BVH stack traversal, so there's no fixed part cap (large scenes not yet timed).
- **Additional Geometry Primitives**:
  - Right triangular prism / wedge (`wedge`), Hexagonal prism (`hex_prism`), and Truncated cone (`cone`).
- **Tabulated Source Energy Spectrum**:
  - `openmc.stats.Tabular` histogram energy distribution with MCNP `SI`/`SP` card generation.
- **Nested Groups Architecture**:
  - Hierarchical Explorer tree, collapsible groups, rigid parent-child transformations, and structured MCNP `c Group:` annotations.

---

## Known Export Limits

- Several sources export as one SDEF, but box sources can't be mixed with sphere or cylinder sources (points
  mix with any one of them).
- Absorption can't be exported for actinide materials (MontePy can't parse `FM ... -2:-6`).
- Mesh tallies export flux only (`FMESH`, reaction rate mesh tallies not exported).
- The geometry check follows universes and LAT=1 / LAT=2 lattices, but not TRCL or rotated fills.
- Special tally treatment cards (`FT` cards) are not exported: capture multiplicity (`FT CAP`), residual nuclei (`FT RES`), ROC curve discrimination (`FT ROC`), surface normal redefinition (`FT FRV`), cell-partitioned detector tallies (`FT ICD`), or charge-separated current (`FT ELC`) (manual §10.2.5).
- Embedded unstructured meshes (`EMBED` card for Abaqus/HDF5 finite-element meshes inside CSG cells; manual §10.1.4) are not supported.
- User-compiled Fortran subroutines (`TALLYX`, `SOURCE`, `SRCDX`; manual §10.2.8 & §10.3.4) cannot be generated or executed from CSG/Python models.
- High-energy nuclear spallation physics models (CEM, LAQGSM, INCL > 150 MeV; manual §10.5) are outside OpenMC's transport scope.
- MCNP decks are validated with MontePy parser but require an MCNP installation to execute transport.
