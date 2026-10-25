# Eigenvalue runs in the headless runner

2026-10-25. `python -m openmc_studio.headless run` takes steady **eigenvalue** projects as well as fixed-source ones, and `results.json` carries k-eff with its standard
deviation. Asked for by SEED for the power-temperature loop (see `docs/seed-fuel-temperature.md`). Code: `studio/openmc_studio/headless.py`. Tests: `test/test_headless.py`
(fixture `test/generated/eigenvalue_pin.*`, written by `node test/generate_fixtures.js`).

## What is accepted and refused

| | |
|---|---|
| Run modes | `describe.runModes` is `["fixed source", "eigenvalue"]`; any other `runMode` is `E_UNSUPPORTED` |
| Caps | the same for both modes: particles per batch at most 1,000,000, batches at most 1000 (`E_LIMIT`, which SEED's adapter reports as `E_BOUNDS_EXCEEDED`) |
| Minimum active batches | **30** (`batches - inactive`); fewer is `E_LIMIT` at `/settings/batches`. MCNP 6.3 manual 2.8.3.2, the same number the page's result checks use |
| Minimum particles per batch | **1000**; fewer is `E_LIMIT` at `/settings/particles`. MCNP 6.3 manual 2.8.1.4 (trial runs about 1000, a final calculation 5000 or more): between 1000 and 5000 the run is accepted and the page's result checks still note it |
| Inactive batches | a whole number from 0 up to below the batch count (`E_SCHEMA_INVALID` at `/settings/inactive`) |
| Tally | not required for an eigenvalue run (k-eff is the result); a fixed-source project still needs one |
| Depletion | a project with `depletion` on is `E_UNSUPPORTED`: it is not a steady eigenvalue run |
| Other first-slice rules | unchanged: a seed is required, no track output, and the page's own pre-run errors (a fissile material, fission neutrons on, neutron sources only, ...) refuse at `validate` and `run` |

`describe.limits.eigenvalue` is `{minActiveBatches: 30, minParticlesPerBatch: 1000}`. A run whose statepoint is of another run mode than the project's, whose inactive count
differs, or that has no finite k-eff with a standard deviation and a k per batch, is `failed` with `E_OUTPUT_INCOMPLETE`, never reported without k-eff.

## The result: `results.json`, `summary` of an eigenvalue run

```
{ "summary": {
    "run_mode": "eigenvalue",
    "batches": 40, "particles": 1000, "inactive": 10, "n_inactive": 10, "seed": 12345,
    "statepoint": "statepoint.40.h5",
    "keff": [<mean>, <std>],            // OpenMC's combined k-eff estimator over the active batches and its standard deviation (the standard error of the mean), both absolute, dimensionless
    "k_combined": [<mean>, <std>],      // OpenMC's k_combined entry of the statepoint, as written (the same estimator)
    "k_generation": [<k of batch 1>, ..., <k of batch N>],   // one per batch, the inactive ones included
    "entropy": [...]                    // only when the project has an entropy mesh
  },
  "tallies": [ ... ] }                  // [] when the project has no tally
```

k-eff has no analytic oracle, so SEED reports it `unverified`: the only entries are the two refusals (`openmc-bad-eigenvalue`, entry version 2, 25 active batches, and
`openmc-bad-eigenvalue-particles`, 500 particles per batch), both expecting `E_BOUNDS_EXCEEDED`. Version 1 of `openmc-bad-eigenvalue` expected `E_UNSUPPORTED`.

Measured on the fixture (UO2 pin cell, 1000 x 40, 10 inactive, one thread): about 6 s per run, k-eff near 1.3 with a standard deviation of several hundred pcm. That is the
noise floor of the loop at the minimum size; a tolerance below it cannot be met (SEED's `stalled`).
