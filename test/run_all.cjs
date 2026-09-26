// Every Studio test, one command, with a saved summary. Profiles, each including the ones before it:
//   quick    Node suites (page logic, generators, importers): no dependencies beyond Node, about a minute.
//   browser  + headless-browser suites (playwright on NODE_PATH, Edge or BROWSER_CHANNEL).
//   physics  + the Python suites that run OpenMC and the MCNP export (fixtures regenerated first), and the
//            companion exporter's own tests. Needs OPENMC_PYTHON, OPENMC_CROSS_SECTIONS, OPENMC_MCNP_PROJECT;
//            starts the machine-wide MCNPy bridge (port 25333), so claim it where agents share a machine.
//   full     + the CAD integration job (setup/cad/run_integration.cjs; needs OPENMC_CAD_PYTHON too).
//
// Nothing is skipped quietly. A profile whose tools are missing is listed as NOT RUN with the reason, a suite
// that reports a skip counts as failed, and the exit code is 0 only when everything asked for ran and passed
// (1 = something failed, 3 = something couldn't run). The summary goes to test/results/last-run.{json,md}.
//
// Run from the repository root:  node test/run_all.cjs [quick|browser|physics|full] [--only <substring>]
// On Windows run it from PowerShell or cmd: Python suites run in WSL (paths as WSL sees them), and Git Bash
// would rewrite /root/... values. Environment variables are the ones setup/cad/run_integration.cjs documents.
const {spawnSync, execFileSync} = require('child_process');
const fs = require('fs'), path = require('path');

const REPO = path.resolve(__dirname, '..');
const WIN = process.platform === 'win32';
const env = process.env;
const PROFILES = ['quick', 'browser', 'physics', 'full'];
const args = process.argv.slice(2);
const profile = args.find(a => PROFILES.includes(a)) || 'quick';
const only = args.includes('--only') ? args[args.indexOf('--only') + 1] : null;
const want = PROFILES.slice(0, PROFILES.indexOf(profile) + 1);

const q = s => `'${String(s).replace(/'/g, `'\\''`)}'`;
const hostPath = p => WIN ? execFileSync('wsl.exe', ['wslpath', '-a', p.split(path.sep).join('/')]).toString().trim() : p;
const listDir = (dir, re) => fs.readdirSync(path.join(REPO, dir)).filter(f => re.test(f)).sort().map(f => `${dir}/${f}`);

// What each profile needs before it can run, and its suites.
function missingFor(p) {
  const miss = [];
  if (p === 'browser' || p === 'full') {
    if (!env.NODE_PATH) miss.push('NODE_PATH (to find playwright)');
    else try { require.resolve('playwright', {paths:env.NODE_PATH.split(path.delimiter)}); } catch (e) { miss.push('playwright on NODE_PATH'); }
  }
  if (p === 'physics' || p === 'full') ['OPENMC_PYTHON', 'OPENMC_CROSS_SECTIONS', 'OPENMC_MCNP_PROJECT'].forEach(k => { if (!env[k]) miss.push(k); });
  if (p === 'full' && !env.OPENMC_CAD_PYTHON) miss.push('OPENMC_CAD_PYTHON');
  return miss;
}
const node = (script, extra = {}) => ({kind:'node', label:script, script, extra});
const py = (script, cwdHost, label = script) => ({kind:'python', label, script, cwdHost});
function suites(p) {
  if (p === 'quick') return [node('test/generate_fixtures.js'),
    ...listDir('test', /^test_.*\.js$/).map(s => node(s))];
  if (p === 'browser') return [...listDir('test', /_browser\.cjs$/).filter(s => !/test_cad_/.test(s)), 'test/test_tiny_model_handles.cjs'].map(s => node(s));
  if (p === 'physics') {
    const studio = hostPath(REPO), exp = env.OPENMC_MCNP_PROJECT;  // the exporter path is as the Python host sees it
    return [...listDir('test', /^test_.*\.py$/).filter(s => !/test_cad_/.test(s)).map(s => py(s, studio)),
      {kind:'python-glob', label:'exporter tests/test_*.py + tests/check_export_mcnp.py', cwdHost:exp}];
  }
  if (p === 'full') return [node('setup/cad/run_integration.cjs')];
  return [];
}

// A skip anywhere fails the suite: unittest's "skipped=N", "[SKIP]", or a line starting SKIP.
const SKIP = /\bskipped=\d+|\[SKIP\]|^\s*SKIP\b/im;
const pyEnv = () => `export PATH="$(dirname ${q(env.OPENMC_PYTHON)}):$PATH" OPENMC_CROSS_SECTIONS=${q(env.OPENMC_CROSS_SECTIONS)} ` +
  `OPENMC_MCNP_PROJECT=${q(env.OPENMC_MCNP_PROJECT)}${env.OPENMC_CAD_PYTHON ? ` OPENMC_CAD_PYTHON=${q(env.OPENMC_CAD_PYTHON)}` : ''}`;
function run(s) {
  const opts = {encoding:'utf8', maxBuffer:1 << 28, timeout:45 * 60 * 1000, killSignal:'SIGKILL'};
  const shell = cmd => spawnSync(WIN ? 'wsl.exe' : 'bash', [...(WIN ? ['-e', 'bash'] : []), '-lc', cmd], opts);
  if (s.kind === 'node') return spawnSync(process.execPath, [path.join(REPO, s.script)], {...opts, cwd:REPO, env:{...env, ...s.extra}});
  if (s.kind === 'python') return shell(`${pyEnv()}; cd ${q(s.cwdHost)} && python ${q(s.script)}`);
  // the exporter's suites, one after another; any failure fails the entry and names the file
  return shell(`${pyEnv()}; cd ${q(s.cwdHost)} && rc=0; for t in tests/test_*.py tests/check_export_mcnp.py; do ` +
    `out=$(python "$t" 2>&1); c=$?; echo "== $t exit $c"; if [ $c -ne 0 ]; then rc=1; echo "$out" | tail -25; fi; ` +
    `echo "$out" | grep -E 'skipped=[0-9]+|\\[SKIP\\]' ; done; exit $rc`);
}

const t0 = Date.now(), results = [], notRun = [];
for (const p of want) {
  const miss = missingFor(p);
  if (miss.length) { notRun.push({profile:p, missing:miss}); console.log(`NOT RUN  ${p}: missing ${miss.join(', ')}`); continue; }
  for (const s of suites(p)) {
    if (only && !s.label.includes(only)) continue;
    const start = Date.now(), r = run(s);
    const timedOut = r.error && r.error.code === 'ETIMEDOUT';
    const out = `${r.stdout || ''}${r.stderr || ''}${timedOut ? '\n(timed out after 45 min)' : ''}`;
    const skipped = SKIP.test(out), ok = r.status === 0 && !skipped;
    const secs = (Date.now() - start) / 1000;
    results.push({profile:p, suite:s.label, ok, skipped, secs:+secs.toFixed(1), tail:ok ? undefined : out.split('\n').slice(-30).join('\n')});
    console.log(`${ok ? 'PASS' : 'FAIL'}  ${s.label}  (${secs.toFixed(0)} s)${skipped ? '  <- something was SKIPPED' : ''}`);
    if (!ok) console.log(out.split('\n').slice(-25).join('\n'));
  }
}

const git = (cwd, a) => { try { return execFileSync('git', ['-C', cwd, ...a]).toString().trim(); } catch (e) { return null; } };
const failed = results.filter(r => !r.ok);
const summary = {
  profile, only, when:new Date().toISOString(), minutes:+((Date.now() - t0) / 60000).toFixed(1),
  studio:{commit:git(REPO, ['rev-parse', '--short', 'HEAD']), dirty:!!git(REPO, ['status', '--porcelain'])},
  exporter:env.OPENMC_MCNP_PROJECT || null, node:process.version, platform:`${process.platform} ${process.arch}`,
  passed:results.length - failed.length, failed:failed.length, notRun, results,
};
const verdict = failed.length ? `FAILED (${failed.length} of ${results.length})` : notRun.length
  ? `INCOMPLETE: ${results.length} passed, NOT RUN: ${notRun.map(n => n.profile).join(', ')}` : `PASSED, all ${results.length} suites`;
const outDir = path.join(REPO, 'test', 'results');
fs.mkdirSync(outDir, {recursive:true});
fs.writeFileSync(path.join(outDir, 'last-run.json'), JSON.stringify(summary, null, 1) + '\n');
fs.writeFileSync(path.join(outDir, 'last-run.md'), [`# Test run: ${verdict}`, '',
  `Profile \`${profile}\`${only ? ` (only "${only}")` : ''}, ${summary.when}, ${summary.minutes} min. Studio ${summary.studio.commit}${summary.studio.dirty ? ' (uncommitted changes)' : ''}` +
  `${summary.exporter ? `, exporter ${summary.exporter}` : ''}, Node ${process.version}.`, '',
  ...notRun.map(n => `- NOT RUN **${n.profile}**: missing ${n.missing.join(', ')}`), '',
  '| Result | Suite | Profile | Seconds |', '|---|---|---|---:|',
  ...results.map(r => `| ${r.ok ? 'pass' : r.skipped ? '**FAIL (skipped)**' : '**FAIL**'} | ${r.suite} | ${r.profile} | ${r.secs} |`), ''].join('\n'));
console.log(`\nStudio tests (${profile}): ${verdict} in ${summary.minutes} min. Summary: test/results/last-run.md`);
process.exit(failed.length ? 1 : notRun.length ? 3 : 0);
