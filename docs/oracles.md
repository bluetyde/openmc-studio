# Oracles: what OpenMC Studio's results are checked against

An **oracle** is an expected value that does not come from the code it checks. This page lists every one Studio has, what kind it is, where its number comes from, how tight it is and which test holds it. If a result is right, it is right against one of these; if there is none for something, that is stated at the end. The page also lists what is **not** an oracle but looks like one (a reference run, a golden file, a pinned hash), so the two are not confused.

Written 2026-10-10 from the tests as they are; it is a catalogue, not a promise of coverage. Where a test does not record the source of a number, the entry says so.

## The rules every oracle follows

- **The expected value never comes from the code under test.** It is a published number, a formula written out again by plain arithmetic in the oracle's own file, a table that another program owns (OpenMC's ICRP coefficients, its cross-section library), or an independent implementation by another method.
- **Tolerances are fixed before any run** and are not loosened after seeing a result. The SEED entries say so in writing (`oracles/seed/README.md`: the first eight were committed before any case was run).
- **A failing case is a finding.** It is kept, with the reason, and is not made to pass by widening the tolerance.
- **An oracle is tested by breaking the code once.** Mutation runs (the code is changed on purpose, the tests must fail) are recorded in the design docs and in `messages/openmc.md`; not every file below has one.
- **Say what it does not prove.** An oracle for the arithmetic of a law does not prove the law.

## The kinds, from strongest to weakest evidence

| Kind | Where the number comes from | What it can catch |
|---|---|---|
| **Literature** | a number printed in a published report, with the page | a formula or constant wrong in the same way as the code |
| **Independent implementation** | the same quantity from another program or another method (OpenMC's own geometry routines against Studio's flattening; a hand-written rule against an importer) | a bug in the method or the numerics |
| **Closed form** | a formula worked out by hand and evaluated in the test's own file | a bug in the code that implements the same physics |
| **Library-checked** | a table owned by another program (OpenMC's atomic masses, ICRP coefficients, cross sections) compared with the value Studio uses | a wrong constant, a wrong unit, a wrong interpolation |
| **Refusal** | a case with one fault that must be refused with a named reason | a check that does not fire |

## The catalogue

### Closed forms against the real transport code (OpenMC runs)

| Oracle | Where the number comes from | Tolerance | Held by |
|---|---|---|---|
| Dose rate from a point source into a void detector ball: the ball-averaged fluence `[2 D a + (a^2 - D^2) ln((D + a)/(D - a))] / (4 pi D) / (4/3 pi a^3)` times the ICRP coefficient at the line energy (log-log interpolation) | the formula written out in the test; the coefficients from `openmc.data.dose_coefficients` (ICRP 116 photons and neutrons, ICRP 74 14.1 MeV neutrons) | 4 sigma of the run's own statistics, and the run's relative error must be under 5 % | `test/test_dose_rates.py` |
| A tally on parts inside a lattice against the same model laid out cell by cell | the cell-by-cell twin (`*_flat.py`, written by `test/generate_fixtures.js`), no lattice in it | 4.5 sigma of the two runs combined, and every volume equal to the shape's own | `test/test_dose_rates.py`, `test/test_generated_models.py` |
| The lattice model's material at 20,000 random points against its flat twin | OpenMC's own point lookup in both | exact (any difference fails) | `test/test_generated_models.py` |
| B-10 slab absorption, flux and heating per source particle, and the void ball (track length exactly 4 cm) | first-flight formulas `(Sa/St)(1 - exp(-St t))` and `(1 - exp(-St t))/St`; cross sections read out of the nuclear-data library for B-10 at 294 K and 0.0253 eV (hash recorded in `oracles/seed/xs/`), the heating cross section is MT 301 | 4 sigma of the statistical error the formula predicts (200,000 histories) plus 0.4 % for neglected elastic scattering; 1e-9 for the void ball | the 6 good entries of `oracles/seed/entries/`, `test/test_seed_oracles.cjs`, `node studio/tools/gen_seed_oracles.cjs --check` |

### Independent implementations

| Oracle | Method | Held by |
|---|---|---|
| MCNP-deck import: Studio's flattened cells (universes, lattices, fill transforms, macrobodies) | OpenMC's own C++ geometry (`openmc.lib.find_material`) on the converter's model, at 4,000 points over the model and 40 in each cell's own box; the import is refused if any differ | `studio/openmc_studio/mcnp_import.py` (on every import), `test/test_mcnp_import.py` |
| The page's `model.py` for an imported deck against the deck | the material (by atom density) at thousands of points, OpenMC reading each | `test/test_mcnp_import_gate.cjs`, `test/mcnp_import_check.py` |
| Hexagonal lattices (`LAT=2`) in imported decks | decks written in `test/test_mcnp_hex.py` from the MCNP 6.3.0 manual's rules (p. 290, example p. 766); the expected material at a point is the nearest element centre and which half of it the point is in, worked out with no OpenMC and no lattice code; both orientations, either first step, either turn, off-origin centre, fill translation, 3D levels up, down and not centred | `test/test_mcnp_hex.py` (17 tests; a mutation run of 14 changes killed 13, and the 14th, a pre-filter that only affects hexagon corners, is the known gap) |
| The exported hex fixture against its twin | `test/generated/hex_array_y_flat.py`, every pin placed by hand | `test/test_mcnp_hex.py` |
| Radial power peaking of a pin map | a 4 x 4 lattice with one enriched pin, run in OpenMC: the peak must be at that pin and its mesh value must equal a material-filter tally of the same material | `test/manual_pin_power.py` (minutes; not in the quick suite) |
| Depletion: the heavy-metal inventory | the fissions the lost heavy-metal atoms imply, against the fissions the power and time imply, using the fission Q values of the chain; 5 % tolerance (Q differs a few percent between nuclides) | `studio/openmc_studio/depletion_writer.py` writes it in every record; `test/test_depletion_writer.py` |
| Depletion: several burnable regions | the per-region inventory check above, per region, as an independent check on the power split | `test/test_depletion_writer.py`, `test/manual_depletion_slices.py` |
| Depletion resume | a burn stopped by a real kill and resumed, against one never stopped; two identical uninterrupted burns also differ past the first transport solve (measured), so the check is what two identical runs also satisfy | `test/manual_depletion_resume.py`, `test/manual_resume_r0.py` (minutes) |

### Library-checked and hand-computed

- **Peak statistics** (`studio/openmc_studio/peak_stats.py`): the expected maximum of m standard normals. m = 2 and 3 against their closed forms to 1e-9; m = 4, 5, 10 against table values (1.0293753730, 1.1629644736, 1.5387527308) to 1e-6; a Monte Carlo check of m = 7. **The test calls these published tables but does not name the source: a gap to close before this page claims a literature oracle.** `test/test_peak_stats.py`.
- **Material assistant** (`studio/openmc_studio/material_assistant.py`): its atomic masses and abundances against `openmc.data`; mass conservation; UO2 stoichiometry (uranium mass share 0.8815 to 2e-4, total atom density 0.0696 to 1 %, the second by a formula written out in the test); borated water's ppm definition and B-10 share. `test/test_material_assistant.py`. The 29 golden cases in `test/fixtures/material_assistant/cases.json` are **not** an oracle: see below.
- **Boron search, variance statistics, eigenvalue result checks** (`boron_search.py`, `variance_stats.py`, `mc_result_checks.py`): values worked out by hand (reactivity in pcm, boron worth, regula falsi, figure of merit, histories needed, the unbiasedness summary, k formatted as in JCGM 100:2008). `test/test_boron_search.py`, `test/test_variance_stats.py`, `test/test_mc_result_checks.py`.
- **Pin power table** (`pin_power_table.py`, `pin_power_view.py`): small grids worked out by hand (a uniform 3 x 3; a 4 x 4 with one hot pin at a known place; an excluded cell; two axial layers); the quarter-symmetry fold. `test/test_pin_power_table.py`, `test/test_pin_power_view.py`.
- **The dose tables written into an MCNP deck** (`DE`/`DF`) against `model.py`'s own padded tables, and the deck's volume against the run's own volume (same cells, boxes, samples and seed). `test/test_dose_mcnp.py` (needs the exporter and the MCNPy gateway).

### Refusals

- The pre-run geometry check finds an overlap, a gap, a lattice with no outer universe and an overlap visible only after a rotated fill, on hand-built broken models, and reports nothing on the same shapes done properly (`test/test_geometry_check.py`).
- Imports refused with the reason: a torus, an all-void deck, a deck with nothing at the top level, an irregular or unreadable hexagonal lattice (`test/test_mcnp_import.py`, `test/test_mcnp_hex.py`).
- A depletion that cannot be resumed (no stored rates, a different chain, a finished burn, a changed step list, an older script) is refused, with the reason (`test/test_depletion_resume.py`).
- The three SEED bad-input entries: `E_UNSUPPORTED` for an eigenvalue case, `E_BOUNDS_EXCEEDED` for two million particles, `E_SCHEMA_INVALID` for no tally (`oracles/seed/entries/openmc-bad-*.json`).

## Checks that look like oracles and are not

- **Golden files generated by the code they guard.** `test/fixtures/material_assistant/cases.json` is written by the Python module and read by the page's JavaScript port: it keeps the two equal, it does not show either is right (the arithmetic oracles above do that). `test/fixtures/prerun/cases.json` (73 cases) does the same for the Python and page pre-run checks.
- **Pinned hashes.** The depletion record's id is the SHA-256 of its canonical JSON, pinned as a literal (`ac9478238c...`) so the format cannot drift; FEED recomputes it from the printed tokens. That shows two programs agree on a format, not that a record's numbers are right.
- **Fixtures taken from a real run** (`test/fixtures/depletion/`, `test/fixtures/pin_power/`) fix the shape of real data; they were produced by OpenMC and Studio, not by an independent method.
- **The nodal "oracle" (withdrawn 2026-10-10).** In the nodal-package experiments (`docs/design/nodal-p2/`), constants and discontinuity factors tallied in the core run itself were first called an oracle. They are not one: the factors (face flux over node-average flux) put the flux tilt in twice, and with them the assembly power is 17 to 23 % wrong while k matches (on the zoned cores). They are a reference run. The nodal experiments' real references are OpenMC's own k, OpenMC's kappa-fission power per assembly (statistical error 0.6 %), and the check that the face flux read from the two sides of an interface agrees (under 1 % with the extrapolated estimate). Those experiments are scripts, not tests.
- **The two-step nodal inputs** (infinite lattices plus strips) are an experiment's result, not a reference.

## What the oracles do not prove

- **No benchmark.** No test compares a Studio run with a published critical or depletion benchmark (a Godiva case from `mit-crpg/benchmarks` is on the TODO list). The eigenvalue checks look at the run's convergence and entropy, not at k against a known value.
- **Depletion has no external reference.** The record's inventory check is internal consistency (atoms lost against the fissions the power implies, to 5 %); no depletion result has been compared with a published burnup calculation.
- **The MCNP export** is checked by the exporter's validator and against OpenMC, point by point. MCNP output is not shared in this project; check a deck yourself before relying on it. Nothing on this page says anything about the decks' behaviour in MCNP.
- **Mesh tallies other than the axial heating bins and the pin-map checks** have no closed form here; energy-binned and current tallies are checked for plumbing, not against a formula.
- **A closed form checks the arithmetic, not the physics assumed:** a void ball and a pure B-10 slab say nothing about scattering, resonances or thermal-scattering data beyond the thermal-scattering regression (`test/test_thermal_scattering.py`, which checks that the library loads, the thermal spectrum changes and the exporter writes the `MT` card).
- **The thin slabs are blind to small cross-section errors** (an error of about 3 % in density is caught, 1 % is not; `oracles/seed/README.md` has the measured sensitivities).
- **The nodal package** has no passing oracle yet: its pass line is the user's to set, and the numbers so far are in `docs/design/nodal-package-plan.md`.

## Adding one

1. Pick the kind. Prefer a literature or independent value over a closed form of your own.
2. Write the expected value in a file that imports nothing from `studio/openmc_studio`; state the source (a page, a method) in the entry. If the source is another program's table, name the program and the table.
3. Fix the tolerance, with its reasoning, before running the code.
4. Make the test, then break the code on purpose and see it fail (commit first; judge by exit code and the summary line).
5. For a SEED entry, add it to `studio/tools/gen_seed_oracles.cjs`, run it, check that the existing entries are byte-identical, and keep it on a branch until SEED's count test has been told the new total.
