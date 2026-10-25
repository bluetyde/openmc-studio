# F2: D-shaped (revolved) profile

Status: design only, 2026-10-25, branch `claude/fusion-dshape`. Nothing built.

## Approach

A new part kind is not needed. A polygon in (R, Z) revolved about the z axis is exactly a stack of cone frustum slabs: in each z slab the solid
is the outer frustum minus the inner frustum. Studio already has a `cone` part (radius r at the bottom, r2 at the top, height h) and a
first-part-wins order, so a generator can write ordinary parts into one group. Nothing changes in the 3D view, the picker, the OpenMC export,
the MCNP export or the model.py round trip.

## Generator

Input: R0, a (minor radius), kappa (elongation), delta (triangularity), N slabs (default 24), layer list (thickness and material, plasma side first).
Profile (Miller shape, one side): R(t) = R0 + a cos(t + asin(delta) sin t), Z(t) = kappa a sin t, t in [0, 2 pi).
Layer k is the profile offset outwards by the sum of the thicknesses so far (offset a polygon vertex along its averaged normal; the offset
is by construction polygonal, so the stated limit applies: a smooth D is a polygon here).

Slab edges are the profile's z levels. For each layer and slab the left and right boundary radius at the slab's bottom and top come from the
polygon edges. Parts, in first-wins order:
1. central hole: the left frustum of the outermost layer, material void;
2. each inner layer's solid, then the plasma (innermost) region as right frusta minus nothing, in that order;
3. the walls, outermost last.
A vertex at the top or bottom of the D (a slab of zero height) is dropped; a frustum whose two radii are equal becomes a cylinder-looking cone, which
is fine for the exporter.

## Checks (pass lines before any code is called done)

- Revolved rectangle volume = cylinder shell; revolved triangle = cone (closed forms).
- Revolved circle with N sides: volume converges to 2 pi^2 R0 a^2 at the expected rate (relative error about (2 pi / N)^2 / 6 for the area).
- Elongated ellipse (delta = 0): volume 2 pi^2 R0 kappa a^2 within the polygon error.
- Stochastic OpenMC volume calculation of the built group agrees inside its error.
- The generated project loads with no Problems and exports to MCNP (consistency checks only; no claim about a run in MCNP).
- Break tests: swapped r and r2, left and right swapped, wrong slab order, offset sign.

## Open decisions (mine unless the user says otherwise)

- Output is a group of ordinary parts (editable, but not parametric after generation). A parametric re-generate button on the group keeps the
  five numbers in the group record; that is a second step.
- Reading `first-wall-geometry/1` (a closed polyline) would reuse the same slab builder. Held until PLOW writes a real example record.
