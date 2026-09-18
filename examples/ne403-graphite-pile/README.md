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
| Source | Box volume filling the drawer, isotropic |
| Tallies | Cross-shape measurement tallies along the measurement channels: flux and He-3 proportional counter response ($^3\text{He}(n,p)^3\text{H}$, MT 103) across x (row 3 at 40 in deep), along depth y (col 7, row 3), up z (col 7 at 40 in deep), and an XZ map |
| Boundary | Vacuum, 1 ft past the pile's sides |

Coordinates: origin at the center of the whole pile, x across the front face, y into the pile
(front face at y = -121.92 cm), z up. Column 7 (from the left) is 4 in right of center; row 3 is
the third row from the bottom. The source is 4 in to the left of that column, as in Figure 1.

## Modeling Highlights

- **Array & Nested Groups**: The 132 apertures are structured using Studio's hierarchical grouping. The parent array group `Apertures (12×11 array)` has grid lattice metadata ($12 \times 1 \times 11$, 8 in pitch) and contains 11 collapsible row groups (`Row 11` down to `Row 1`). The measurement channel (`Aperture r3 c7`) is located inside `Row 3`.
- **He-3 Detector Response**: Includes both unweighted flux mesh tallies and He-3 reaction-rate response tallies ($^3\text{He}(n,p)^3\text{H}$, MT 103, 5316 b at thermal) along the measurement channels to simulate proportional counter readings.
- **Source Spectrum**: PuBe source modeled as a Maxwell spectrum with T = 2.8 MeV (mean energy 4.2 MeV, close to PuBe's). Can also be replaced with a tabulated spectrum using Studio's SI/SP card importer.
