# Nodal core package (optional add-on): plan

Status (2026-10-07): **planned, not started.** Nothing here is built. Written after the deep dive on openndm (`research/other-project-surveys/2026-10-07-deep-dive/03-rizkiokt-openndm.md`)
and the decision that this is an **optional package** for users doing a PWR-type core, not part of the core app. A simple TRIGA or shielding user never sees it.

## What it is

An add-on component for OpenMC Studio that turns a lattice model into few-group constants (`openmc.mgxs.Library`), solves a coarse 3D core with
[openndm](https://github.com/rizkiokt/openndm) (MIT; C++17 core, Python API; eigenvalue, critical boron, rods, Doppler and moderator feedback, transient),
and shows the nodal k and power map **beside OpenMC's own k**. The first user is RAFT's BEAVRS PWR lesson, which needs fast boron, rod and feedback sweeps
that Monte Carlo cannot give.

## What the package is allowed to claim

openndm's own full-core comparison against OpenMC (its requirement "C-4") is **not started**. Until this package has run that comparison and shown it, the tab says
"fast estimate, checked against OpenMC on N cases" and shows the k difference in pcm beside every nodal result. No accuracy statement reaches a lesson before step P2 passes.

## What exists in Studio today (checked 2026-10-07)

- Rectangular and hexagonal lattice models and a RegularMesh tally with per-voxel mean and std in `results.json`.
- `provenance.json` records versions, nuclear-data hash, settings, seed, outcome. It does not yet record optional-component versions
  (`docs/plans/11` in the SEED repo says installed-component versions go in run provenance when relevant).
- No group-constant generation, no sweeps, no critical-boron search, no per-pin or per-assembly table.
- Optional components are planned by SEED (`experiment-studio/docs/plans/11-runtime-and-shared-acceptance.md`, "Optional add-ons"): each app publishes component
  IDs, versions, required/optional, dependencies, platforms, capabilities, hashes, sizes and licences. Nothing for it is built; the first add-on is CAD.

## Steps (each stops with a go/no-go)

**P0: can Studio make the group constants? (1 to 2 days, the first experiment.)** From a generated lattice test model (a small assembly array), build an
`openmc.mgxs.Library` with a chosen group structure and the lattice domains, run OpenMC to fill it, and load it into openndm in a throwaway script in the sandbox
(no repo change). Go/no-go: does it work with no extra user steps, and how long does it take on a small core? Output: a note with times and the manual steps found.

**P1: wrap the solver (2 days).** A small module that takes the library, the lattice map and pitch, runs openndm, and returns k, a power map and (optional) critical boron.
Set `OMP_NUM_THREADS` explicitly (the deep dive saw it stall at 16 threads, fine at 1 to 8). Pin one openndm version. Test against openndm's own published numbers
(IAEA-2D SANM +21.5 pcm from 1.02959, BIBLIS-2D) before anything of ours: if the wrapper cannot reproduce them, stop.

**P2: the comparison against OpenMC (the C-4 check; 3 to 4 days).** The same small core run both ways: OpenMC k and a lattice mesh power map against the nodal ones.
Report the k difference in pcm and the power-map differences per assembly. Proposed pass line (to be decided by the user after seeing the first numbers, not before):
agreement within a stated number of pcm and a stated percent in assembly power, with the uncertainty of the OpenMC side included. A failing case is kept as a test.

**P3: the tab (3 to 4 days).** Core tab with the lattice map, group structure choice, "Solve", the nodal k and power map beside OpenMC's k, and the P2 note.
Absent package: the tab is not shown, and the operation says "needs the nodal package" with a setup route (SEED's rule: a missing capability blocks that operation only).

**P4: package manifest (1 to 2 days).** Follows SEED's component manifest format (`seed.component-manifest/0.1`, SEED branch `claude/w2-runtime-contract`,
`docs/runtime-contract.md` and `schema/component-manifest.schema.json`; the SEED agent's note is in `messages/openmc.md`, 2026-10-07). One file, `seed.components.json`,
in this repo, with a component of kind `addon`:
- `id` `nodal-core`, our own semantic version, `title`, `description`; `platforms` limited to what openndm's wheel really supports (not yet checked: Windows via WSL x64 is the
  tested case; macOS arm64 only if a wheel or a build is confirmed);
- `appVersions.min` the Studio version that has the Core tab (P3);
- `dependsOn` the app's core runtime component (its id comes from Studio's own core manifest, to be written with the CAD add-on; not invented here) with a minimum version;
- `capabilities` `group-constants` and `nodal-solve`: the names SEED's note gives as examples, so a Studio operation can refuse with a message naming the missing component;
- `artifacts` the pinned openndm wheel (https URL, sha256, download and expanded sizes, archive type), and our wrapper if shipped separately;
- `license` `spdx: MIT`, with the notices file hash (openndm's MIT notice goes in the package's third-party notices).
SEED pins the manifest hash in its own catalog; a project or agent never supplies a manifest or an install command. Studio keeps owning its capability checks. Models, results and
custom materials stay out of the component folder (removing the add-on must not touch them). The install root, the "only a human presses Add" rule and the trust source are
**undecided by the user**: do not depend on them. Provenance records the installed component versions on every nodal result. Fake-artifact tests first. The manifest for the CAD add-on
comes first (the plan's first case), and the core runtime component's id and version come with it.

**P5: RAFT handoff (1 day).** A result file: nodal k, power map, critical boron, rod worth, with the full provenance and the P2 comparison. RAFT reads that file and nothing else.
The BEAVRS reference data (boron letdown, HZP states) stays RAFT's side; `virtual-reactor/validation/m8_beavrs_hzp.py` already compares against it.

## How to prove it right

1. openndm's own benchmark numbers reproduced through our wrapper (P1).
2. OpenMC vs nodal on a small core, per the P2 comparison, kept as tests; each kept as a regression number.
3. Break tests: scramble the lattice map ordering, swap the group order, drop an assembly's domain; each must make a check fail (the library and the map must share one domain ordering).
4. Removing the package: Studio launches, core runs work, the tab is gone, saved projects still open (SEED plan 11 acceptance).
5. Provenance names the openndm and package versions on every nodal result.

## Risks

- **Library mismatch:** the domain ordering of the MGXS library and the lattice map must agree (openndm has a helper for it; use it, test it).
- **Accuracy on a real core:** nodal diffusion has stated limits (rod cusping, no pin-power reconstruction). The tab says what it cannot do.
- **Thread stall and maintenance:** pre-1.0, one main author; pin a commit, record the version, set threads explicitly.
- **Group constants cost:** generating them needs an OpenMC run per assembly type; on a full core this is minutes to hours, not seconds. P0 measures it.
- **Scope creep:** depletion, pin power, transients stay out until P2 passes.

## Not in this plan

Depletion; the pin-power table and IFP kinetics (separate items from the investigation report); GPU or Metal engines; any claim of accuracy for non-PWR cores.

## Decisions for the user

1. Studio owns the package; RAFT is the first consumer, SEED packages and installs it. (Proposed.)
2. The pass line in P2: decided after the first comparison numbers, by the user.
3. Start with P0 now. The manifest format is now written (SEED W2, pending its merge to SEED main), so only the open install-root and trust questions remain with the user. Recommended: start P0; write the manifest after the CAD add-on's manifest exists.
