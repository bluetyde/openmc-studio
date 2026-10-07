# MCNPy 0.0.7: issues found while speeding up model.mcnp (2026-10-06)

MCNPy 0.0.7 (MIT, author Peter J. Kowal, RPI) is the Java-backed OpenMC-to-MCNP translator behind Studio's model.mcnp tab.
**It is not on PyPI or public GitHub.** It comes from the RPI NuCoMP group's GitHub Enterprise server
(`github.rpi.edu/NuCoMP/mcnpy`, built into a wheel and installed from a local file; docs at
`pages.github.rpi.edu/NuCoMP/mcnpy_docs`; see the exporter's `CLAUDE.md`, "MCNPy install notes"), and may need RPI access
to reach. Do **not** confuse it with two unrelated projects that share the name: `sandialabs/mcnpy` (Sandia, C++/pybind11,
MCNP PTRAC particle-tracking analysis, BSD-3) and PyPI `mcnpy` (monleon96/MCNPy, versions 0.1.0 to 0.2.5, GPL): neither has
`deck_formatter.py`, `metapy` or the OpenMC translator, so neither is where these issues go.

These are notes and runnable examples for a report to the RPI NuCoMP authors; nothing has been sent. Test case throughout: the NE403 graphite pile imported from
[`test/fixtures/mcnp/graphite_pile.mcnp`](../../test/fixtures/mcnp/graphite_pile.mcnp) (267 cells, 309 surfaces, 2 materials).
Numbers are cold runs in WSL Ubuntu, Python 3.11.15, on a loaded machine (about +-40%); call counts are exact.

## 1. `deck_formatter.line_wrap` never returns for a token longer than the line limit (a bug)

MCNP input is limited to 128 columns (80 in MCNP5 and early MCNP6), so wrapping long cards is intended. The bug is a single
token with no blank, such as a union written without blanks `(-1000:-1001:...)`: there is no blank to break at, the loop in
`line_wrap` rebuilds the same string forever, memory grows, and `Deck.write` has already opened the output file, so it is left
empty. A union of 18 terms (109 characters) wraps; 22 terms (133 characters) never returns.

- Example (no Java needed, loads the module from its file): [`line_wrap_hang.py`](line_wrap_hang.py). Expected output on 0.0.7:
  10 and 18 terms "returns", 22 and 26 terms "HANGS".
- Suggested behaviour: break after a `:` (MCNP allows blanks around the colon), or stop with an error naming the cell and the
  limit. Exporter's own `deck_format.py` already raises "a data token cannot fit within 128 columns".
- How we hit it: a dummy cell naming 300 surfaces made `Deck.write` run for more than 8 minutes. A model with any cell whose
  union has more than about 22 terms (fewer with 4-digit surface ids) hits it in the normal path.
- Our workaround: `cell_regions.py` in the exporter cuts long unions after their colons in the cards it writes itself
  (exporter branch `claude/direct-cell-cards`, pending merge).

## 2. Exporting N cells costs O(N^2) Java round trips (performance; to verify before reporting)

Stack samples of the main thread during `openmc_to_mcnp` put all of the time in py4j `socket.readinto`. MCNPy's own stage
lines show where: "Translating Universes and Cells" is short and **"Making Universes" is almost all of it** (292 s of 311 s
on the pile with full regions; 116 s of 125 s with one-term placeholder regions). The sampled chain is
`Deck.add -> Deck.get_universe -> Deck.universes -> wrap.py getter -> return_value_converter -> is_instance_of / __getattr__ ->
send_command` (`deck.py` lines about 557-605, `wrap.py` about 216 and 448), i.e. every `Deck.add` re-reads the deck's whole
universe collection through Java. A second agent's reading (not yet verified by us): each read walks all cells added so far,
about 11 py4j calls per cell, mostly repeated reflection lookups, so about 11 N^2 calls (784,000 for N = 267, about 100 s).

- Total py4j calls for the pile, counted by wrapping `GatewayClient.send_command` ([`count_rpc.py`](count_rpc.py)):
  2,988,277 with the world cell expanded, 2,060,072 with it written as `#cell` complements.
- Translate time by number of cells (first k cells of the same model): 25 -> 21.5 s, 50 -> 32.6, 100 -> 61.0, 200 -> 148.6,
  267 -> 407.1: about 0.6 s a cell to 100 cells, then steeper.
- Examples (need the MCNPy gateway on the machine-wide port 25333, so post `CLAIM: MCNPy` in `messages/openmc.md` before
  running them; each takes the exporter project folder as an argument):
  [`time_stages.py`](time_stages.py) (each pipeline stage), [`phase_timer.py`](phase_timer.py) (MCNPy's own stage lines with
  timestamps), [`sample_translate.py`](sample_translate.py) (stack sampling), [`count_rpc.py`](count_rpc.py) (call counts).
  Usage is in each file's docstring; they expect the pile's `model.xml` in a folder (`generate` it with the page's
  `commitMcnpImport`, as `test/test_mcnp_import_gate.cjs` does).
- Possible exact fixes: a `get_universe` that reads the already-held universe list, and cached reflection lookups in `metapy`.

## What we did about it in the exporter (openmc-mcnp-project)

- `world_complement.py` (exporter `c765b21`): the rest-of-the-world cell as `#cell` complements, 2.99 M to 2.06 M calls.
- `cell_regions.py` (branch `claude/direct-cell-cards`): plain cells translated with a short placeholder region, real region
  written into the card afterwards; pile translate 407 s to 134 s. See [the plan](../design/mcnp-import-speed-plan.md).
- `geometry_check.py` (exporter `410d9d9`): validate 973 s to 16-36 s (OpenMC's Python `Geometry.find` replaced by
  `openmc.lib.find_cell` above 60,000 points x cells); unrelated to MCNPy, same pipeline.
