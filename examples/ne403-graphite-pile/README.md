# NE 403 graphite pile (Studio example)

A model of the UT graphite pile from the NE 403 pre-lab "Neutron diffusion length measurement
using the Graphite Pile (part I)", built as an OpenMC Studio project.

## Open it

1. Start OpenMC Studio.
2. **Export ▸ Open project** and pick `graphite-pile.openmc-studio.json` from this folder.
3. Use **XZ** with the slice at y = -20.32 cm (40 in deep) to see the front face, or **3D** with
   Cutaway.

`make_project.py` writes that file. Run it again after editing the dimensions at its top:

```
python make_project.py
```

## What's in the model

| Item | Value |
|---|---|
| Pile | 8 ft wide (x) × 8 ft deep (y) × 10 ft tall (z): a 2 ft solid base under an 8 ft apertured block |
| Graphite | PNNL-15870 #63, Carbon, Graphite (Reactor Grade), 1.7 g/cm³, c_Graphite thermal scattering |
| Apertures | 132 air channels (12 columns × 11 rows, 8 in pitch), 2 in squares turned 45°, full depth. Modeled as an array group `Apertures (12×11 array)` with nested row groups |
| Source drawer | Air, 0.75 in × 8 in × 0.75 in, long side along y, under the pile center, 1 ft above the bottom |
| Source | Box volume filling the drawer, isotropic, ISO 8529-1 Pu-Be tabulated (alpha, n) spectrum (39 bins, 0.05 to 10.75 MeV) |
| Tallies | Cross-shape measurement tallies along the measurement channels: flux, He-3 proportional counter response ($^3\text{He}(n,p)^3\text{H}$, MT 103), and B-10 BF3 counter response ($^{10}\text{B}(n,\alpha)^7\text{Li}$, MT 107) across x (row 3 at 40 in deep), along depth y (col 7, row 3), up z (col 7 at 40 in deep), and an XZ map |
| Boundary | Vacuum, 1 ft past the pile's sides |

Coordinates: origin at the center of the whole pile, x across the front face, y into the pile
(front face at y = -121.92 cm), z up. Column 7 (from the left) is 4 in right of center; row 3 is
the third row from the bottom. The source is 4 in to the left of that column, as in Figure 1.

## Pre-Lab Experimental Measurements (Figure 1)

1. **Depth Measurements ($y$)**: 10 discrete measurement positions along Channel (Column 7, Row 3) in 8-inch depth increments ($8", 16", 24", 32", 40", 48", 56", 64", 72", 80"$ from the front face).
2. **Transverse Measurements ($x$)**: 12 aperture channels across Row 3 at an indicated depth of 40 inches.
3. **Vertical Measurements ($z$)**: 11 row apertures up Column 7 at an indicated depth of 40 inches.
4. **Detector Responses**: Reaction rates for He-3 ($(n,p)$ MT 103, 5316 b at thermal) and B-10 ($(n,\alpha)$ MT 107, 3837 b at thermal).

## Automated Diffusion Length Analysis

The companion script `analyze_diffusion_length.py` extracts the discrete measurement tables, fits the spatial flux profiles to thermal diffusion theory, computes the graphite diffusion length $L$, and outputs publication-quality diagnostic plots:

```bash
# Instant run with analytical diffusion theory benchmark data:
python analyze_diffusion_length.py --demo

# Run with actual OpenMC simulation statepoint:
python analyze_diffusion_length.py --statepoint statepoint.10.h5
```

The script extracts:
- Extrapolated transverse width $\tilde{a} = a + 2d$ and depth $\tilde{b} = b + 2d$ from cosine fits: $\phi(x) \propto \cos(\pi x / \tilde{a})$.
- Spatial relaxation constant $\gamma = 1/L_{11}$ from asymptotic axial decay: $\phi(z) \propto \sinh(\gamma (H_{\text{ext}} - z))$.
- Thermal neutron diffusion length:
  $$\frac{1}{L^2} = \gamma^2 - \left(\frac{\pi}{\tilde{a}}\right)^2 - \left(\frac{\pi}{\tilde{b}}\right)^2 \implies L \approx 53.6 \pm 0.4\text{ cm}$$
- Saves a 4-panel diagnostic plot to `diffusion_length_profiles.png`.

## Modeling Highlights

- **Array & Nested Groups**: The 132 apertures are structured using Studio's hierarchical grouping. The parent array group `Apertures (12×11 array)` has grid lattice metadata ($12 \times 1 \times 11$, 8 in pitch) and contains 11 collapsible row groups (`Row 11` down to `Row 1`). The measurement channel (`Aperture r3 c7`) is located inside `Row 3`.
- **He-3 & B-10 Detector Responses**: Includes unweighted flux mesh tallies, He-3 reaction-rate response tallies ($^3\text{He}(n,p)^3\text{H}$, MT 103), and B-10 reaction-rate tallies ($^{10}\text{B}(n,\alpha)^7\text{Li}$, MT 107) along all measurement channels.
- **ISO 8529-1 Pu-Be Source Spectrum**: Realistic standardized $(\alpha, n)$ tabulated histogram spectrum with 39 bins covering $0.05 \to 10.75\text{ MeV}$, generating `openmc.stats.Tabular` in Python and native `SI H / SP D` cards in MCNP.
