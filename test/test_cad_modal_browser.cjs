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

    // 1. Test CAD to CSG Modal
    console.log('Testing CAD to CSG Import Modal...');
    const cadImportBtn = page.locator('#rbody button:has-text("CAD to CSG…")');
    assert.equal(await cadImportBtn.count(), 1, 'CAD to CSG button must exist in Convert tab');
    await cadImportBtn.click();

    const isImportVisible = await page.evaluate(() => {
      const m = document.querySelector('#cadImportMenu');
      return m && !m.hidden;
    });
    assert.equal(isImportVisible, true, 'Clicking CAD to CSG… must show #cadImportMenu');

    // Verify elements in import modal
    assert.equal(await page.locator('#cad-select-file-btn').count(), 1, 'File select button must exist');
    assert.equal(await page.locator('#cad-group-name').count(), 1, 'Group name input must exist');
    assert.equal(await page.locator('#cad-import-run').count(), 1, 'Import run button must exist');
    assert.equal(await page.locator('#cad-import-run').isDisabled(), true, 'Import button should be disabled without file');
    console.log('  [PASS] CAD Import modal elements');

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

    const saved = await page.evaluate(() => window.__stepSaved);
    assert(saved, 'STEP Export should have invoked saveFile');
    assert(saved.filename.endsWith('.step'), 'Filename should end with .step');
    assert(saved.dataLength > 100, 'STEP file data length should be > 100 characters');
    console.log(`  [PASS] STEP Export execution (${saved.filename}, ${saved.dataLength} bytes, note: ${saved.note})`);

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
