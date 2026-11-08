# MCNP exporter

The code that turns a Studio model into an MCNP deck: MCNPy translation, remediation of the cards MCNPy
gets wrong (`src/remediate_deck.py`), and validation against the OpenMC model (`src/validate_deck.py`,
MontePy parse plus a sampled geometry comparison). Studio's MCNP worker (`studio/openmc_studio/mcnp_worker.py`)
runs the same three stages as `src/export_mcnp.py`.

It was a separate repository, openmc-mcnp-project, until 2026-11-08 and was bundled here at its commit
`ee59927`. It is now part of Studio and covered by Studio's LICENSE and AUTHORS.

- Dependencies: `requirements.txt` and `environment.yml`. MCNPy is not on PyPI; see INSTRUCTIONS.md.
- Tests: `tests/test_*.py` and `tests/check_export_mcnp.py`, run from this folder. `node test/run_all.cjs physics`
  runs them with Studio's suites.
- `geometry.xml`, `materials.xml`, `settings.xml` and `pin_cell*.mcnp` are the small pin-cell model the
  validator tests use.
- `OPENMC_MCNP_PROJECT` can still point Studio at a different checkout of this folder; without it Studio
  uses this one.
