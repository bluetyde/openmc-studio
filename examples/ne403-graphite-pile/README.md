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
| Apertures | 132 air channels (12 columns × 11 rows, 8 in pitch), 2 in squares turned 45°, full depth. They are one group, "Apertures" |
| Source drawer | Air, 0.75 in × 8 in × 0.75 in, long side along y, under the pile center, 1 ft above the bottom |
| Source | Box volume filling the drawer, isotropic |
| Tallies | Mesh flux tallies with 1 in bins: across (x) through row 3 at 40 in deep; along the depth (y) of column 7, row 3; up (z) column 7 at 40 in deep; and an XZ flux map at 40 in deep |
| Boundary | Vacuum, 1 ft past the pile's sides |

Coordinates: origin at the center of the whole pile, x across the front face, y into the pile
(front face at y = -121.92 cm), z up. Column 7 (from the left) is 4 in right of center; row 3 is
the third row from the bottom. The source is 4 in to the left of that column, as in Figure 1.

## Check before comparing with the lab

- **Source spectrum**: Studio has no tabulated spectrum yet, so the PuBe source is a Maxwell
  spectrum with T = 2.8 MeV (mean 4.2 MeV). Use the course's starter source for real numbers:
  replace the SDEF lines in the exported MCNP deck, or the source energy in model.py.
- **Row and column positions** come from Figure 1 (top row 4 in below the top, bottom row 12 in
  above the base, outer columns 4 in from the sides). Adjust `COL_X` and `ROW_Z` if the real pile
  differs.
- **He-3 response** ((n,alpha) reaction-rate tallies) isn't in the model yet.
- **Lattice**: the pre-lab asks for an MCNP repeated-structure lattice. Studio writes every
  aperture as its own cell instead; the geometry is the same, but the deck won't have LAT/FILL cards.
