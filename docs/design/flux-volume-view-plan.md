# Plan: 3D volume view of flux maps (mesh-maps plan, stage 2 in detail)

> **Status (2026-09-26):** milestone 1 done (Slice / Brightest / Surface / Hide noisy). Since then rays step
> voxel to voxel instead of half a voxel at a time (a fixed step skipped thin voxels), and maps too fine for that
> fall back to the slice with a note. Since 2026-09-26 also: cylindrical maps, Glow, and half-resolution drawing
> while the camera moves. Nothing in this plan is open.

Task I. Studio branch `claude/volume-view`. Written 2026-09-25. Builds on stage 1 (done): 3D box maps are now
easy to make.

Goal: in the 3D view, a 3D flux (or dose) map is drawn as a volume you can orbit, not one slice at a time,
with the geometry still hiding what's behind it.

## What we have (checked 2026-09-25)

- The 3D view is WebGL 2: a ray-traced geometry pass (writes depth), kernel meshes for imported CAD, and a
  per-pixel depth readback (`V3.depth`, RGBA-packed distances) used to occlude overlays.
- Today a mesh map is drawn in 3D by `drawMesh3D()`: a **JavaScript loop over every pixel** that intersects
  the ray with the slice plane, looks up the voxel and checks the depth. One slice only, and on the CPU,
  so it can't simply march through the volume: at 1500x900 pixels and 200 steps that's 270M lookups a frame.
- WebGL 2 has 3D textures (`texImage3D`, guaranteed up to 256³) and float/half-float formats.

## Design

- **Upload**: when a 3D map is shown, normalise its values to 0-1 on the same log scale as the legend and
  upload them as a 3D texture (`R8` for the colour index; a second `R8` mask for voxels to hide). 100³ is 1 MB;
  anything over 256 per side is reduced (max-pooling for "brightest", averaging for the rest) with a note.
- **Ray-march on the GPU**: a full-screen pass. Each pixel's ray is clipped to the map's box, to the cutaway
  half-space (the same one the geometry uses, so you can cut the model open and see inside the flux), and to
  the geometry's depth, then marched at half a voxel per step.
- **Three looks**, chosen in the layer controls in 3D mode (Slice stays the default):
  - **Brightest along the ray** (maximum intensity): one clear value per pixel, cheap, no blending guesswork.
  - **Surface at a level**: the first point where the map crosses a level the user picks ("flux above 10% of
    peak"), shaded from the local gradient, so it reads as a shape.
  - **Glow**: emission-absorption blending, for a soft cloud; last, and only if the first two feel flat.
- **Hide noisy voxels**: an option to leave out voxels whose relative error is over 50%, using the error
  numbers stage 1 already reports. A volume view otherwise gives a lot of visual weight to pure noise.
- **Depth**: upload the existing `V3.depth` readback as a texture and decode it in the shader, so the volume
  is occluded exactly like the slice overlay is today. (A shared depth texture from the geometry pass would
  avoid the readback; that's a later optimisation, not needed for correctness.)
- **Speed**: while orbiting, march at double step and half resolution; refine when the camera stops. The cost
  depends on pixels x steps, not on voxel count, so 100³ and 200³ feel the same.
- **Colour**: the same viridis log ramp and legend as the slice view, so a volume and a slice of the same map
  agree. Dose maps (dose plan, stage 2) work the same way.

## Tests

- **A reference marcher in plain JavaScript** (the same maths as the shader, one ray at a time) is the test
  oracle. The browser test renders a small known volume with WebGL (headless Edge's software renderer) and
  compares chosen pixels with the reference.
- Known volumes: a single hot voxel must appear at the pixel its centre projects to, from three camera
  angles; the brightest mode shows the maximum along a ray, not the first value; the surface mode is empty
  for a level above the peak and non-empty below it; a part in front of the volume hides it; the cutaway
  reveals the inside.
- The mask: with "hide noisy voxels" on, a voxel with 80% error vanishes and one with 5% stays.
- Performance smoke test: a 200³ map renders a frame in the browser test without timing out; the orbit
  (coarse) path is used while dragging.
- The existing 3D suites (CAD meshes, caps, picking, tiny-model handles) still pass.

## Risks

- Headless WebGL: Edge's software renderer is slow; keep test volumes and canvases small.
- `V3.depth` is packed into RGBA bytes: decode it identically in GLSL and JavaScript, and test with a part
  exactly behind the hot voxel.
- The page is edited by several agents; keep the change inside the 3D overlay code and the layer controls,
  and run everyone's 3D tests before merging.
- Picking: clicking in the volume should still select the part behind it, not be swallowed by the overlay.

## Size

Large: 3-4 sessions (shader and upload, the three looks, tests, polish).

## Later (stages 3 and 4 of the mesh-maps plan, unchanged)

Smooth flux curves from functional expansion tallies, then event clouds (Gaussian splats of collision and
fission sites).
