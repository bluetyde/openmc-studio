# OpenMC Studio review and future workflow

Reviewed 2026-09-18: https://github.com/bluetyde/openmc-studio and D:\OpenMC.
Local HEAD and GitHub HEAD both resolve to ad60cf67e693adf8e9e0aec4552539e0b48a3db1. Local tracked worktree was clean. This is a targeted source review, not certification of transport physics or a full application audit.

## Findings to address

### P1: B-10 preset does not resolve its material or reaction reliably

Evidence: studio/openmc_studio/static/index.html:549, 1494-1501, 2372-2384.

Normalization defaults responseScore to '(n,p)'. The B-10 preset inherits that nonempty value instead of choosing '(n,a)'. Automatic material lookup only handles He-3, so a B-10 preset with an empty responseMat produces matVar=None, even if a B10 material exists. The material and reaction selectors are hidden for presets. The generated macro filter then attempts mat.get_nuclide_atom_densities() on None if execution reaches that statement; earlier reaction lookup may also fail.

Reproduced the resolver expressions with a B10 material present: responseMatId='', responseScore='(n,p)', matVar='None'. Presets should explicitly resolve their isotope, reaction and material, validate availability, and override stale custom fields. Test fresh presets, switching between presets, and loading saved projects.

### P1: Custom detector material response silently uses only its first component

Evidence: studio/openmc_studio/static/index.html:1478-1479, 1496.

The generator takes comps.split(':')[0] and constructs a filter from just that nuclide. A multi-isotope detector therefore omits other response contributions, and reordering composition text changes the selected nuclide. Natural-element component names can also fail library lookup. The fallback atom density of 1.0 masks missing nuclides instead of reporting inconsistent material data.

Either expose and validate one explicit response nuclide, or compute a material response from all applicable nuclides on a shared energy grid. Reject missing material/nuclide data. Add a two-isotope fixture and verify that composition order does not change its result.

### P2: Dense rays silently lose geometry after 96 BVH candidates

Evidence: studio/openmc_studio/static/index.html:3989, 4229-4247.

MAX_CAND is 96, and traversal stops when that many intersecting leaf bounding boxes are collected. Candidates are sorted by CSG priority only after truncation. Omitted parts can include the visible surface or a higher-priority overlap, especially for nested or deep arrays and cutaways. Bounding-box hits consume slots even when the ray misses the actual shape. Supporting a large total part count does not remove this per-ray limit.

Use traversal that preserves the required visible/CSG intersections, or detect overflow and provide a safe fallback with a visible diagnostic. Add fixtures with more than 96 intersecting bounds and compare rendered/picked geometry with the full geometry evaluator. This finding is source-confirmed; no GPU reproduction was run in this review.

## Future development workflow

1. Start from recorded facts: branch, commit, clean/dirty status, and remote HEAD. Read TODO.md before older handoff notes. Preserve unrelated edits.
2. Keep this review's findings in the active backlog until each has a regression fixture and a verified fix. Prioritize detector correctness before more geometry features.
3. Retain small regression fixtures in git. The tracked test/shielding_demo.py is an executable model example; no tracked CI workflow or automated assertion suite was found. Convert valuable scratch checks into repeatable tests with explicit expected results.
4. Use three validation levels: fast syntax and pure model tests; OpenMC integration tests in the supported environment; browser checks for editing, rendering and asynchronous run/result changes. Fast tests should not require the large nuclear-data library.
5. For detector changes, verify preset selection, response units, isotope mixtures, unavailable reaction data, and saved-project round trips. Compare a small reference response numerically, with documented tolerances.
6. For geometry changes, compare point classification with OpenMC, test overlaps and lost particles, and check both slice and 3D views. Include deleted lattice elements, moderator selection, rotations and dense-ray cases.
7. For export changes, record the companion openmc-mcnp-project commit and dependency versions. Distinguish translation, parser validation, geometry checks, and actual MCNP execution. Do not describe an unexecuted MCNP deck as transport-verified.
8. Record reproducibility details with validation: Studio and exporter commits, Python/OpenMC/Java versions, nuclear-data identity, OS/browser, fixture, seed, command and result. Test Windows/WSL and macOS launchers when their behavior changes; mark unavailable-platform checks pending.
9. Keep TODO.md concise and current. Its header still names c44381e; the completed progress item still contains present-tense statements about missing progress. Move historical rationale into a completed section and retain one clear current status per item. Older workspace progress notes contain superseded architecture and feature limits.
10. Finish each change with a short handoff: problem, files changed, checks and results, limits, next action, and commit/push status. Commit related code, fixtures and documentation together after review.

## Validation and limits of this review

- GitHub HEAD checked through authenticated git access; it matches the local source reviewed. Browser retrieval of the repository was unavailable.
- All six tracked Python files under studio parsed successfully. The inline JavaScript parsed successfully using Node.
- The B-10 resolver was exercised independently using the source expressions; this was not an end-to-end browser test.
- An initial broad Python file scan encountered a non-UTF-8 untracked filesystem file; the authoritative syntax check was rerun against tracked source files only.
- No OpenMC transport run, MCNP execution, browser/GPU test, or macOS validation was performed. No application code was changed.
