# Diff-based model.mcnp export: short plan (future work)

Status (2026-10-06): **not started, on purpose.** Decided after the translate speedups (exporter `776bc09`, pending merge): a full translate
of the 267-cell imported lattice test deck is now about 14 s (407 s before), so diffing is no longer urgent. It is still the way to make edits
(CAD edits especially) feel instant, like OpenMC's own export. Plan only; nothing here is built.

## Goal

After a small edit, rebuild only what the edit touches. Target: a CAD or part edit shows its new model.mcnp in about a second, not
the 6-14 s fixed cost of a full translate (Java bridge, per-cell work), then remediate (2.7 s on the lattice test deck) and validate (30 s).

## What is already instant, and what isn't

- Source, tally and settings edits already skip translate: the worker caches the translated geometry by a hash of the materials and
  geometry XML (in memory, lost when the worker restarts).
- Geometry and material edits redo the whole translate. That is the case diffing is for.
- Remediate and validate also run on every export; validate (30 s) belongs in the background (H in
  `mcnp-import-speed-plan.md`), and remediate would need its own incremental path.

## Why it is not straightforward

One edit touches several cards, and the cards refer to each other by number:

- **A material** is the `M` card, its `MT` card (S(a,b)), the material number and density on every cell that uses it, and the FM
  material references on tallies. One change, many cards elsewhere.
- **A cell** is its own card, a `#n` in the world cell, a number in the graveyard cell's list, tally bins that name it, group
  comments, and the stable-id block.
- **A surface** is its card plus every cell region that names it (and a changed surface type changes the card format).
- **Universes and lattices** are the hard part: `U`, `FILL`, `LAT` arrays that name universe numbers, and MCNPy numbers the cells and
  surfaces it creates for a lattice from a counter that lives as long as the process (measured: the same model gives `5 0 -14`, then
  `6 0 -15`, ... when translated again in one process). A diff-built deck can only match a full translate if that numbering is
  reproduced or fixed.

## Approach (in this order, each step shippable)

1. **Persistent deck cache.** Keep the last translated deck and the model state it came from (per-cell and per-material content
   hashes) on disk, so the cache survives a restart. Small change in `mcnp_worker.py`; helps repeat exports only.
2. **A dependency map.** From the OpenMC model, build "which cards depend on which objects" (material -> cells, surface -> cells,
   cell -> world `#` list / graveyard / tally bins). Pure Python, testable without MCNPy.
3. **Splice for the safe cases only.** A fast path for models whose cells are plain root-universe cells (the case `cell_regions.py`
   already handles): changed region, added or removed cell, changed material or density. Rewrite just those cards in the previous
   deck's text, then run remediate on the result. Anything else (lattice, universe fill, transformation, hex lattice, a surface type
   change, a changed material set) takes the full translate, with a note saying why; never a silent fallback.
4. **Materials** next: material -> cells map, rewrite the `M`/`MT` cards and the cells that use them.
5. **Lattices and universes**: probably never; full translate stays the answer.

## How to prove it right

- The deck built by splicing must be **byte-identical to a full translate of the edited model.** Property test: random edit
  sequences (move a part, change a radius, add/remove a part, change a material) on the generated test models and a synthetic grid;
  every step compared with a fresh full translate, each in its own process (see `tests/test_mcnpy_speed_identity.py` for why).
- `validate_deck` still runs on the result, as for any deck.
- Predicate tests: each unsupported feature must take the full path and say so.

## Open questions

- Is the fixed cost of a full translate (about 6 s: Java start-up is already paid by the warm worker; the rest is per-cell and
  materials) small enough that step 1 plus H make edits feel fast without 3-5? Measure with the speedups merged first.
- How to number lattice cells reproducibly (a fixed start for MCNPy's counter?), if lattices are ever brought in.
- Whether remediate (graveyard list, world `#` list, tally cards) can be made incremental cheaply or should just be re-run.
