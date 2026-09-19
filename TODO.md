# TODO

What's next for OpenMC Studio, roughly in priority order. Latest pushed commit: `49f85da` (2026-09-18).

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

### 2. Package: Reactor Physics & Core Safety
- **Automated Reactivity Coefficient Sweeps**:
  - **Moderator Density / Void Coefficient ($\alpha_v$)**: Parameter sweep of moderator density ($0 \to 100\%$ void) with automated plot of $k_{\text{eff}}$ and derivative $\alpha_v = \partial \rho / \partial v$ in $\text{pcm} / \% \text{void}$.
  - **Doppler Fuel Temperature Coefficient ($\alpha_T$)**: Temperature sweep ($300\text{ K} \to 1800\text{ K}$) using OpenMC Doppler broadening to determine Doppler defect and $\alpha_T = \partial \rho / \partial T$ in $\text{pcm}/\text{K}$.
  - **Pitch-to-Diameter ($p/d$) Ratio Sweep**: Lattice pitch sweep mapping the transition between under-moderated and over-moderated core regimes ($k_\infty$ maximum).
  - **Critical Mass / Dimension Search**: Binary search routine for critical radius, enrichment, or soluble boron concentration to achieve $k_{\text{eff}} = 1.00000$.
- **Point Kinetics Parameters via Iterated Fission Probability (IFP)**:
  - Calculation and dashboard display of effective delayed neutron fraction $\beta_{\text{eff}}$, delayed group precursors $(\beta_i, \lambda_i)$, and prompt neutron lifetime $\ell_p$ / generation time $\Lambda$.
- **Thermal Scattering Tables $S(\alpha, \beta)$**:
  - Material inspector selector and automatic composition suggestion for `c_H_in_H2O`, `c_H_in_polyethylene`, `c_Graphite`, `c_D_in_D2O`, `c_Be` with MCNP `MT` cards.
- **Core Depletion & Fuel Burnup (`openmc.deplete`)**:
  - Power history (MW), depletion timesteps (EFPD / MWd/kgHM), and interactive evolution curves for $k_{\text{eff}}$, U-235 consumption, Pu-239 breeding, and fission product equilibrium (Xe-135, Sm-149).

### 3. Package: Radiation Protection & Detection Lab
- **Pulse Height Multichannel Analyzer (MCA) Spectrum (`openmc.PulseHeightFilter`)**:
  - Pulse height tally simulating true energy deposition spectra in scintillators and semiconductor detectors (NaI(Tl), HPGe, LaBr3, plastics).
  - Interactive MCA spectrum viewer with linear/log counts vs keV/MeV, photopeak identification, single/double escape peaks, and Compton edge marker.
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

---

## Completed

- **Hexagonal Lattices (`openmc.HexLattice`)**:
  - Full support for hexagonal arrays with flat-to-flat pitch, concentric ring universe assignments (outermost ring down to center), $x$/$y$ orientation, and solid moderator fill.
  - Interactive Hexagonal array tool in editor UI with pitch, rings, and orientation settings.
  - Python `openmc.HexLattice` script generation and MCNP `LAT 2` export compatibility.
- **Cylindrical Mesh Tallies**:
  - Support for `openmc.CylindricalMesh` ($r, \phi, z$) with custom radial, azimuthal, and axial binning grids and arbitrary spatial origin.
  - Full simulation extraction in `results.py` and 2D canvas annular-sector slice rendering in UI.
  - MCNP export with `FMESH ... GEOM=CYL ORIGIN=... AXS=0 0 1 VEC=1 0 0`.
- **Ellipsoid & Quadric Primitives**:
  - General ellipsoid primitive (`openmc.Quadric`) supporting semi-axes $a, b, c$, arbitrary 3D center, and full 3D Euler rotations.
  - Analytical ray-ellipsoid quadratic intersection in WebGL 2 raymarching fragment shader (`ty == 6`).
  - Exact CPU ray picking and 2D canvas slice cross-section rendering.
  - MCNP quadric/ellipsoid translation (`SQ`/`ELL`).

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
  - Multi-nuclide custom detector responses with $N_i$-weighted cross-section interpolation across all constituent nuclides on a unified energy grid, invariant to composition text order.
- **3D Dense Raymarching BVH Acceleration**:
  - Primitive intersection filtering at BVH leaf nodes prior to stack insertion; increased candidate budget from 96 to 128 with visual overflow diagnostic tint.
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
  - Native `openmc.RectLattice` and MCNP `LAT 1` export with unit universes and oriented tilted surfaces, reducing code from >1000 lines down to ~216 lines.
  - Support for missing/deleted array lattice elements using solid moderator universes.
  - Automatic host moderator material detection and UI selector.
- **He-3 Proportional Counter Detector Response**:
  - Unperturbed virtual detector response tallies with `openmc.EnergyFunctionFilter` and MCNP `FM` multiplier cards.
- **3D WebGL 2 Raymarching with BVH**:
  - Accelerated rendering supporting 10,000+ parts using data textures and BVH stack traversal.
- **Additional Geometry Primitives**:
  - Right triangular prism / wedge (`wedge`), Hexagonal prism (`hex_prism`), and Truncated cone (`cone`).
- **Tabulated Source Energy Spectrum**:
  - `openmc.stats.Tabular` histogram energy distribution with MCNP `SI`/`SP` card generation.
- **Nested Groups Architecture**:
  - Hierarchical Explorer tree, collapsible groups, rigid parent-child transformations, and structured MCNP `c Group:` annotations.

---

## Known Export Limits

- One `SDEF` source only in the MCNP export.
- Absorption can't be exported for actinide materials (MontePy can't parse `FM ... -2:-6`).
- Mesh tallies export flux only (`FMESH`).
- The geometry check doesn't cover universes or lattices.
- MCNP decks are validated with MontePy parser but require an MCNP installation to execute transport.
