# CAD fixtures

`generate.py` creates author-owned drilled-block and annular-cylinder solids,
including translated/rotated variants. Dimensions are millimeters. The holes
extend beyond both caps before subtraction. Analytical volumes and explicit
hole/material points provide references independent of GEOUNED.

Generate and convert them with `setup/cad/verify.py`; output belongs outside the
repository. The verifier compares OpenMC's evaluation of the emitted analytical
regions with FreeCAD containment and analytical volume formulas. No nuclear
data or transport execution is needed. This is sampled geometry evidence, not
a proof of equivalence for arbitrary CAD.

Stage 2 adds `native_fixtures.py` (a 34-case FreeCAD-written corpus with expected
values derived from construction parameters, plus `teeth()` and `browser_reports()`)
and `handwritten_step.py`, an independent STEP writer with no OpenCASCADE code whose
output is committed in `external/` with its expectations in `expected/external.json`.
`mixed.step` and `expected/native_report_*.json` are real engine output replayed by
the browser test; regenerate them with `browser_reports()` after changing the
recognizer (the end-to-end test fails if the live engine disagrees with them).

These generated fixtures use this repository's MIT license. Do not add private
or company CAD here.
