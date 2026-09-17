# TODO

## MCNP export: show translation progress instead of a static message

Right now the Export -> "MCNP input" flow shows a static
"Translating with MCNPy... (the first export takes about 15 s while MCNPy starts)"
message for the whole call, with no feedback while it runs. On large models
(e.g. examples/ne403-graphite-pile, 134 parts) the export can take several
minutes under Rosetta, and there's no way to tell it's still working vs. stuck.

MCNPy already prints named stages during translation (Materials -> Surfaces ->
Universes/Cells -> Filling Cells -> Lattices), so a step-based progress
indicator ("Stage 3 of 5: Translating Cells") is achievable. A true percentage
isn't, since MCNPy doesn't report fractional progress internally.

Needs changes in three places:
- `studio/openmc_studio/mcnp_worker.py` - forward MCNPy's stage print lines as
  `@@PROGRESS` messages instead of letting the server's `_reader` thread
  discard everything that isn't a `@@RESULT` line.
- `studio/openmc_studio/server.py` - `McnpWorker.run()` currently blocks
  synchronously on `self.results.get(timeout=600)`; needs a way for the client
  to poll current stage instead of just waiting on the final result.
- `studio/openmc_studio/static/index.html` - replace the static "Translating
  with MCNPy..." text with a step-based progress bar driven by the above.
