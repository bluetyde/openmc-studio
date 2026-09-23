// CAD stage 5 gate, restart: the real Studio server and engine across a restart.
//
// Session 1: probe the engine, convert test/fixtures/cad/triso_layers.step (csg), shut down
// through the normal path. Session 2, same runs folder: the old session's jobs are gone
// (jobs are session-scoped), the engine is NOT trusted until it is probed again, and the
// same file converts to the same components.
//
//   OPENMC_CAD_PYTHON  the CAD interpreter to test (e.g. a freshly installed lock env; required)
//   STUDIO_PYTHON      Python 3.11+ for the server (default python3)
//   E2E_PORT           default 8766
// On Windows the server runs in WSL. Fails, never skips, without the engine.
// Run: node test/test_cad_restart_e2e.cjs   (from PowerShell/cmd on Windows)
const {spawn, execFileSync} = require('child_process');
const fs = require('fs'), path = require('path'), assert = require('assert'), crypto = require('crypto');

const CAD = process.env.OPENMC_CAD_PYTHON, PY = process.env.STUDIO_PYTHON || 'python3';
const PORT = Number(process.env.E2E_PORT || 8766), WIN = process.platform === 'win32';
const REPO = path.resolve(__dirname, '..');
const q = s => `'${String(s).replace(/'/g, `'\\''`)}'`;
const shellSync = s => (WIN ? execFileSync('wsl.exe', ['-e', 'bash', '-lc', s]) : execFileSync('bash', ['-lc', s])).toString();
const STEP = fs.readFileSync(path.join(__dirname, 'fixtures', 'cad', 'triso_layers.step'));

async function session(repo, runs, token, fn) {
  const srv = WIN ? spawn('wsl.exe', ['-e', 'bash', '-lc', cmd()]) : spawn('bash', ['-lc', cmd()]);
  function cmd() {
    return `export OPENMC_CAD_PYTHON=${q(CAD)} OPENMC_STUDIO_TOKEN=${q(token)}; mkdir -p ${q(runs)}; ` +
      `cd ${q(repo + '/studio')} && echo $$ > ${q(runs + '/server.pid')} && exec ${q(PY)} -m openmc_studio --port ${PORT} --runs ${q(runs)} --no-browser`;
  }
  let out = '';
  srv.stdout.on('data', d => { out += d; }); srv.stderr.on('data', d => { out += d; });
  const exited = new Promise(r => srv.on('exit', r));
  const api = async (p, opts = {}) => {
    const r = await fetch(`http://127.0.0.1:${PORT}${p}`, {...opts, headers:{'Content-Type':'application/json', 'X-Studio-Token':token}});
    return {status:r.status, body:await r.json()};
  };
  const ping = async () => { try { return (await fetch(`http://127.0.0.1:${PORT}/api/ping`)).ok; } catch (e) { return false; } };
  try {
    for (let i = 0; i < 120 && !(await ping()); i++) await new Promise(r => setTimeout(r, 500));
    if (!(await ping())) throw new Error('Studio did not start:\n' + out);
    return await fn(api);
  } finally {
    try { shellSync(`kill -INT $(cat ${q(runs + '/server.pid')}) 2>/dev/null || true`); } catch (e) { /* gone */ }
    await Promise.race([exited, new Promise(r => setTimeout(r, 20000))]);
    assert.match(out, /OpenMC Studio stopped\./, 'the server must shut down through its normal path:\n' + out.slice(-800));
  }
}

async function run(api, body) {
  const {status, body:job} = await api('/api/cad/jobs', {method:'POST', body:JSON.stringify(body)});
  assert.equal(status, 202, JSON.stringify(job));
  for (let i = 0; i < 1200; i++) {
    const {body:st} = await api(`/api/cad/jobs/${job.id}`);
    if (['succeeded', 'failed', 'cancelled', 'timed_out'].includes(st.state)) {
      assert.equal(st.state, 'succeeded', JSON.stringify(st));
      return {id:job.id, result:(await api(`/api/cad/jobs/${job.id}/result`)).body};
    }
    await new Promise(r => setTimeout(r, 250));
  }
  throw new Error('job did not finish');
}

(async () => {
  if (!CAD) throw new Error('OPENMC_CAD_PYTHON must name the CAD interpreter; this gate never skips');
  const repo = WIN ? execFileSync('wsl.exe', ['wslpath', '-a', REPO.split(path.sep).join('/')]).toString().trim() : REPO;
  const runs = `/tmp/openmc-studio-cad-restart-${PORT}`, token = crypto.randomBytes(16).toString('hex');
  shellSync(`rm -rf ${q(runs)}`);
  const upload = {mode:'csg', filename:'triso_layers.step', data:STEP.toString('base64')};
  const shape = r => r.solids.map(s => ({key:s.key, status:s.status, cells:s.component.cells.map(c => c.region),
    surfaces:s.component.surfaces}));

  const first = await session(repo, runs, token, async api => {
    assert.equal((await api('/api/cad/capabilities')).body.engine_verified, false);
    await run(api, {mode:'probe'});
    const caps = (await api('/api/cad/capabilities')).body;
    assert.equal(caps.engine_verified, true);
    const conv = await run(api, upload);
    return {jobs:(await api('/api/cad/jobs')).body.jobs.map(j => j.id), versions:caps.probe.versions, conv};
  });
  console.log(`  [PASS] session 1: probe verified the engine (${JSON.stringify(first.versions)}) and converted the TRISO particle`);

  const second = await session(repo, runs, token, async api => {
    const jobs = (await api('/api/cad/jobs')).body.jobs;
    assert.deepEqual(jobs, [], 'jobs belong to their session');
    assert.equal((await api(`/api/cad/jobs/${first.conv.id}`)).status, 404, 'an old job id is unknown now');
    assert.equal((await api('/api/cad/capabilities')).body.engine_verified, false, 'trust is not carried across a restart');
    await run(api, {mode:'probe'});
    assert.equal((await api('/api/cad/capabilities')).body.engine_verified, true);
    return {conv:await run(api, upload)};
  });
  assert.deepEqual(shape(second.conv.result), shape(first.conv.result), 'the same file converts the same way after a restart');
  assert.equal(second.conv.result.counts.accepted, 5);
  console.log('  [PASS] session 2: old jobs gone, engine re-probed before use, identical conversion');
  shellSync(`rm -rf ${q(runs)}`);
  console.log('test_cad_restart_e2e: PASS');
})().catch(e => { console.log(e.stack); console.log('test_cad_restart_e2e: FAILED'); process.exit(1); });
