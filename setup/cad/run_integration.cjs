// The CAD integration job (stage 5 of docs/cad-import-plan.md): every CAD suite, in order,
// against the real engines. It exits 0 ONLY if every suite ran and passed with nothing
// skipped. A missing tool is a failure, not a skip: this job can't pass by skipping.
//
// Required (paths as the server host sees them; on Windows the host is WSL):
//   OPENMC_CAD_PYTHON      pinned CAD interpreter (setup/cad/locks)
//   OPENMC_PYTHON          Python with openmc (Studio's server environment)
//   OPENMC_MCNP_PROJECT    companion exporter checkout
//   OPENMC_CROSS_SECTIONS  cross_sections.xml, for the transport run in the CSG end-to-end
//   NODE_PATH              must resolve playwright
// Optional: OPENMC_MCNP_PYTHON (default OPENMC_PYTHON), E2E_PORT (default 8766),
//           BROWSER_CHANNEL (default msedge; use chromium on Linux CI).
//
// Run from the repository root:  node setup/cad/run_integration.cjs
// On Windows run it from PowerShell or cmd (Git Bash rewrites /root/... values).
// The MCNP parity suite starts the machine-wide MCNPy bridge (port 25333).
const {spawnSync, execFileSync} = require('child_process');
const path = require('path');

const REPO = path.resolve(__dirname, '..', '..');
const WIN = process.platform === 'win32';
const env = process.env;
const need = ['OPENMC_CAD_PYTHON', 'OPENMC_PYTHON', 'OPENMC_MCNP_PROJECT', 'OPENMC_CROSS_SECTIONS', 'NODE_PATH'];
const missing = need.filter(k => !env[k]);
if (missing.length) {
  console.error(`CAD integration job: FAILED before starting - set ${missing.join(', ')}. Nothing is skipped here.`);
  process.exit(2);
}
try { require.resolve('playwright', {paths:env.NODE_PATH.split(path.delimiter)}); } catch (e) {
  console.error('CAD integration job: FAILED - playwright is not on NODE_PATH.');
  process.exit(2);
}
const q = s => `'${String(s).replace(/'/g, `'\\''`)}'`;
const repoHost = WIN ? execFileSync('wsl.exe', ['wslpath', '-a', REPO.split(path.sep).join('/')]).toString().trim() : REPO;
const MPY = env.OPENMC_MCNP_PYTHON || env.OPENMC_PYTHON;

// A Python suite runs on the server host, with the interpreter's own bin first on PATH.
const py = (interp, script, extra = '') => ({kind:'python', label:script,
  cmd:`export PATH="$(dirname ${q(interp)}):$PATH" OPENMC_CAD_PYTHON=${q(env.OPENMC_CAD_PYTHON)} ` +
      `OPENMC_CROSS_SECTIONS=${q(env.OPENMC_CROSS_SECTIONS)} OPENMC_MCNP_PROJECT=${q(env.OPENMC_MCNP_PROJECT)} ${extra}; ` +
      `cd ${q(repoHost)} && ${q(interp)} ${script}`});
const node = (script, extra = {}) => ({kind:'node', label:script + (extra.E2E_CAD_MODE ? ` (${extra.E2E_CAD_MODE})` : ''), script, extra});

const SUITES = [
  py(env.OPENMC_PYTHON, 'test/test_cad_git_policy.py'),
  py(env.OPENMC_PYTHON, 'test/test_cad_schema.py'),              // needs openmc: its OpenMC comparison must run
  py(env.OPENMC_PYTHON, 'test/test_cad_jobs.py'),
  py(env.OPENMC_PYTHON, 'test/test_cad_jobs_http.py'),
  py(env.OPENMC_CAD_PYTHON, 'test/test_cad_worker_protocol.py'), // the CAD Python runs its real-FreeCAD case
  {...py(env.OPENMC_CAD_PYTHON, 'setup/cad/verify.py --output "$(mktemp -d -u /tmp/openmc-cad-verify-XXXXXX)"'), label:'setup/cad/verify.py'},
  py(env.OPENMC_CAD_PYTHON, 'setup/cad/check_rejections.py'),
  py(env.OPENMC_PYTHON, 'test/test_cad_jobs_engine.py'),
  py(env.OPENMC_PYTHON, 'test/test_cad_native_engine.py'),
  node('test/test_cad_modal_browser.cjs'),
  node('test/test_cad_import_browser.cjs'),
  node('test/test_cad_csg_browser.cjs'),
  node('test/test_cad_csg_gate.cjs', {OPENMC_PYTHON:env.OPENMC_PYTHON}),
  node('test/test_cad_import_e2e.cjs', {STUDIO_PYTHON:env.OPENMC_PYTHON}),
  node('test/test_cad_import_e2e.cjs', {STUDIO_PYTHON:env.OPENMC_PYTHON, E2E_CAD_MODE:'csg'}),
  node('test/test_cad_mcnp_parity.cjs', {OPENMC_MCNP_PYTHON:MPY}),
  node('test/test_cad_restart_e2e.cjs', {STUDIO_PYTHON:env.OPENMC_PYTHON}),
];

// A skip anywhere fails the job: unittest's "skipped=N", "[SKIP]", or a line starting SKIP.
// (Not the bare word: the exporter reports "0 on-surface points skipped" in a passing check.)
const SKIP = /\bskipped=\d+|\[SKIP\]|^\s*SKIP\b/im;
const results = [];
const t0 = Date.now();
for (const s of SUITES) {
  const start = Date.now();
  // A hung suite fails after 30 minutes with its output, instead of stalling the job silently.
  const opts = {encoding:'utf8', maxBuffer:1 << 28, timeout:30 * 60 * 1000, killSignal:'SIGKILL'};
  const r = s.kind === 'python'
    ? spawnSync(WIN ? 'wsl.exe' : 'bash', [...(WIN ? ['-e', 'bash'] : []), '-lc', s.cmd], opts)
    : spawnSync(process.execPath, [path.join(REPO, s.script)], {...opts, cwd:REPO, env:{...env, ...s.extra}});
  const timedOut = r.error && r.error.code === 'ETIMEDOUT';
  const out = `${r.stdout || ''}${r.stderr || ''}${timedOut ? ' (timed out after 30 min)' : ''}`;
  const skipped = SKIP.test(out);
  const ok = r.status === 0 && !skipped;
  results.push({label:s.label, ok, skipped, secs:(Date.now() - start) / 1000});
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${s.label}  (${((Date.now() - start) / 1000).toFixed(0)} s)${skipped ? '  <- something was SKIPPED' : ''}`);
  if (!ok) console.log(out.split('\n').slice(-25).join('\n'));
}
const bad = results.filter(r => !r.ok);
console.log(`\nCAD integration job: ${bad.length ? `FAILED (${bad.length} of ${results.length})` : `PASSED, all ${results.length} suites, nothing skipped`} in ${((Date.now() - t0) / 60000).toFixed(1)} min`);
process.exit(bad.length ? 1 : 0);
