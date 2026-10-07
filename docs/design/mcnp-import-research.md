# Importing MCNP decks Studio didn't write: which converter

Written 2026-09-26, before the import was built; kept as the record of why this converter. **Status:** geometry
and materials import is done this way (`studio/openmc_studio/mcnp_import.py`, Convert > Import MCNP deck); sources
and tallies are next.

## What was compared

- [openmc_mcnp_adapter](https://github.com/openmc-dev/openmc_mcnp_adapter) 0.1.0 (openmc-dev, MIT licence,
  Argonne): `mcnp_to_model(deck)` returns an `openmc.Model`.
- [csg2csg](https://github.com/makeclean/csg2csg) 0.0.27: converts between MCNP, Serpent, OpenMC, PHITS, FLUKA and
  SCONE; writes geometry.xml and materials.xml.

**Test decks with a known answer:** the six MCNP-bundle decks. Each is Studio's export of an OpenMC model that is
kept (`mcnp-bundle/work/<case>/export/model.xml`). The decks cover point, box and sphere geometry, macrobodies
(`RPP`, `RCC`), general planes and `GQ` (rotated boxes), `#` complements, a `LAT=1` lattice with a translated
`FILL` (a lab lattice deck), a `LAT=2` hex lattice, photon decks (`MODE N P`, `IMP:n,p`), and S(α,β) (`MT`).

**Check:** 3,000 random points in each model's bounding box; at each point, the material found by OpenMC's own
C++ geometry (`openmc.lib.find_material`, what transport uses), compared by atom density (void = 0) between the
converted model and the original. (A first version used the pure-Python `Geometry.find`, which ignores fill
translations and so blamed the adapter for the lattice test deck; the C++ lookup is the right oracle.)

## Results

| Deck | adapter | csg2csg |
|---|---|---|
| shielding_demo (RPP, spheres, GQ-free, S(α,β)) | 3000/3000 | 3000/3000, S(α,β) dropped |
| two_sources (photons, `IMP:n,p`) | 3000/3000 | **fails**: can't parse `IMP:n,p=` |
| current_box (plug cut from a box) | 3000/3000 | 3000/3000, S(α,β) dropped |
| dose_tank (photons) | 3000/3000 | **fails** (`IMP:n,p=`) |
| hex_array (`LAT=2`) | **refused**: "Hexagonal lattices not supported" | **fails** |
| a lab lattice deck (`LAT=1`, translated `FILL`, rotated boxes as `GQ`) | 3000/3000 | **fails** |
| a course draft deck, typo fixed (`*TR` in degrees, `LAT=1`, universes) | converts: 5 cells, 1 lattice | converts, but the lattice is lost (a plain fill) |

A draft course deck as it was doesn't convert with the adapter: surface 1 is `RPP -2.54 2.54 -2.54 -2.54 0 20.32`, zero
thickness in y (a typo; probably `-2.54 2.54`). The adapter refuses it with "ymin must be less than ymax".
That's the right call, though the message would need Studio's translation into "surface 1: …".

**What the adapter carries over:** cells, surfaces (including macrobodies, `GQ`, `*TR`/`TR`, `TRCL`), universes,
`LAT=1` lattices with explicit or single fills, materials with S(α,β). **What it doesn't:** tallies (none), the
source and run settings (`SDEF`/`NPS` are ignored: it returns a default eigenvalue settings object), material
names from comments, hex lattices.

## Recommendation

Build on **openmc_mcnp_adapter**. It was exact on every deck it accepted, it refuses what it can't do instead
of guessing, it is maintained by the OpenMC developers under MIT, and it returns an `openmc.Model`: the same
objects Studio's server already handles. csg2csg failed on four of six decks, drops S(α,β), and silently turned
a lattice into a plain fill, which is the worst failure mode for this use.

## How it fits Studio (step 1 built; 2-4 open)

1. **Geometry and materials through the adapter, shown as imported CSG.** Studio already has read-only imported
   CSG components from the CAD work (analytic cells with a region, rendered and exported). An imported deck
   becomes one component per top-level cell, universes and lattices kept as they are, plus Studio materials made
   from the deck's (names taken from the `c` comment above each `M` card when there is one). Editing imported
   geometry stays out of scope, as for CAD.
2. **Sources and tallies parsed by Studio itself**, for the subset Studio has: `SDEF` point/box/sphere/cylinder
   with `ERG` lines, `SP -2/-3/-4`, `SI H`/`SP D` histograms, `NPS`/`KCODE`; `F4` on cells with `E`, `FM`, `DE/DF`;
   `FMESH`; `F1` with `FS`. The companion exporter's validator already reads most of these cards back and would be
   the starting point. Anything else is listed in the Log as not imported, with its line, never dropped quietly.
3. **Hex lattices (`LAT=2`)**: contribute support upstream to the adapter, or convert them in Studio's own step
   until then; refuse with a clear message in the meantime.
4. **Checks:** every import is verified the way this report did it: point sampling of the imported model against
   the adapter's `openmc.Model`, and a round trip (import → Studio's own MCNP export → the exporter's geometry
   comparison). Test decks: the six bundle decks, the exporter's `pin_cell.mcnp`, course decks, and a few public benchmark decks (e.g. ICSBEP-style pin cells) for things Studio never
   writes (`TRCL`, `LIKE n BUT`, `#` of cells, repeated structures).

**Effort:** step 1 is 2–3 sessions (the CAD component path does much of the work), step 2 another 2, step 4 one;
step 3 depends on upstream.
