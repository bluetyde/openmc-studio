// CAD stage 2 gate, browser half: the native import workflow in real Chromium.
// The server is replaced by a stand-in that replays REAL engine reports
// (test/fixtures/cad/expected/native_report_*.json, made by the FreeCAD worker), so
// this checks the browser's handling exactly as the engine answers. The end-to-end
// run against the real server and engine is test/test_cad_import_e2e.cjs.
// Requires playwright. Run: node test/test_cad_import_browser.cjs
const {chromium} = require('playwright');
const fs = require('fs'), path = require('path'), assert = require('assert');

const FX = path.join(__dirname, 'fixtures', 'cad');
const MIXED = JSON.parse(fs.readFileSync(path.join(FX, 'expected', 'native_report_mixed.json'), 'utf8'));
const ASSEMBLY = JSON.parse(fs.readFileSync(path.join(FX, 'expected', 'native_report_assembly.json'), 'utf8'));
const MIXED_STEP = fs.readFileSync(path.join(FX, 'mixed.step'));
const inventoryOf = rep => ({...rep, solids:rep.solids.map(({part, evidence, kind, status, ...row}) => row)});

(async () => {
  const browser = await chromium.launch({headless:true, channel:process.env.BROWSER_CHANNEL || 'msedge'});
  let failures = 0;
  const check = async (name, fn) => {
    try { await fn(); console.log(`  [PASS] ${name}`); } catch (e) { failures++; console.log(`  [FAIL] ${name}\n${e.stack}`); }
  };
  try {
    const page = await browser.newPage({viewport:{width:1440, height:1000}});
    const pageErrors = [];
    page.on('pageerror', e => pageErrors.push(e.message));
    await page.route('**/*', route => route.fulfill({status:404, body:''}));
    await page.setContent(fs.readFileSync(path.join(__dirname, '../studio/openmc_studio/static/index.html'), 'utf8'));

    // A stand-in server. scenario() sets how jobs behave; calls are recorded.
    await page.evaluate(([mixed, assembly]) => {
      clearTimeout(LIVE.timer); stopMcnpProgress(); liveMcnpTick = () => {};
      LOCAL.on = true; LOCAL.token = 't';
      const inventoryOf = rep => ({...rep, solids:rep.solids.map(({part, evidence, kind, status, ...row}) => row)});
      window.FAKE = {calls:[], verified:false, available:true, native:mixed, inspect:inventoryOf(mixed),
        nativeState:'succeeded', jobs:{}, n:0, reports:{mixed, assembly}};
      api = async (p, opts = {}) => {
        const method = opts.method || 'GET', body = opts.body ? JSON.parse(opts.body) : null;
        FAKE.calls.push({method, path:p, body});
        if (p === '/api/cad/capabilities')
          return {available:FAKE.available, engine_verified:FAKE.verified, max_input_bytes:16777216,
                  reason:FAKE.available ? null : 'Set OPENMC_CAD_PYTHON to a tested Linux CAD interpreter'};
        if (p === '/api/cad/jobs' && method === 'POST') {
          const id = (++FAKE.n).toString(16).padStart(32, '0');
          FAKE.jobs[id] = {mode:body.mode, polls:0};
          return {id, state:'queued'};
        }
        const m = p.match(/^\/api\/cad\/jobs\/([0-9a-f]{32})(\/result)?$/);
        if (m) {
          const job = FAKE.jobs[m[1]];
          if (method === 'DELETE') { job.cancelled = true; return {id:m[1], state:'cancelling'}; }
          if (m[2]) return job.mode === 'probe' ? {ok:true, versions:{geouned:'1.6.2'}} : job.mode === 'inspect' ? FAKE.inspect : FAKE.native;
          job.polls++;
          const final = job.mode === 'native' ? FAKE.nativeState : 'succeeded';
          if (job.cancelled) return {id:m[1], state:'cancelled'};
          if (job.polls < 2 || final === 'running') return {id:m[1], state:'running', progress:'checking solid 1 of 5'};
          if (job.mode === 'probe' && final === 'succeeded') FAKE.verified = true;
          if (final === 'failed') return {id:m[1], state:'failed', error:'ValueError: FreeCAD could not read this STEP file', diagnostics:'Traceback: ... could not read'};
          return {id:m[1], state:'succeeded', progress:'converted'};
        }
        throw new Error('unexpected ' + method + ' ' + p);
      };
    }, [MIXED, ASSEMBLY]);

    const openImport = async () => {
      await page.locator('#rtabs button[data-tab="Convert"]').click();
      await page.locator('#rbody button:has-text("Import CAD…")').click();
    };
    // imports: a project from before CAD import has none; normalizeProject gives it [].
    const snapshot = () => page.evaluate(() => JSON.stringify({parts:S.parts, groups:S.groups, imports:S.imports || [], world:S.settings.worldR}));
    const choose = async buf => page.locator('#cadFileInput').setInputFiles({name:'mixed.step', mimeType:'application/step', buffer:buf});
    const status = () => page.locator('#cad-import-status').innerText();

    await check('an unverified engine is probed with a real conversion before import is offered', async () => {
      await openImport();
      await page.waitForSelector('#cad-select-file-btn');
      const calls = await page.evaluate(() => FAKE.calls.filter(c => c.method === 'POST').map(c => c.body.mode));
      assert.deepEqual(calls, ['probe'], 'the first thing the dialog does is a probe job');
      await page.locator('#cad-import-cancel').click();
    });

    await check('an unavailable engine says why and imports nothing', async () => {
      const before = await snapshot();
      await page.evaluate(() => { FAKE.available = false; FAKE.verified = false; });
      await openImport();
      await page.waitForSelector('#cad-unavailable');
      assert.match(await page.locator('#cad-unavailable').innerText(), /OPENMC_CAD_PYTHON/);
      await choose(MIXED_STEP);
      await page.locator('#cad-import-run').click();
      assert.match(await status(), /unavailable/);
      assert.equal(await snapshot(), before);
      await page.locator('#cad-import-cancel').click();
      await page.evaluate(() => { FAKE.available = true; FAKE.verified = true; });
    });

    let firstIds = [];
    await check('inspect -> choose native -> preview -> partial import is one undoable change', async () => {
      // A 1 cm world the import will reach past, set as a recorded edit so undo has it as the step before.
      await page.evaluate(() => { HISTORY.boundary = true; S.settings.worldR = 1; FAKE.calls = []; renderAll(); });
      await page.waitForFunction(() => JSON.parse(HISTORY.current).settings.worldR === 1);
      const before = await snapshot();
      await openImport();
      await page.waitForSelector('#cad-select-file-btn');
      await choose(MIXED_STEP);
      await page.locator('#cad-import-run').click();                 // Inspect
      await page.waitForSelector('#cad-inventory-rows');
      assert.equal(await page.locator('#cad-inventory-rows .invrow').count(), 5);
      const sent = await page.evaluate(() => FAKE.calls.find(c => c.method === 'POST' && c.body.mode === 'inspect').body);
      assert.equal(Buffer.from(sent.data, 'base64').toString('latin1'), MIXED_STEP.toString('latin1'), 'the uploaded bytes are the file');
      assert.equal(sent.filename, 'mixed.step');
      assert.equal(await page.locator('input[name="cad-mode"][value="csg"]').isDisabled(), true, 'CSG import is shown but not offered yet');
      await page.locator('#cad-import-run').click();                 // Convert
      await page.waitForSelector('#cad-preview-rows');
      assert.equal(await page.locator('#cad-preview-rows .cadrow[data-status="accepted"]').count(), 3);
      assert.equal(await page.locator('#cad-preview-rows .cadrow[data-status="rejected"]').count(), 2);
      assert.match(await page.locator('#cad-preview-rows').innerText(), /different cylinders|not a supported primitive/);
      assert.match(await page.locator('.cadwarn').innerText(), /Shield block.*Liner.*overlap/);
      assert.equal(await page.locator('#cad-import-run').isDisabled(), true, 'omissions must be accepted explicitly');
      assert.equal(await page.locator('#cad-grow-world').isChecked(), true, 'growing the world is offered when parts reach past it');
      await page.locator('#cad-allow-partial').check();
      await page.locator('#cad-import-run').click();                 // Import 3 parts
      assert.equal(await page.evaluate(() => document.querySelector('#cadImportMenu').hidden), true);
      const after = await page.evaluate(() => ({
        parts:S.parts.filter(p => p.cadSource).map(p => ({id:p.id, name:p.name, pending:p.materialPending, material:p.material, group:p.group, key:p.cadSource.key})),
        imports:S.imports, world:S.settings.worldR, errors:problems().filter(p => p.sev === 'error').map(p => p.text),
        infos:problems().filter(p => p.sev === 'info').map(p => p.text), sel}));
      assert.equal(after.parts.length, 3);
      assert.ok(after.parts.every(p => p.pending === true && p.material === 'void'), 'imported parts are pending, stored as Void');
      assert.equal(new Set(after.parts.map(p => p.group)).size, 1, 'one group for the import');
      assert.deepEqual(after.sel, {kind:'group', id:after.parts[0].group});
      assert.equal(after.imports.length, 1);
      assert.deepEqual(after.imports[0].omitted.map(o => o.key), ['mixed / Drilled plate', 'mixed / Collar']);
      assert.ok(after.imports[0].omitted.every(o => o.reasons.length), 'omitted solids keep their reasons');
      assert.equal(after.imports[0].sha256, MIXED.source_sha256);
      assert.ok(after.world > 1, 'the world grew to fit');
      assert.equal(after.errors.filter(t => /needs a material/.test(t)).length, 3, 'each pending part blocks a run');
      assert.ok(after.infos.some(t => /2 solids were left out/.test(t)), 'the omission is reported');
      firstIds = after.parts.map(p => p.id);
      // One undo removes the whole import, world change included; redo restores it.
      await page.evaluate(() => new Promise(r => setTimeout(r, 50)));
      await page.evaluate(() => { undo(); });
      assert.deepEqual(JSON.parse(await snapshot()), JSON.parse(before), 'one undo returns to exactly the pre-import project');
      await page.evaluate(() => { redo(); });
      assert.equal(await page.evaluate(() => S.parts.filter(p => p.cadSource).length), 3);
    });

    await check('a repeated import gets fresh, unique identities', async () => {
      await page.evaluate(() => { FAKE.native = FAKE.reports.assembly; FAKE.inspect = (r => ({...r, solids:r.solids.map(({part, evidence, kind, status, ...row}) => row)}))(FAKE.reports.assembly); });
      for (let round = 0; round < 2; round++) {
        await openImport();
        await page.waitForSelector('#cad-select-file-btn');
        await choose(MIXED_STEP);
        await page.locator('#cad-import-run').click();
        await page.waitForSelector('#cad-inventory-rows');
        await page.locator('#cad-import-run').click();
        await page.waitForSelector('#cad-preview-rows');
        await page.locator('#cad-import-run').click();
      }
      const st = await page.evaluate(() => ({
        ids:[...S.parts, ...S.groups, ...S.materials, ...S.sources, ...S.tallies].map(o => o.id),
        imports:S.imports.map(i => i.id), fromCad:S.parts.filter(p => p.cadSource).map(p => ({id:p.id, name:p.name, imp:p.cadSource.import}))}));
      assert.equal(new Set(st.ids).size, st.ids.length, 'no two objects share an ID');
      assert.equal(new Set(st.imports).size, 3);
      assert.equal(st.fromCad.length, 3 + 5 + 5);
      assert.ok(firstIds.every(id => st.fromCad.some(p => p.id === id)), 'earlier parts keep their IDs');
      const rods = st.fromCad.filter(p => /^Fuel rod/.test(p.name)).map(p => p.name);
      assert.equal(new Set(rods).size, rods.length, 'duplicate CAD labels get distinct Studio names');
    });

    await check('picking a material, or Void on purpose, clears the block', async () => {
      const gid = await page.evaluate(() => S.imports[1].group);
      await page.evaluate(g => select('group', g), gid);
      const mat = await page.evaluate(() => S.materials[0].id);
      await page.locator('#props .matpick').first().click();
      await page.locator(`#matList [data-mat="${mat}"]`).click();
      const st = await page.evaluate(g => S.parts.filter(p => p.group === g).map(p => [p.material, !!p.materialPending]), gid);
      assert.ok(st.length === 5 && st.every(([m, pend]) => m === mat && !pend), JSON.stringify(st));
      // A single part: keep it as empty space deliberately.
      const pid = await page.evaluate(() => S.parts.find(p => p.materialPending).id);
      await page.evaluate(id => select('part', id), pid);
      await page.locator('#props button:has-text("Keep as Void (empty space)")').click();
      const p = await page.evaluate(id => { const q = S.parts.find(x => x.id === id); return [q.material, !!q.materialPending]; }, pid);
      assert.deepEqual(p, ['void', false]);
      const stillPending = await page.evaluate(() => S.parts.filter(p => p.materialPending).length);
      const errs = await page.evaluate(() => problems().filter(p => p.sev === 'error' && /needs a material/.test(p.text)).length);
      assert.equal(errs, stillPending, 'exactly the undecided parts still block a run');
    });

    await check('save and reopen keep every imported part, its source and the import record', async () => {
      const saved = await page.evaluate(async () => {
        let out = null;
        window.saveFile = async (filename, data) => { out = {filename, data}; };
        saveProject();
        return out;
      });
      assert.ok(saved && saved.data, 'Save project produced a file');
      const before = await page.evaluate(() => JSON.stringify({parts:S.parts, groups:S.groups, imports:S.imports}));
      await page.evaluate(() => { S.parts = []; S.groups = []; S.imports = []; renderAll(); });
      await page.locator('#openFile').setInputFiles({name:saved.filename, mimeType:'application/json', buffer:Buffer.from(saved.data)});
      await page.waitForFunction(() => S.parts.length > 0);
      const after = await page.evaluate(() => JSON.stringify({parts:S.parts, groups:S.groups, imports:S.imports}));
      assert.deepEqual(JSON.parse(after), JSON.parse(before));
      const pending = await page.evaluate(() => problems().filter(p => /needs a material/.test(p.text)).length);
      assert.ok(pending > 0, 'a reopened project still blocks runs for undecided parts');
    });

    await check('cancelling during conversion stops the job and changes nothing', async () => {
      const before = await snapshot();
      await page.evaluate(() => { FAKE.nativeState = 'running'; FAKE.calls = []; });
      await openImport();
      await page.waitForSelector('#cad-select-file-btn');
      await choose(MIXED_STEP);
      await page.locator('#cad-import-run').click();
      await page.waitForSelector('#cad-inventory-rows');
      await page.locator('#cad-import-run').click();
      await page.waitForFunction(() => /checking solid/.test(document.querySelector('#cad-import-status').textContent));
      await page.locator('#cad-import-cancel').click();
      await page.waitForFunction(() => FAKE.calls.some(c => c.method === 'DELETE'));
      assert.equal(await snapshot(), before);
      await page.evaluate(() => { FAKE.nativeState = 'succeeded'; });
    });

    await check('a failed conversion shows the engine\'s reason and changes nothing', async () => {
      const before = await snapshot();
      await page.evaluate(() => { FAKE.nativeState = 'failed'; });
      await openImport();
      await page.waitForSelector('#cad-select-file-btn');
      await choose(MIXED_STEP);
      await page.locator('#cad-import-run').click();
      await page.waitForSelector('#cad-inventory-rows');
      await page.locator('#cad-import-run').click();
      await page.waitForFunction(() => /could not read/.test(document.querySelector('#cad-import-status').textContent));
      assert.equal(await page.locator('#cad-import-run').innerText(), 'Convert', 'the user can try again from the same step');
      assert.equal(await snapshot(), before);
      await page.locator('#cad-import-cancel').click();
      await page.evaluate(() => { FAKE.nativeState = 'succeeded'; });
    });

    await check('only STEP files are accepted', async () => {
      await openImport();
      await page.waitForSelector('#cad-select-file-btn');
      await page.locator('#cadFileInput').setInputFiles({name:'part.iges', mimeType:'text/plain', buffer:Buffer.from('IGES')});
      assert.match(await status(), /Only STEP/);
      assert.equal(await page.locator('#cad-import-run').isDisabled(), true);
      await page.locator('#cad-import-cancel').click();
    });

    assert.deepEqual(pageErrors, [], 'no page errors');
  } finally {
    await browser.close();
  }
  if (failures) { console.log(`test_cad_import_browser: ${failures} FAILED`); process.exit(1); }
  console.log('test_cad_import_browser: PASS');
})();
