# CAD engine environment

The pinned FreeCAD/GEOUNED environment behind Convert > Import CAD…, its checks,
and the integration job. Setup for users is in [INSTRUCTIONS.md](../../INSTRUCTIONS.md#6-optional-cad-import-step-files);
this page is the developer view. `verify.py` started as the stage-0 engine spike and
remains the quickest real-engine check.

`run_integration.cjs` is the CAD integration job: all 17 CAD suites against the real
engines, browser, OpenMC and the MCNP exporter. It exits 0 only if every suite ran and
passed with nothing skipped; missing tools fail it before it starts. There is no hosted CI:
run this job before merging CAD changes. It needs no accounts or secrets, only the tools below.

## Reproduce on Linux x86-64 / WSL

From the repository root, with Conda available:

```bash
conda create -n openmc-cad --file setup/cad/locks/linux-64.explicit.txt
conda activate openmc-cad
python setup/cad/verify.py --output "$HOME/OpenMC-cad-check-$(date +%s)"
python setup/cad/check_rejections.py
python test/test_cad_git_policy.py
```

Choose a new output directory outside the repository on every run. The verifier
refuses to overwrite an existing result. It exits nonzero on a failed conversion,
missing dependency or timeout; it never reports success by skipping CAD tests.
Each fixture runs in its own child process with a 180-second deadline and its own
working directory. This fixture runner is not the future cancellable server job
manager and is not an upload sandbox.

The explicit lock records the full installed package URLs, builds and MD5
checksums. `environment.yml` records the original solve inputs; it is not an exact
lock. Keep the existing OpenMC/MCNP environment unchanged. Do not install these
engines in the repository or vendor their code. Native Windows and macOS are not
validated by this lock. Clean-machine installation is checked by creating the
environment from the lock with an empty package cache (`CONDA_PKGS_DIRS` pointing at a
new folder), so every package comes from its recorded URL and checksum, and then running
the real-engine suites against it.

FreeCAD's conda-forge Python modules are in the environment's `lib` directory.
The adapter adds this directory before importing FreeCAD and initializes FreeCAD
before Part. Importing FreeCAD can clear names from `__main__`, so the fixture
checker keeps its verification dependencies local. No shell command is stored
in `OPENMC_CAD_PYTHON`, and this stage does not change Studio's worker setting.

## Verified scope

The four cases are a drilled block and annular cylinder, both axis-aligned and
translated/rotated. Each checks five explicit hole/material probes and 20,000
seeded points against FreeCAD containment. Sampled CSG volume is checked against
an analytical formula with a six-standard-error threshold. STEP readback volume
must also agree with the formula. No generated Python is executed.

The report records versions, source bounds converted to centimeters, the
millimeter-to-centimeter unit convention, source/XML hashes, point counts and
volume evidence. Raw STEP, XML and logs remain in the external output directory.
Rejection checks cover multiple solids, an open face, a torus, unsupported file
extensions and the 16 MiB input limit. The adapter also limits emitted XML to
8 MiB and rejects suspicious-solid artifacts.

## Findings for the next stages

- GEOUNED 1.6.2 with `voidGen=False` emits one cell for each of these single-solid
  cases, with centimeter coordinates and no background region. Keep Studio as
  the owner of the finite world and background in the future import adapter.
- These cells are marked `material="void"`. This is an unassigned CAD region,
  not a user's intentional choice of void. Require material assignment later.
- The writer assigns `boundary="vacuum"` to the final surface even when it is
  an internal hole surface. The future XML adapter must normalize internal
  boundaries to transmission and construct an explicit world boundary. The
  stage-0 checks evaluate regions only; this XML is not a runnable transport model.
- Rotated curved surfaces can become general quadrics. Preserve their coefficients
  and Boolean expressions in the new CSG schema; never approximate them with boxes.
- Assemblies, source-to-cell mapping, microscopic features, external CAD fixtures,
  uploads, cancellation, rendering, material assignment and transport remain later
  gates. The sampling checks do not establish general CAD correctness.

Upstream still warns against GEOUNED 1.6.3/1.6.4 as of 2026-09-23:
https://github.com/GEOUNED-org/GEOUNED#geouned

FreeCAD/GEOUNED and their dependencies retain their own licenses. The environment
recipe and adapter do not relicense or bundle those projects.
