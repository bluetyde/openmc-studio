// The Move/Scale gizmo must work on sub-centimetre models, not only reactor-sized ones.
// A TRISO particle is ~0.05 cm across, so the camera sits ~0.19 cm from it.
// Requires playwright. Run: node test/test_tiny_model_handles.cjs
const {chromium} = require('playwright');
const fs = require('fs'), path = require('path'), assert = require('assert');

const TRISO = JSON.parse(fs.readFileSync(path.join(__dirname, '../examples/triso-particle/triso-particle.openmc-studio.json'), 'utf8'));

(async () => {
  const browser = await chromium.launch({headless:true, channel:process.env.BROWSER_CHANNEL || 'msedge'});
  try {
    const page = await browser.newPage({viewport:{width:1440, height:1000}});
    const errors = []; page.on('pageerror', e => errors.push(e.message));
    await page.route('**/*', route => route.fulfill({status:404, body:''}));
    await page.setContent(fs.readFileSync(path.join(__dirname, '../studio/openmc_studio/static/index.html'), 'utf8'));

    // Put the project in place and stand the 3D camera up without WebGL: buildHandles only
    // needs the camera basis, which is pure arithmetic.
    const handlesFor = (project, mode, partIndex) => page.evaluate(([project, mode, partIndex]) => {
      clearTimeout(LIVE.timer); stopMcnpProgress(); liveMcnpTick = () => {};
      const o = JSON.parse(JSON.stringify(project));
      normalizeProject(o); S = o;
      CAM.target = [0, 0, 0]; CAM.yaw = -0.9; CAM.pitch = 0.45; CAM.dist = 0;
      V3.geom = {B: camBasis(1440, 1000)};
      setTool(mode); select('part', S.parts[partIndex].id);
      const A = adapter3D();
      return {pxPerCm: A.pxPerCm, handles: buildHandles(toolTarget(), A).map(h => ({key:h.key, x:h.x, y:h.y}))};
    }, [project, mode, partIndex]);

    const axesOf = hs => [...new Set(hs.map(h => h.key.replace(/-?1$/, '')))].sort();

    // ---- The bug: a TRISO layer, selected, with Move active.
    let r = await handlesFor(TRISO, 'move', 3); // Silicon carbide (SiC)
    assert.ok(r.pxPerCm > 1000, `expected a close camera, got ${r.pxPerCm} px/cm`);
    assert.ok(r.handles.every(h => Number.isFinite(h.x) && Number.isFinite(h.y)),
      'every move handle must land at a real pixel: ' + JSON.stringify(r.handles));
    assert.deepEqual(axesOf(r.handles), ['move0', 'move1', 'move2'], 'all three move axes must be offered');
    // They must be far enough from the centre to grab (hitHandle allows 8 px).
    const c = [1440 / 2, 1000 / 2];
    assert.ok(r.handles.every(h => Math.hypot(h.x - c[0], h.y - c[1]) > 20),
      'move handles must stand clear of the centre');

    // ---- Scale on the same sphere: the radius handles sit at the surface.
    r = await handlesFor(TRISO, 'scale', 3);
    assert.ok(r.handles.length && r.handles.every(h => Number.isFinite(h.x) && Number.isFinite(h.y)),
      'every radius handle must land at a real pixel: ' + JSON.stringify(r.handles));
    assert.deepEqual(axesOf(r.handles), ['radius0', 'radius1', 'radius2'], 'all three radius axes must be offered');
    const rad = Math.hypot(r.handles[0].x - c[0], r.handles[0].y - c[1]);
    const want = r.pxPerCm * TRISO.parts[3].r;
    assert.ok(Math.abs(rad - want) / want < 0.25, `radius handle should sit near the surface (${want.toFixed(0)} px), got ${rad.toFixed(0)} px`);

    // ---- A reactor-sized model must be untouched by the fix.
    const BIG = JSON.parse(JSON.stringify(TRISO));
    BIG.settings.worldR = 100;
    BIG.parts.forEach((p, i) => { p.r = [25, 35, 39, 42.5, 46][i]; });
    r = await handlesFor(BIG, 'move', 3);
    assert.ok(r.pxPerCm < 10, `expected a far camera, got ${r.pxPerCm} px/cm`);
    assert.deepEqual(axesOf(r.handles), ['move0', 'move1', 'move2'], 'large models keep all three move axes');
    assert.ok(r.handles.every(h => Number.isFinite(h.x) && Number.isFinite(h.y)));

    assert.deepEqual(errors, [], 'no page errors');
    console.log('test_tiny_model_handles: PASS');
  } finally {
    await browser.close();
  }
})();
