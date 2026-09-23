// CAD stage 3 gate: imported analytical CSG matches the CAD solids, voids included,
// through Studio's OWN representation and model.py generation.
//
// 1. CAD Python: real 'csg' conversions of the fixtures (test/fixtures/cad/csg_fixtures.py)
//    plus FreeCAD ground truth - which source solid contains each of ~3000 points per
//    case, and the stage-0 hole probes.
// 2. Headless Edge: each report goes through commitCsgImport and buildScript, exactly
//    as in the app, giving a model.py and the owner of every OpenMC cell.
// 3. OpenMC Python: test/cad_csg_check.py builds each geometry from that model.py and
//    requires every point to be in exactly one cell - the right component's cell, or
//    the World cell in holes and outside.
// It also checks that no Python was generated during conversion, overlapping solids
// and unconvertible files are refused at commit, schema 2 round-trips and a newer
// schema is refused, and MCNP export stays off for these projects.
//
//   OPENMC_CAD_PYTHON=...  the pinned CAD interpreter (as the CAD host sees it; required)
//   OPENMC_PYTHON=...      a Python with openmc (default: python3)
// On Windows both run inside WSL. Fails, never skips, without the engine.
// Run: node test/test_cad_csg_gate.cjs   (from PowerShell/cmd on Windows; see test_cad_import_e2e.cjs)
const {chromium} = require('playwright');
const {execFileSync} = require('child_process');
const fs = require('fs'), os = require('os'), path = require('path'), assert = require('assert');

const CAD = process.env.OPENMC_CAD_PYTHON;
const OPY = process.env.OPENMC_PYTHON || 'python3';
const WIN = process.platform === 'win32';
const REPO = path.resolve(__dirname, '..');
const q = s => `'${String(s).replace(/'/g, `'\\''`)}'`;
const sh = script => (WIN ? execFileSync('wsl.exe', ['-e', 'bash', '-lc', script], {maxBuffer:1 << 26})
                          : execFileSync('bash', ['-lc', script], {maxBuffer:1 << 26})).toString();
const hostPath = p => WIN ? execFileSync('wsl.exe', ['wslpath', '-a', p.split(path.sep).join('/')]).toString().trim() : p;

(async () => {
  if (!CAD) throw new Error('OPENMC_CAD_PYTHON must name the pinned CAD interpreter; this gate never skips');
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'studio-csg-gate-'));
  const tmpHost = hostPath(tmp), repoHost = hostPath(REPO);
  let failed = 0;
  const check = (name, fn) => { try { fn(); console.log(`  [PASS] ${name}`); } catch (e) { failed++; console.log(`  [FAIL] ${name}\n${e.stack}`); } };
  const browser = await chromium.launch({headless:true, channel:process.env.BROWSER_CHANNEL || 'msedge'});
  try {
    // 1. Real conversions and FreeCAD truth.
    sh(`cd ${q(repoHost)} && ${q(CAD)} -c ${q("import sys; sys.path[:0] = ['studio', 'test/fixtures/cad']; import csg_fixtures as c; c.main(sys.argv[1])")} ${q(tmpHost + '/cad')}`);
    const gate = JSON.parse(fs.readFileSync(path.join(tmp, 'cad', 'gate.json'), 'utf8'));
    check('conversion generated no Python at all', () => assert.deepEqual(gate.python_files, []));

    // 2. Studio's own import and model generation.
    const page = await browser.newPage();
    const pageErrors = [];
    page.on('pageerror', e => pageErrors.push(e.message));
    await page.route('**/*', r => r.fulfill({status:404, body:''}));
    await page.setContent(fs.readFileSync(path.join(REPO, 'studio', 'openmc_studio', 'static', 'index.html'), 'utf8'));
    await page.evaluate(() => { clearTimeout(LIVE.timer); stopMcnpProgress(); liveMcnpTick = () => {}; window.BLANK = JSON.stringify(S); });
    const built = {};
    for (const [name, c] of Object.entries(gate.cases)) {
      built[name] = await page.evaluate(([name, report]) => {
        S = normalizeProject(JSON.parse(BLANK));
        try {
          commitCsgImport(report, name + '.step', {allowPartial:true});
        } catch (e) { return {refused:e.message}; }
        const r = buildScript(problems(), false);
        const owners = {};
        r.cells.forEach((o, i) => {
          owners[i + 1] = o.kind === 'component' ? csgComponents().find(k => k.id === o.id).source.key : o.kind;
        });
        const roundTrip = normalizeProject(JSON.parse(JSON.stringify(S)));
        return {model:r.text, owners, schema:S.schema, components:csgComponents().length,
          cells:csgComponents().reduce((n, k) => n + k.cells.length, 0), sameAfterSave:JSON.stringify(roundTrip.csg) === JSON.stringify(S.csg),
          pending:problems().filter(p => /needs a material/.test(p.text)).length};
      }, [name, c.report]);
    }
    const toCheck = {};
    for (const [name, b] of Object.entries(built)) {
      if (b.refused) continue;
      fs.writeFileSync(path.join(tmp, `${name}.py`), b.model);
      toCheck[name] = {model:`${tmpHost}/${name}.py`, owners:b.owners, truth:gate.cases[name].truth};
    }
    fs.writeFileSync(path.join(tmp, 'cases.json'), JSON.stringify(toCheck));

    // 3. OpenMC builds each geometry from Studio's model.py and answers for every point.
    const verdict = JSON.parse(sh(`${q(OPY)} ${q(repoHost + '/test/cad_csg_check.py')} ${q(tmpHost + '/cases.json')}`).trim().split('\n').pop());

    for (const name of ['drilled_block', 'annular_cylinder', 'drilled_block_rotated', 'annular_cylinder_rotated',
                        'hollow_sphere', 'triso_coating', 'clean_assembly']) {
      check(`${name}: every point in exactly the right cell, holes in the World`, () => {
        const v = verdict[name], b = built[name];
        assert.ok(!b.refused, `commit refused: ${b.refused}`);
        assert.ok(!v.error, v.error);
        assert.equal(v.overlaps, 0, `overlapping cells: ${JSON.stringify(v.examples)}`);
        assert.equal(v.gaps, 0, `points in no cell: ${JSON.stringify(v.examples)}`);
        assert.equal(v.mismatch, 0, `wrong cell: ${JSON.stringify(v.examples)}`);
        assert.ok(v.solid_points > 50 && v.points - v.solid_points > 50, 'both solid and empty space were sampled');
        assert.equal(b.schema, 2);
        assert.ok(b.sameAfterSave, 'saving and reopening keeps the components exactly');
        assert.equal(b.pending, b.cells, 'every imported cell needs a material decision');
      });
    }
    check('hole probes landed in the World cell', () => {
      for (const name of ['drilled_block', 'annular_cylinder', 'drilled_block_rotated', 'annular_cylinder_rotated']) {
        const holes = gate.cases[name].truth.filter(t => t.probe === 'hole');
        assert.ok(holes.length > 0, `${name} has hole probes`);
      }
      // (their correctness is part of each case's zero-mismatch check above)
    });
    check('the multi-solid assembly keeps one component per source solid', () => {
      assert.equal(built.clean_assembly.components, 4);
      const keys = Object.values(built.clean_assembly.owners).filter(k => k !== 'world');
      assert.equal(new Set(keys).size, 4);
    });
    check('overlapping solids are refused at commit, naming them', () => {
      assert.match(built.mixed.refused || '', /overlap/);
      assert.match(built.mixed.refused, /Shield block/);
      assert.match(built.mixed.refused, /Liner/);
    });
    check('an unconvertible file is refused, with GEOUNED\'s reason kept', () => {
      assert.match(built.torus.refused || '', /No solid/);
      assert.match(gate.cases.torus.report.solids[0].reasons.join(' '), /Toroid|torus|surface/i);
    });

    // Schema and MCNP guards, in the same page.
    const guards = await page.evaluate(([report]) => {
      S = normalizeProject(JSON.parse(BLANK));
      commitCsgImport(report, 'drilled_block.step', {});
      const saved = JSON.parse(JSON.stringify(S));
      const newer = {...saved, schema:3};
      let apiCalled = false;
      const realApi = api;
      api = async () => { apiCalled = true; return {}; };
      LOCAL.on = true;
      return exportMcnp().then(() => {
        api = realApi; LOCAL.on = false;
        return {v2ok:validProject(saved), v3ok:validProject(newer), v3why:projectProblem(newer),
          v1ok:validProject({...saved, schema:undefined, csg:undefined}),
          logText:document.querySelector('#log').innerText, apiCalled};
      });
    }, [gate.cases.drilled_block.report]);
    check('schema 2 loads, schema 1 still loads, a newer schema is refused with a reason', () => {
      assert.ok(guards.v2ok && guards.v1ok);
      assert.equal(guards.v3ok, false);
      assert.match(guards.v3why, /newer OpenMC Studio/);
    });
    check('MCNP export stays off for imported CSG, with the reason, and sends nothing', () => {
      assert.equal(guards.apiCalled, false);
      assert.match(guards.logText, /MCNP export is off for projects with imported CAD geometry/);
    });
    check('no page errors', () => assert.deepEqual(pageErrors, []));
  } finally {
    await browser.close();
    fs.rmSync(tmp, {recursive:true, force:true});
  }
  if (failed) { console.log(`test_cad_csg_gate: ${failed} FAILED`); process.exit(1); }
  console.log('test_cad_csg_gate: PASS');
})();
