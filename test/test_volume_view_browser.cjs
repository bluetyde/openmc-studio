// 3D volume view (plans/flux-volume-view-plan.md, milestone 1): the shader against its CPU reference.
// A known 10 x 10 x 10 map is drawn by drawVolume3D with a fixed camera into a scratch overlay, and chosen pixels
// of the WebGL result are compared with volumeRayCPU (the same maths one ray at a time):
//   - Brightest shows the maximum along the ray (a hot voxel behind a cooler one still wins);
//   - Surface is empty for a level above the peak, and hits the hot voxel for a level below it;
//   - geometry nearer than the map (a depth buffer) hides it; the cutaway removes the half facing the camera;
//   - Hide noisy drops a voxel whose relative error is over 50%.
// Requires playwright (headless Edge's software WebGL2). Run: node test/test_volume_view_browser.cjs
const {chromium} = require('playwright');
const fs = require('fs'), path = require('path'), assert = require('assert');

(async () => {
  const browser = await chromium.launch({headless:true, channel:process.env.BROWSER_CHANNEL || 'msedge'});
  let failed = 0;
  const check = async (name, fn) => { try { await fn(); console.log(`  [PASS] ${name}`); } catch (e) { failed++; console.log(`  [FAIL] ${name}\n${e.stack}`); } };
  try {
    const page = await browser.newPage({viewport:{width:1000, height:800}});
    const errors = []; page.on('pageerror', e => errors.push(e.message));
    await page.route('**/*', route => route.fulfill({status:404, body:''}));
    await page.setContent(fs.readFileSync(path.join(__dirname, '../studio/openmc_studio/static/index.html'), 'utf8'));
    await page.evaluate(() => {
      clearTimeout(LIVE.timer); stopMcnpProgress(); liveMcnpTick = () => {};
      // a 10^3 map over [-10, 10]^3: a faint background, a warm voxel at the centre, a hot one behind it (z = -7)
      const n = 10, v = new Array(n * n * n).fill(1e-3), rel = new Array(n * n * n).fill(0.05);
      const at = (i, j, k) => i + n * (j + n * k);
      v[at(5, 5, 5)] = 0.1; v[at(5, 5, 1)] = 1.0;
      window.__t = {name:'map', kind:'mesh', mesh_type:'regular', dims:[n, n, n], lower:[-10, -10, -10], upper:[10, 10, 10],
        scores:['flux'], values:{flux:v}, rel_err:{flux:rel}};
      // camera on +z looking down -z at the origin, 1 px = 0.05 cm at the origin plane
      const W = 200, H = 160;
      window.__B = {pos:[0.25, 0.25, 50], f:[0, 0, -1], r:[1, 0, 0], u:[0, 1, 0], focal:1000};
      window.__W = W; window.__H = H;
      window.__draw = () => {
        V3.volGL = undefined;
        const cv = document.createElement('canvas'); cv.width = W; cv.height = H;
        const ok = drawVolume3D(cv.getContext('2d'), __B, __t, W, H);
        const G = V3.volGL, px = new Uint8Array(4);
        G.gl.readPixels(W / 2, H / 2, 1, 1, G.gl.RGBA, G.gl.UNSIGNED_BYTE, px);  // the centre ray
        return {ok, px:Array.from(px), V:{mn:G.V.mn, mx:G.V.mx}};
      };
      window.__cpu = (mode, level, depth, cut) => {
        const V = volumeData(__t, VOLVIEW.hideNoisy);
        return volumeRayCPU(V, __t, __B.pos, __B.f, depth ?? Infinity, mode, level === undefined ? 0 : volumeLevelByte(V, level), cut);
      };
      document.querySelector('#cutaway').checked = false;
      V3.depth = null;
    });
    const ramp = b => page.evaluate(b => ramp(VIRIDIS, (b - 1) / 254), b);
    const near = (a, b, tol = 3) => a.every((x, i) => Math.abs(x - b[i]) <= tol);

    await check('Brightest: the centre ray shows the hottest voxel along it, as the CPU reference does', async () => {
      await page.evaluate(() => { VOLVIEW.mode = 'mip'; VOLVIEW.hideNoisy = false; });
      const r = await page.evaluate(() => __draw()), b = await page.evaluate(() => __cpu('mip'));
      assert.ok(r.ok, 'WebGL2 volume rendering is available');
      assert.equal(b, 255, 'the hot voxel (the peak) is on the centre ray');
      const want = (await ramp(b)).map(c => Math.round(c * 0.85));
      assert.ok(near(r.px.slice(0, 3), want), `${r.px} vs ${want}`);
      assert.ok(Math.abs(r.px[3] - 217) <= 2, `alpha ${r.px[3]}`);
    });

    await check('Surface: at 90% of the peak only the hot voxel counts; at 5% the warm voxel in front is hit first', async () => {
      await page.evaluate(() => { VOLVIEW.mode = 'iso'; VOLVIEW.level = 90; });
      let r = await page.evaluate(() => __draw());
      assert.equal(await page.evaluate(() => __cpu('iso', 90)), 255, 'only the hot voxel reaches 90% of the peak');
      assert.equal(r.px[3], 255);
      await page.evaluate(() => { VOLVIEW.level = 5; });
      assert.ok(await page.evaluate(() => __cpu('iso', 5)) < 255, 'at 5% the warm centre voxel, in front, is hit first');
      r = await page.evaluate(() => __draw());
      assert.equal(r.px[3], 255);
    });

    await check('geometry in front hides the map (depth buffer); geometry behind does not', async () => {
      await page.evaluate(() => { VOLVIEW.mode = 'mip'; });
      const r = await page.evaluate(() => {
        const W = __W, H = __H, buf = new Uint8Array(W * H * 4).fill(255), tmax = 200;
        const put = dist => { const q = Math.round(dist / tmax * 16777214); for (let i = 0; i < W * H; i++) buf.set([q >> 16 & 255, q >> 8 & 255, q & 255, 255], 4 * i); };
        put(30);  // a wall 30 cm from the camera, in front of the map (it starts 40 cm away)
        V3.depth = {buf, w:W, h:H, tmax};
        const hidden = __draw().px[3];
        put(80);  // a wall behind the map's far side (60 cm)
        const shown = __draw().px[3];
        V3.depth = null;
        return {hidden, shown};
      });
      assert.equal(r.hidden, 0); assert.ok(r.shown > 200);
      assert.equal(await page.evaluate(() => __cpu('mip', undefined, 30)), 0);
    });

    await check('the cutaway removes the half facing the camera', async () => {
      const r = await page.evaluate(() => {
        document.querySelector('#cutaway').checked = true; view.plane = 'xy'; view.slice = -5;  // keeps z < -5
        const px = __draw().px; document.querySelector('#cutaway').checked = false; return px;
      });
      const b = await page.evaluate(() => __cpu('mip', undefined, undefined, {axis:2, at:-5, side:1}));
      assert.equal(b, 255, 'the hot voxel (z = -7) is in the kept half');
      const cpuFront = await page.evaluate(() => { view.slice = -9; return __cpu('mip', undefined, undefined, {axis:2, at:-9, side:1}); });
      assert.ok(cpuFront < 255, 'with the cut at z = -9 the hot voxel is removed');
      assert.ok(near(r.slice(0, 3), (await ramp(255)).map(c => Math.round(c * 0.85))));
    });

    await check('Hide noisy leaves out a voxel with more than 50% error', async () => {
      const r = await page.evaluate(() => {
        __t.rel_err.flux[5 + 10 * (5 + 10 * 1)] = 0.8;  // the hot voxel is noisy now
        __t = {...__t};  // a new result object, so the texture is rebuilt
        VOLVIEW.mode = 'mip'; VOLVIEW.hideNoisy = true;
        const a = __draw().px; VOLVIEW.hideNoisy = false; const b = __draw().px;
        return {a, b};
      });
      assert.equal(await page.evaluate(() => { VOLVIEW.hideNoisy = true; const x = __cpu('mip'); VOLVIEW.hideNoisy = false; return x; }) < 255, true);
      assert.notDeepEqual(r.a.slice(0, 3), r.b.slice(0, 3), 'the colour on the centre ray changes');
    });

    await check('the 3D controls appear only in 3D with a regular map', async () => {
      const r = await page.evaluate(() => {
        view.mode = 'slice'; syncVolumeControls(__t); const inSlice = $('#volMode').hidden;
        view.mode = '3d'; syncVolumeControls(__t); const in3d = $('#volMode').hidden;
        syncVolumeControls({...__t, mesh_type:'cylindrical'}); const cyl = $('#volMode').hidden;
        return {inSlice, in3d, cyl};
      });
      assert.deepEqual(r, {inSlice:true, in3d:false, cyl:true});
    });
    assert.deepEqual(errors, []);
  } finally { await browser.close(); }
  if (failed) { console.log(`test_volume_view_browser: ${failed} FAILED`); process.exit(1); }
  console.log('test_volume_view_browser: PASS');
})();
