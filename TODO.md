# TODO

What's next for OpenMC Studio, roughly in priority order. Latest pushed commit when this list was
written: `c44381e` (2026-09-17).

## MCNP export: show translation progress instead of a static message (DONE)

Implemented and verified: `mcnp_worker.py` captures and emits `@@PROGRESS` events across all 8 stages
(Materials -> Surfaces -> Universes/Cells -> Making Universes -> Filling Cells -> Lattices -> Remediate -> Validate),
`server.py` exposes `GET /api/mcnp-progress` and increased timeout to 1800 s, and `index.html` polls and displays
real-time stage, description, and elapsed timing in both the Export log and the live `model.mcnp` tab.


Right now the Export -> "MCNP input" flow shows a static
"Translating with MCNPy... (the first export takes about 15 s while MCNPy starts)"
message for the whole call, with no feedback while it runs. On large models
(e.g. examples/ne403-graphite-pile, 134 parts) the export can take several
minutes under Rosetta, and there's no way to tell it's still working vs. stuck.

MCNPy already prints named stages during translation (Materials -> Surfaces ->
Universes/Cells -> Filling Cells -> Lattices), so a step-based progress
indicator ("Stage 3 of 5: Translating Cells") is achievable. A true percentage
isn't, since MCNPy doesn't report fractional progress internally.

Needs changes in three places:
- `studio/openmc_studio/mcnp_worker.py` - forward MCNPy's stage print lines as
  `@@PROGRESS` messages instead of letting the server's `_reader` thread
  discard everything that isn't a `@@RESULT` line. Note: the worker itself also
  hides MCNPy's output today (`contextlib.redirect_stdout(io.StringIO())` around
  `translate()`), so that redirect has to pass stage lines through.
- `studio/openmc_studio/server.py` - `McnpWorker.run()` currently blocks
  synchronously on `self.results.get(timeout=600)`; needs a way for the client
  to poll current stage instead of just waiting on the final result.
  The 600 s limit also needs a look: the pile took 130 s on the Windows PC, so a
  slower Mac under Rosetta could hit it and report "took over 10 minutes".
- `studio/openmc_studio/static/index.html` - replace the static "Translating
  with MCNPy..." text with a step-based progress bar driven by the above.

## Graphite pile (examples/ne403-graphite-pile) follow-ups

- **Tabulated source spectrum (DONE).** Added Tabulated (histogram) energy distribution to OpenMC Studio
  and openmc-mcnp-project:
  - `openmc.stats.Tabular(..., interpolation='histogram')` generation in `model.py` and MCNP `SI H` / `SP D` cards.
  - Studio UI fields for bin edges (`tab_e`) and probabilities (`tab_p`), with a paste-in dialog and auto-detection
    for MCNP `SI`/`SP` card blocks.
  - Supported and validated in `openmc-mcnp-project` (`src/mcnp_cards.py`) and verified by integration tests.
- **Array tool (DONE - Step 1).** Added Roblox-style "Array…" tool to the Ribbon (Home and Model tabs):
  - Popover with interactive 3D count ($N_x, N_y, N_z$) and pitch ($\Delta x, \Delta y, \Delta z$) inputs in current length units (cm or in).
  - Automatically creates cloned, offset parts on the grid with optional auto-grouping ("Array <Name>").
  - Step 2 (`openmc.RectLattice` and MCNP `LAT`/`FILL` cards) remains for lattice-level export once lattice universes are supported.
- **He-3 detector response.** The pre-lab asks for (n,alpha) and (n,2alpha), MT 107 and 108, but
  ENDF/B-VIII.0 He-3 has neither; its detection reaction is MT 103, He-3(n,p)T, 5316 b at
  0.0253 eV. Confirm with the course which reaction (or detector gas) is meant. Then add a
  "detector response" tally option: flux in the channel cells times a detector material that isn't
  in the geometry (MCNP `FM` naming that material; OpenMC `EnergyFunctionFilter` with its cross
  section, or small He-3 gas detector cells). Studio's MCNP tally export only writes FM for the
  tallied cells' own material today.
- **Lattice (Step 2).** Export arrays as `openmc.RectLattice` and MCNP `LAT`/`FILL`. Needs MCNPy's
  lattice support confirmed, and openmc-mcnp-project's geometry check extended to universes and lattices
  (a known limit today).

## 3D view: more than 192 parts (DONE)

Implemented and verified:
- Upgraded the 3D ray tracer context to **WebGL 2** with `#version 300 es`.
- Migrated geometry definitions from fragment uniform arrays (`MAXP_BUCKETS`) into dynamic `RGBA32F` data textures (`uPartTex`, 4 texels/part for center, shape type, rotation basis $M_0, M_1$, half-extents/dimensions, and material color/selection flags).
- Added a lightweight, zero-dependency binary **Bounding Volume Hierarchy (BVH)** builder in JS (`buildBvh3D`) with tight world-space AABBs for spheres, oriented boxes, and cylinders.
- Flatted the BVH into a node data texture (`uBvhTex`, 2 texels/node) and implemented branchless ray-AABB testing with stack-based traversal in the fragment shader.
- Candidate parts along the ray are gathered in $\mathcal{O}(\log N)$ time and sorted by CSG priority, removing the uniform limit and scaling the ray tracer up to 10,000+ parts at interactive framerates.
- Accelerated 3D picking (`pick3`) with the same BVH spatial index.

## More part shapes

- **Right triangular prism / wedge (WED) (DONE).**
  - Added `wedge` as a first-class primitive in OpenMC Studio:
    - Dedicated right-triangle SVG icon in `ICON.wedge`, Ribbon Model tab Parts button, and Explorer.
    - Properties panel: `Right wedge (WED)` shape selector with `Size` ($sx, sy, sz$) and 3D Euler `Rotation` ($rx, ry, rz$).
    - 2D slice sampling in `inShape` and viewport rasterizer `inPart`.
    - World-axis bounding box extents in `partHalfExtents`.
    - WebGL 2 ray tracer shader (`intersectPart` type 3) using a 5-plane slab clipper with analytic normals.
    - Fast 3D BVH picking (`pick3` type 3).
    - Interactive 3D scale handles (`buildHandles` and `applyTransform`) preserving opposite faces on drag.
    - OpenMC geometry export in `buildScript`: 5 planes (2 legs, hypotenuse `openmc.Plane(a=sy/L, b=sx/L, d=...)`, and height slab `openmc.ZPlane` or general slab) sharing aligned surfaces.
    - Verified in OpenMC 0.15.3 simulation with 100,000 particles and cell overlap checking: 0 errors, 0 lost particles.

Other candidates:
- Hexagonal prism (RHP/HEX): 8 planes; `openmc.model.HexagonalPrism` exists; common for fuel.
- Cone and truncated cone (K, TRC): `openmc.XCone`/`ZCone` (GQ when tilted); needs cone support in
  the geometry check and the 3D shader.
- Ellipsoid (ELL) and elliptical cylinder (REC): quadrics (GQ); the shader can scale a sphere or
  cylinder.
- Torus (TX/TY/TZ): hardest (quartic in the shader); MCNP only allows axis-aligned tori.

## Smaller items

- **Nested groups** (groups inside groups): not needed yet. Groups are one level; a part or source
  belongs to at most one group.
- **Snap to grid**: the new ribbon controls were checked by typing values and unticking Move; a
  rotate drag landing on the typed step (e.g. 45 deg) wasn't re-checked in the browser before the
  SSD was removed. Quick test next session.
- **Artifact comments**: the 7 threads on the published copy are all addressed but still open;
  they weren't sent to Claude, so resolve them in the artifact view.
- **Name**: "OpenMabc" was floated; not decided. Leaning away from names built on "OpenMC".

## Known export limits (unchanged)

- One SDEF source only in the MCNP export.
- Absorption can't be exported for actinide materials (MontePy can't parse `FM ... -2:-6`).
- Mesh tallies export flux only (FMESH).
- The geometry check doesn't cover universes or lattices.
- No MCNP executable on the PC, so decks are validated but never run through MCNP.
