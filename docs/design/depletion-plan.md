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

**D1: model side (2 to 3 days).** Depletable-material flag, volume per burnable material (from the stochastic calculation Studio already runs, or the analytic volume for primitives where Studio has one), the
Depletion settings block, the `deplete.py` generation, Problems checks (no fuel, no volume, no power, fixed-source run, MCNP export refused with a named message).

**D2: the writer (2 days).** `depletion_writer.py` plus tests (below), wired into the run. Provenance gets the chain hash.

**D3: the view and Export (3 days).** Depletion tab, estimate before run, Stop, resume from `prev_results` if the run is interrupted.

**D4: FEED reads Studio's record (1 day, with the FEED agent).** The FEED reader (`claude/agy-depletion-reader` in the other clone) reads a Studio-written file, converts with 0.8815 and refuses a non-oxide fuel.
This is the point at which that branch can merge. Studio does not edit FEED.

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
