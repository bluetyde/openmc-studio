// Real Chromium interaction tests; mocked export API avoids the shared MCNPy gateway.
// Requires playwright. Run: node test/test_mcnp_editor_browser.cjs
const {chromium} = require('playwright');
const fs = require('fs'), path = require('path'), assert = require('assert');
(async () => {
  const browser = await chromium.launch({headless:true, channel:process.env.BROWSER_CHANNEL || 'msedge'});
  try {
    const page = await browser.newPage({viewport:{width:1440,height:1000}});
    const errors = []; page.on('pageerror', e => errors.push(e.message));
    await page.route('**/*', route => route.fulfill({status:404,body:''}));
    await page.setContent(fs.readFileSync(path.join(__dirname,'../studio/openmc_studio/static/index.html'),'utf8'));
    await page.evaluate(() => {
      clearTimeout(LIVE.timer); stopMcnpProgress();
      liveMcnpTick = () => {}; // tests drive each export explicitly
      window.fixture = ['Title','1 1 -1 -1 imp:n=1','2 0 1', '', '1 so 10', '',
        'M1 1001.80c 1','F4:N 1','     2','c '+ 'x'.repeat(127),'NPS 100'].join('\n');
      LOCAL.on = true;
      LIVE.ctx = {cells:[{kind:'part',id:S.parts[0].id}],surfaces:[{owner:{kind:'part',id:S.parts[0].id}}],materials:[S.materials[0]],tallyScores:[],groups:[]};
      LIVE.sentScript = mcnpScript(problems());
      LIVE.report = {deck:fixture,ok:true,seconds:1,notes:['WARNING: surface 1 needs review']};
      MCNP_EDITOR.deck = fixture;
      setDocTab('mcnp'); renderMcnp(problems());
    });
    await page.locator('#tabMcnp').focus();
    await page.keyboard.press('Control+f');
    await page.locator('#mFind').fill('so');
    assert.equal(await page.locator('#mFindCount').textContent(),'1 / 1');
    assert.equal(await page.locator('#mPosition').textContent(),'Ln 5, Col 3');
    assert.equal(await page.evaluate(() => CSS.highlights.get('mcnp-search').size),1);
    await page.keyboard.press('Escape');
    await page.keyboard.press('Control+g');
    await page.locator('#mGoLine').fill('9'); await page.keyboard.press('Enter');
    assert.equal(await page.locator('#mPosition').textContent(),'Ln 9, Col 1');
    assert.equal(await page.locator('#mcnpCode .mcard').count(),2);
    await page.locator('#mcnpDiagnostics button').filter({hasText:'129 columns'}).click();
    assert.equal(await page.locator('#mPosition').textContent(),'Ln 10, Col 1');
    await page.locator('#mcnpCode [data-line="1"] .mref').filter({hasText:'-1'}).click();
    assert.equal(await page.locator('#mPosition').textContent(),'Ln 5, Col 1');
    assert.equal(await page.evaluate(() => sel.id),await page.evaluate(() => S.parts[0].id));
    await page.locator('#mcnpCode [data-line="1"] .mref').first().focus();
    await page.keyboard.press('Enter');
    assert.equal(await page.locator('#mPosition').textContent(),'Ln 7, Col 1');
    // Reference wrapping must preserve existing inline-edit targets.
    await page.locator('#mcnpCode [data-line="1"] .ed').click();
    assert.equal(await page.locator('#mcnpCode .edin').count(),1);
    await page.keyboard.press('Escape');
    await page.evaluate(() => {
      MCNP_EDITOR.previous = fixture;
      LIVE.report.deck = fixture.replace('NPS 100','NPS 200');
      renderMcnp(problems());
    });
    assert.equal(await page.locator('#mcnpCode .mchanged').count(),1);
    await page.locator('#mChanges').uncheck();
    assert.equal(await page.locator('#mcnpCode .mchanged').count(),0);
    // Exercise real asynchronous request handling without launching an exporter.
    await page.evaluate(async () => {
      api = async url => { if (url === '/api/mcnp-live') throw Error('Fixture connection failure at line 5'); return {}; };
      await sendLive(true);
    });
    assert.match(await page.locator('#mcnpStatus').textContent(),/Outdated.*failed/);
    assert.ok((await page.locator('#mcnpCode').textContent()).includes('NPS 200'));
    assert.equal(await page.locator('#mcnpCode .ed:not(.stale)').count(),0);
    assert.equal(await page.locator('#mcnpDiagnostics button').filter({hasText:'connection failure'}).count(),0);
    await page.evaluate(async () => {
      api = async () => ({deck:fixture,ok:true,seconds:1}); await sendLive(true);
    });
    assert.match(await page.locator('#mcnpStatus').textContent(),/Current/);
    await page.evaluate(async () => { await sendLive(true); });
    assert.match(await page.locator('#mChangeCount').textContent(),/^0 added\/changed · 0 removed/);
    // A late response must not overwrite a newer successful export.
    await page.evaluate(async () => {
      let firstResolve, calls = 0;
      api = async url => url === '/api/mcnp-live' ? (++calls === 1 ? new Promise(resolve => { firstResolve = resolve; }) : {deck:fixture,ok:true,seconds:1}) : {};
      const first = sendLive(true); await sendLive(true);
      firstResolve({deck:'Old response',ok:true,seconds:1}); await first;
    });
    assert.ok((await page.locator('#mcnpCode').textContent()).includes('NPS 100'));
    await page.locator('#mFindBtn').click(); await page.locator('#mFind').fill('<img>');
    assert.equal(await page.locator('#mFindCount').textContent(),'No matches');
    await page.locator('#mFind').fill('');
    await page.setViewportSize({width:1050,height:800});
    assert.ok(await page.locator('#mGoLine').isVisible());
    await page.screenshot({path:process.env.MCNP_EDITOR_SCREENSHOT || path.join(require('os').tmpdir(),'mcnp-editor.png')});
    assert.deepEqual(errors, []);
    console.log('Chromium MCNP editor interactions, failed-update retention and recovery PASSED');
  } finally { await browser.close(); }
})().catch(e => {console.error(e);process.exitCode=1;});
