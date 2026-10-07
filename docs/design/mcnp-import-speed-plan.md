# Fix the slow model.mcnp for big MCNP imports: plan

Status (2026-10-07): **largely done; see the TODO.** The lattice test deck's export went from 23.5 min to about 45 s: validate fixed by the
`openmc.lib` cell lookup (exporter `410d9d9`), the world cell written as `#cell` complements (`c765b21`), plain cells' regions written
directly (`f7f78c2`), and MCNPy's own round trips cut without changing the deck (`776bc09`). What the measurements showed differs from
the guesses below: MCNPy's cost was Java round trips, mainly its cell-adding loop (the 292 s sits in the stage printed as
"Translating Universes and Cells", not "Making Universes"), not region terms alone. H (validate in the background) is done too: the live tab shows the deck at once and the check follows. Still open: the
future diff-based export ([mcnp-diff-export-plan.md](mcnp-diff-export-plan.md)). The sections below are the original plan and the first
measurements, kept as history. It narrows
`openmc-large-import-export.md` (the broader proposal of 2026-10-04, in the shared plans folder): same rules
(measure first, never bypass a later edit, keep the validated path as the fallback), with what I found in the code.

## 1. The problem

After Convert > Import MCNP deck, the model.mcnp tab re-translates the imported geometry through MCNPy. The
lattice lab deck (266 cells) was still translating after 10 minutes (2026-09-26, a single uncontrolled
observation). A small native model takes about 8 s. The tab is unusable on a deck of this size, and every edit
of geometry or materials pays it again.

## 2. What the code shows (read 2026-10-06; nothing run through MCNPy)

- The tab's job (`mcnp_worker.py`) runs five stages in one process: (1) run model.py and export model.xml,
  (2) `translate()` in the exporter (MCNPy, Java round trips), (3) `remediate()`, (4) `add_group_comments`,
  (5) `validate_deck()`, which checks the deck against the OpenMC model at 20,000 sample points.
- The worker caches stage 2 by a hash of the geometry and materials XML, so only the first export of a geometry
  is slow. The cache lives in a temporary folder and dies with the worker.
- The lattice test deck as Studio imports it (`import_deck`, measured in WSL, 26.8 s for the import itself): 266 flat cells,
  4 components, 285 surfaces (231 generic planes, 26 x, 24 z, 4 y), about 20 half-spaces per cell (median 612
  bytes of region JSON). That is not a huge model, so something in the pipeline scales badly. The lattice was
  expanded element by element, so MCNPy sees 266 plain cells and none of the original `LAT`/`FILL` structure.
- Studio's own progress line only distinguishes stages inside MCNPy; the ten minutes were never split by stage.
  I called it "MCNPy" in the notes without evidence.

## 3a. First measurement (2026-10-06, the lattice test deck, one cold run, WSL Ubuntu, openmc-mcnp 3.11.15)

| Stage | Seconds |
|---|---|
| 0 imports + Java bridge (once per worker) | 17.8 |
| 1 model.py + model.xml + load_model | 0.8 |
| 2 MCNPy translate (cache miss) | 407.1 |
| 3 remediate | 13.1 |
| 5 validate, 20,000 samples | **973.1** (peak 708 MB) |
| Total | about 1,410 (23.5 min) |

The model has 267 cells, 309 surfaces and 2 materials. **Validate is the largest stage (69%), not MCNPy
(29%).** The worker's job timeout is 1,800 s, so a somewhat bigger deck would time out. A 1,000-sample profile of
`validate_deck` ran past 15 minutes under cProfile, so most of validate's cost does not scale with the sample
count. Scripts: `time_stages.py`, `sample_validate.py`, `gen_pile_model.cjs` (scratch folder, not in the repo).

**MCNPy translate scaling (same day, the first k cells of the same model, cache miss, `slice_translate.py`):**

| Cells | Surfaces | Translate (s) | Per cell (s) |
|---|---|---|---|
| 25 | 92 | 21.5 | 0.86 |
| 50 | 102 | 32.6 | 0.65 |
| 100 | 127 | 61.0 | 0.61 |
| 200 | 239 | 148.6 | 0.74 |
| 267 (all) | 309 | 407.1 | 1.52 |

Up to 100 cells it is about linear (0.6 s a cell, about 20 s of it fixed). Past that it steepens: 100 to 200 cells
costs 2.4x, and the last 67 cells (and 70 more surfaces) cost 258 s, 3.9 s a cell. So MCNPy's time grows faster
than the model: something in it scans cells against surfaces. One run per size, so the exact exponent is not
known, but the direction is clear. A model twice as big would take much more than twice as long, which is why
the saving from not re-translating (G) or not translating imported cells (C) is larger than a straight
proportion. It also means translating in small independent pieces (the old option B) would be cheap per piece,
but G gets the same gain without the risk that surface numbers differ between pieces, so B stays dropped.

**Why validate is slow (found 2026-10-06 by stack sampling; 100 samples took 384 s, 20,000 took 973 s).**
`check_geometry` (exporter `src/geometry_check.py`) checks `n_samples` random points plus 500 points in each
cell with a finite bounding box (about 25 of the lattice test deck's 266; cells of tilted planes have none): about 32,000
points. The deck side is numpy and fast (`deck.locate`). The OpenMC side calls the pure-Python
`openmc.Geometry.find()` once per point, and every sampled stack sits inside it (`Universe.find >
Cell.__contains__ > Region.__contains__ > Surface.evaluate`): about 30 ms a point with 267 cells, which is the
973 s. `openmc.lib.find_cell` (C++) answers the same question in microseconds. That is fix D below. My
"points x cells x terms in Python" guess was right about the stage and wrong about the cause.

## 3. Step 1: measure (no code change; needs the MCNPy claim)

Time each stage on the lattice test deck, three runs, cold and warm (cache hit), with `time.perf_counter()` around the five
stages in a throwaway copy of the worker loop (scratch folder, no repo change). Then find the scaling by
running stage 2 and stage 5 on slices of the same import (the first 25, 50, 100 and all 266 cells, same
surfaces): linear, or worse? Also record peak memory and, for stage 2, how many Java calls it makes.

| If this dominates | It means | Go to |
|---|---|---|
| Stage 2 (MCNPy) grows faster than linearly | A per-cell or per-surface scan inside MCNPy | 4A, 4G |
| Stage 2 is linear but large (seconds per cell) | Round-trip cost of generic planes and long regions | 4G, 4C |
| Stage 5 (validate) (measured: this one, 973 s) | Fixed cost in the checker, then points x cells x terms in Python | 4D, 4H |
| Stage 3 (remediate) | Macrobody detection or card rebuild is quadratic | 4E |
| Stage 1 | model.py builds regions slowly | 4F |

Save the numbers in the log and in this file before choosing.

## 4. Candidate fixes (G and H are the preferred directions; D now that validate is measured to dominate)

**A. Content-keyed disk cache (always worth doing).** Key the translation by the hash of the materials and
geometry XML as now, but store it on disk under the runs folder so it survives a worker restart and a Studio
restart. Cost: small. Gain: the slow translation happens once per imported deck, not once per session. It does
not fix the first run, so it is not the answer alone.

**C. Skip MCNPy for imported geometry.** Imported geometry is read-only, and Studio already holds it as
surfaces plus regions (`mcnp_import.py`), so the exporter can write its cell and surface cards directly, as it
already does for macrobodies and lattices (`macrobody_cards.py`, `lattice_cards.py`). Native parts in the same
project would still go through MCNPy, and the two blocks would be merged with renumbering. Support predicate:
write imported cells directly only when the deck uses nothing the writer doesn't know; otherwise fall back to
the validated MCNPy path or refuse, with the reason in the Log. This is the biggest gain and the biggest risk,
and `validate_deck` stays on as the proof.

**D. Validation cost (measured to dominate on the lattice test deck; cause found, see 3a):** find the OpenMC cell of every
sample point with `openmc.lib.find_cell` (C++) instead of `Geometry.find` in Python. Same points, same
comparisons, same errors. `check_geometry` keeps the Python `find` for the one case that needs the whole
instance path (lattice bin chains) and as the fallback when `openmc.lib` can't start (no nuclear data). The
initialisation needs the model XML and the cross-section library, so it belongs in the validation subprocess
of H. Expected: 973 s to about 10 s on the lattice test deck. The sample count and the checks stay the same; do not lower
them to save time.

**E / F. Remediate and model.py:** fix only what stage timing blames.

**G. Convert the diff from the imported baseline (the user's idea; it replaces B and the "not chosen" idea).**
An import is a known baseline: the original deck, whose cells, surfaces and materials Studio read and checked
against OpenMC. Keep that baseline (hash, the original cell and surface cards, and what Studio read from them).
On each export compare the model with the baseline, object by object: imported cells and surfaces that are
untouched pass through as the original cards (so `LAT`/`FILL` and universes stay, and nothing is re-translated);
only the changed objects and what depends on them are written fresh (an edited material or density rewrites that
material card and the density on the cells that use it; a native part added to the project goes through MCNPy as
now; sources, tallies and settings are remediated as now). Imported geometry is read-only, so its cards can't
change except through materials, which makes the dependency set small and checkable. This makes the first export
of an unedited import near instant and every later one proportional to the edit, which is what the user wants
from "go from diff". Rules from the existing plan apply: an explicit support predicate (decks using only what
the pass-through knows; else fall back to MCNPy or refuse with the reason), invalidation per edit kind (table in
that plan), and `validate_deck` stays on as the proof, comparing the exported deck with the OpenMC model.
Catch to test first: the flattened Studio cells and the original cells are different views of the same geometry,
so the baseline must map each Studio cell back to its original card (`mcnp_cell` already records the number;
lattice elements map to the one original filled cell).

**H. Validate in the background, not in the live path (the user's idea, 2026-10-06).** Validation never changes
the deck, so the tab doesn't have to wait for it. Split a job into two results: the deck (after remediate), then
the validation verdict. The tab shows the deck at once with a status line: "Validation: not run / running /
passed / failed".
- **Separate process.** `validate_deck` needs the deck and the OpenMC model, not MCNPy or Java, so it runs in its
  own subprocess and the live worker stays free for the next edit. A newer revision kills the older validation.
- **One verdict per revision.** Edits are coalesced; a verdict is stored with the revision's hash and can never
  attach to a different one (the existing plan's stale-export rule).
- **Export to file is the gate.** Saving or exporting the deck waits for a passing verdict for that exact
  revision, or writes the file with an "unvalidated" header only if the user chooses that. Nothing leaves Studio
  as a checked deck without being checked.
- **Same checks, same samples.** H moves when validation runs, not what it checks; it must not lower the sample
  count. It does not make validation cheaper, so the cost found in the profile is still fixed separately (D or E
  below as the profile says) for the moment the user hits export.
- **With G:** G removes most of translate and shrinks what validation must prove (unchanged cells are the
  original cards); H removes validation from the first view. Together an unedited import shows its deck almost
  at once and the verdict follows. H alone takes the live tab from about 23 minutes to about 7 (translate is
  still there), so H needs G or C to feel fast, and G or C need H or a cheaper validate to finish.
- **Tests:** a stale verdict is dropped; a newer edit cancels the older validation; export refuses (or marks) an
  unvalidated revision; a failing validation shows its text on the right revision; the deck shown is
  byte-identical to the one validated.

## 5. Correctness checks (required before any speed claim)

- Old and new decks agree: run `validate_deck` (point by point against OpenMC) on both, and compare the cell,
  surface and material cards structurally (same regions per cell number), not as text.
- Every deck in `test/fixtures/mcnp/` (shielding demo, lattice test deck, hex array, outside features) plus a mixed project
  (an imported component and a native part).
- Edits after import: a changed material density, a changed source and tally, a moved native part. A stale
  export must never replace a newer one.
- Bad input still refuses: an unsupported shape under C falls back or refuses, never silently drops a cell.
- A new test per fix that fails on the old code, `verify_invariants` exit 0, and
  `node test/run_all.cjs full`. The unexplained one-off `test_generated_models.py` failure of 2026-09-26 gets
  one extra look if it recurs.

## 6. Target

From the existing plan, kept: at least 5x lower median end-to-end time on the lattice test deck (cold), no more than 10%
regression on small models beyond noise. The absolute number is set after step 1, not before. If 5x isn't
reachable, report the measured bottleneck and revise the target in writing.

## 7. Work split, claims and order

1. **Me, step 1** (needs a `CLAIM: MCNPy` in the log, branch `claude/mcnp-import-speed`, my clone only): measure,
   write the numbers here, choose the fix.
2. **Me, the fix.** It touches the exporter (`export_mcnp.py`, possibly a new card writer) as well as
   `mcnp_worker.py`, so it needs two branches and two commits, exporter first. MCNPy and physics judgment stay with
   me; none of this goes to agy.
3. **Possible agy task afterward**, only if C is chosen: a well-specified card writer for plain surfaces
   (planes, cylinders, spheres, cones) and region expressions with unit tests, once the brief can state every
   MCNP format rule with its manual page (rule 9) and forbids silent catches (rule 10).
4. Merge, pull the shared installs, log and release, as usual.

## 8. Open questions for you

- (Answered 2026-10-06: go from the diff, G, then C only if needed.)
- Should big imports get a visible "translating, step N of M, Cancel" state while this is unsolved?
