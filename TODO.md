# TODO

What's next for OpenMC Studio, roughly in priority order. Updated 2026-09-19 (review of `c44381e..be160fe`
and the MCNP lattice work; fixes listed under Completed).

## Open items carried over

- **MCNP lattices, remaining**:
  - Rectangular lattices export as `LAT=1`/`FILL` and hexagonal ones as `LAT=2`/`FILL`, and both pass the
    geometry check. Tested: the pile, a deleted site, 3D and 2D arrays, an outer universe, hex arrays in both
    orientations and with two axial levels.
  - Still open: prove it once in real MCNP. Plot the pile deck and a hex deck with lattice index labels
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
- **PuBe spectrum**: the pile uses a Maxwell stand-in (T = 2.8 MeV). Paste the course's starter SI/SP
  cards into the tabulated source.
- **3D view at scale**: time the WebGL 2 BVH view on a few thousand parts; the 10,000-part figure is a
  target, not a measurement. The 128-candidate-per-ray limit tints overflowing pixels magenta.
- **Snap to grid**: re-check that a rotate drag lands on the typed step (e.g. 45°) in the browser.
- **Artifact comments**: the 7 threads on the published copy are addressed but still open; resolve them
  in the artifact view.
- **Name**: "OpenMabc" was floated; not decided.
- **Mac copy**: pull both repos (openmc-studio and openmc-mcnp-project) on the Mac; the exporter changes for
  detector tallies and lattices are on GitHub `main` now.
- **GEOUNED / CAD import**: browser import remains disabled. A real single-solid conversion spike and
  reproducible environment are implemented under `setup/cad/`; Studio integration is still pending.
  STEP export requires FreeCAD and supports selected primitives. See section 5 and
  [the implementation plan](docs/cad-import-plan.md) before enabling import.


---

## Active Backlog (Modular Architecture)

### 1. Core Workbench & Measurement Suite
- **3D Caliper & Dimension Measurement Tool**:
  - Interactive distance measurement in the 3D WebGL viewport and 2D slice views.
  - Click two points to measure distance in cm, inspect minimum clearance/gap, check wall thickness, and display coordinate readouts.
- **STL / OBJ Geometry Exporter**:
  - Tessellate and export 3D geometry to `.stl` for 3D printing physical reactor models (senior design, lab demos) or `.obj` for rendering in Blender/CAD.
- **Advanced Graphing Suite**:
  - **Lethargy Flux Spectrum**: Plot flux per unit lethargy $\phi(u) = E \cdot \phi(E)$ vs. $\log_{10} E$, presenting the thermal Maxwellian peak, $1/E$ slowing-down resonance region, and fission spectrum on equal footing.
  - **1D Spatial Line Cuts**: Extract 1D radial or axial flux profiles from 2D/3D mesh tallies with shaded $\pm 1\sigma$ Monte Carlo uncertainty bands.
  - **Reaction Rate & Absorption Breakdown**: Interactive pie and stacked bar charts detailing neutron fate (% absorbed in fuel vs moderator vs poison vs leakage).
- **Mesh maps: slabs, 3D and how to look at them** (full plan: `Claude Code Test\plans\mesh-maps-plan.md`):
  - A mesh tally is a **slab**: one axis has a single bin, so it looks like a sliver from any other view. The
    bins and corners are already editable in the tally properties; what's missing is saying so.
  - Stage 1: a Map control (XY / XZ / YZ slab or 3D box) with a thickness field, the voxel count **and the
    expected relative error**, an "add the other two planes" button, an edge-on hint in the viewport, and
    layer labels that name the plane.
  - Stage 2: a volume view for 3D maps (brightest-along-ray, isosurface), marched per pixel so resolution
    doesn't cost frames. Today a 3D mesh is tallied in full but drawn one slice at a time.
  - Stage 3: functional expansion tallies (`SpatialLegendreFilter`, `ZernikeFilter`, ...) for a smooth flux
    field with real error bars instead of a million voxels. Experiment on the pile first; MCNP has no
    equivalent, so the export must refuse it with a reason.
  - Stage 4: Gaussian splats for **event clouds** (fission, collision and source sites, track vertices), where
    each splat is one event. Not for mesh tallies: a fitted cloud smooths across material boundaries and is
    hard to read values from.
  - Note on cost: the same histories over 100x more voxels give about 10x the relative error, so a 3D map is a
    statistics decision, not a memory one.
- **VTK export of mesh tallies and geometry** (cheap): `mesh.write_data_to_vtk()` is one call and the official
  OpenMC plotter exports VTK too. Gives a real 3D flux view in ParaView now, without waiting for the volume
  renderer in the mesh plan's stage 2. Add STL export of the geometry for CAD viewers while we're there.
- **Overlap and lost-particle check before a run** (cheap): the official plotter has an overlap view for this.
  Problems catches modelling mistakes, but nothing catches two parts overlapping in space, which silently
  biases results. We already do this for MCNP decks in `geometry_check.py`; the OpenMC side is missing.
  Sample points (or use OpenMC's geometry-debug run) and report the offending pair in Problems.
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
- **Point Kinetics Parameters via Iterated Fission Probability (IFP)**:
  - Calculation and dashboard display of effective delayed neutron fraction $\beta_{\text{eff}}$, delayed group precursors $(\beta_i, \lambda_i)$, and prompt neutron lifetime $\ell_p$ / generation time $\Lambda$.
- **Core Depletion & Fuel Burnup (`openmc.deplete` & MCNP `BURN`)**:
  - Power history (MW), depletion timesteps (EFPD / MWd/kgHM), and interactive evolution curves for $k_{\text{eff}}$, U-235 consumption, Pu-239 breeding, and fission product equilibrium (Xe-135, Sm-149).
  - MCNP companion `BURN` card export: time steps, power levels, volume tracking (`MATVOL`), and CINDER90 inventory tracking (manual §10.3.3, Example 57).



### 3. Package: Radiation Protection & Detection Lab
- **Pulse Height Multichannel Analyzer (MCA) Spectrum (`openmc.PulseHeightFilter`)**:
  - Pulse height tally simulating true energy deposition spectra in scintillators and semiconductor detectors (NaI(Tl), HPGe, LaBr3, plastics).
  - Interactive MCA spectrum viewer with linear/log counts vs keV/MeV, photopeak identification, single/double escape peaks, and Compton edge marker.
- **Neutron Capture Multiplicity & Coincidence Counting (`FT CAP`)**:
  - Pulse multiplicity distributions, factorial moments, and coincidence time-gating (`gate predelay width`) on neutron capture absorbers ($^3\text{He}$, $^{10}\text{B}$) for safeguards counters (manual §10.2.5.5–§10.2.5.7, Examples 39 & 40; PRINT Table 118).

- **Fluence-to-Dose Conversion (ICRP / ANSI)**:
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
- **Import an MCNP deck** (`openmc_mcnp_adapter` converts MCNP models to OpenMC):
  - We already write MCNP decks *and* check them against the OpenMC model point by point. Import closes the
    loop: read a hand-written deck (e.g. the user's NE403 graphite deck) into Studio's scene graph, then run
    the existing geometry check to prove the round trip.
  - Expect gaps: macrobodies, lattices, transforms and repeated structures each need mapping back, and Studio
    parts are shapes rather than raw cells, so some decks will import as geometry we can display but not edit
    as parts. Say so per cell rather than failing the whole file.
- **FreeCAD / GEOUNED CAD import roadmap** (started 2026-09-23):
  - Full architecture, acceptance gates, environment setup and proposed ignore rules:
    [CAD import implementation plan](docs/cad-import-plan.md).
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
    `native` job modes, and **Convert > Import CAD…**: engine probe, inventory, mode choice (CSG shown, disabled),
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
  - [ ] **Stage 5 — parity and packaging:** companion MCNP export checks, real engine/browser integration
    CI, clean-machine setup and platform locks. CAD release checks cannot pass through dependency skips.
    Add IGES and further native shapes only after separate geometry-preservation tests.
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
  - The graphite pile has no cell that qualifies anyway: the aperture spans the full depth of its element and
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
    warning). model.mcnp writes arrays cell by cell; the pile's deck validates again (87,500 points).
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
  - Added material tally filter using `openmc.MaterialFilter` to evaluate reaction rates across distributed cells.
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
