// Real Chromium interaction test for the Convert ribbon tab and 3D STL export dialog.
// Verifies ribbon tab navigation, dialog opening, options selection,
// export execution, and dismissals via Cancel, Escape, and outside click.
// Requires playwright. Run: node test/test_convert_tab_browser.cjs
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

    // 1. Verify 'Convert' tab in ribbon
    console.log('Testing Convert tab in ribbon...');
    const convertTab = page.locator('#rtabs button[data-tab="Convert"]');
    assert.equal(await convertTab.count(), 1, 'Convert tab button must exist in ribbon tabs');
    await convertTab.click();

    // Verify ribbon groups inside Convert tab
    const rlabels = await page.locator('#rbody .rlabel').allTextContents();
    assert(rlabels.includes('3D Mesh'), 'Convert ribbon must contain "3D Mesh" group');
    assert(rlabels.includes('CAD Translation'), 'Convert ribbon must contain "CAD Translation" group');
    assert(rlabels.includes('Nuclear Decks'), 'Convert ribbon must contain "Nuclear Decks" group');
    console.log('  [PASS] Convert tab navigation and ribbon groups');

    // 2. Open STL Export Dialog from Convert tab
    console.log('Testing STL Export Menu from Convert tab...');
    const stlBtn = page.locator('#rbody button:has-text("Export STL…")');
    assert.equal(await stlBtn.count(), 1, 'Export STL button must exist');
    await stlBtn.click();

    const isMenuVisible = await page.evaluate(() => {
      const m = document.querySelector('#stlMenu');
      return m && !m.hidden;
    });
    assert.equal(isMenuVisible, true, 'Clicking Export STL… must show #stlMenu');

    // Verify form elements in dialog
    const hasScope = await page.locator('#stl-scope').count();
    const hasFormat = await page.locator('#stl-format').count();
    const hasQuality = await page.locator('#stl-quality').count();
    const hasUnits = await page.locator('#stl-units').count();
    assert.equal(hasScope, 1, 'Scope selector must exist');
    assert.equal(hasFormat, 1, 'Format selector must exist');
    assert.equal(hasQuality, 1, 'Quality selector must exist');
    assert.equal(hasUnits, 1, 'Units selector must exist');
    console.log('  [PASS] STL Export dialog fields');

    // 3. Test Export invocation and dismissal
    await page.selectOption('#stl-format', 'binary');
    await page.selectOption('#stl-quality', '32');
    await page.selectOption('#stl-units', 'cm');

    await page.evaluate(() => {
      window.__exported = null;
      const origSave = window.saveFile;
      window.saveFile = (filename, data, note) => {
        window.__exported = { filename, byteLength: data.byteLength || data.length, note };
        return Promise.resolve();
      };
    });

    await page.locator('#stl-export-btn').click();
    assert.equal(await page.evaluate(() => document.querySelector('#stlMenu').hidden), true, 'Export button must hide #stlMenu');

    const exportData = await page.evaluate(() => window.__exported);
    assert(exportData, 'Export should have called saveFile');
    assert(exportData.byteLength > 84, 'Exported binary data length should exceed header');
    console.log(`  [PASS] STL Export execution (${exportData.filename}, ${exportData.byteLength} bytes)`);

    // 4. Test dismissals: Cancel button
    await stlBtn.click();
    assert.equal(await page.evaluate(() => !document.querySelector('#stlMenu').hidden), true);
    await page.locator('#stl-cancel').click();
    assert.equal(await page.evaluate(() => document.querySelector('#stlMenu').hidden), true, 'Cancel button must hide #stlMenu');
    console.log('  [PASS] Dismissal via Cancel button');

    // Test dismissals: Escape key
    await stlBtn.click();
    assert.equal(await page.evaluate(() => !document.querySelector('#stlMenu').hidden), true);
    await page.keyboard.press('Escape');
    assert.equal(await page.evaluate(() => document.querySelector('#stlMenu').hidden), true, 'Escape key must hide #stlMenu');
    console.log('  [PASS] Dismissal via Escape key');

    // Test dismissals: Click outside
    await stlBtn.click();
    assert.equal(await page.evaluate(() => !document.querySelector('#stlMenu').hidden), true);
    await page.mouse.click(10, 10);
    assert.equal(await page.evaluate(() => document.querySelector('#stlMenu').hidden), true, 'Click outside must hide #stlMenu');
    console.log('  [PASS] Dismissal via outside click');

    // 5. Test Export tab integration
    console.log('Testing Export tab...');
    const exportTab = page.locator('#rtabs button[data-tab="Export"]');
    await exportTab.click();
    const exportStlBtn = page.locator('#rbody button:has-text("Export STL…")');
    assert.equal(await exportStlBtn.count(), 1, 'Export STL button must also exist in Export tab');
    await exportStlBtn.click();
    assert.equal(await page.evaluate(() => !document.querySelector('#stlMenu').hidden), true, 'Opening STL dialog from Export tab must work');
    await page.keyboard.press('Escape');
    console.log('  [PASS] Export tab integration');

    assert.equal(errors.length, 0, `Browser errors detected: ${errors.join(', ')}`);
    console.log('All Convert tab and STL browser tests PASSED successfully!');
  } finally {
    await browser.close();
  }
})().catch(err => {
  console.error(err);
  process.exit(1);
});
