# Plan: dose rates (flux-to-dose conversion)

> **Status (2026-09-26):** all three stages done, and dose on parts inside lattices (per-instance volumes).
> Cell volumes come from OpenMC's own volume calculation rather than the point sampler this plan first
> proposed. Still open: H*(10), and a real-MCNP comparison.

Task G. Studio branch `claude/dose`, exporter branch `claude/dose`. Written 2026-09-25. **All three stages done** (Studio `fe77b57`, `56d4b29`, `88dbdb8`; exporter `8c3b92f`).

Goal: a detector or flux map can show **dose rate** (µSv/h, or mrem/h with imperial units on) instead of
flux, in OpenMC and in the MCNP deck, with the two using the same numbers so they can be compared.

## What we have to work with (checked 2026-09-25)

- **OpenMC** ships ICRP dose coefficients: `openmc.data.dose_coefficients(particle, geometry, data_source)`,
  with `data_source` `icrp116` (default) or `icrp74`, `geometry` AP, PA, LLAT, RLAT, ROT or ISO, for
  neutrons (68 points, 1 meV to 10 GeV) and photons (55 points, 10 keV to 10 GeV). Units: pSv·cm².
  These are **effective dose** coefficients. There is no ambient dose equivalent, H*(10), which is what a
  survey meter reads.
- **OpenMC** applies them with `EnergyFunctionFilter(energy, y, interpolation='log-log')` (checked: log-log is
  accepted). Outside the table's energy range it scores **zero**.
- **MCNP 6.3** removed its built-in dose tables for copyright reasons (manual p. 464; the tables are in
  Appendix F as DE/DF input). So the deck carries explicit `DEn LOG e1…eK` / `DFn LOG f1…fK` tables (p. 465).
  Outside the table's range MCNP uses the **end values**, not zero.
- **Studio** already makes detector-response tallies (`EnergyFunctionFilter` from cross sections, exported as
  `FM`); the dose tally follows the same path. Tallies are **per source particle** today, and cell tallies are
  **volume-integrated** (track length, cm): the exporter writes `SD=1` so MCNP matches OpenMC.

## The three things that make it a dose *rate*

1. **Coefficients** (pSv·cm²): from OpenMC, written identically into model.py and the MCNP deck.
   Out-of-range fix: pad each table the same way in both codes: prepend a point at the lowest transported
   energy (1e-5 eV neutrons, the photon cutoff for photons) and append one at 20 MeV if needed, each carrying
   the nearest table value. Both codes then see identical functions everywhere particles exist. A test checks
   the padded OpenMC filter against MCNP's clamping rule.
2. **Volume** (cm³), because a cell tally is track length: fluence = tally / V.
   - Mesh tallies: the voxel volume, exact.
   - Cell tallies: sample points in each dosed cell's bounding box with the geometry check's point locator
     (`geometry_check.py` already walks every universe and lattice). Volume = box volume x fraction inside,
     with its own error (40,000 points gives about 1%). Exact for an uncut sphere, box or cylinder, which the
     tests use to prove it.
   - The same V goes into model.py (results divide by it) and the MCNP `SD` card for that tally (MCNP divides
     by it). One volume, two codes: no hidden disagreement from MCNP computing its own.
3. **Source rate** (particles/s): a new optional Settings field, "Source emission rate". With it: dose rate =
   coefficient x fluence per source particle x rate x 3600 s/h x 1e-12 Sv/pSv. Without it Studio shows
   pSv per source particle and says what's missing. In MCNP the rate factor goes on an `FM` constant, so the
   deck prints Sv/h directly and a tally comment (`FC`) says so.

## Stage 1: dose on cell tallies (OpenMC side)

- Tally properties: Response gets "Dose (ICRP-116)"; with it, "Irradiation geometry" (AP default, PA, LLAT,
  RLAT, ROT, ISO) and "Data" (ICRP-116, ICRP-74). The Detector menu gets two presets: "Dose rate, neutrons" and
  "Dose rate, neutrons + photons" (the second only when photon transport is on; otherwise Problems says why).
- model.py: one `EnergyFunctionFilter` per particle (with a `ParticleFilter`), padded tables, log-log. The
  volumes are written as data in model.py with a comment giving their error.
- Results: "Dose rate" row per tally, per particle and total, in µSv/h or mrem/h (follows the imperial
  switch), relative error combining the tally error and the volume error.
- Problems: a dose tally without a source rate is info, not error (it still runs, in pSv per source particle).

## Stage 2: dose maps

- A mesh tally can score dose instead of flux: colour ramp and legend in µSv/h (or mrem/h). Voxel volume is
  exact, so no sampling is needed.
- The flux map's error line and "Add the other two planes" work unchanged.

## Stage 3: MCNP export

- Exporter: a dose tally becomes `F4` + `DE`/`DF` (padded table, LOG LOG) + `SD` (Studio's volume) +
  `FM` (rate factor) + `FC` naming the units, source and data set. Photons get their own tally number.
  Dose maps: `FMESH` with `DE`/`DF` (mesh tallies accept dose functions, manual p. 115 / PDF page 119).
- Validator: DE/DF present, same length, energies increasing, values positive, SD matches the model's volume.
- Card lines wrap within 128 columns (68 numbers per card, so continuation lines).

## Tests

- **Independent physics check**: a 14.1 MeV isotropic point source in void and a small sphere at distance r.
  Fluence per source particle is 1/(4πr²) (times the small-sphere correction), so dose per source particle is
  known exactly from the coefficient at 14.1 MeV. OpenMC's dose tally must match within its statistical error.
  This checks the coefficients, the units, the volume and the rate factor in one go, without trusting either
  code.
- Padding: the padded filter equals MCNP's clamped function at energies below, inside and above the table.
- Volume sampling: uncut sphere, box and cylinder within 3 sigma of the exact volume; a part cut by a higher
  part gets the cut volume.
- Unit switching: µSv/h and mrem/h show the same quantity (1 mrem = 10 µSv).
- Exporter: `check_export_mcnp.py` case with a dose tally; the deck validates, DE/DF match model.py's numbers
  exactly, SD equals the volume.
- Browser: preset → Results row with the right unit; no source rate → the per-source-particle wording.

## Demo

The shielding demo with a D-T generator at 1e8 n/s: dose rate at the He-3 detector with the shield, then with
the lead removed, as one number each. Then a dose map through the shield.

## Risks and decisions

- **Effective dose, not H*(10).** OpenMC has no H*(10) table. Say "effective dose" in the UI and the deck
  comments so nobody reads it as a survey-meter reading. Adding H*(10) later needs a table with a clear
  source and licence (ICRP-74 Table A.42 values; the MCNP manual's Appendix F copy is not ours to reuse).
- **Tiny detector cells** need targeted sampling (bounding box, not the world), or their volume error swamps
  the tally. That's why sampling is per dosed cell.
- **Eigenvalue runs** have no absolute source rate from the user; dose there needs a power normalization.
  Stage 1 refuses dose in eigenvalue mode with that reason.
- **Photon dose** needs photon transport on; neutron-induced photons count only then. Problems says so.
- Nothing here is checked against MCNP until the real-MCNP runs happen (see the MCNP bundle item).

## Size

Stage 1 medium (2-3 sessions with tests), stage 2 small, stage 3 medium (exporter + validator + tests).
