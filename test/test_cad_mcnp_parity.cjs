// CAD stage 5 gate: MCNP parity for imported analytical CSG.
//
// 1. CAD Python: real 'csg' conversions + FreeCAD truth (test/fixtures/cad/csg_fixtures.py).
// 2. Headless Edge: Studio's commitCsgImport + mcnpScript (the script the MCNP export uses),
//    with a material on every imported cell and a cell tally on one of them.
// 3. OpenMC Python: model.py --export-xml.
// 4. The companion exporter (export_mcnp.py): the deck must validate, its geometry must match
//    OpenMC with NO cell left unsampled, and it must carry Studio's materials, source and tally.
// 5. test/cad_mcnp_check.py: every FreeCAD truth point (dense in each solid, hole probes
//    included) is located in the MCNP deck, in exactly the right cell - deck against CAD.
// 6. The app path: a real Studio server exports one project through /api/export-mcnp.
//
//   OPENMC_CAD_PYTHON    the pinned CAD interpreter (required)
//   OPENMC_MCNP_PYTHON   a Python with openmc, MontePy and MCNPy (required)
//   OPENMC_MCNP_PROJECT  the companion exporter checkout, as that Python sees it (required)
//   E2E_PORT             port for the Studio server of step 6 (default 8766)
// On Windows these run inside WSL. The MCNPy bridge (port 25333) is machine-wide: claim it
// first where agents share a machine. Fails, never skips, without the tools.
// Run: node test/test_cad_mcnp_parity.cjs   (from PowerShell/cmd on Windows)
const {chromium} = require('playwright');
const {spawn, execFileSync} = require('child_process');
const fs = require('fs'), os = require('os'), path = require('path'), assert = require('assert'), crypto = require('crypto');

const CAD = process.env.OPENMC_CAD_PYTHON, MPY = process.env.OPENMC_MCNP_PYTHON, EXP = process.env.OPENMC_MCNP_PROJECT;
const PORT = Number(process.env.E2E_PORT || 8766);
const WIN = process.platform === 'win32';
const REPO = path.resolve(__dirname, '..');
const q = s => `'${String(s).replace(/'/g, `'\\''`)}'`;
const sh = (script, opts = {}) => (WIN ? execFileSync('wsl.exe', ['-e', 'bash', '-lc', script], {maxBuffer:1 << 27, ...opts})
                                       : execFileSync('bash', ['-lc', script], {maxBuffer:1 << 27, ...opts})).toString();
const hostPath = p => WIN ? execFileSync('wsl.exe', ['wslpath', '-a', p.split(path.sep).join('/')]).toString().trim() : p;
// The exporter's Python must find `openmc` and Java next to it; put its bin first on PATH.
const envPy = `export PATH="$(dirname ${q(MPY)}):$PATH";`;

(async () => {
  for (const [k, v] of Object.entries({OPENMC_CAD_PYTHON:CAD, OPENMC_MCNP_PYTHON:MPY, OPENMC_MCNP_PROJECT:EXP}))
    if (!v) throw new Error(`${k} must be set; this gate never skips`);
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'studio-mcnp-parity-'));
  const tmpHost = hostPath(tmp), repoHost = hostPath(REPO);
  let failed = 0;
  const check = (name, fn) => { try { fn(); console.log(`  [PASS] ${name}`); } catch (e) { failed++; console.log(`  [FAIL] ${name}\n${e.stack}`); } };
  const browser = await chromium.launch({headless:true, channel:process.env.BROWSER_CHANNEL || 'msedge'});
  try {
    sh(`cd ${q(repoHost)} && ${q(CAD)} -c ${q("import sys; sys.path[:0] = ['studio', 'test/fixtures/cad']; import csg_fixtures as c; c.main(sys.argv[1])")} ${q(tmpHost + '/cad')}`);
    const gate = JSON.parse(fs.readFileSync(path.join(tmp, 'cad', 'gate.json'), 'utf8'));

    const page = await browser.newPage();
    await page.route('**/*', r => r.fulfill({status:404, body:''}));
    await page.setContent(fs.readFileSync(path.join(REPO, 'studio', 'openmc_studio', 'static', 'index.html'), 'utf8'));
    await page.evaluate(() => { clearTimeout(LIVE.timer); stopMcnpProgress(); liveMcnpTick = () => {}; window.BLANK = JSON.stringify(S); });
    const build = ([name, report]) => {
      S = normalizeProject(JSON.parse(BLANK));
      try { commitCsgImport(report, name + '.step', {allowPartial:true}); } catch (e) { return {refused:e.message}; }
      const m = {...clone(CUSTOM_MAT), id:newId('m'), name:'Graphite', comps:'C:1', density:1.7};
      S.materials.push(m);
      csgComponents().forEach(k => k.cells.forEach(c => { c.material = m.id; delete c.materialPending; }));
      select('component', csgComponents()[0].id);
      addTally('cell');  // a cell tally on the first imported component
      const P = problems(), r = buildScript(P, false, MCNP_OPTS), owners = {};
      r.cells.forEach((o, i) => { owners[i + 1] = o.kind === 'component' ? csgComponents().find(k => k.id === o.id).source.key : o.kind; });
      return {script:mcnpScript(P), owners, errors:P.filter(p => p.sev === 'error').map(p => p.text), project:JSON.parse(JSON.stringify(S)),
        live:(liveMcnpTick !== undefined), cells:csgComponents().reduce((n, k) => n + k.cells.length, 0)};
    };
    const built = {};
    for (const [name, c] of Object.entries(gate.cases)) built[name] = await page.evaluate(build, [name, c.report]);
    const exported = Object.keys(built).filter(n => !built[n].refused);
    check('the convertible cases build without Problems errors', () => {
      assert.deepEqual(Object.keys(built).filter(n => built[n].refused).sort(), ['mixed', 'torus']);
      for (const n of exported) assert.deepEqual(built[n].errors, [], n);
    });

    // OpenMC XML, then the companion exporter on each case.
    const cases = {};
    for (const n of exported) {
      fs.mkdirSync(path.join(tmp, n));
      fs.writeFileSync(path.join(tmp, n, 'model.py'), built[n].script);
      cases[n] = {dir:`${tmpHost}/${n}`};
    }
    sh(`${envPy} for d in ${exported.map(n => q(`${tmpHost}/${n}`)).join(' ')}; do (cd "$d" && ${q(MPY)} model.py --export-xml >/dev/null); done`);
    const reports = {};
    for (const n of exported) {
      try {
        sh(`${envPy} cd ${q(`${tmpHost}/${n}`)} && ${q(MPY)} ${q(EXP + '/src/export_mcnp.py')} model.xml --out-dir deck --name ${q(n)} --report report.json > export.log 2>&1`, {timeout:900000});
      } catch (e) { /* a failed export is asserted below, with its report */ }
      reports[n] = fs.existsSync(path.join(tmp, n, 'report.json')) ? JSON.parse(fs.readFileSync(path.join(tmp, n, 'report.json'), 'utf8'))
        : {ok:false, validation:fs.readFileSync(path.join(tmp, n, 'export.log'), 'utf8')};
    }
    for (const n of exported) {
      check(`${n}: the deck validates, every cell sampled, full Studio deck`, () => {
        const r = reports[n], v = r.validation || '';
        assert.equal(r.ok, true, v.slice(-1500));
        assert.match(v, /geometry matches OpenMC at \d+ sampled points/);
        assert.doesNotMatch(v, /WARNING: cell \d+ .*no sampled point/, 'a cell escaped the geometry comparison');
        const deck = fs.readFileSync(path.join(tmp, n, 'deck', `${n}_runnable.mcnp`), 'utf8');
        assert.match(deck, /^M\d+\s/m, 'Studio materials in the deck');
        assert.match(deck, /^SDEF\b/m, 'Studio source in the deck');
        assert.match(deck, /^F\d*4:N\b/m, 'the cell tally on the imported component');
        if (/rotated/.test(n)) assert.match(deck, /\bGQ\b/, 'rotated curved surfaces become GQ cards');
      });
    }

    // Deck against CAD, directly.
    const toCheck = Object.fromEntries(exported.map(n => [n, {deck:`${tmpHost}/${n}/deck/${n}_runnable.mcnp`, owners:built[n].owners, truth:gate.cases[n].truth}]));
    fs.writeFileSync(path.join(tmp, 'mcnp_cases.json'), JSON.stringify(toCheck));
    const verdict = JSON.parse(sh(`${envPy} OPENMC_MCNP_PROJECT=${q(EXP)} ${q(MPY)} ${q(repoHost + '/test/cad_mcnp_check.py')} ${q(tmpHost + '/mcnp_cases.json')}`).trim().split('\n').pop());
    for (const n of exported) {
      check(`${n}: every CAD truth point is in the right MCNP cell`, () => {
        const v = verdict[n];
        assert.ok(!v.error, v.error);
        assert.equal(v.lost, 0, `points in no MCNP cell: ${JSON.stringify(v.examples)}`);
        assert.equal(v.overlap, 0, `points in two MCNP cells: ${JSON.stringify(v.examples)}`);
        assert.equal(v.mismatch, 0, `wrong MCNP cell: ${JSON.stringify(v.examples)}`);
        assert.ok(v.ok > 0.95 * v.points && v.solid_points > 50, JSON.stringify(v));
        if (/drilled|annular/.test(n)) assert.ok(v.hole_probes > 0, 'hole probes were included');
      });
    }

    // The app path: Studio's own export endpoint for one project.
    const token = crypto.randomBytes(16).toString('hex'), runs = `/tmp/openmc-studio-mcnp-parity-${PORT}`;
    const server = spawn(WIN ? 'wsl.exe' : 'bash', [...(WIN ? ['-e', 'bash'] : []), '-lc',
      `${envPy} export OPENMC_STUDIO_TOKEN=${q(token)} OPENMC_MCNP_PROJECT=${q(EXP)}; rm -rf ${q(runs)}; mkdir -p ${q(runs)}; ` +
      `cd ${q(repoHost + '/studio')} && echo $$ > ${q(runs + '/server.pid')} && exec ${q(MPY)} -m openmc_studio --port ${PORT} --runs ${q(runs)} --no-browser`]);
    let out = '';
    server.stdout.on('data', d => { out += d; }); server.stderr.on('data', d => { out += d; });
    const exited = new Promise(r => server.on('exit', r));
    const ping = async () => { try { return (await fetch(`http://127.0.0.1:${PORT}/api/ping`)).ok; } catch (e) { return false; } };
    try {
      for (let i = 0; i < 120 && !(await ping()); i++) await new Promise(r => setTimeout(r, 500));
      const n = 'drilled_block_rotated';
      const res = await fetch(`http://127.0.0.1:${PORT}/api/export-mcnp`, {method:'POST',
        headers:{'Content-Type':'application/json', 'X-Studio-Token':token},
        body:JSON.stringify({script:built[n].script, project:built[n].project, name:n})});
      const r = await res.json();
      check('Studio\'s /api/export-mcnp exports an imported-CSG project with every cell checked', () => {
        assert.equal(res.status, 200);
        assert.equal(r.ok, true, JSON.stringify(r).slice(0, 1500));
        assert.match(r.validation || '', /geometry matches OpenMC/);
        assert.doesNotMatch(r.validation || '', /WARNING: cell \d+ .*no sampled point/);
      });
    } finally {
      try { sh(`kill -INT $(cat ${q(runs + '/server.pid')}) 2>/dev/null || true`); } catch (e) { /* gone */ }
      await Promise.race([exited, new Promise(r => setTimeout(r, 20000))]);
      check('the Studio server shut down cleanly', () => assert.match(out, /OpenMC Studio stopped\./, out.slice(-800)));
    }
  } finally {
    await browser.close();
    fs.rmSync(tmp, {recursive:true, force:true});
  }
  if (failed) { console.log(`test_cad_mcnp_parity: ${failed} FAILED`); process.exit(1); }
  console.log('test_cad_mcnp_parity: PASS');
})();
