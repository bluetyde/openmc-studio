# The `fuel-temperature` transfer (SEED's return direction)

2026-10-25. OpenMC Studio's side of the power-temperature loop's return half: a FEED fuel temperature becomes an OpenMC material temperature. SEED owns the loop, the
recipe and the records; Studio owns the physics of the receiving end. Code: `studio/openmc_studio/transfer.py`, entry point `python -m openmc_studio.headless transfer`
(a `seed.transfer-request/0.2` on stdin, one reply line on stdout, exit 0 for every answer). `describe` lists the field in `transfers`.
Tests: `test/test_transfer_fuel_temperature.py` (32), `test/test_fuel_temperature_regen.js` (5).

## What it sets, and what the number must be

- **Sets:** `Material.temperature` in kelvin, the "Temperature" field of a Studio project material, for each project material the recipe names. It applies to every part
  that uses the material. Studio has **no per-cell temperature**, and one material has one temperature, so a temperature that changes along the fuel needs one material per
  axial zone (each its own entry and its own source row).
- **Means:** the **volume-mean temperature of the fuel region** the material fills, **absolute, in K**: not a change, not Celsius, not normalized. It is **not** an
  effective Doppler temperature. Studio does not convert one into the other, so the recipe must state `mapping.spatial.meaning: "volume-mean"`; anything else is refused. A
  sender that only has centre-line or cell-centre temperatures (FEED's `temperature_radial`) has to form the volume mean itself, in its recipe, before sending.
- It is used as given: OpenMC interpolates the cross sections between the library's temperatures (`settings.temperature.method` stays what the project says).

## The accepted request

```
{ "schema": "seed.transfer-request/0.2",
  "recipe": { "schema": "seed.transfer-recipe/0.2", "recipeId": "...",
    "source": { "quantity": "fuel_temperature", "unit": "K", "dimension": "temperature", ... },
    "target": { "app": "openmc-studio", "artifact": "project", "revision": "...", "field": "fuel-temperature" },
    "units": { "to": "K" },
    "normalization": { "kind": "none", ... },
    "mapping": { "spatial": { "meaning": "volume-mean",
                              "materials": [ { "material": "<project material id>", "region": "<row label>" } ],
                              "columns": { "region": "<label column>", "value": "<value column>" } },     // columns optional
                 "time": { "kind": "steady" }, "extrapolation": "refused" },
    "applicability": { "range": { "min": 500, "max": 1500 } } },                                          // optional, can only narrow
  "recipeDigest": "...",
  "source": { "data": <table or scalar> },
  "target": { "artifact": "project", "revision": "...", "content": "<the project text, project.json>" } }
```

Source data, `seed.quantity-data/0.2`:

- **table:** `columns` = a `label` column (default name `region`), one `value` column in K (the only one with that role, or named in `columns.value`), optionally its `std`
  column in K (recorded in `checks`, not used); one row per region; the recipe's `materials[].region` picks the row. Rows of regions the recipe does not name are ignored.
- **scalar:** `{kind: "scalar", unit: "K", value, std?}` for a recipe that names exactly one material and no region.

The reply: `{ok: true, output: {content}, checks: {applied: [{material, region, temperatureK, previousK, sourceStdK, rangeK}], meaning, sets, reformatted}}` or
`{ok: false, errors: [{code, field, message}]}` (all problems found, at most 20; never a partial project). `content` is the whole new project text in Studio's own format
(`JSON.stringify(project, null, 2)`; the final newline is kept as the input had it), so only the named materials' `temperature` lines differ. **model.py is not in the
reply**: SEED regenerates it from the new project text with Studio's generator, as it does at every validate and run; `test_fuel_temperature_regen.js` shows that
regeneration is byte-identical every time and differs from the old script only in the temperature lines.

## Refusals

| Code | When |
|---|---|
| `E_UNITS` | the source unit is not K or its dimension is not `temperature` (degC is refused); `units.to` is not K; the data's unit or a std unit is not K; a normalization other than `none` is claimed (a temperature is absolute) |
| `E_COVERAGE` | a named material has no row for its region in the source (nothing is extrapolated, defaulted or carried over); no label column |
| `E_NUMERIC` | a value or std that is NaN, infinite, missing, a string, a boolean or a list (NaN and Infinity tokens in the JSON are refused at parse) |
| `E_TEMPERATURE_RANGE` | a value outside what the cross-section data supports: **250 K to 2500 K** for the ENDF/B-VIII.0 neutron data (every neutron file has 250, 294, 600, 900, 1200, 2500 K), narrower for a material with a thermal scattering table (`c_U_in_UO2`, `c_O_in_UO2` 296 to 1200 K, `c_Graphite` 296 to 2000 K, `c_H_in_H2O` 284 to 800 K, read from the files); a table name not in that list has no known range and is refused. The recipe's `applicability.range` can narrow, never widen. Refused, not clamped |
| `E_UNSUPPORTED` | another `target.field`, a non-steady time mapping, a `meaning` other than `volume-mean` |
| `E_RECIPE_INVALID` | an unknown key in `mapping.spatial`, extrapolation not `refused`, a material the project does not have or names twice, a quantity name that differs from the recipe's, a scalar with several materials or a region |
| `E_SCHEMA_INVALID` | the request, the table (duplicate column names, two std columns, a repeated region, a row of the wrong length) or the target project is not what it says |

## What exists today for the loop's noise question

- `describe` and the runner are **fixed-source only**: `headless run` refuses an eigenvalue project (`E_UNSUPPORTED`), so the runner does **not** run or report k-eff today.
  Studio's `results.load` does read k-eff with its standard deviation from an eigenvalue statepoint (`summary.keff = [mean, std]`); `headless._extract` rejects the run mode
  before it gets there. Letting the runner do eigenvalue runs is a separate, small change (not made).
- Tally results carry an **absolute standard deviation and a relative error per bin** (`rows[].std`, `rows[].rel_err`); the SEED adapter writes the `std` column.
- Timing (WSL Ubuntu, OpenMC 0.15.3, 16 cores idle, 2026-10-25): the TRISO example, fixed source 1000 x 10, takes 5.4 s on 1 thread and 4.6 s on 4 threads, wall time through
  `headless run`; Studio's depletion pin fixture as an eigenvalue case (2000 x 15, 5 inactive, k-eff 1.3683 +/- 0.0047 = 471 pcm) takes 5.4 s wall on 4 threads, run directly
  as model.py. Twenty-five passes of that size would be about two and a half minutes of OpenMC time; the noise of 2000 x 10 active is already 471 pcm, so a loop that wants to
  tell convergence from noise needs far more histories per pass, and its time grows with them.
