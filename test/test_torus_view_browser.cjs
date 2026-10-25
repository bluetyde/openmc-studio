// The torus in the two views, in a real (headless) browser: the 3D ray-march shader against the page's own ray code, and the 2D slice against the inside test.
//   - 3D: for a grid of pixels, "something is drawn here" in the WebGL image must agree with pick3 (the CPU ray code) for tori of several shapes and axes, seen from
//     several sides, with the spans of the torus hidden and shown by other parts; at least a few thousand pixels are covered, so agreement cannot be empty.
//   - 2D: in each slice plane the colour of a pixel is the torus colour exactly where inShape says it is inside.
// Requires playwright (headless Edge's software WebGL2). Run: node test/test_torus_view_browser.cjs
const {chromium} = require('playwright');
const fs = require('fs'), path = require('path'), assert = require('assert');

(async () => {
  const browser = await chromium.launch({headless: true, channel: process.env.BROWSER_CHANNEL || 'msedge'});
  let failed = 0;
  const check = async (name, fn) => { try { await fn(); console.log(`  [PASS] ${name}`); } catch (e) { failed++; console.log(`  [FAIL] ${name}\n${e.stack}`); } };
  try {
    const page = await browser.newPage({viewport: {width: 1000, height: 800}});
    const errors = []; page.on('pageerror', e => errors.push(e.message));
    await page.route('**/*', route => route.fulfill({status: 404, body: ''}));
    await page.setContent(fs.readFileSync(path.join(__dirname, '../studio/openmc_studio/static/index.html'), 'utf8'));
    await page.evaluate(() => {
      clearTimeout(LIVE.timer); stopMcnpProgress(); liveMcnpTick = () => {};
      window.__setup = (ring, extra) => {
        S = sampleModel(); S.groups = []; S.tallies = []; S.sources = [];
        const m = S.materials[0].id, m2 = S.materials[1].id;
        S.materials[0].color = '#00c800';      // the torus is the only green thing, so "drawn" can mean "torus" (a void part is drawn as a faint ball)
        S.settings.worldR = 60; S.settings.worldFill = 'void';
        S.parts = [...(extra || []).map((o, i) => Object.assign(newPart('x' + i, 'extra' + i, o.shape), {material: o.material === 'void' ? 'void' : m2}, o)),
          Object.assign(newPart('t1', 'Ring', 'torus'), {material: m}, ring)];
        S.parts.forEach(p => { if (p.material === m2 && p.shape === 'torus') p.material = m; });
      };
    });
    const grid3 = async (ring, extra, cut) => page.evaluate(({ring, extra, cut}) => {
      __setup(ring, extra);
      view.mode = '3d'; view.plane = 'xz'; view.slice = 0; document.querySelector('#cutaway').checked = !!cut;
      let covered = 0, disagree = 0, total = 0;
      for (const [yaw, pitch] of [[-0.9, 0.45], [0.3, 1.2], [2.0, -0.6], [1.0, 0.05], [-2.4, 1.45]]) {
        CAM.yaw = yaw; CAM.pitch = pitch; CAM.dist = 110;
        draw3D();
        const gl = V3.gl, c = document.getElementById('vp3'), W = c.width, H = c.height, px = new Uint8Array(W * H * 4);
        gl.readPixels(0, 0, W, H, gl.RGBA, gl.UNSIGNED_BYTE, px);
        for (let y = 2; y < H; y += 5) for (let x = 2; x < W; x += 5) {
          const o = ((H - 1 - y) * W + x) * 4, drawn = px[o + 1] > 50 && px[o + 1] > px[o] + 20 && px[o + 1] > px[o + 2] + 20, picked = pick3(x + 0.5, y + 0.5) === S.parts.length - 1;
          if (picked) covered++; if (drawn !== picked) disagree++; total++;
        }
      }
      return {covered, disagree, total, err: V3.err};
    }, {ring, extra, cut});
    const rings = [
      ['round z', {a: 30, b: 8, c: 8}], ['tall z (b > c)', {a: 30, b: 14, c: 6}], ['flat z (b < c)', {a: 30, b: 5, c: 12}],
      ['x axis', {a: 25, b: 15, c: 5, axis: 'x', x: 8}], ['y axis, offset', {a: 35, b: 4, c: 20, axis: 'y', z: -6}], ['turned 30 degrees (view only)', {a: 30, b: 12, c: 6, rx: 30}]];
    for (const [name, ring] of rings) {
      await check(`3D shader agrees with the page's ray code: ${name}`, async () => {
        const r = await grid3(ring);
        assert.ok(!r.err, r.err);
        assert.ok(r.covered > 2500, `only ${r.covered} pixels covered`);
        assert.ok(r.disagree <= 0.015 * r.covered + 5, `${r.disagree} of ${r.covered} covered pixels disagree`);   // silhouette pixels: the shader's edge shading against the picker's exact hit
      });
    }
    // The surface is shaded by 0.30 + 0.70 * |n . view| (a headlight), so a wrong normal shows as a wrong brightness. For a torus alone in view, the brightness of each drawn
    // pixel is fitted against that value computed from torusSpans' normal; a straight line through all of them means the shader's normal is the true one.
    for (const [name, ring] of [['tall z (b > c)', {a: 30, b: 14, c: 6}], ['flat z (b < c)', {a: 30, b: 5, c: 12}], ['y axis', {a: 35, b: 4, c: 20, axis: 'y', z: -6}]]) {
      await check(`3D shading follows the surface normal: ${name}`, async () => {
        const r = await page.evaluate(ring => {
          __setup(ring); view.mode = '3d'; document.querySelector('#cutaway') && (document.querySelector('#cutaway').checked = false);
          const xs = [], ys = [];
          for (const [yaw, pitch] of [[-0.9, 0.45], [0.3, 1.2], [2.0, -0.6]]) {
            CAM.yaw = yaw; CAM.pitch = pitch; CAM.dist = 110; draw3D();
            const gl = V3.gl, c = document.getElementById('vp3'), W = c.width, H = c.height, px = new Uint8Array(W * H * 4), B = V3.geom.B;
            gl.readPixels(0, 0, W, H, gl.RGBA, gl.UNSIGNED_BYTE, px);
            const part = S.parts[0], q = partUniform(part);
            for (let y = 4; y < H; y += 7) for (let x = 4; x < W; x += 7) {
              const rd = rayFor(B, x + 0.5, y + 0.5), o = v3sub(B.pos, q.c), lo = q.cols.map(m => v3dot(o, m)), ld = q.cols.map(m => v3dot(rd, m));
              const sp = torusSpans(lo, ld, q.dims[0], q.dims[1], q.dims[2]).find(t => t.t1 > 0);
              if (!sp) continue;
              const t0 = Math.max(sp.t0, 0); if (t0 > sp.t0) continue;         // the camera is outside, so the first span starts at t0 > 0
              const nw = [0, 1, 2].map(i => q.cols[0][i] * sp.n0[0] + q.cols[1][i] * sp.n0[1] + q.cols[2][i] * sp.n0[2]);
              const lam = 0.30 + 0.70 * Math.max(-(nw[0] * rd[0] + nw[1] * rd[1] + nw[2] * rd[2]), 0);
              const k = ((H - 1 - y) * W + x) * 4, L = (px[k] + px[k + 1] + px[k + 2]) / 3;
              if (L < 18) continue;
              xs.push(lam); ys.push(L);
            }
          }
          const n = xs.length, mx = xs.reduce((a, b) => a + b, 0) / n, my = ys.reduce((a, b) => a + b, 0) / n;
          let sxy = 0, sxx = 0, syy = 0; for (let i = 0; i < n; i++) { sxy += (xs[i] - mx) * (ys[i] - my); sxx += (xs[i] - mx) ** 2; syy += (ys[i] - my) ** 2; }
          return {n, corr: sxy / Math.sqrt(sxx * syy), slope: sxy / sxx};
        }, ring);
        assert.ok(r.n > 800, `only ${r.n} shaded pixels compared`);
        assert.ok(r.slope > 0 && r.corr > 0.995, `brightness against the true normal: correlation ${r.corr.toFixed(4)} over ${r.n} pixels`);
      });
    }
    await check('3D: parts inside the hole and across the tube show through correctly', async () => {
      const r = await grid3({a: 30, b: 12, c: 6}, [{shape: 'sphere', r: 8}, {shape: 'box', sx: 8, sy: 90, sz: 3}]);
      assert.ok(!r.err, r.err);
      assert.ok(r.covered > 2500 && r.disagree <= 0.015 * r.covered + 5, JSON.stringify(r));
    });
    // The thinnest tube Problems does not warn about (c / a = 0.01): the single-precision quartic must still find it, a pixel for a pixel against the picker.
    await check('3D shader keeps a thin tube (c / a = 0.01) that the picker finds', async () => {
      const r = await grid3({a: 30, b: 0.6, c: 0.3});
      assert.ok(!r.err, r.err);
      assert.ok(r.covered > 150, `only ${r.covered} pixels covered`);
      assert.ok(r.disagree <= 0.08 * r.covered + 5, `${r.disagree} of ${r.covered} covered pixels disagree`);
    });
    // The cut-away plane (y = 0) removes the half facing the camera. A ray that enters the cut inside the hole has already left the first tube, so only the torus's
    // second span is left for it: a shader that kept one span per part would draw nothing there.
    for (const [name, ring] of [['z axis', {a: 30, b: 12, c: 6}], ['x axis', {a: 25, b: 15, c: 5, axis: 'x'}]]) {
      await check(`3D cutaway: the second span is drawn where the first is cut off (${name})`, async () => {
        const r = await grid3(ring, [], true);
        assert.ok(!r.err, r.err);
        assert.ok(r.covered > 2500 && r.disagree <= 0.015 * r.covered + 5, JSON.stringify(r));
      });
    }
    for (const plane of ['xy', 'xz', 'yz']) {
      await check(`2D slice (${plane}): the torus colour is exactly where inShape says inside`, async () => {
        const r = await page.evaluate(plane => {
          __setup({a: 30, b: 10, c: 6, axis: 'x', x: 3, y: -2, z: 1});
          S.parts.push(Object.assign(newPart('t2', 'Ring z', 'torus'), {a: 20, b: 3, c: 9, material: S.materials[1].id, z: 40}));
          view.mode = plane; view.plane = plane; view.zoom = 1;
          const out = [];
          for (const slice of [0, 4, 40]) {
            view.slice = slice; drawViewport();
            const cv = document.getElementById('vp'), ctx = cv.getContext('2d'), {W, H, scale, cx, cy} = vpGeom, dpr = cv.width / W;
            const c1 = hexRgb(matById(S.parts[0].material).color), c2 = hexRgb(matById(S.parts[1].material).color);
            const [uA, vA, wA] = {xy: [0, 1, 2], xz: [0, 2, 1], yz: [1, 2, 0]}[plane];
            let match = 0, miss = 0, inside = 0;
            for (let y = 3; y < H; y += 4) for (let x = 3; x < W; x += 4) {
              const pt = [0, 0, 0]; pt[uA] = (x + 0.5 - cx) / scale; pt[vA] = -(y + 0.5 - cy) / scale; pt[wA] = slice;
              const ci = cellIndexAt(pt[0], pt[1], pt[2]);
              const around = [[-3, 0], [3, 0], [0, -3], [0, 3]].map(([dx, dy]) => { const q = pt.slice(); q[uA] += dx / scale; q[vA] -= dy / scale; return cellIndexAt(q[0], q[1], q[2]); });
              if (around.some(a => a !== ci)) continue;      // on or next to an outline, which the page blends towards white
              const d = ctx.getImageData(Math.round((x + 0.5) * dpr), Math.round((y + 0.5) * dpr), 1, 1).data;
              const near = (a, b) => Math.abs(a[0] - b[0]) + Math.abs(a[1] - b[1]) + Math.abs(a[2] - b[2]) < 60;
              // skip pixels on an outline (they are blended towards white)
              const drawnTorus = near([d[0], d[1], d[2]], c1) || near([d[0], d[1], d[2]], c2);
              if (ci >= 0) { inside++; if (drawnTorus) match++; else miss++; } else if (drawnTorus) miss++;
            }
            out.push({slice, inside, match, miss});
          }
          return out;
        }, plane);
        for (const o of r) {
          assert.ok(o.inside > 40 || o.slice === 40, `slice ${o.slice}: only ${o.inside} pixels inside a torus`);
          assert.ok(o.miss <= 0.03 * Math.max(o.inside, 1) + 40, `slice ${o.slice}: ${o.miss} pixels disagree with inShape (${o.match} agree)`);
        }
        assert.ok(r.some(o => o.inside > 40 && o.match > 0.9 * o.inside), 'most torus pixels are drawn in the torus colour: ' + JSON.stringify(r));
      });
    }
    await check('no page errors', async () => assert.deepStrictEqual(errors, []));
  } finally { await browser.close(); }
  console.log(failed ? `${failed} FAILED` : 'all passed');
  process.exit(failed ? 1 : 0);
})();
