# SEED oracle entries for OpenMC Studio

Entries in the `seed.oracle/0.1` format that SEED's OpenMC adapter runs (`adapters/openmc` in the SEED repository) before it lets an agent run cases: the oracle set must pass, with its pins unchanged, or the run is refused. The app owns them (decision D3); SEED loads them from here and checks every file's hash.

Do not edit anything in `entries/` or `models/` by hand: `node studio/tools/gen_seed_oracles.cjs` writes them, and `node studio/tools/gen_seed_oracles.cjs --check` (and `test/test_seed_oracles.cjs`) fail when a file differs from what the generator makes. `xs/b10-294K-0.0253eV.json` is written once by `studio/tools/seed_oracle_xs.py` in the OpenMC environment.

## The rules (fixed before the first run: commit 5c9a05b holds the entries and tolerances of the first eight, 2e07970 those of the heating entry; no case had been run yet)

1. **An expected value comes from a formula** and from cross sections read out of the nuclear data library (B-10 at 294 K and 0.0253 eV, with the library file's hash recorded in `xs/`). Transport never produces an expected value.
2. **A tolerance is 4 sigma of the statistical error the formula predicts** for the case's 200,000 histories (20,000 x 10), plus 0.4 % where the formula neglects elastic scattering (0.057 % of all collisions at this energy). The generator computes it from the case alone.
3. **A case that fails is a finding, not a reason to widen a tolerance.**

All cases: fixed source, seed 12345, one thread, `temperature = 294 K, nearest`, 20,000 particles x 10 batches. A beam or point source of one neutron at a time; results are per source particle.

## The cases

| Entry | Quantity | Expected | Tolerance (rel) | First run (2026-10-05) |
|---|---|---|---|---|
| `openmc-void-ball-flux` | `Void ball:flux` (cm) | 4 exactly: a point source at the centre of a void ball of radius 4 cm, every particle crosses the whole radius | 1e-9 | 4.0, std 0 |
| `openmc-b10-slab-thin-absorption` | `B-10 thin slab:absorption` | 0.603318: first-flight absorption probability `(Sa/St)(1 - exp(-St t))`, 4 cm of pure B-10 at 0.001 g/cm3, optical thickness 0.925 | 0.0113 | 0.603669 (+0.06 %, 0.3 sigma) |
| `openmc-b10-slab-thin-flux` | `B-10 thin slab:flux` (cm) | 2.609054: the beam's track length `(1 - exp(-St t))/St` | 0.0089 | 2.610637 (+0.06 %) |
| `openmc-b10-slab-thick-absorption` | `B-10 thick slab:absorption` | 0.937207: 12 cm, optical thickness 2.78 | 0.00632 | 0.936743 (-0.05 %) |
| `openmc-b10-slab-thick-flux` | `B-10 thick slab:flux` (cm) | 4.052961 | 0.0117 | 4.051035 (-0.05 %) |
| `openmc-b10-heating-profile-heating` | `B-10 profile slab:heating` (eV) | 1412703: heating per source particle, `N kappa (1 - exp(-St t))/St` with kappa = 9.00282e9 eV b, the library's neutron heating cross section at 0.0253 eV (MT 301 of B10.h5), 4 cm of pure B-10 at 0.001 g/cm3 along z (the beam along +z); the same as 0.6033 absorptions x 2.342 MeV (kappa / sigma_a) | 0.0089 | 1413542 (+0.06 %, 0.3 sigma of its own 0.22 %) |
| `openmc-bad-eigenvalue` | refusal | `E_UNSUPPORTED`: the first slice runs fixed-source cases only | | |
| `openmc-bad-too-many-particles` | refusal | `E_BOUNDS_EXCEEDED`: two million particles per batch is over the runner's limit | | |
| `openmc-bad-no-tally` | refusal | `E_SCHEMA_INVALID`: a project with no tally would produce no result | | |

The heating entry's project also holds a cell tally and a 4-bin axial mesh tally of heating (1 x 1 x 4 voxels over the slab). The entry judges the whole slab; SEED's adapter tests (`tests/openmc-heating.test.ts`) compare each axial bin with the same formula, `N kappa (exp(-S z0) - exp(-S z1))/S` with its own predicted error, and check that the bins add up to the cell tally (the first run: 483847, 383869, 304503, 241324 eV, total 1413543, equal to the cell tally to 1e-9; the formula gives 483590 for the first bin, +0.05 %).

The absorption and flux entries of a slab are tied by `absorption = Sigma_a x flux`. The void ball tests geometry, the track-length estimator and the adapter's plumbing exactly (no statistics); the slabs test the library cross sections, number densities and the absorption and flux tallies against closed formulas.

## What they can and cannot see

- The void ball and a 1e-6 error in it: caught (tolerance 1e-9).
- The thin slab's absorption moves by about 0.6 % per 1 % change in number density or absorption cross section, against a tolerance of 1.13 %: an error of about 3 % is caught reliably, 2 % is at the edge, 1 % is not. Measured (2026-10-05, a 3 % higher density in the model): absorption 0.6145 against 0.6033 expected (+1.85 %), flux 2.5801 against 2.6091 (-1.11 %): both fail their entries.
- The thick slab's absorption is nearly saturated (0.94) and blind to density, but its flux moves by about 0.8 % per 1 % change (tolerance 1.17 %): an error of about 1.5 % or more is caught there. That is the most sensitive entry for the cross sections and number densities. Measured (a 2 % higher density): flux 3.9858 against 4.0530 expected (-1.66 %): fails; its absorption moves only +0.31 % and still passes, as predicted.
- The heating entry has the flux entries' sensitivity (the same 0.0089 tolerance on the same track length, so a 3 % density error fails it); that was not measured separately. Heating from photons (photon transport is off) is not covered.
- Quantities with another score (current, reaction rates), mesh tallies other than the axial heating bins above, energy bins and eigenvalue runs are **not covered**: the adapter reports such quantities as unverified.
- The first slice's checks (`E_UNSUPPORTED`, `E_BOUNDS_EXCEEDED`, `E_SCHEMA_INVALID`) are the three bad-input entries; a project the Studio page itself rejects is refused at `validate` with the page's own problem text, which is not an entry.
