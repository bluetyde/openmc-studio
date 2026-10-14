# Nodal P2 experiments (throwaway scripts, not part of the app)

Run in WSL with a venv holding `openndm 0.3.0` on top of the OpenMC 0.15.3 environment; `openmc` and the venv's `python` both on PATH, venv first;
`OPENMC_CROSS_SECTIONS` set; `OMP_NUM_THREADS=8`. The results table and the rules found are in [`../nodal-package-plan.md`](../nodal-package-plan.md).

- `e1_core_tallied.py [particles batches inactive K]`: constants and discontinuity factors tallied in the core run itself (called the oracle at first; E7 shows it is not one). `REUSE=1` reads the last statepoint in the folder; `VARIANT=noouter` drops factors on vacuum faces.
- `e2_two_step.py [particles batches inactive K]`: infinite lattices and fuel-plus-reflector strips, assembled by neighbour; face flux extrapolated to zero slab width (`ADF=slab` for the fixed slab 1/20).
- `e3_face_flux.py [particles batches inactive K]`: the face-flux estimators compared by interface continuity and by k (K = 80).
- `e1_output_K20.txt`, `e2_output_K20.txt`: the K = 20 outputs.
- `e3_output_K80.txt`: E3's table; its last row (extrapolated) is the oracle number quoted in the plan. `e1_core_tallied.py` itself still uses a fixed slab (its K = 10/20/40 numbers are the fixed-slab rows).
- `e2_output_K80_extrap.txt`: E2 with the extrapolated face flux (the E2 number quoted in the plan); `e2_output_K20.txt` is the fixed-slab run.
- `e4_checkerboard.py`: three ways to assemble the two-step input (one-fuel strips; checkerboard strips; checkerboard strips and a color set).
- `e5_swap_pieces.py`: core-run pieces and strip pieces swapped one at a time, with the core's factors put in one class of faces at a time.
- `e4_output_K80.txt`, `e5_output_K80.txt`: their outputs.
- `e6_zoned_core.py`, `e6_output_K80.txt`: the second core (9 x 9, radially zoned), same swaps as E5.
- `e7_thick_reflector.py`: the core-tallied factors on one class of faces at a time, with 1, 2 or 3 reflector layers (`REFL`), k and assembly power against OpenMC. Its findings withdraw the word "oracle" used for E1 and E5/E6.
- `e8_equivalence.py`, `e8_output_K80.txt`: factors by generalised equivalence theory (true face flux over a parabola built from the MC node flux and net currents); the Fick-law check of the library D; D scaled per group. `MAPS`-style class modes as in E7.
- `e9a_dump.py` (one core run, writes `data/<core>.npz`), `data/*.npz` (the Monte Carlo data of the zoned 9 x 9 and 11 x 11 cores and the 8 x 8 checkerboard: node flux, face flux, net currents, assembly power, constants), `e9_current_d.py` (reads them, no Monte Carlo: fits D per kind and group to the currents and solves with openndm), `e9_output.txt`.
- `e10_d_source.py`, `e10_output.txt`: the fast-group D against the flux-averaged D, from a 300-group transport tally in three positions of the 9 x 9 zoned core, and how many intermediate groups the collapse needs. `e9a_dump.py` now also tallies a 120-group transport library in every position and saves the flux-averaged D (`c_Dflux`) and the library-style collapse (`c_Dharm`) in `data/*.npz`; `e9_current_d.py` solves with it (`e10_output_solve.txt`).
- `e11_checker_diag.py`, `e11_output.txt`: where the 8 x 8 checkerboard's power error sat (by kind, by flux group, Fick's law by pair of kinds); `e11b_orientation.py`, `e11b_output.txt`: the check that showed openndm's results are listed bottom-up (the cause), `e11_output_solve.txt`: E9/E10's solves redone with the right row order. The old outputs carry a note: their checkerboard power columns are invalid.
- `e12_library_path.py`, `e12_output.txt`: the flux-averaged D through OpenMC's own library path (an intermediate structure condensed with `get_condensed_library`), the cost, and the nodal solve of the result on the three cores (`CORE=zoned1|zoned2|checker1`, `STRUCTS=...`).
- `e14_swap_fields.py`, `e14_output.txt`: the two-step constants against the core run's, one field at a time (`data/pieces.npz` holds the pieces' constants).
- `e15_critical_spectrum.py`, `e15_output.txt`: the critical-buckling correction of the fuel's fine-group constants (`data/fine_inf.npz`; `REBUILD=1` reruns the Monte Carlo).
- `e13_two_step_library.py`, `e13_output.txt`: the two-step inputs built from small runs through the library path (infinite lattices, strips), assembled by kind and solved against the three cores.
