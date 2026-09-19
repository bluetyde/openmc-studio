# TODO

What's next for OpenMC Studio, roughly in priority order. Latest pushed commit: `ad60cf6` (2026-09-18).

---

## Active Backlog

### Core Capabilities for Future Sprints

#### Lattices & Geometries
- **Hexagonal Lattices (`openmc.HexLattice`)**:
  - Support hexagonal arrays with flat-to-flat pitch and concentric ring universe assignments for VVER, fast reactors (SFR), and hexagonal graphite blocks.
- **Cylindrical Mesh Tallies**:
  - Support `openmc.CylindricalMesh` ($r, \theta, z$) in addition to `openmc.RegularMesh` for cylindrical reactor cores, pressure vessels, and beam tubes.
- **Ellipsoid & Quadric Primitives**:
  - Ellipsoid (`openmc.Ellipsoid`) and Elliptical Cylinder (`openmc.ZCylinder` / `openmc.Quadric`).

---

## Completed

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
