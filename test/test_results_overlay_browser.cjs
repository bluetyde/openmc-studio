// Particle tracks must be clickable in the 3D view, not only in the 2D slice, and the
// viewport's Clear button must clear the overlay without throwing the run away.
// Requires playwright. Run: node test/test_results_overlay_browser.cjs
const {chromium} = require('playwright');
const fs = require('fs'), path = require('path'), assert = require('assert');

// One neutron running along +x through the middle of the model, plus a stray one far away.
const RESULTS = {
  tallies: [],
  tracks: [
    {id:[1, 1, 7], tracks:[{xyz:[-30, 0, 0, 0, 0, 0, 30, 0, 0], E:[2e6, 1e6, 5e5]}]},
    {id:[1, 1, 9], tracks:[{xyz:[-30, 0, 80, 30, 0, 80], E:[2e6, 1e6]}]},
  ],
};

(async () => {
  const browser = await chromium.launch({headless:true, channel:process.env.BROWSER_CHANNEL || 'msedge'});
  try {
    const page = await browser.newPage({viewport:{width:1440, height:1000}});
    const errors = []; page.on('pageerror', e => errors.push(e.message));
    await page.route('**/*', route => route.fulfill({status:404, body:''}));
    await page.setContent(fs.readFileSync(path.join(__dirname, '../studio/openmc_studio/static/index.html'), 'utf8'));

    await page.evaluate(results => {
      clearTimeout(LIVE.timer); stopMcnpProgress(); liveMcnpTick = () => {};
      LOCAL.on = true; LOCAL.token = 'test-token'; LOCAL.results = results;
      S.settings.worldR = 100;
      CAM.target = [0, 0, 0]; CAM.yaw = -0.9; CAM.pitch = 0.45; CAM.dist = 0;
      V3.geom = {B: camBasis(1440, 1000)};
      document.querySelector('#showTracks').checked = true;
      document.querySelector('#showMesh').checked = true;
    }, RESULTS);

    // ---- 3D picking: click the middle of the first track.
    const hit = await page.evaluate(() => {
      const B = V3.geom.B, q = project3(B, [0, 0, 0]);          // midpoint of track [1,1,7]
      const picked = pickTrack3(q[0], q[1]);
      return {picked, sel: LOCAL.selTrack, replayShown: !document.querySelector('#replayBtn').hidden};
    });
    assert.equal(hit.picked, true, 'clicking a track in the 3D view must select it');
    assert.deepEqual(hit.sel, [1, 1, 7], 'it must select the track under the cursor');
    assert.equal(hit.replayShown, true, 'selecting a track must offer Replay');

    // Clicking empty space in 3D deselects rather than picking the far-away track.
    const miss = await page.evaluate(() => ({picked: pickTrack3(5, 5), sel: LOCAL.selTrack}));
    assert.equal(miss.picked, false, 'empty space must not pick a track');
    assert.equal(miss.sel, null, 'and must clear the selection');

    // ---- Clear overlay hides the layers but keeps the run loaded.
    const cleared = await page.evaluate(() => {
      LOCAL.selTrack = [1, 1, 7];
      clearOverlay();
      return {
        mesh: document.querySelector('#showMesh').checked,
        tracks: document.querySelector('#showTracks').checked,
        selTrack: LOCAL.selTrack,
        stillLoaded: !!LOCAL.results,
        trackCount: LOCAL.results ? LOCAL.results.tracks.length : 0,
      };
    });
    assert.equal(cleared.mesh, false, 'Clear must untick the flux map');
    assert.equal(cleared.tracks, false, 'Clear must untick the tracks');
    assert.equal(cleared.selTrack, null, 'Clear must drop the selected track');
    assert.equal(cleared.stillLoaded, true, 'Clear must NOT discard the results');
    assert.equal(cleared.trackCount, 2, 'the run keeps its tracks so the layers can come back');

    // ---- The same action is offered in the Physics tab, next to the other Clear buttons.
    const labels = await page.evaluate(() => {
      ribbonTab = 'Physics'; renderRibbon();
      return [...document.querySelectorAll('#rbody button')].map(b => b.textContent.trim());
    });
    assert.ok(labels.includes('Clear overlay'), 'Physics tab should offer Clear overlay: ' + labels.join(' | '));
    assert.ok(labels.includes('Clear tallies') && labels.includes('Clear sources'), 'beside the existing Clear buttons');

    assert.deepEqual(errors, [], 'no page errors');
    console.log('test_results_overlay_browser: PASS');
  } finally {
    await browser.close();
  }
})();
