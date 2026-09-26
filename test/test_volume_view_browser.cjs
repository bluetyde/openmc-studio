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

    await check('a thin hot voxel on a long ray is drawn, as the CPU reference sees it (review: skipped at 1,024 steps)', async () => {
      const r = await page.evaluate(() => {
        const keep = [__t, __B];
        const n = 2048, v = new Array(n).fill(0);
        v[1500] = 1; v[0] = 1e-3;  // one hot voxel 1 cm thick, 1,500 cm down the ray
        __t = {name:'thin', kind:'mesh', mesh_type:'regular', dims:[n, 1, 1], lower:[0, -20, -20], upper:[n, 20, 20],
          scores:['flux'], values:{flux:v}, rel_err:{flux:new Array(n).fill(0.05)}};
        __B = {pos:[-1, 0.02, 0.02], f:[1, 0, 0], r:[0, 1, 0], u:[0, 0, 1], focal:1e6};
        VOLVIEW.mode = 'mip'; VOLVIEW.hideNoisy = false;
        const max3d = document.createElement('canvas').getContext('webgl2').getParameter(0x8073);  // MAX_3D_TEXTURE_SIZE
        const out = max3d >= n ? {gpu:__draw().px, cpu:__cpu('mip')} : {max3d};
        [__t, __B] = keep;
        return out;
      });
      if (r.max3d) { console.log(`    (this GPU's 3D textures stop at ${r.max3d}; checked by test_volume_view.js only)`); return; }
      assert.equal(r.cpu, 255);
      assert.ok(near(r.gpu.slice(0, 3), (await ramp(255)).map(c => Math.round(c * 0.85))), `${r.gpu}`);
    });

    await check('a map too big to march exactly falls back to the slice, with a note', async () => {
      const r = await page.evaluate(() => {
        const t = {...__t, dims:[2000, 2000, 200]};
        V3.volGL = undefined;
        const cv = document.createElement('canvas'); cv.width = __W; cv.height = __H;
        return {ok:drawVolume3D(cv.getContext('2d'), __B, t, __W, __H), note:V3.volNote};
      });
      assert.equal(r.ok, false);
      assert.match(r.note, /too fine to march every voxel|3D textures stop at/);
    });

    // Many pixels at once: each GPU pixel against volumeRayCPU for the ray through that pixel's centre.
    await page.evaluate(() => {
      window.__many = (t, B, mode, level, pts) => {
        const keep = [__t, __B]; __t = t; __B = B;
        V3.volGL = undefined;
        const cv = document.createElement('canvas'); cv.width = __W; cv.height = __H;
        const ok = drawVolume3D(cv.getContext('2d'), B, t, __W, __H), G = V3.volGL;
        const V = volumeData(t, false), px = new Uint8Array(4), out = [];
        for (const [x, y] of pts) {
          G.gl.readPixels(x, y, 1, 1, G.gl.RGBA, G.gl.UNSIGNED_BYTE, px);
          const fx = (x + 0.5 - __W / 2) / B.focal, fy = (y + 0.5 - __H / 2) / B.focal;
          const d = [0, 1, 2].map(k => B.f[k] + B.r[k] * fx + B.u[k] * fy);
          const lv = mode === 'iso' ? volumeLevelByte(V, level) : level;
          out.push({gpu:Array.from(px), cpu:volumeRayCPU(V, t, B.pos, d, Infinity, mode, lv)});
        }
        [__t, __B] = keep;
        return {ok, out, note:V3.volNote};
      };
      // a cylindrical map about (2, -1): 6 rings from r = 3 to 15, a half turn in 8 bins, 4 z layers; values by cell
      const nr = 6, np = 8, nz = 4, lin = (a, b, n) => Array.from({length:n + 1}, (_, i) => a + (b - a) * i / n);
      const v = [];
      for (let k = 0; k < nz; k++) for (let j = 0; j < np; j++) for (let i = 0; i < nr; i++) v.push((i + 1) * (j % 3 + 1) * (k + 1) * 1e-3);
      window.__cyl = {name:'cyl', kind:'mesh', mesh_type:'cylindrical', dims:[nr, np, nz], origin:[2, -1, 0],
        r_grid:lin(3, 15, nr), phi_grid:lin(0.3, 0.3 + Math.PI, np), z_grid:lin(-8, 8, nz),
        scores:['flux'], values:{flux:v}, rel_err:{flux:v.map(() => 0.05)}};
      // a camera at pos looking at target, z up
      window.__lookAt = (pos, target, focal) => {
        const nrm = v => { const l = Math.hypot(...v); return v.map(x => x / l); };
        const f = nrm(target.map((x, k) => x - pos[k])), r = nrm([f[1], -f[0], 0]);
        const u = [r[1] * f[2] - r[2] * f[1], r[2] * f[0] - r[0] * f[2], r[0] * f[1] - r[1] * f[0]];
        return {pos, f, r, u, focal};
      };
      window.__oblique = __lookAt([-30, -40, 25], [2, -1, 0], 260);
      // a box map with a smooth peak (six decades), so a glow has something to show everywhere
      const m = 12, g = [];
      for (let k = 0; k < m; k++) for (let j = 0; j < m; j++) for (let i = 0; i < m; i++)
        g.push(Math.exp(-((i - 5.5) ** 2 + (j - 5.5) ** 2 + (k - 5.5) ** 2) / 10));
      window.__smooth = {name:'smooth', kind:'mesh', mesh_type:'regular', dims:[m, m, m], lower:[-10, -10, -10], upper:[10, 10, 10],
        scores:['flux'], values:{flux:g}, rel_err:{flux:g.map(() => 0.05)}};
    });
    const grid = [];
    for (let y = 8; y < 160; y += 16) for (let x = 6; x < 200; x += 16) grid.push([x, y]);
    const agree = (r, rgb) => r.out.filter(({gpu, cpu}) => rgb(cpu) === null ? gpu[3] === 0 : gpu[3] > 0 && gpu.slice(0, 3).every((c, k) => Math.abs(c - rgb(cpu)[k]) <= 4));

    await check('cylindrical maps: Brightest on the GPU matches the reference, pixel by pixel, from an oblique camera', async () => {
      await page.evaluate(() => { VOLVIEW.mode = 'mip'; VOLVIEW.hideNoisy = false; });
      const r = await page.evaluate(pts => __many(__cyl, __oblique, 'mip', 0, pts), grid);
      assert.ok(r.ok, r.note);
      const colours = await page.evaluate(() => Array.from({length:256}, (_, b) => b ? ramp(VIRIDIS, (b - 1) / 254).map(c => Math.round(c * 0.85)) : null));
      const hits = r.out.filter(o => o.cpu > 0).length;
      assert.ok(hits > 20 && hits < r.out.length, `the map covers part of the view (${hits} of ${r.out.length})`);
      const ok = agree(r, b => colours[b]);
      assert.ok(ok.length >= r.out.length - 2, `${ok.length} of ${r.out.length} pixels agree`);
    });

    await check('cylindrical maps: Surface hits where the reference does', async () => {
      await page.evaluate(() => { VOLVIEW.mode = 'iso'; VOLVIEW.level = 40; });
      const r = await page.evaluate(pts => __many(__cyl, __oblique, 'iso', 40, pts), grid);
      const same = r.out.filter(({gpu, cpu}) => (gpu[3] > 0) === (cpu > 0)).length;
      assert.ok(r.out.some(o => o.cpu > 0) && r.out.some(o => !o.cpu));
      assert.ok(same >= r.out.length - 2, `${same} of ${r.out.length}`);
    });

    await check('Glow: GPU colour and coverage match the reference (box and cylindrical maps)', async () => {
      await page.evaluate(() => { VOLVIEW.mode = 'glow'; VOLVIEW.glow = 40; });
      for (const which of ['box', 'cyl']) {
        const r = await page.evaluate(([pts, which]) => which === 'box'
          ? __many(__smooth, __lookAt([-40, -35, 30], [0, 0, 0], 260), 'glow', 40, pts)
          : __many(__cyl, __oblique, 'glow', 40, pts), [grid, which]);
        let good = 0, lit = 0;
        for (const {gpu, cpu} of r.out) {
          if (cpu[3] > 0.01) lit++;
          const want = cpu.map(c => Math.round(c * 255));
          if (gpu.every((c, k) => Math.abs(c - want[k]) <= 6)) good++;
        }
        assert.ok(lit > 10, `${which}: ${lit} lit pixels`);
        assert.ok(good >= r.out.length - 3, `${which}: ${good} of ${r.out.length} pixels agree`);
      }
    });

    await check('while the camera moves the volume is drawn at half resolution, then in full', async () => {
      const r = await page.evaluate(() => {
        VOLVIEW.mode = 'mip';
        const size = () => { const G = V3.volGL; return [G.cv.width, G.cv.height]; };
        V3.volGL = undefined;
        const cv = document.createElement('canvas'); cv.width = __W; cv.height = __H;
        V3.drag = {mode:'orbit'}; drawVolume3D(cv.getContext('2d'), __B, __t, __W, __H); const moving = size(); const coarse = V3.volCoarse;
        V3.drag = null; V3.wheelAt = 0; drawVolume3D(cv.getContext('2d'), __B, __t, __W, __H); const still = size();
        V3.wheelAt = Date.now(); drawVolume3D(cv.getContext('2d'), __B, __t, __W, __H); const wheel = size(); V3.wheelAt = 0;
        return {moving, still, wheel, coarse};
      });
      assert.deepEqual(r.moving, [100, 80]); assert.deepEqual(r.wheel, [100, 80]); assert.deepEqual(r.still, [200, 160]);
      assert.equal(r.coarse, true);
    });

    await check('the 3D controls appear only in 3D, for box and cylindrical maps; Glow has its strength slider', async () => {
      const r = await page.evaluate(() => {
        view.mode = 'slice'; syncVolumeControls(__t); const inSlice = $('#volMode').hidden;
        view.mode = '3d'; syncVolumeControls(__t); const in3d = $('#volMode').hidden;
        syncVolumeControls({...__t, mesh_type:'cylindrical'}); const cyl = $('#volMode').hidden;
        VOLVIEW.mode = 'glow'; syncVolumeControls(__t); const glow = $('#volGlowWrap').hidden, level = $('#volLevelWrap').hidden;
        return {inSlice, in3d, cyl, glow, level};
      });
      assert.deepEqual(r, {inSlice:true, in3d:false, cyl:false, glow:false, level:true});
    });
    assert.deepEqual(errors, []);
  } finally { await browser.close(); }
  if (failed) { console.log(`test_volume_view_browser: ${failed} FAILED`); process.exit(1); }
  console.log('test_volume_view_browser: PASS');
})();
