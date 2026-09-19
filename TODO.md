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
  - **RPP Macrobody Element**: Represent the `LAT=1` base element cell using a single `RPP` macrobody card instead of 6 individual `PX/PY/PZ` planes (improves deck readability and matches human-written deck conventions; requires adding `RPP` support to `geometry_check.py`).
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
- **GEOUNED**: commit be160fe's title says "add GEOUNED integration", but only the backlog entry below
  exists; nothing is integrated yet.


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
- **Stochastic Geometry Volumes (`openmc.calculate_volumes`)**:
  - Stochastic ray-tracing volume calculation populating volume $\pm 1\sigma$ directly onto parts/materials for volumetric normalization ($\text{reactions/cm}^3/\text{s}$).
- **Multiple Independent Sources (`SDEF` Multi-Source)**: done in the MCNP export.
  - One SDEF: `ERG=Dn` with `SI n S` picks the source, and `SP n` gives the strengths. Everything else is
    `=FERG=`, with one DS entry per source (manual p. 379-408). The validator reads every source back and
    compares it with OpenMC.
  - Still open: a box source together with a sphere or cylinder source. MCNP's one SDEF card has one volume
    shape, so the export refuses the mix; Problems could warn. Points mix with any one shape.
  - In model.mcnp, clicking source cards only links to a source when there's one source.
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

### 5. Package: CAD & Geometry Interoperability
- **GEOUNED CAD-to-OpenMC Translation**:
  - Integration with **GEOUNED** (open-source tool developed by UNED utilizing FreeCAD and OpenCASCADE):
    - **CAD to CSG**: Convert standard engineering CAD models (STEP / IGES) into native OpenMC constructive solid geometry (CSG) surfaces and cells with analytical representations.
    - **CSG to CAD**: Round-trip export of OpenMC Studio CSG models back into STEP format for modification in commercial CAD software (SolidWorks, Inventor, FreeCAD).
    - Automatic solid decomposition and void region generation for complex nuclear components.
- **DAGMC Direct Accelerated Geometry**:
  - Direct import and visualization of faceted DAGMC `.h5m` surface mesh models.
- **OpenMC Python & XML Importer**:
  - Drag-and-drop parser for existing `model.py` scripts and XML suites (`geometry.xml`, `materials.xml`, `settings.xml`, `tallies.xml`) into OpenMC Studio's scene graph.

### 6. MCNP 6.3 Performance & Geometry Optimizations (Research Analysis)
- **Negative Universes (`u=-n`) for Lattice Tracking Acceleration**:
  - Manual ref: §5.5.5.1 (PDF p. 288–289). Precede the `u=` entry with a minus sign (e.g. `u=-2`) for any finite cell fully enclosed by the unit cell boundary (fuel pellet, clad, inner gas gap). Tells MCNP tracking to skip distance-to-boundary calculations against higher-level lattice boundaries, yielding an estimated 10–25% speedup in particle tracking.
- **Macrobodies (`RPP`, `RCC`, `HEX`) vs. Primitive Half-Space Planes**:
  - Manual ref: §3.4.1 #5 (PDF p. 243) & §5.3.4 (PDF p. 271–278). Replace sets of 6 planar surfaces (`PX`, `PY`, `PZ`) with native `RPP` macrobodies, and cylindrical pins with `RCC`. Reduces surface card counts by up to 75%, simplifies boolean intersections, and accelerates MCNP internal ray-bounding evaluations.
- **Pruning the Complement Operator (`#`)**:
  - Manual ref: §3.4.1 #6 (PDF p. 243) & §2.2.1 (PDF p. 56). Avoid nested `#` complement tokens which trigger de Morgan surface expansions during particle tracking.
- **Direct Analytic Source Sampling (`SP -2`, `SP -3`)**:
  - Manual ref: §5.8.1–5.8.3 (PDF p. 379, 396–400). Replace large discrete histogram tables (`SI/SP`) with closed-form analytic sampling (Maxwell `SP -2`, Watt fission `SP -3`, Gaussian fusion `SP -4`) for $O(1)$ random number evaluation.
- **I/O & Worker Disk Overhead Reduction (`PRDMP 0 0 0 0`)**:
  - Manual ref: §3.4.3 #2 (PDF p. 244). Add `PRDMP 0 0 0 0` and suppress unneeded print tables in automated worker runs to eliminate scratch `RUNTPE` disk writes.

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

