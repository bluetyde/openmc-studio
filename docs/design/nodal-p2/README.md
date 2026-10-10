# Nodal P2 experiments (throwaway scripts, not part of the app)

Run in WSL with a venv holding `openndm 0.3.0` on top of the OpenMC 0.15.3 environment; `openmc` and the venv's `python` both on PATH, venv first;
`OPENMC_CROSS_SECTIONS` set; `OMP_NUM_THREADS=8`. The results table and the rules found are in [`../nodal-package-plan.md`](../nodal-package-plan.md).

- `e1_core_tallied.py [particles batches inactive K]`: constants and discontinuity factors tallied in the core run itself (the oracle). `REUSE=1` reads the last statepoint in the folder; `VARIANT=noouter` drops factors on vacuum faces.
- `e2_two_step.py [particles batches inactive K]`: infinite lattices and fuel-plus-reflector strips, assembled by neighbour; face flux extrapolated to zero slab width (`ADF=slab` for the fixed slab 1/20).
- `e3_face_flux.py [particles batches inactive K]`: the face-flux estimators compared by interface continuity and by k (K = 80).
- `e1_output_K20.txt`, `e2_output_K20.txt`: the K = 20 outputs.
