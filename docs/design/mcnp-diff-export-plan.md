# Diff-based model.mcnp export: plan

Status (2026-10-07): **planned, not started.** The speed work (translate 407 s to 14 s, validation moved to the background) made big imports
usable. This plan is the next step: make a CAD or part edit show its new model.mcnp in about a second, the way OpenMC's own export does.

## Goal and numbers

After a small edit, rebuild only the cards the edit touches. Today every geometry or material edit pays the full pipeline. Measured on
the 267-cell imported lattice deck:

| stage | full cost today | after this plan (safe edits) |
|---|---|---|
| translate (MCNPy, Java bridge) | about 14 s | skipped; only the touched cards are rewritten (target < 0.2 s) |
| remediate | 2.7 s | re-run, then made incremental if it still shows (target < 0.5 s) |
| validate | 30 s, now in the background | unchanged, background |

Target for a safe edit: deck on screen in about 1 s. Small models already take 1 to 3 s in total, so the payoff is mostly for big ones.

## What is already instant

- Source, tally and settings edits skip translate: the worker caches the translated geometry by a hash of the materials and geometry XML
  (in memory, lost when the worker restarts).
- Validation no longer blocks the tab (H, merged 2026-10-07).
- Geometry and material edits redo the whole translate. That is the case this plan is for.

## Why it is not straightforward

One edit touches several cards, and the cards refer to each other by number:

- **A material**: the `M` card, its `MT` card (S(a,b)), the material number and density on every cell that uses it, FM references on tallies.
- **A cell**: its card, a `#n` in the world cell, a number in the graveyard cell's list, tally bins that name it, group comments,
  the stable-id block.
- **A surface**: its card plus every cell region that names it; a changed surface type changes the card format.
- **Universes and lattices**: `U`, `FILL`, `LAT` arrays name universe numbers, and MCNPy numbers the cells and surfaces it creates for a lattice
  from a counter that lives as long as the process (the same model translated twice in one process gives different numbers).
  A spliced deck can match a full translate only if that numbering is reproduced or fixed.

## The idea in one paragraph

Keep the last deck as a list of **cards with owners** (the OpenMC object each card came from), plus a **dependency map** (which cards
mention which numbers). On an edit, diff the OpenMC model against the model the deck came from, find the changed objects, rewrite only
their cards and the cards that depend on them, and leave everything else as it was. Anything the splicer does not understand takes the full
translate and says why. The result must be **byte-identical to a full translate of the edited model**; that is the whole correctness story.

## Phases (each shippable on its own, in this order)

**Phase 0: measure first (half a day).** Time a full translate + remediate for small, medium and large models (the generated test models,
`aperture_block`) with the warm worker, split into Java start-up, materials, per-cell work. If a small model is already under about 1.5 s
end to end, the phases below matter only for models above a size threshold, and that threshold becomes the gate. Output: a table in this file.

**Phase 1: persistent baseline.** Save the last translated deck and, for every cell, surface and material, a content hash of its OpenMC
definition, in the app cache (survives a restart). Only `mcnp_worker.py` changes. Helps repeat exports; no splicing yet.

**Phase 2: card index and dependency map.** Parse a deck into cards with their number, kind and owner, and build both directions of the
map: material -> cells, surface -> cells, cell -> world `#` list / graveyard / tally bins / group comments. Pure Python, no MCNPy, tested
against the decks the exporter already produces (round-trip: index then re-join gives the same bytes).

**Phase 3: splice the plain cases.** Models whose changed objects are plain root-universe cells and their surfaces (the case
`cell_regions.py` already writes directly): changed region, moved or resized part, added or removed cell, changed density. Rewrite those
cards in the baseline deck, update the world and graveyard lists, re-run remediate. Anything else takes the full translate.

**Phase 4: materials.** A changed or added material: rewrite the `M`/`MT` cards and every cell that names it. Allowed only when the
numbers of the other materials stay the same.

**Phase 5: incremental remediate** if Phase 3 timing shows it is now the bottleneck (graveyard and world `#` lists, tally cards).

**Phase 6 (probably never): lattices and universes.** Full translate stays the answer. Revisit only if MCNPy's cell counter can be
fixed to a known start, which would need an upstream change (see `docs/mcnpy-issues/`).

## What takes the full path, and says so

Lattice or universe fill, a `TR` change, a surface type change, a macrobody conversion change, a new tally on a changed cell, more than
a quarter of the cells changed (a diff that big is not a win), a baseline that is missing or older than the code version. Never a silent
fallback: the tab says "full export: <reason>" so a slow one is explained.

## How to prove it right

1. **Byte-identity property test.** Random edit sequences (move a part, change a radius, add or remove a part, change a density, change
   a material) on the generated test models and a synthetic grid. After every step the spliced deck must equal a fresh full translate
   of the same model, each translation in its own process (see `tests/test_mcnpy_speed_identity.py`: the lattice counter is process-wide).
2. `validate_deck` still runs on the spliced deck, in the background, like any deck. An edit followed by its undo returns the original bytes.
3. **Predicate tests**: each unsupported feature takes the full path with its reason.
4. **Mutation test** (commit first): break the dependency map (drop the world `#` update, the graveyard update, the density cells) and
   see the identity test fail.
5. **Real edits**: the CAD edit path in the browser, deck before and after, compared with a full export.

## Risks

- A card missed by the dependency map gives a deck that differs from a full translate. Mitigation: byte-identity as the gate, and a
  switch (`MCNP_SPLICE=0`) that forces the full path.
- Baseline drift: any change to translate or remediate invalidates the baseline (store a version key; a mismatch means the full path).
- Number stability: the splice must keep the card numbers a full translate would give; if a full translate would renumber (an added cell
  in the middle), take the full path rather than renumber.

## Order and effort

Phase 0 (0.5 day), 1 (0.5), 2 (1.5), 3 (2 to 3), 4 (1), 5 only if needed. Stop after Phase 3 if the measured edit time is under about 1 s
on the big models; Phases 4 and 5 are optional.

## Decisions for the user

1. Is a size threshold acceptable (small models keep the plain full export; splicing only above it)? Recommended: yes, less code on the
   common path.
2. Baseline in the project folder (travels with the project) or the app cache (disposable)? Recommended: app cache.
