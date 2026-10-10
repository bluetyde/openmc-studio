# Depletion in Studio and a real `depletion.json` writer: plan

Status (2026-10-07): **planned, not started.** Goal: Studio runs a fixed-power depletion of a fuel model with OpenMC's own `openmc.deplete`, shows the result, and writes the
`depletion.json` hand-off record that FEED and RAFT import. No depletion engine of our own. This belongs to the Reactor Physics package (TODO section 2).

## What exists today

| Piece | State |
|---|---|
| `studio/openmc_studio/depletion_record.py` | merged (`5d37195`): burnup arithmetic in MWd/tU, `build_record`, `write`, `read`, `validate`, `to_oxide_basis`. 7 tests, 14 of 14 deliberate breaks caught. Exercised only with hand-made numbers; **no caller**. |
| FEED's answer on the basis | OFFBEAT `Bu` is per tonne of oxide; the consumer applies the oxide factor of the model it uses (**0.8815** in OFFBEAT's Lassmann burnup model; **0.881** in the `UO2MATPRO` conductivity, which divides by 0.881: FEED's plan 10, section 2); one value per axial slice; refused for non-oxide fuel. The record stays on heavy metal. |
| Depletion chain file | **present**: `/root/nuclear_data/chains/chain_endfb80_pwr.xml` (27.5 MB, 3,820 nuclides, 7 reaction types in the chain, fission yields loaded; installed 2026-09-27). The deep-dive session's note that no chain file exists was wrong. Its licence and its source version are not recorded anywhere yet. |
| OpenMC 0.15.3 | `Model.deplete(method, ...)`, `CoupledOperator`, integrators (`Predictor`, `CECM`, `CELI`, `LEQI`, `EPCRK4`, `CF4` and the SI variants), `Results` (`get_keff`, `get_atoms`, `get_times`, `get_source_rates`, `get_mass`, ...). |
| Studio's run path | `server.py` `Studio.start` runs `python model.py`; `results.py` reads a statepoint; `provenance.py` writes `provenance.json` per run. Eigenvalue runs exist. The headless runner (SEED's path) refuses eigenvalue runs (`headless.py`: `E_UNSUPPORTED`). |
| Cell volumes | Studio already runs an OpenMC stochastic volume calculation before dose runs (`mcnp_worker.dose_description`, `calculate_volumes`, 200,000 samples). A depletable material needs a volume. |
| MCNP side | `BURN` export is open in the TODO. **Out of scope here**: the MCNP export refuses a depletion setup with a named message. |

Not in Studio: any depletion settings, a depletable-material flag, a chain setting, a depletion run kind, a results view, a writer that calls `depletion_record`.

## Design

**What the user sets (Settings, a Depletion block; eigenvalue runs only).**
- Which materials burn (a flag on a material; fuel presets default on). Each burnable material is one region, or axial slices of one part (for FEED).
- Power (W for the whole model, or W per gram of heavy metal), a list of time steps in days, one decay-only cooling step as an option.
- Integrator (default: predictor-corrector `CE/CM`; a plain predictor offered for quick looks), chain file (default: found next to the nuclear data; recorded with its hash).
- Particles per transport solve: depletion runs one transport solve per step (two per step for predictor-corrector), so the page shows the estimated solve count and warns before a long run.

**How it runs.** A generated `deplete.py` is `model.py` plus a final block: set material volumes, `model.deplete(...)`, write `depletion_results.h5` and then the record. It runs through the same
run folder, log stream, Stop button and `provenance.json` as a transport run, with `kind: "depletion"` and the chain file hash in the record. Generation stays in the page's `generate()`
(and `regen_script.cjs` for SEED) so `model.py` and `deplete.py` share one geometry block.

**The writer (`depletion_writer.py`, new).** Reads `depletion_results.h5` with `openmc.deplete.Results` and calls `depletion_record.build_record`:
- time steps in days from `get_times`; power history from `get_source_rates`; k and its sigma per step from `get_keff`;
- regions: name, OpenMC cell ids, initial heavy-metal mass computed from the initial composition and volume (kg);
- burnup per region and step in MWd/tU from the record module's own arithmetic, **cross-checked against OpenMC's** (the module refuses a record whose burnup disagrees with its power history);
- optional isotopics (atoms/b-cm) for a listed set (U-235, U-238, Pu-239, Pu-240, Pu-241, Xe-135, Sm-149 by default);
- the run's provenance block plus the chain file and its hash.
The writer never changes the burnup basis: oxide conversion stays the consumer's job, with the factor of the consumer's own model (0.881 or 0.8815, see above).

**The view.** A Depletion results tab: k versus burnup with its error bars, a nuclide inventory chart (U-235, Pu-239, Xe-135, Sm-149 over time), a burnup table per region, and "Export depletion.json".

## Steps (each stops with a go/no-go)

**D0: feasibility (1 day).** On a generated UO2 pin cell in WSL: `model.deplete` with the present chain, 5 steps, 20 W/gHM-class power, predictor-corrector, 4 threads. Measure time per step, memory and
the size of `depletion_results.h5`; confirm `get_keff`, `get_atoms`, `get_source_rates` give what the writer needs. Output: a note with the numbers. Stop if a step costs more than a few minutes on this machine.

**D0 result (2026-10-07, done).** UO2 3.5 % pin cell, 38 W/gHM (183.6 W), 2D reflective, OpenMC 0.15.3 in WSL, scratch script outside the repo.
- **It works end to end.** `Results` gave the times, k with sigma, source rates and nuclide counts; `depletion_record.build_record` took them and validated; burnup 38.0 and 190.0 MWd/tU = power x time / heavy-metal mass.
  U-235 fell 0.69 % in 5 days; Pu-239, Xe-135 and Sm-149 appeared. Qualitative only; no accuracy claim.
- **The full chain (3,820 nuclides) is impractical here**: one step at 10,000 x 40 did not finish in 15 minutes (a first CE/CM run was stopped after 1 h 27 min). The time is spent inside OpenMC's transport, scoring reaction rates for thousands of nuclides.
  `reduce_chain_level` is required. Level 3 from {U-234/235/236/238, O-16} keeps 1,285 nuclides: a small run (2,000 x 20, predictor, 2 threads, 3 transport solves) took 296 s with 3.76 GB peak memory and a 1.2 MB results file.
- **Chain reduction by level, measured** (seed U-234/235/236/238, O-16; nuclides kept / key nuclides still missing): level 1: 1,167 (no Pu-239); 2: 1,223 (no Pu-239); 3: 1,285 (no Pu-240, Pu-241, Am); 4: 1,333 (no Pu-241); 5: 1,365 (no Pu-242, Am-241); 6: 1,396 (no Am-243, Cm-244); 7: 1,426. **About 1,100 of the nuclides at level 1 are fission products** (they come with the fission yields); each actinide level adds only 30 to 60. So the size of the chain is set by the fission products, not by how far up the actinide chain it reaches.
- **A "gradual" chain that steps up as nuclides become significant** (asked 2026-10-07) is feasible in principle (run in segments with `prev_results`, rebuild the chain from the nuclides above a threshold) but **not useful**: going from level 3 to level 6 costs 9 % more nuclides, so a fixed higher level (6) is simpler and nearly as cheap; the real cost lever is the fission products, which `Chain.reduce` cannot trim. Whether a segmented restart even keeps the previous inventory when the chain changes was not tried. Recommended: a fixed level chosen from the run length (default 6), the nuclides the user asked for always kept, and the chosen level and the kept-nuclide count written into the record's provenance.
- **Timing is contaminated**: the machine's load was 14 to 17 on 16 cores (another agent's BEAVRS sweep). Quote no timing from D0; repeat on an idle machine.
- **Gate:** the "a few minutes per step" rule cannot be judged on this load; proceed with the reduced chain.

**D1: model side (2 to 3 days).** Depletable-material flag, volume per burnable material (from the stochastic calculation Studio already runs, or the analytic volume for primitives where Studio has one), the
Depletion settings block, the `deplete.py` generation, Problems checks (no fuel, no volume, no power, fixed-source run, MCNP export refused with a named message). **Base the generation on the merged `depletion_script.py`**
(text only, eight integrators, injection-safe quoting, 14 tests) and extend it, because as written it (a) loads `model.py` with `runpy.run_path`, and Studio's `model.py` computes volumes only inside its `if __name__ == "__main__"` block, so a depletion
run would start with no material volumes; (b) has no `reduce_chain_level` or other operator options; (c) takes one power for the whole run, not a list per step; (d) never writes the record. Each is a small change plus tests.

**D1 result (2026-10-08, done; decisions taken: an explicit Burnable flag on a material, a fixed chain level with 6 as the default, power as W per gram of heavy metal).**
- **Settings > Depletion** (flat settings keys `depletion`, `depPower`, `depSteps`, `depIntegrator`, `depReduce`; older projects get them with depletion off) and a **Burnable** box on a material (shown when depletion is on).
- **model.py** marks burnable materials `depletable = True` and defines `prepare_depletion(model)`, which measures each burnable material's volume with OpenMC's stochastic volume calculation (the boxes and cells come from the same machinery as the dose volumes).
- **deplete.py** is written by `depletion_script.build_script` (extended: `power_density`, `reduce_chain_level`, a `prepare` hook; the output for the old settings is unchanged) beside model.py when `/api/run` gets a project with depletion on, and is what runs. `depletion_run.py` finds the chain file (`OPENMC_CHAIN_FILE`, else the `chains` folder beside the nuclear data), and the provenance record names the chain by its SHA-256 and the new settings.
- **Errors** (page and `prerun_check.py`, held equal by golden cases): not an eigenvalue run, no burnable material in use, no heavy metal (U, Pu, Th), a burnable material filling the world or used by imported CAD, bad power, steps, integrator or chain level; and, page only, a burnable material in a part inside a lattice, or no chain file found. The page also says model.mcnp leaves depletion out (it has no BURN card).
- **Checked end to end** on the UO2 pin Studio generates (`test/generate_depletion_pin.cjs`, `test/manual_depletion_run.py`, and once through the page): the source rate equals 38 W/g x the heavy-metal mass computed by hand (231.42 W against 231.35 W: the stochastic volume is within 0.03 %), burnup is 38.0 and 190.0 MWd/tU, U-235 falls, Pu-239 and Xe-135 appear, k falls. **First clean timing** (machine load about 1): 126 s for 3 transport solves (2,000 x 15, predictor, chain level 3, 4 threads, script run by hand) and 95 s through the page; peak memory 3.8 GB. Still one pin cell; a larger model scales with particles and cells.
- **Not in D1:** the depletion record (D2), the results tab and the estimate before a run (D3), depletion in lattices and imported CAD, regions finer than one per burnable material (FEED wants axial slices: D4 conversation), the headless/SEED path.

**D2: the writer (2 days).** `depletion_writer.py` plus tests (below), wired into the run. Provenance gets the chain hash.

**D2 result (2026-10-08, done).** `depletion_writer.py` and a hook in the server: when a depletion run ends well, `depletion.json` is written beside `depletion_results.h5`, the provenance record names it (`depletion_record`: status, id, whether the check passed) and hashes it with the other outputs, and the Log says "Depletion record written". A refusal or a crash writes `depletion-record.txt` and a note, and never changes the run's status.
- **The record id** FEED's case asked for: `depletion_record.record_id` (SHA-256 of the canonical JSON without the id), added to every built record and checked by `validate`; a record with no id (older writers) still validates. Schema name unchanged (`studio.depletion/0.1`: nothing consumes it yet; to settle with FEED).
- **Units** are in the record's provenance: days, W, MWd per tonne of initial heavy metal (every nuclide with Z of 90 or more), isotopics as atoms in the whole region, k with sigma. The basis stays heavy metal.
- **One burnable region per record (superseded by D4: several regions are now written, power split by a tally).** OpenMC's results file keeps no reaction rates in this setup (the rate arrays are empty), so the power of each of several burnable materials is not in it. This replaces the plan's cross-check "against OpenMC's own burnup", which does not exist, and the plan's per-region split.
- **The check** that went in instead: the heavy-metal atoms the run lost against the fissions power x time implies (over the fission Q of the fissile nuclides present, from the chain): 1.0037 on the pin (tolerance 5 %: the Q differs by a few percent between nuclides, so it catches a wrong power or unit, not a 1 % error). A failed check does not stop the record; it is flagged in the record and the log.
- **Verified on a real run** (UO2 pin, predictor, steps 1 and 4 days; by hand and once through the page): the heavy-metal mass 6.0901 g against 6.0880 g worked out from the dimensions, burnup 38.0 and 190.0, cell id 1 and the material name found from `summary.h5`, the chain named by hash. Numbers from that run are kept as a fixture (`test/fixtures/depletion/pin_run_data.json`) so the arithmetic is tested without a run.

**D3: the view and Export (3 days).** Depletion tab, estimate before run, Stop, resume from `prev_results` if the run is interrupted.

**D3 result (2026-10-08, done).**
- **Results page**: a run that burned fuel gets a **Depletion** section (after the run checks): the region, its heavy-metal mass, steps, integrator, chain level, power density, wall time and record id; a table of every point (step, day, burnup in MWd/tU, k with its sigma); a k-against-burnup chart with 1-sigma bars; an inventory chart (U-235, U-236, Pu-239, Pu-241, Xe-135, Sm-149 per starting heavy-metal atom, log scale); an **incomplete** label and a **check** label when the record says so; and **Save depletion.json** (served byte for byte by `GET /api/runs/<id>/depletion-record`). A run with no record shows why instead. What the page shows is the record; the only numbers it computes are the table's running days and the inventory as a fraction of the starting heavy-metal atoms.
- **Estimate before a run** (Settings > Depletion): the number of transport solves from the integrator (steps x 1 for the predictor, x 2 for CE/CM, CE/LI and LE/QI, x 4 for CF4 and EPC-RK4, plus one; the stochastic-implicit ones are not counted). **The time is not guessed**: after a depletion run finishes, the page keeps how long a solve took here and what particles x batches it ran with (browser storage), and the next estimate scales that by particles x batches and says it is a guess; with no earlier run it says there is no time estimate yet. On the pin: 29.5 s per solve at 2,000 x 15 (88.6 s for 3 solves, machine quiet).
- **A stopped or failed burn** leaves a record of the steps it finished, marked incomplete (`provenance.complete`, `steps_done`, `steps_planned`, and a note), written by the same server hook; checked on a real run killed after the second solve (2 of 3 steps, burnup still 38 W/g x time). **Resume from `prev_results`** was not built here; it is built since (2026-10-10): [depletion-resume-plan.md](depletion-resume-plan.md).
- **A defect D3 found in D2**: the record never held Xe-135 and Sm-149 although the writer listed them (only heavy nuclides were read). Fixed, the fixtures were remade from a new real run, and the manual run now checks for them.
- Still not here: depletion in lattices and imported CAD, regions finer than one per burnable material, SEED's headless path, a visual check of the charts beyond their structure (the browser pane was too small to judge them by eye).

**D4: FEED reads Studio's record (1 day, with the FEED agent).** The FEED reader (`claude/agy-depletion-reader` in the other clone) reads a Studio-written file, converts with 0.8815 and refuses a non-oxide fuel.
This is the point at which that branch can merge. Studio does not edit FEED.

**D4 result (2026-10-08, done on Studio's side).** FEED's reader is merged (FEED main) and reads a record Studio's own writer made; Studio pins the id format (`test_depletion_record.py`, `TestIdFormatIsPinned`: the canonical text rebuilt from the file's own tokens, the way FEED's JavaScript does it, equals the id; the real record's id is also pinned as a literal). What was open was the region question, now answered:
- **Several burnable materials give several regions.** `prepare_depletion` adds a kappa-fission tally over the burnable materials (before its volume calculation, because that calculation leaves a `model.xml` that the transport run reads and a tally added afterwards is silently missing). The writer reads that tally from each step's transport statepoint `openmc_simulation_n<step>.h5` and splits the source rate by it, so each region gets its own power, burnup and isotopics, and its own inventory check. The statepoint is the solve the step began with (its k-eff equals the results file's, checked per step; a missing statepoint, a missing tally or another solve refuses the record with the reason).
- **Approximation:** the split uses the beginning-of-step flux of each step: exact for the predictor, an approximation for the integrators that average several solves (the other solves' statepoints overwrite each other's names). The record says so (`provenance.region_power`).
- **Checked on a real run** (`test/manual_depletion_slices.py`): the pin cut into two axial slices, 3.5 % below and 5 % above, both burnable. The slices took 32.9 and 43.1 W/g of heavy metal at the start; **each slice's inventory check, which does not use the tally, came to 1.004** (a 50/50 split would be 13 % off), burnups 164 and 216 MWd/tU, heavy-metal masses within 0.04 % of the hand calculation, region powers summing to the source rate.
- **Results page** with several regions: one burnup column per region plus the mass-weighted average, the k chart against the average burnup, one inventory chart per region.
- **Not done:** the case-side import in FEED (their M6, needs the SEED recipe); regions finer than a material (a slice must be its own material and part, so the user models slices by hand); several burnable regions inside lattices; resume of a stopped burn.

**D5: SEED headless (later).** Allow eigenvalue depletion runs through the headless runner; an oracle entry is a separate decision.

## How to prove it right

1. **Arithmetic oracle (exists):** 1 MW for 1 day on 1,000 kg HM is 1.0 MWd/tU; the record refuses a hand-edited burnup that disagrees with its power history.
2. **A closed-form depletion check through the real writer:** `openmc.deplete.IndependentOperator` with hand-given one-group micro cross sections and flux gives U-235 depletion N(t) = N0 exp(-sigma phi t); the
   test runs that through `Results` and the writer and compares the inventory in the record with the formula. No Monte Carlo, runs in seconds, isolates the reading and writing from the physics.
3. **Energy bookkeeping:** burnup from power and time against burnup from fissions times the fission-q value OpenMC uses, within the stated tolerance.
4. **Self-consistency on a real pin cell:** k falls with burnup; U-235 falls; Pu-239 rises; Xe-135 reaches equilibrium within the first steps; halving the step size changes k at the end by less than a tolerance set
   after seeing the numbers (a convergence test, **not** an accuracy claim). No published reference value is claimed until one is sourced and checked.
5. **Break tests (commit first):** wrong time unit (days vs seconds), wrong mass basis, dropped cooling step, reversed step order, burnup not cumulative, the chain hash omitted. Each must fail a test.
6. **Round trip:** Studio-written record read by `depletion_record.read` and by FEED's reader (D4).
7. **Cancel and resume:** Stop mid-run leaves a readable partial `depletion_results.h5`; the record says "incomplete" and lists the finished steps.

## Risks

- **Run time:** two transport solves per step with predictor-corrector; a 3D model at 100,000 particles is hours. The estimate before the run and the particle default matter more than any code.
- **Memory and file size:** thousands of nuclides per material; `depletion_results.h5` can be large. D0 measures it.
- **Chain choice:** the present chain is the ENDF/B-VIII.0 PWR chain (thermal-spectrum fission yields). Fine for LWR-like and thermal systems; for graphite-moderated or fast systems the yields differ. State it next to the chain name.
- **Normalisation:** OpenMC's fission-q normalisation is the default; changing it changes burnup. Record the mode.
- **Volume accuracy:** stochastic volumes carry statistical error that scales every burnup number; record the volume and its uncertainty.
- **Heavy-metal mass:** burnup per tU needs the initial heavy-metal mass; for a material with no uranium it is undefined and the writer refuses.

## Alignment with FEED's plan 10 (burnup as a frozen state; `fuel-performance-studio/docs/plans/10-burnup.md`, read 2026-10-07)

FEED plans to take a burnup from a depletion record only at its milestone M6, and says what it needs from Studio:
- **A real writer that a run calls.** This plan is that (D1 to D3). FEED's M6 waits for it.
- **A record id.** FEED's case carries `burnup.source`, "a depletion record's id". `studio.depletion/0.1` has **no id field today** (`depletion_record.py`, top-level keys: schema, time steps, regions, k, isotopics, provenance). Add one in D2: the SHA-256 of the record's canonical JSON with the id left out, written by `build_record`, checked by `validate`. A schema addition: bump to `studio.depletion/0.2` or keep `0.1` while unreleased (to decide with FEED; nothing consumes the record yet).
- **Heavy-metal basis in MWd/kgHM or MWd/tHM, one value per slice.** The record is in MWd/tU; FEED accepts both units. No change.
- **The oxide factor is the consumer's.** FEED's plan notes the model constant is 0.881, not 0.8815, for its `UO2MATPRO` law. The record carries no factor, so nothing here changes; the TODO's earlier line (oxide burnup = heavy-metal x 0.8815) is corrected to say the factor depends on the consumer's model.
- **The chain file exists** (`/root/nuclear_data/chains/chain_endfb80_pwr.xml`). FEED's plan lists "no chain file" among its M6 blockers; that blocker is not real. What is still open is the chain's recorded source and licence (decision 3 below).
- **Oxide only.** FEED refuses non-oxide fuel; Studio's depletion examples for FEED should be UO2.
- FEED's first fuel is an LWR UO2 pin with Zircaloy: the PWR chain's thermal-spectrum yields fit it. A good D0 model is the same pin (so FEED's later M6 test has a matching record).

## Not in this plan

MCNP `BURN` export; an own-engine depletion; fuel performance coupling; isotopic output beyond a listed set; decay-heat and activity outputs (OpenMC has them; later); the SEED oracle.

## Decisions for the user

1. Go ahead with D0 (a one-day measurement) first? Recommended: yes; it decides the rest.
2. Default integrator: predictor-corrector `CE/CM` (twice the cost, more accurate) or plain predictor? Recommended: `CE/CM`, with a quick-look option.
3. Where the chain file comes from for other machines: the present file's origin and licence are not recorded. Recommended: record its source and hash now, and make it a data reference in the package manifest.
