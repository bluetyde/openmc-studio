// CAD stage 2 gate, end to end: a real browser, the real Studio server and the real
// FreeCAD engine. Imports test/fixtures/cad/mixed.step through Studio's own page,
// saves the project, reopens it, and checks nothing was lost.
//
// It starts its own Studio server (and stops only that one) on E2E_PORT, with CAD
// jobs pointed at OPENMC_CAD_PYTHON. On Windows the server runs inside WSL, where
// the CAD engine lives; elsewhere it runs directly. It FAILS, never skips, without
// the engine.
//
//   OPENMC_CAD_PYTHON=/path/to/openmc-cad/bin/python   (as the server's OS sees it; required)
//   STUDIO_PYTHON=python3                                (any Python 3.11+ for the server)
//   E2E_PORT=8766
// Requires playwright. Run: node test/test_cad_import_e2e.cjs
// On Windows, set the variables in PowerShell or cmd: Git Bash rewrites /root/... values
// into Windows paths when it starts node (or export MSYS2_ENV_CONV_EXCL='*' first).
const {chromium} = require('playwright');
const {spawn, execFileSync} = require('child_process');
const fs = require('fs'), path = require('path'), assert = require('assert'), crypto = require('crypto');

const CAD = process.env.OPENMC_CAD_PYTHON;
const PY = process.env.STUDIO_PYTHON || 'python3';
const PORT = Number(process.env.E2E_PORT || 8766);
const TOKEN = crypto.randomBytes(16).toString('hex');
const WIN = process.platform === 'win32';
const REPO = path.resolve(__dirname, '..');
const FIXTURE = path.join(__dirname, 'fixtures', 'cad', 'mixed.step');
const EXPECTED = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures', 'cad', 'expected', 'native_report_mixed.json'), 'utf8'));

const shell = script => WIN ? spawn('wsl.exe', ['-e', 'bash', '-lc', script]) : spawn('bash', ['-lc', script]);
const shellSync = script => (WIN ? execFileSync('wsl.exe', ['-e', 'bash', '-lc', script]) : execFileSync('bash', ['-lc', script])).toString();
const q = s => `'${String(s).replace(/'/g, `'\\''`)}'`;

async function ping() {
  try { const r = await fetch(`http://127.0.0.1:${PORT}/api/ping`); return r.ok; } catch (e) { return false; }
}

(async () => {
  if (!CAD) throw new Error('OPENMC_CAD_PYTHON must name the pinned CAD interpreter; this gate never skips');
  if (await ping()) throw new Error(`Port ${PORT} is already serving something; set E2E_PORT to a free port`);
  // Forward slashes: wsl.exe hands arguments to a shell that would eat backslashes.
  const repo = WIN ? execFileSync('wsl.exe', ['wslpath', '-a', REPO.split(path.sep).join('/')]).toString().trim() : REPO;
  const runs = `/tmp/openmc-studio-cad-e2e-${PORT}`;   // outside the checkout, as CAD jobs require
  // exec: the recorded PID is the server itself, so we stop exactly what we started.
  const server = shell(`export OPENMC_CAD_PYTHON=${q(CAD)} OPENMC_STUDIO_TOKEN=${q(TOKEN)}; rm -rf ${q(runs)}; mkdir -p ${q(runs)}; ` +
    `cd ${q(repo + '/studio')} && echo $$ > ${q(runs + '/server.pid')} && exec ${q(PY)} -m openmc_studio --port ${PORT} --runs ${q(runs)} --no-browser`);
  let out = '';
  server.stdout.on('data', d => { out += d; });
  server.stderr.on('data', d => { out += d; });
  const exited = new Promise(r => server.on('exit', r));
  let browser, failed = false;
  try {
    for (let i = 0; i < 120 && !(await ping()); i++) await new Promise(r => setTimeout(r, 500));
    if (!(await ping())) throw new Error('Studio did not start:\n' + out);
    browser = await chromium.launch({headless:true, channel:process.env.BROWSER_CHANNEL || 'msedge'});
    const context = await browser.newContext({acceptDownloads:true, viewport:{width:1440, height:1000}});
    const page = await context.newPage();
    const pageErrors = [];
    page.on('pageerror', e => pageErrors.push(e.message));
    await page.goto(`http://127.0.0.1:${PORT}/?token=${TOKEN}`);
    await page.waitForFunction(() => typeof LOCAL !== 'undefined' && LOCAL.on === true, null, {timeout:60000});

    // Import: the dialog probes the real engine first, then inspects and converts.
    await page.locator('#rtabs button[data-tab="Convert"]').click();
    await page.locator('#rbody button:has-text("Import CAD…")').click();
    await page.waitForSelector('#cad-select-file-btn', {timeout:120000});
    await page.locator('#cadFileInput').setInputFiles(FIXTURE);
    await page.locator('#cad-import-run').click();
    await page.waitForSelector('#cad-inventory-rows', {timeout:120000});
    assert.equal(await page.locator('#cad-inventory-rows .invrow').count(), 5);
    await page.locator('#cad-import-run').click();
    await page.waitForSelector('#cad-preview-rows', {timeout:300000});
    assert.equal(await page.locator('.cadrow[data-status="accepted"]').count(), 3);
    assert.equal(await page.locator('.cadrow[data-status="rejected"]').count(), 2);
    await page.locator('#cad-allow-partial').check();
    await page.locator('#cad-import-run').click();
    await page.waitForFunction(() => S.parts.some(p => p.cadSource));

    // The live engine produced exactly the committed report's parts.
    const imported = await page.evaluate(() => S.parts.filter(p => p.cadSource).map(p => ({key:p.cadSource.key, p})));
    const want = Object.fromEntries(EXPECTED.solids.filter(r => r.status === 'accepted').map(r => [r.key, r.part]));
    assert.deepEqual(imported.map(x => x.key).sort(), Object.keys(want).sort());
    for (const {key, p} of imported) {
      for (const [k, v] of Object.entries(want[key])) {
        if (k === 'name') continue;
        if (typeof v === 'number') assert.ok(Math.abs(p[k] - v) <= 1e-12 * Math.max(1, Math.abs(v)), `${key}.${k}: ${p[k]} vs ${v}`);
        else assert.equal(p[k], v, `${key}.${k}`);
      }
      assert.equal(p.materialPending, true);
    }
    // Runs are blocked until materials are decided; the generated model.py already has the parts.
    const st = await page.evaluate(() => ({errors:problems().filter(p => p.sev === 'error').map(p => p.text),
      script:(x => typeof x === 'string' ? x : x.text)(buildScript(problems()))}));
    assert.equal(st.errors.filter(t => /needs a material/.test(t)).length, 3, st.errors.join('\n'));
    assert.ok(/Shield block/.test(st.script) && /Fuel rod/.test(st.script), 'model.py includes the imported parts');

    // Settle the materials through the UI, then save and reopen through the UI.
    const gid = await page.evaluate(() => S.imports[0].group);
    await page.evaluate(g => select('group', g), gid);
    await page.locator('#props .matpick').first().click();
    await page.locator('#matList [data-mat="void"]').click();
    assert.equal(await page.evaluate(() => S.parts.filter(p => p.materialPending).length), 0);
    const before = await page.evaluate(() => JSON.stringify({parts:S.parts, groups:S.groups, imports:S.imports}));
    const [download] = await Promise.all([page.waitForEvent('download'), page.evaluate(() => saveProject())]);
    const saved = await download.path();
    await page.evaluate(() => { S.parts = []; S.groups = []; S.imports = []; renderAll(); });
    await page.locator('#openFile').setInputFiles(saved);
    await page.waitForFunction(() => S.parts.length > 0);
    const after = await page.evaluate(() => JSON.stringify({parts:S.parts, groups:S.groups, imports:S.imports}));
    assert.deepEqual(JSON.parse(after), JSON.parse(before), 'save and reopen round-trip the import exactly');
    assert.deepEqual(pageErrors, []);
    console.log('test_cad_import_e2e: PASS (real browser, server and FreeCAD engine)');
  } catch (e) {
    failed = true;
    console.log(e.stack);
    console.log('--- server output ---\n' + out.slice(-3000));
  } finally {
    if (browser) await browser.close();
    // Stop only the server this test started, through its normal shutdown path.
    try { shellSync(`kill -INT $(cat ${q(runs + '/server.pid')}) 2>/dev/null || true`); } catch (e) { /* already gone */ }
    await Promise.race([exited, new Promise(r => setTimeout(r, 15000))]);
    if (!/OpenMC Studio stopped\./.test(out)) { failed = true; console.log('server did not shut down cleanly:\n' + out.slice(-1500)); }
  }
  process.exit(failed ? 1 : 0);
})();
