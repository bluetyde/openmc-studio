# Plan: make the flux map's slab obvious and easy to change

**Status (2026-09-26):** stage 1 done; stage 2's first milestone done (see [flux-volume-view-plan.md](flux-volume-view-plan.md)); stages 3-4 not started. Current support: [../SUPPORT.md](../SUPPORT.md).

Task F. Studio branch `claude/mesh-maps`. Written 2026-09-20, after a flux map looked like a narrow column in
the YZ view: the map is a one-voxel-thick sheet (`dimension = [100, 1, 100]`, y from -5 to 5), seen edge-on.

## Where the settings already are

Select the mesh tally in the Explorer and the Properties panel shows `Bins (XYZ)`, `Lower corner` and
`Upper corner` (index.html, the tally fields near the `meshGeom` select). They are `dimension`, `lower_left`
and `upper_right` from model.py. Values are held in cm and shown in the chosen unit, so they read in inches
while the imperial display is on.

So nothing is hidden. What's missing is that a mesh **is** a slab, which way it faces, and how to change that
without editing three vectors by hand.

## 1. A "Map" control in the tally properties (regular meshes only)

- A select: **XY slab · XZ slab · YZ slab · 3D box**, derived from the current bins (the axis with one bin
  names the slab; none means 3D). Nothing new is stored, so old projects and fixtures still load.
- Choosing a slab sets that axis to 1 bin and centres it on the current viewport slice; choosing 3D gives the
  flat axis the same bin count and extent as the larger of the other two.
- A **Thickness** field next to it, shown for slabs only: the extent along the flat axis (its corners stay
  symmetric about the centre). Same unit handling as the corner fields.
- A **Centre on the current slice** button, for when the viewport has moved since the map was made.

## 2. Say how big it is, and how noisy, before it's too late

- Under the fields, one line: voxels = nx·ny·nz, the per-voxel size in the current unit, and the **expected
  relative error** per voxel at the current particle count.
- The error is what actually limits a 3D map. The same histories spread over 100x more voxels give about 10x
  the relative error, so a sheet at 1% goes to roughly 10% as a box. Scale from the last run's mesh tally when
  there is one (error scales as 1/sqrt(counts per voxel)), otherwise from particles x batches over voxels.
- The existing "over a million voxels" warning stays; add the same numbers to the Problems entry.
- For the 3D box, the control is a single **resolution** N (voxels per axis over the box), with the three bin
  fields still there for anyone who wants them uneven.

## 3. Three planes in one go

- In the tally properties, a button **Add the other two planes**: copies the selected map twice, flipping the
  flat axis, names them `<name> (XY)` / `(XZ)` / `(YZ)`, and keeps bins and extents consistent.
- The graphite pile model already does this by hand; this is the same thing without the typing.

## 4. Tell the user when a map is edge-on

The real problem in the screenshots is silence: the map was there, but nearly invisible.

- When a visible mesh layer's flat axis lies in the current view plane, the viewport hint line reads, e.g.
  "Flux map (XZ) is edge-on here — switch to the XZ view, or give it thickness."
- When the current slice sits outside a map's extent, say that instead: "Flux map (XZ) covers y = -5 to 5 in;
  this slice is at y = 40."
- Both are hints in the viewport, not Problems entries: nothing is wrong with the model.

## 5. Label the layers

- In the layer list, each mesh layer gets its plane and thickness: `Flux map (XZ) · slab y = 0 ± 5 cm`, or
  `· 3D box, 100³ voxels` when it isn't a slab. That alone would have answered the question.

## Stage 1 tests

- `test/test_frontend_model.js`: the Map control round-trips (XZ slab → 3D → XZ slab gives back the same bins
  and corners); Thickness changes only the flat axis; "Add the other two planes" makes three tallies with the
  right flat axes and names; the edge-on hint fires for a slab seen from a perpendicular view and not from its
  own; the voxel count is right.
- `test/generate_fixtures.js`: a `flux_3d` fixture (a real 3D box mesh) plus its `_mcnp` twin.
- `test/test_generated_models.py`: the 3D mesh builds and runs, and its tally has the expected shape.
- Worker end-to-end: `flux_3d_mcnp` exports; the `FMESH` card carries all three `INTS` greater than 1. The
  per-cm² note in the export still applies and should appear.
- Re-run the other agents' suites (cylindrical view, tally ownership, MCNP editor and columns) since they
  touch the same file.

## Stage 1 risks

- `index.html` is edited by three agents; keep to the tally-properties block, the layer list and the viewport
  hint, rebase before merging, and run their tests.
- Unit display: corners and thickness are cm underneath, inches on screen. Convert in one place, and test the
  imperial path.
- A cylindrical mesh has its own fields (`nr`, `nphi`, `nz`, radius, z, origin). The Map control is for regular
  meshes only; leave cylindrical alone, since Codex has just reworked its editing and rendering.
- Going 3D multiplies voxels and memory: a 100×1×100 sheet is 10k voxels, 100×100×100 is a million. That's why
  the count and the warning come with the control rather than after the run.

---

# Stage 2: see the 3D map as a volume (separate branch, after stage 1)

Today a 3D mesh is tallied in full but drawn one slice at a time: `meshLayer()` picks the single slice at the
current view plane, and `drawMesh3D()` ray-marches that. So the data is already 3D and the view is not. Stage 1
makes 3D maps easy to ask for; this stage makes them worth looking at.

Why it's worth doing: the usual route to a 3D flux picture is exporting to ParaView or VisIt. A built-in
volume view that you can orbit, with no export, is unusual in a teaching tool and follows from the renderer we
already have (it ray-marches per pixel and occludes against the geometry).

- **Volume mode** for a 3D mesh layer, chosen in the layer list beside the existing slice mode:
  - **brightest along the ray** (maximum intensity projection): one clear answer per pixel, no blending
    guesswork, cheap;
  - **isosurface** at a level the user picks ("where is flux above 10% of peak"), which reads as a shape
    rather than fog;
  - transparency-blended emission as a third option if the first two feel flat.
- **Performance**: march a coarse step while the camera moves and refine when it stops; keep the existing
  depth buffer so geometry still occludes the cloud. Budget the march by pixels, not voxels, so a 100³ map
  costs the same per frame as 50³.
- **Colour**: keep the existing log ramp and the legend, so a volume and a slice of the same tally agree.
- **Stretch, genuinely rare**: refine where it matters. Run coarse, find the voxels with the steepest gradient
  or the worst relative error, and offer a second tally refined only there. Nothing in this class of tool does
  that on its own.
- **Tests**: the renderer has a canvas test double already (`test/test_cylindrical_view.js`) - use the same
  approach: a known 3D array whose brightest voxel must land at a known pixel, an isosurface that must be
  empty below the peak and non-empty above, and geometry occlusion still hiding voxels behind a part.

---

# Stage 3: a smooth flux field without voxels (functional expansion tallies)

The instinct behind "represent the flux smoothly instead of as a million boxes" already has a rigorous form,
and OpenMC ships it: `SpatialLegendreFilter`, `ZernikeFilter`, `ZernikeRadialFilter`, `SphericalHarmonicsFilter`.
These tally the **moments of a basis expansion during transport**, so the smooth field comes with proper
uncertainties on each coefficient. A Gaussian fitted to voxels afterwards is a picture of the data; an
expansion tally is the data.

- **Experiment first, no UI.** One script, one model: the graphite pile with a `SpatialLegendreFilter` in z
  along a channel, order ~6-10, beside the existing mesh map of the same line. Compare the curve and the error
  bars against the 96-bin mesh for the same particle count, and see which is smoother per CPU second.
- Only if that reads well: a Studio tally kind "profile (Legendre)" with an axis, a range and an order, drawn
  as a curve with an error band in the Results panel rather than as a layer in the viewport.
- **MCNP has no equivalent**, so such a tally must be refused by the exporter with that reason, the way
  surface currents were before `FS`. Studio would say so in Problems before the export does.
- For the pile this is a natural fit: flux against depth as one smooth curve with error bars, instead of
  96 noisy bins, is exactly the plot the lab asks for.

# Stage 4: Gaussian splats, for event clouds rather than meshes

3D Gaussian splatting fits this app, but not on the mesh. Splatting a mesh tally means blending a fitted cloud
over data that already has a grid: it smooths across material boundaries where flux genuinely steps, and a
blended cloud is hard to read a number off. Brightest-along-ray and isosurfaces (stage 2) stay more honest.

Where splats do earn their place is the data that has **no grid**:

- fission sites, collision sites and source sites;
- track vertices from `tracks.h5`, which the viewport already draws as lines.

Each splat is then one event, not a fit, so nothing is invented. A density cloud of collision sites shows
where neutrons actually interact, orbitable, with no mesh tally at all.

- The 3D view is already WebGL 2 with its own BVH, so splats have a home: point sprites with an anisotropic
  covariance, depth-sorted back to front, blended into the existing depth buffer so geometry still occludes.
- Start with collision or fission sites from a small run, one colour ramp by energy, with a size control.
- Only after that, and only if someone asks: splats as a level-of-detail layer for a 3D mesh tally, clearly
  labelled a visualisation, with the voxel values still authoritative. Weight any such fit by 1/sigma^2 so
  noisy voxels don't pull the shape around.

**Order across all four stages**: stage 1 (small, fixes the confusion), stage 2 (makes 3D maps worth looking
at), stage 3 (physics-grade smooth field, experiment first), stage 4 (event clouds; visual, optional).
