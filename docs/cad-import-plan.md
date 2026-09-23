# ADR: Real CAD import with FreeCAD and GEOUNED

Status: Staged implementation plan. Prepared 2026-09-22 against Studio f515d40.
Progress 2026-09-23: stage 0 implemented and validated on four real WSL fixtures;
see [setup and findings](../setup/cad/README.md). Later stages remain pending.
Owner: OpenMC Studio maintainers. Implementation gates below determine readiness.

## Decision

Use FreeCAD/OpenCASCADE to read and inspect CAD, and GEOUNED to convert complex
analytical solids into CSG. Offer two clearly identified results:

1. Native parts: validated boxes, spheres, cylinders and cones, editable with
   Studio's existing dimension controls.
2. Imported CSG components: surfaces and Boolean regions produced by GEOUNED,
   with names, material assignment and cell tallies. Initially their geometry
   is read-only; they are not mislabeled as editable native primitives.

Build the first route and prove the second route in a command-line fixture
spike at the outset. Do not declare general CAD import complete after only
shipping primitive recognition. DAGMC is a separate later capability, not an
automatic fallback, and ordinary STL is not an OpenMC transport geometry.

GEOUNED documents both OpenMC XML output and its load/convert/export workflow.
Use those public interfaces behind a version-specific adapter, not an import
of an internal module with no conversion call.
[Official example](https://geouned-org.github.io/GEOUNED/dev/example_of_use.html),
[API reference](https://geouned-org.github.io/GEOUNED/dev/python_api.html).

## Corrections to the pasted proposal

Options considered:

| Approach | Decision and trade-off |
|---|---|
| Primitive classifier alone | Useful first release, but insufficient for holes and general CAD; cannot satisfy the full request alone |
| GEOUNED alone | Reuses real decomposition, but still requires a Studio CSG data model and loses native dimension editing |
| Classifier plus GEOUNED | Recommended staged approach: native editing where geometry is proven equivalent, general analytical regions elsewhere |
| DAGMC for all CAD | Separate future transport path with different dependencies and editing semantics; not part of this initial implementation |

Consequences: conversion remains an optional heavy dependency; saved geometry
must remain portable; two geometry representations require shared validation,
selection and material semantics. The initial UI favors explicit import modes
over an untested automatic mixture.

- Fixed face/edge counts are hints, not recognition criteria. CAD kernels may
  split an otherwise cylindrical face at a seam. Conversely, spherical or
  cylindrical support surfaces can bound only a small trimmed portion.
- Fit a candidate primitive, rebuild it with the kernel, and compare both
  directions of the geometric difference. Volume alone misses displaced holes
  and different shapes with equal volume.
- A cylindrical shell is not a full cylinder. Preserve its inner void using
  a validated region representation; until that exists, route it to GEOUNED or
  report it unsupported. Do not depend on insertion order to invent a shell.
- Use the CAD reader's unit handling and a documented kernel-to-Studio unit
  boundary. Do not scan STEP text for one unit token and multiply a second time.
- The current valid void material ID is `void`, not `m_void`. Do not assign
  the first available material automatically. Track pending material assignment
  separately so an unassigned solid is not silently simulated as empty space.
- Studio groups currently organize parts and lattices; they are not a general
  Boolean-tree interchange format. General CSG requires new model support.
- No automatic partial imports: present omissions before the user commits them.

## End-to-end user workflow

1. Convert > Import CAD checks available capabilities and displays the supported
   format/version. First release accepts STEP/STP only.
2. User selects a file. Server creates a unique job and preserves the source as
   an immutable job artifact. The project remains unchanged during conversion.
3. Worker reads the assembly, applies placements, inventories solids, and reports
   invalid/open shapes, units and unsupported surfaces by source object name.
4. User chooses native-parts import or analytical-CSG import. The report makes
   the different editing capabilities visible. A later Auto mode can route each
   solid only after mixed-mode material/overlap semantics have passed tests.
5. Worker converts and validates. A preview lists every source solid as accepted,
   rejected or failed; it displays the bounding dimensions and material mappings.
6. User commits the validated result as one undoable transaction. Cancellation
   or failure adds nothing. Partial import requires an explicit choice identifying
   omitted solids, retained in the project report.
7. The saved project contains all geometry needed to reopen it without the CAD
   file or FreeCAD. Original CAD is needed only for reconversion or source edits.
   Track relative attachment references and source hashes, never required absolute
   Windows/WSL paths. Warn about changed source files rather than replacing parts.
8. Material assignment and a finite world boundary must be resolved before a
   transport run. No dummy hydrogen or arbitrary first-material assignments.

## Runtime and dependency layout

Keep the existing OpenMC environment unchanged. Create a separate Conda
environment, `openmc-cad`, containing mutually compatible Python, FreeCAD,
OpenCASCADE and GEOUNED. Initial target: Linux x86-64 under WSL, where the Studio
server already runs. Prefer the same operating-system side for server and worker:

Browser on Windows -> Studio server in WSL -> CAD Python in WSL -> job directory
on WSL's Linux filesystem. The server supplies the module's source location to
the worker; dependency installation does not require copying the repository.

Set `OPENMC_CAD_PYTHON` to that environment's actual Python executable through
local configuration. The existing launcher accepts an executable path, not a
string containing `wsl ...` or a shell command. Native Windows support needs its
own tested environment lock. If crossing hosts becomes necessary, add an explicit
launcher using argument arrays, path mapping and process ownership; do not guess
that finding wsl.exe makes a CAD engine available. macOS/ARM is a separate gate.

Upstream's installation guide uses a separate Python 3.11 environment and
conda-forge GEOUNED, with FreeCAD among its dependencies. Treat that as the
starting environment recipe, not proof of a tested combination.
[Installation guide](https://geouned-org.github.io/GEOUNED/dev/quick_install_guide.html).

Version gate: upstream currently warns against GEOUNED 1.6.3 and 1.6.4 because
of incorrect conversions and suggests 1.6.2 or earlier. Start by evaluating
1.6.2, confirm the warning's current status when implementation starts, and pin
the version/build that passes our fixtures. Do not install an unqualified latest.
Record Python, FreeCAD, OCCT, GEOUNED, adapter and platform versions in each report.
[Upstream warning](https://github.com/GEOUNED-org/GEOUNED#geouned).

Track an environment recipe and platform-specific lockfiles after solving and
testing them. No invented FreeCAD/OCCT pins in this planning document. The health
probe must construct a solid and complete a tiny conversion; successful imports
of Python modules alone do not make `can_import` true.

## Backend design and job contract

Retain `cad_worker.py` as the protocol entry point. Move geometry work to small
modules: `cad/read.py`, `cad/primitives.py`, `cad/geouned_adapter.py`,
`cad/schema.py`, `cad/validate.py`, and `cad/report.py`.

Use one disposable CAD subprocess per job initially. Conversion errors, native
kernel crashes and memory growth must not poison later jobs. Serialize jobs at
first; no MCNPy gateway is needed for CAD conversion. Harden the existing manager:
correlate every result by job ID, reject late results, terminate only the owned
process group on cancellation/timeout, wait for termination, then clean up.
Terminate before closing blocking stdout reads. A subprocess is crash isolation,
not a security sandbox; use a dedicated low-privilege account/container if the
server is later exposed to untrusted remote uploads.

Proposed API: POST conversion creates a job and returns 202/jobId; GET job status
returns progress and the report; DELETE cancels; GET job result returns the
validated geometry. Status includes actual capabilities, versions and reasons
for unsupported modes. Conversion must not block the HTTP request for minutes.

Use server-generated paths and allowlisted formats, never a client filename or
project title as a path. Preserve a sanitized original name only as metadata.
Limit upload size, solid count, processing time, output size, AST depth and mesh
size. Keep existing local-server authentication. Defaults are configurable and
benchmarked in phase 0, with explicit limit errors and no truncated geometry.

Place private inputs, converted STEP, intermediate XML, debug solids and logs
under the configured user-data/job root outside the checkout. Cache keys include
source hash, all engine versions, tolerance settings, mode and adapter version.
Delete cancelled job scratch; retain failure reports for a documented short
retention period. Referenced source attachments are durable project data, not
evictable cache entries. Give users a clear-cache action.

## Route A: native primitive recognition

Read valid closed solids and fully resolved assembly placements through FreeCAD.
Obtain face surface classes and trimmed topology. Merge equivalent support
surfaces where safe; keep stable source assembly paths even for duplicate labels.

First support box, sphere, capped cylinder and cone/frustum. For each candidate:

- Recover the local orthonormal frame and dimensions from the actual surfaces
  and cap offsets. For a cylinder, compute cap positions along the axis rather
  than averaging arbitrary plane origin points.
- Reconstruct the solid in the source coordinate system. Require a valid closed
  result and compare symmetric-difference volume, boundary distances, bounds and
  deterministic interior/exterior test points. Fail uncertain Boolean comparisons.
- Use scale-aware, recorded tolerances. Calibrate against microscopic coatings
  and large assemblies; do not accept a tolerance that can erase the smallest
  feature under test. Geometric equivalence is within stated tolerances, not a
  claim of exact arithmetic or proof from a few samples.
- Convert kernel millimeters to Studio centimeters once. Preserve double precision.
  For arbitrary cylinder directions, normalize to axis `z` plus Euler rotations
  using Studio's Rz*Ry*Rx convention; validate the reconstructed matrix rather
  than expecting unique Euler angles. Handle gimbal lock and reject unhandled
  reflection/scale transforms explicitly.
- Emit existing native-part fields and assign fresh IDs at commit. Display a
  pending material badge with valid `material:'void'` storage; require intentional
  void or real material selection before running.

Add wedge/hex-prism/ellipsoid recognition only with independent fixtures and
equivalence checks. STEP files produced by other CAD tools must be represented
in the fixture corpus; self-roundtrips alone can reproduce the same bug twice.

## Route B: genuine GEOUNED conversion

In the pinned adapter, call the documented `CadToCsg` workflow: load STEP,
start conversion, export OpenMC XML. Set a job-local output location and stop on
unsupported spline surfaces; never choose a setting that silently removes or
ignores them. Treat suspicious-solid diagnostics as validation failures unless
explicitly resolved, not cosmetic warnings. Verify the exact release's arguments
in phase 0 rather than copying development API signatures into production.
[Public API](https://geouned-org.github.io/GEOUNED/dev/python_api.html).

Consume XML as data with a bounded XML parser and an explicit OpenMC region
grammar; do not execute generated Python and do not regex-convert STEP text.
OpenMC XML is the initial interchange contract. A direct in-memory adapter may
replace it later if it reduces loss and its API can be maintained.

Create a versioned Studio intermediate representation containing:

- Surface table: ID, supported mathematical type, coefficients, unit convention.
- Region tree: halfspace(surface ID, sign), intersection, union, complement.
- Cells: stable Studio ID, region, material status, source-solid path and label.
- Component metadata: source hash, adapter/engine versions, bounds, validation
  status, conversion settings, cell-to-source map and preview asset identity.

Start with planes and quadrics/sphere/cylinder/cone forms that can be represented
without approximation. Reject unsupported types, including tori if the renderer
or exporters cannot handle them. Expand support one surface type at a time.
Inspect surface coefficients during unit conversion: it is not sufficient to
multiply every quadric coefficient by the same scale factor. Prefer the verified
OpenMC XML unit convention; a millimeter/centimeter fixture gate prevents double
conversion.

Handle one source solid decomposed into several cells as one selectable component
with child cells. Preserve assembly placements and independent instances. Imported
cells must not pass through the existing native-part overlap-priority rewriting:
their regions already encode the geometry. Detect overlapping imported solids or
overlap with an existing project and report it before commit. First general-CSG
release imports into a new project; merging with existing geometry is a later gate.

Choose one owner for world and void generation. Recommended initial adapter:
import material regions from GEOUNED and construct the finite world plus complement
background in Studio. Verify that choice on actual converter output; if a release
requires generated voids, retain its complete validated partition instead. Never
retain both backgrounds or silently clip the imported geometry to an old world.

## Studio changes required for general CSG

- Introduce project schema version 2 with imported components, surfaces and region
  trees. Migrate version-1 projects unchanged; older clients must report unsupported
  schema rather than silently discard imported geometry.
- Update serialization, Problems validation, selection, materials and cell-tally
  mappings. General CSG does not expose misleading radius/width handles. Geometry
  edits and component transforms remain disabled until their full contract is tested.
- Add a 2D region evaluator and 3D display path. Initially use kernel-derived,
  tolerance-tagged triangle meshes per source solid for 3D display and picking;
  they are display assets, not transport geometry. Cross-sections and generated
  inputs use the analytical regions. Bind both to the same conversion hash.
- Do not insert arbitrary cells into the existing primitive ray shader without
  implementing their semantics. Exceeding shader/surface/candidate budgets must
  trigger an explicit supported preview path or visible limit error, never omission.
- Extend `buildScript`/worker to generate exact OpenMC surfaces and regions without
  evaluating source text. Preserve stable cell/material IDs and tally ownership.
- MCNP export for imported CSG is a separate parity gate in the companion exporter.
  Until it passes, disable that action for these projects with a specific reason;
  never export only the native subset or label a GEOUNED deck as a full Studio deck
  with materials/sources/tallies it does not contain.

## Delivery sequence and acceptance gates

| Stage | Concrete deliverable | Gate before moving on |
|---|---|---|
| 0: engine spike, 2-3 days | Pinned WSL environment, real health probe, FreeCAD solid inventory, GEOUNED XML for a drilled block and annular cylinder | Both holes survive independent point/volume checks; versions and units recorded; no mocks used to claim conversion |
| 1: job infrastructure, 2-3 days | Isolated cancellable jobs, safe files, diagnostics, adapter contract | Concurrent requests, crash, timeout, cancellation, stale replies, malformed inputs and cleanup tested |
| 2: native STEP import, 3-5 days | Four validated primitive classifiers, report/preview, fresh IDs, material mapping, atomic undo | Translated/rotated/mm/cm/inch fixtures; repeated imports; near-miss shapes rejected; browser import/save/reload passes |
| 3: CSG data model, 3-5 days | XML adapter, schema migration, region AST, OpenMC generation, source mapping | Annular cylinder and drilled block match CAD with correct voids; no generated Python execution |
| 4: general-CSG Studio workflow, 4-7 days | Analytical slices, 3D preview/picking, materials, tallies, persistence and run integration | Actual browser + OpenMC geometry tests; budget limits and unsupported surfaces visible; no missing cells |
| 5: parity and packaging, 2-4 days | Companion MCNP mapping tests, setup docs, CI locks, supported-platform matrix | Conversion-specific integration job cannot pass on all skips; clean-machine install and restart pass |

These are estimates for one developer, about 1-2 weeks for a narrow native importer
and roughly 3-5 weeks for the full initial workflow. Revise after stage 0; engine
compatibility, complex CAD and renderer work can increase the schedule. Each stage
has its own branch and reviewable PR. Feature flags depend on passing capabilities,
not merely whether a button or module exists. IGES follows separately: sew/validate
closed solids in FreeCAD, then feed normalized STEP to the proven adapter. Open
shells remain errors unless an explicit, validated healing operation succeeds.

## Test plan

Small generated fixtures: all four primitives, arbitrary rotations, axis-aligned
cases, mirrored instance rejection, duplicate names, multiple assembly instances,
mm/cm/m/inch units, TRISO-size shells, thin caps, translated large coordinates,
annular cylinders, drilled blocks, disconnected solids, malformed STEP, open
shells, NURBS/fillets, unsupported surfaces and very large expressions.

Assertions: source solid coverage, bijective or explicit one-to-many mappings,
preserved holes, no overlaps, explicit void partition, volume/boundary equivalence,
source-to-cell containment away from tolerance bands, and no dropped surfaces.
Use boundary-focused deterministic probes plus sampled points with recorded seed;
sampling alone is not mathematical proof. Validate actual emitted OpenMC geometry
and run geometry-debug on representative fixtures. An MCNP parser/export test is
not a real MCNP transport test; label each separately and claim the shared gateway
only for tests that actually use it.

Maintain a fast dependency-free suite and a mandatory pinned FreeCAD/GEOUNED
integration CI job. Optional local skips are allowed, but a CAD release cannot
pass its integration gate through skips. Include real-browser upload, cancellation,
partial-import choice, unique IDs, selection, material mapping, undo and reload.

## Repository layout and Git policy

Keep the adapter in the existing Studio repository. Install the engines as
dependencies outside the checkout; do not vendor FreeCAD/GEOUNED or add their
entire repositories as submodules. If an upstream patch becomes necessary, pin
an explicitly maintained fork/commit and record it in the environment recipe.

Track:

```text
setup/cad/environment.yml
setup/cad/locks/<validated-platform-lock>
setup/cad/verify.py
studio/openmc_studio/cad/*.py
test/test_cad_*.py
test/test_cad_*.cjs
test/fixtures/cad/README.md
test/fixtures/cad/generate.py
test/fixtures/cad/<small-author-owned-fixtures>
test/fixtures/cad/expected/<small-reference-outputs>
docs/cad-conversion.md
```

Keep outside Git: Conda environments, FreeCAD installations/AppImages, actual user
CAD uploads, cached B-Reps, debug decomposition files, generated meshes, job logs,
conversion scratch, large simulation results and machine-specific paths. Ordinary
portable `.openmc-studio.json` examples remain versioned. Larger public datasets
should use a documented download/checksum manifest; use Git LFS only for an
explicitly selected public reference asset that must be versioned.

Proposed `.gitignore` additions/adjustments, not applied by this plan:

```gitignore
# Local CAD engines and machine configuration
/.cad-env/
/.cad-runtime/
/setup/cad/local.env
/setup/cad/local.json

# Fallback locations only; normal runtime data belongs outside the checkout
/.cad-cache/
/cad-work/
/_cad_work/
/cad-runs/
/test/generated/cad/

# Native documents and artifacts: explicitly allow curated fixtures below
*.FCStd
*.FCStd1
*.FCStd2
*.FCStd*~
*.FCLock
*.FCBak
*.brep
*.step
*.stp
*.iges
*.igs
*.stl
*.h5m
*.AppImage
FreeCAD.log

# Only public, small, deliberately reviewed fixture inputs/expected outputs
!test/fixtures/cad/**/*.FCStd
!test/fixtures/cad/**/*.brep
!test/fixtures/cad/**/*.step
!test/fixtures/cad/**/*.stp
!test/fixtures/cad/**/*.iges
!test/fixtures/cad/**/*.igs
!test/fixtures/cad/**/*.stl
!test/fixtures/cad/expected/**/*.xml
```

Integrate this with the existing CAD rules, avoiding duplicate blocks. The current
file already ignores STEP/IGES/STL broadly, but only exempts STEP/STP/STL in fixture
and example trees; IGES and B-Rep tests would currently remain hidden. Existing
global `geometry.xml` and similar ignores also require explicit exceptions for
curated reference outputs. Decide which existing broad examples exceptions to
retain before narrowing them; do not accidentally remove tracked examples.

Acceptance check: use `git check-ignore -v --no-index` against a committed matrix
of private upload, runtime output, curated fixture, expected XML, environment
recipe and lockfile paths. Verify both ignored and deliberately tracked cases.
Ignore rules do not remove files already tracked and are not a confidentiality
boundary. Record licenses and provenance for any redistributed CAD/test assets;
never put interview/company-provided files into fixtures by default.

## First implementation task

Start with stage 0 in an isolated branch/environment: validate a pinned GEOUNED
release on a drilled block and a hollow cylinder, produce real OpenMC XML, and
show that the holes, placements and units survive. This is the evidence needed
to settle the XML adapter and renderer scope before re-enabling general CAD import.
Do not start by adding buttons or restoring the old analytical parsers.
