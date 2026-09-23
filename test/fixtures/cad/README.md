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

These generated fixtures use this repository's MIT license. Do not add private
or company CAD here. Externally authored fixture coverage is a later gate.
