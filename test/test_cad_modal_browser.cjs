// Real Chromium interaction test for the Convert tab CAD modals (Import & Export).
// Verifies opening modals, form elements, file input handling, STEP export execution,
// and dismissals via Cancel button, Escape key, and outside clicks.
// Requires playwright. Run: node test/test_cad_modal_browser.cjs
const {chromium} = require('playwright');
const fs = require('fs'), path = require('path'), assert = require('assert');

(async () => {
  const browser = await chromium.launch({headless:true, channel:process.env.BROWSER_CHANNEL || 'msedge'});
  try {
    const page = await browser.newPage({viewport:{width:1440, height:1000}});
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    await page.route('**/*', route => route.fulfill({status:404, body:''}));
    await page.setContent(fs.readFileSync(path.join(__dirname, '../studio/openmc_studio/static/index.html'), 'utf8'));

    await page.evaluate(() => {
      clearTimeout(LIVE.timer);
      stopMcnpProgress();
      liveMcnpTick = () => {};
    });

    console.log('Testing Convert tab CAD buttons...');
    const convertTab = page.locator('#rtabs button[data-tab="Convert"]');
    await convertTab.click();

    // 1. Test the CAD import modal (offline: no local server, so import is unavailable)
    console.log('Testing CAD Import Modal...');
    const cadImportBtn = page.locator('#rbody button:has-text("Import CAD…")');
    assert.equal(await cadImportBtn.count(), 1, 'Import CAD button must exist in Convert tab');
    await cadImportBtn.click();

    const isImportVisible = await page.evaluate(() => {
      const m = document.querySelector('#cadImportMenu');
      return m && !m.hidden;
    });
    assert.equal(isImportVisible, true, 'Clicking Import CAD… must show #cadImportMenu');

    // Verify elements in import modal
    assert.equal(await page.locator('#cad-select-file-btn').count(), 1, 'File select button must exist');
    assert.match(await page.locator('#cad-unavailable').innerText(), /local Studio server/, 'Offline, the modal says why import is unavailable');
    assert.equal(await page.locator('#cad-import-run').count(), 1, 'Import run button must exist');
    assert.equal(await page.locator('#cad-import-run').isDisabled(), true, 'Import button should be disabled without file');
    console.log('  [PASS] CAD Import modal elements');

    const beforeImport = await page.evaluate(() => JSON.stringify(S));
    await page.locator('#cadFileInput').setInputFiles({name:'sample.step', mimeType:'text/plain', buffer:Buffer.from('ISO-10303-21;')});
    await page.locator('#cad-import-run').click();
    assert.match(await page.locator('#cad-import-status').innerText(), /unavailable/);
    assert.equal(await page.evaluate(() => JSON.stringify(S)), beforeImport, 'Unsupported import must not change the scene');

    // Test dismissals: Cancel button
    await page.locator('#cad-import-cancel').click();
    assert.equal(await page.evaluate(() => document.querySelector('#cadImportMenu').hidden), true, 'Cancel button must hide #cadImportMenu');
    console.log('  [PASS] CAD Import dismissal via Cancel');

    // Test dismissals: Escape key
    await cadImportBtn.click();
    assert.equal(await page.evaluate(() => !document.querySelector('#cadImportMenu').hidden), true);
    await page.keyboard.press('Escape');
    assert.equal(await page.evaluate(() => document.querySelector('#cadImportMenu').hidden), true, 'Escape key must hide #cadImportMenu');
    console.log('  [PASS] CAD Import dismissal via Escape');

    // Test dismissals: Click outside
    await cadImportBtn.click();
    assert.equal(await page.evaluate(() => !document.querySelector('#cadImportMenu').hidden), true);
    await page.mouse.click(10, 10);
    assert.equal(await page.evaluate(() => document.querySelector('#cadImportMenu').hidden), true, 'Click outside must hide #cadImportMenu');
    console.log('  [PASS] CAD Import dismissal via outside click');

    // 2. Test CSG to STEP Export Modal
    console.log('Testing CSG to STEP Export Modal...');
    const cadExportBtn = page.locator('#rbody button:has-text("CSG to STEP…")');
    assert.equal(await cadExportBtn.count(), 1, 'CSG to STEP button must exist in Convert tab');
    await cadExportBtn.click();

    const isExportVisible = await page.evaluate(() => {
      const m = document.querySelector('#cadExportMenu');
      return m && !m.hidden;
    });
    assert.equal(isExportVisible, true, 'Clicking CSG to STEP… must show #cadExportMenu');

    // Verify elements in export modal
    assert.equal(await page.locator('#cad-export-name').count(), 1, 'Filename input must exist');
    assert.equal(await page.locator('#cad-export-units').count(), 1, 'Units dropdown must exist');
    assert.equal(await page.locator('#cad-export-run').count(), 1, 'Export run button must exist');
    console.log('  [PASS] CAD Export modal elements');

    // Test Export execution
    await page.selectOption('#cad-export-units', 'mm');
    await page.evaluate(() => {
      window.__stepSaved = null;
      const origSave = window.saveFile;
      window.saveFile = (filename, data, note) => {
        window.__stepSaved = { filename, dataLength: data.length, note };
        return Promise.resolve();
      };
    });

    await page.locator('#cad-export-run').click();
    assert.equal(await page.evaluate(() => document.querySelector('#cadExportMenu').hidden), true, 'Export button must hide #cadExportMenu');

    assert.equal(await page.evaluate(() => window.__stepSaved), null, 'Offline export must not save an invalid STEP');
    assert.match(await page.locator('#log').innerText(), /FreeCAD worker/);
    await page.evaluate(() => {
      LOCAL.on = true;
      api = async () => ({ok:false, error:'Unsupported shape: wedge'});
    });
    await cadExportBtn.click();
    await page.locator('#cad-export-run').click();
    assert.equal(await page.evaluate(() => window.__stepSaved), null, 'Server rejection must not invoke a fallback');
    assert.match(await page.locator('#log').innerText(), /Unsupported shape: wedge/);
    await page.evaluate(() => {
      api = async () => ({ok:true, step_data:'verified worker output', units:'mm'});
    });
    await cadExportBtn.click();
    await page.locator('#cad-export-run').click();
    assert.ok(await page.evaluate(() => window.__stepSaved), 'Successful worker output can be downloaded');
    console.log('  [PASS] No invalid fallback on offline/server failures; successful worker output downloads');

    const ingestion = await page.evaluate(() => {
      S.parts = []; S.groups = []; S.tallies = [];
      const raw = {id:'same',shape:'sphere',name:'CAD sphere',x:0,y:0,z:0,r:.025};
      const a = insertCadParts([raw], 'first', 'cm')[0];
      const b = insertCadParts([raw], 'second', 'cm')[0];
      let rejected = false;
      try { insertCadParts([raw], 'bad units', 'mm'); } catch(e) { rejected = true; }
      return {ids:[a.id,b.id], materials:S.parts.map(p=>p.material),
        count:S.parts.length, rejected, errors:problems().filter(p=>p.sev==='error'),
        defaults:[a.rx,a.ry,a.rz,a.r]};
    });
    assert.notEqual(ingestion.ids[0], ingestion.ids[1]);
    assert.deepEqual(ingestion.materials, ['void','void']);
    assert.equal(ingestion.count, 2); assert.ok(ingestion.rejected);
    // CAD carries no materials: an inserted part is Void AND pending, which blocks a run
    // until someone chooses (the CAD import plan: never simulate an unassigned solid as empty space).
    assert.equal(ingestion.errors.length, 2);
    assert.ok(ingestion.errors.every(e => /needs a material/.test(e.text)), JSON.stringify(ingestion.errors));
    assert.deepEqual(ingestion.defaults, [0,0,0,.025]);

    // Test dismissals: Cancel button
    await cadExportBtn.click();
    assert.equal(await page.evaluate(() => !document.querySelector('#cadExportMenu').hidden), true);
    await page.locator('#cad-export-cancel').click();
    assert.equal(await page.evaluate(() => document.querySelector('#cadExportMenu').hidden), true, 'Cancel button must hide #cadExportMenu');
    console.log('  [PASS] CAD Export dismissal via Cancel');

    // Test dismissals: Escape key
    await cadExportBtn.click();
    assert.equal(await page.evaluate(() => !document.querySelector('#cadExportMenu').hidden), true);
    await page.keyboard.press('Escape');
    assert.equal(await page.evaluate(() => document.querySelector('#cadExportMenu').hidden), true, 'Escape key must hide #cadExportMenu');
    console.log('  [PASS] CAD Export dismissal via Escape');

    // 3. Test Export Tab Integration
    console.log('Testing Export tab STEP export button...');
    const exportTab = page.locator('#rtabs button[data-tab="Export"]');
    await exportTab.click();
    const exportStepBtn = page.locator('#rbody button:has-text("Export STEP…")');
    assert.equal(await exportStepBtn.count(), 1, 'Export STEP button must exist in Export ribbon tab');
    await exportStepBtn.click();
    assert.equal(await page.evaluate(() => !document.querySelector('#cadExportMenu').hidden), true, 'Clicking Export STEP in Export tab must open #cadExportMenu');
    await page.keyboard.press('Escape');
    console.log('  [PASS] Export tab integration');

    assert.equal(errors.length, 0, `Browser errors detected: ${errors.join(', ')}`);
    console.log('All Convert tab CAD browser tests PASSED successfully!');
  } finally {
    await browser.close();
  }
})().catch(err => {
  console.error(err);
  process.exit(1);
});
