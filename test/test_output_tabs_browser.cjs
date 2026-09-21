// Real Chromium interaction test for the output tabs (Problems / Log / Results / Runs).
// Every tab must be reachable by clicking it, not only when a run finishes.
// Requires playwright. Run: node test/test_output_tabs_browser.cjs
const {chromium} = require('playwright');
const fs = require('fs'), path = require('path'), assert = require('assert');

const RUNS = {runs:[
  {id:'20260921-180000-triso-particle', name:'TRISO particle', status:'done', started:1790000000},
  {id:'20260921-175000-triso-particle', name:'TRISO particle', status:'failed', started:1789999000},
]};
const RESULTS = {tallies:[], tracks:[], summary:null};

(async () => {
  const browser = await chromium.launch({headless:true, channel:process.env.BROWSER_CHANNEL || 'msedge'});
  try {
    const page = await browser.newPage({viewport:{width:1440,height:1000}});
    const errors = []; page.on('pageerror', e => errors.push(e.message));
    await page.route('**/*', route => route.fulfill({status:404, body:''}));
    await page.setContent(fs.readFileSync(path.join(__dirname, '../studio/openmc_studio/static/index.html'), 'utf8'));

    // Local mode: the server is connected, so Results and Runs are offered.
    await page.evaluate(([RUNS_FIXTURE, RESULTS_FIXTURE]) => {
      clearTimeout(LIVE.timer); stopMcnpProgress();
      liveMcnpTick = () => {};
      LOCAL.on = true; LOCAL.token = 'test-token';
      // setContent has no origin to fetch from, so stand in for the server directly.
      window.runsFetches = 0;
      window.api = async path => {
        if (path === '/api/runs') { window.runsFetches++; return RUNS_FIXTURE; }
        if (/^\/api\/runs\/[^/]+\/results$/.test(path)) return RESULTS_FIXTURE;
        throw new Error('unexpected request ' + path);
      };
      document.querySelector('#otResults').hidden = false;
      document.querySelector('#otRuns').hidden = false;
      setOutTab('log');
    }, [RUNS, RESULTS]);

    const shown = () => page.evaluate(() => ['problems', 'log', 'results', 'runs'].filter(k => !document.querySelector('#' + k).hidden));
    const selected = () => page.evaluate(() => ['otProblems', 'otLog', 'otResults', 'otRuns'].filter(k => document.querySelector('#' + k).getAttribute('aria-selected') === 'true'));

    // Each tab opens its own pane, and only that one.
    for (const [btn, pane] of [['#otResults', 'results'], ['#otRuns', 'runs'], ['#otProblems', 'problems'], ['#otLog', 'log'], ['#otResults', 'results']]) {
      await page.locator(btn).click();
      assert.deepEqual(await shown(), [pane], `clicking ${btn} should show only #${pane}`);
      assert.deepEqual(await selected(), [btn.slice(1)], `clicking ${btn} should select it`);
    }

    // The regression the user hit: a finished run switches to Results, and you can still
    // leave and come back to it afterwards.
    await page.evaluate(() => loadResults('20260921-180000-triso-particle', true));
    assert.deepEqual(await shown(), ['results'], 'a finished run opens Results');
    await page.locator('#otLog').click();
    await page.locator('#otResults').click();
    assert.deepEqual(await shown(), ['results'], 'Results must be reachable again after leaving it');

    // Opening Runs lists the past runs and refreshes them each time.
    const before = await page.evaluate(() => window.runsFetches);
    await page.locator('#otRuns').click();
    await page.waitForFunction(() => document.querySelectorAll('#runs .runrow').length === 2);
    assert.ok(await page.evaluate(() => window.runsFetches) > before, 'opening Runs should refresh the list');
    assert.equal(await page.locator('#runs .runrow').count(), 2);
    // Results is offered for the finished run only.
    assert.equal(await page.locator('#runs [data-results]:not([disabled])').count(), 1);
    assert.equal(await page.locator('#runs [data-load]').count(), 2);

    assert.deepEqual(errors, [], 'no page errors');
    console.log('test_output_tabs_browser: PASS');
  } finally {
    await browser.close();
  }
})();
