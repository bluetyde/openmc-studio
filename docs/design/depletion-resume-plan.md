# Resume of a stopped depletion run: plan

Status: plan only (2026-10-08). Nothing is built. Read with [depletion-plan.md](depletion-plan.md) (D1 to D4 are done; D3 left "resume from `prev_results`" open).

## What the person gets

A depletion run that was stopped, crashed or killed leaves a record of the steps it finished, marked incomplete (D3). Today the only way on is to start again from step 0 and pay for every transport solve a second time. With resume, the Results page of such a run has a **Resume this burn** button. It starts a new run that continues from the last step the first run saved, and ends with one complete `depletion.json` for the whole burn, from time 0 to the last step, with a note that it was resumed and from which run.

Why it matters: depletion on a real model is hours of transport per step (the pin cell is about 30 s per solve; a lattice is not). A burn that dies at step 7 of 10 should cost steps 7 to 10, not 1 to 10.

## What OpenMC 0.15.3 does (read from the installed source, `openmc/deplete/abc.py`; not yet run)

- `CoupledOperator(model, chain_file, prev_results=Results(...))` takes the compositions and the **volumes** of the burnable materials from the last entry of the previous results (`transfer_volumes`), so a restart must **not** measure the volumes again.
- `Integrator(..., continue_timesteps=True)` checks that the previous steps are the same as the first steps of the list it is given (it compares the time steps **and** the source rates with `np.array_equal`) and starts at `prev_res[-1].time[0]`, index N-1. So the new run is given the **whole original step list**, not just the remaining steps, and the same power density and heavy-metal mass.
- A results file written by a stopped run holds, for each finished step, the beginning-of-step compositions, k, source rate and times. The entry of the step that was running when it stopped is the last one; its end composition was never saved. The restart redoes that step's depletion from its saved beginning-of-step state.
- **The catch:** for that first step the restart does not run transport. It takes the reaction rates **stored in the last entry** (`_get_bos_data_from_restart`). `integrate(write_rates=False)` is OpenMC's default, and it is what Studio uses today: that is why D2 found "results keep no reaction rates". A restart from a file with no stored rates would either fail or deplete with empty rates (a burn with no transmutation, which looks fine and is wrong). So **resume needs the rates stored**, which means new runs must be started with `write_rates=True`, and a run made before this feature cannot be resumed (it is refused with a plain reason, not guessed at).

## Decisions I recommend (each is yours to change)

1. **Resume makes a new run folder; it never edits the stopped run.** The new folder gets copies of the stopped run's `model.py`, `project.json`, `depletion_results.h5` and its `openmc_simulation_n*.h5` statepoints. The original stays exactly as it was, with its incomplete record, and the new run's provenance names it (`resumed_from`: run id, sha-256 of the copied results file, steps done). The resumed run uses the **stopped run's project, not what the page shows now**: resuming a burn with a different model would mix two models in one record.
2. **New runs always store rates** (`write_rates=True`). The file grows (rates per nuclide reaction per material per step; on the reduced chain this is small, to be measured). Runs made before this feature are not resumable. Nothing else in Studio's records changes.
3. **The power split by tally stays.** With rates stored, per-region power could be read from them instead of from the kappa-fission tally (D4). That would be a simplification, but it changes working D4 code and is not needed for resume. Not in this plan; noted as a later option.
4. **Refuse rather than guess.** Resume is refused, with the reason, when: the run is not a depletion run; its record is complete; its results file cannot be opened (a kill during a write can corrupt an HDF5 file); the results hold no reaction rates; the chain file's sha-256 differs from the one recorded; or a run is already going. When the machine's OpenMC version or nuclear data differ from the recorded ones, resume goes ahead only with a warning in the log and a note in the new record (the existing record check already lists those differences).

## Changes, in order

**R0. Find out what a restart really does (about 2 hours, real OpenMC, pin cell).** Three questions, answered by running, before any design is fixed:
- Does a stopped run started with `write_rates=True` hold usable rates in its last entry, and how much bigger is the file?
- Does a restart from the same file **without** rates fail loudly or deplete wrongly? (Decides how hard the refusal must be.)
- Is a resumed burn **identical** to an uninterrupted one? The seed is the same for every solve and the first resumed step reuses the stored rates, so for the predictor the atoms and k should agree to the last digit, and for CE/CM to a very small tolerance. If they agree, that is the best oracle this feature can have (see below). If they do not, find out why before building anything.

**R1. `depletion_script.py`: two options.** `write_rates` (default off, so every existing generated script and test stays byte for byte) and `resume` (give `prev_results` to the operator, pass `continue_timesteps=True`, and do **not** call `prepare_depletion` to measure volumes). Unit tests on the generated text, like the existing 18.

**R2. `model.py` generation: the tally must not live inside the volume measurement.** Today `prepare_depletion` adds the D4 power-split tally and measures the volumes. A resume must keep the tally (the resumed steps need it) and skip the volumes. So `prepare_depletion(model, measure_volumes=True)` adds the tally always and measures the volumes only when asked. Old `model.py` files (single argument) are recognised and their runs refused for resume with "made by an older Studio". The page test for the generated text is extended.

**R3. `depletion_run.py` and the server: start a resume.** New route `POST /api/runs/<id>/resume`. It checks the refusals above, makes the new folder (copies as in decision 1), writes the resume `deplete.py`, writes provenance (`resumed_from`), and starts it through the same path as a normal run (one active run, same stream, same record hook). Normal depletion runs now pass `write_rates`.

**R4. `depletion_writer.py`: one record for the whole burn.** `from_run` reads the whole results file as before. It adds `provenance.resumed_from` and a note ("resumed after step 2 of 5 from run ...") and keeps the inventory check over the whole burn. The multi-region power split reads `openmc_simulation_n<step>.h5` for every step, old and new; the copied statepoints make that work. A resumed run that is stopped again can be resumed again (the chain of `resumed_from` is kept as a list).

**R5. Page.** An incomplete depletion run gets **Resume this burn** under its Depletion section (and a "resumed from" line on the resumed run's header). A refusal shows its reason in the section. Test like `test_depletion_page.js`.

**R6. Real runs and docs.** `test/manual_depletion_resume.py`: stop a run, resume it, compare with an uninterrupted run. Update `depletion-plan.md`, TODO, progress file and the log. Mutation run on the new code (commit first; judge by exit code).

## How to prove it right

1. **Identical to an uninterrupted run (the main oracle):** the same pin, steps `1, 4, 10`, predictor. Run uninterrupted. Run again, kill it after the second transport solve, resume. Compare atoms of every listed nuclide and k at every point: expect equality, or a stated tiny tolerance if CE/CM differs. Do it once for the predictor, once for CE/CM, once for the two-slice case (to check the copied statepoints and the split).
2. **Break tests (commit first):** resume without `continue_timesteps`; with the volumes measured again; from a file with no rates (must be refused); with a different chain file (refused); with the run's project replaced by the page's; with a time step list that differs from the original; dropping the copied statepoints (multi-region must refuse, not guess). Each must fail a test.
3. **Corrupt file:** truncate a copy of a results file and ask for a resume: refused with the reason, original untouched.
4. **The original is never changed:** hash every file of the stopped run before and after a resume.
5. **A chain of two:** stop, resume, stop again, resume again: one record, correct step count, both runs named.

## Risks

- **The kill can corrupt the results file.** Stop sends a signal while OpenMC may be writing HDF5. R0 finds out how Studio's Stop behaves; if it can corrupt, Stop should signal a polite stop (let the current step's save finish) or resume must say plainly that a corrupt file cannot be used. This is the one place the feature can lose a user's burn, so it gets its own test.
- **A kill during the transport solve is the normal case** (that is what the pin test did) and is fine: the file only holds finished entries.
- **Different OpenMC or data on resume.** A burn resumed on a changed machine mixes two environments. Warned and recorded, not refused (people do upgrade); the record check shows it.
- **File size** with stored rates: measured in R0; if large for big models it becomes a setting (default on).
- **CE/CM and the other multi-stage integrators:** the restart reuses the stored rates of the beginning-of-step solve only. R0 shows whether that matches an uninterrupted run; if not, resume is offered for the predictor only until it does.

## Not in this plan

Resume of an **eigenvalue** (non-depletion) run to add batches. OpenMC can continue from a statepoint, and it would be useful (for example to cut the noise of a pin-power map), but it is a different feature with its own questions (source file kept, batch bookkeeping, what a "continued run" is in provenance). A separate small plan if wanted. Also not here: changing the step list on resume, resume from a different machine, and resume in the headless/SEED path (D5).

## Effort

About 2 days: R0 2 hours, R1 and R2 half a day, R3 and R4 half a day, R5 and R6 half a day, with the real runs taking a few minutes each. R0 can change this: if the identical-run check fails, the plan changes before any code does.
