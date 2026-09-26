// 3D volume view: the CPU reference marcher (volumeRayCPU, which the shader mirrors) reads every voxel on a ray.
// Review finding: fixed-length steps capped at 1,024 per ray skipped a thin hot voxel on a long ray. The browser test
// checks the shader against this reference; this one checks the reference against brute force.
// Run: node test/test_volume_view.js
const fs = require('fs'), vm = require('vm'), path = require('path'), assert = require('assert');

const html = fs.readFileSync(path.join(__dirname, '..', 'studio', 'openmc_studio', 'static', 'index.html'), 'utf8');
const el = {addEventListener() {}, insertAdjacentHTML() {}, querySelector: () => el, querySelectorAll: () => [], style: {}, dataset: {},
  classList: {add() {}, remove() {}, toggle() {}}, setAttribute() {}, appendChild() {}, append() {}, add() {}, getContext: () => null};
const sb = {console, URLSearchParams, btoa, atob, TextEncoder, Option: class {}, window: {}, location: {protocol: 'http:', search: ''},
  document: {querySelector: () => el, querySelectorAll: () => [], getElementById: () => el, createElement: () => el, createTextNode: () => el, addEventListener() {}},
  fetch: () => Promise.resolve({ok: false}), ResizeObserver: class { observe() {} disconnect() {} },
  requestAnimationFrame() {}, setTimeout() {}, setInterval() {}};
vm.createContext(sb);
vm.runInContext(html.match(/<script>([\s\S]*?)<\/script>/)[1], sb);
const {volumeRayCPU, volumeRefusal} = sb;

let failed = 0;
const test = (name, fn) => {
  try { fn(); console.log(`  [PASS] ${name}`); } catch (e) { failed++; console.log(`  [FAIL] ${name}\n${e.stack}`); }
};
const map = (dims, lower, upper, fill) => {
  const data = new Uint8Array(dims[0] * dims[1] * dims[2]);
  fill(data);
  return {t: {dims, lower, upper}, V: {data}};
};

test('a thin hot voxel at the start of a long ray is seen (the reproduced case)', () => {
  const {t, V} = map([2048, 1, 1], [0, 0, 0], [2048, 1, 1], d => { d[0] = 255; });
  assert.equal(volumeRayCPU(V, t, [-1, 0.5, 0.5], [1, 0, 0], Infinity, 'mip', 0), 255);
  assert.equal(volumeRayCPU(V, t, [-1, 0.5, 0.5], [1, 0, 0], Infinity, 'iso', 200), 255);
});

test('...and anywhere along it, in either direction', () => {
  for (const at of [1, 777, 1024, 2046, 2047]) {
    const {t, V} = map([2048, 1, 1], [0, 0, 0], [2048, 1, 1], d => { d[at] = 200; });
    assert.equal(volumeRayCPU(V, t, [-1, 0.5, 0.5], [1, 0, 0], Infinity, 'mip', 0), 200, `voxel ${at}, +x`);
    assert.equal(volumeRayCPU(V, t, [2050, 0.5, 0.5], [-1, 0, 0], Infinity, 'mip', 0), 200, `voxel ${at}, -x`);
  }
});

test('every voxel a ray crosses counts, against dense sampling, on random maps and rays', () => {
  let seed = 7;
  const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
  let equal = 0, total = 0;
  for (let m = 0; m < 60; m++) {
    const dims = [0, 1, 2].map(() => 1 + Math.floor(rnd() * 14));
    const lower = [0, 1, 2].map(() => -10 * rnd()), upper = lower.map(l => l + 1 + 20 * rnd());
    const {t, V} = map(dims, lower, upper, d => { for (let i = 0; i < d.length; i++) d[i] = rnd() < 0.15 ? 1 + Math.floor(rnd() * 255) : 0; });
    for (let r = 0; r < 40; r++) {
      const origin = [0, 1, 2].map(k => lower[k] - 5 + (upper[k] - lower[k] + 10) * rnd());
      const target = [0, 1, 2].map(k => lower[k] + (upper[k] - lower[k]) * rnd());
      const dir = target.map((x, k) => x - origin[k]);
      const got = volumeRayCPU(V, t, origin, dir, Infinity, 'mip', 0);
      // brute force: 20,000 points along the ray through the box
      const len = Math.hypot(...dir), rd = dir.map(x => x / len);
      let dense = 0;
      for (let s = 0; s < 60; s += 60 / 20000) {
        const q = origin.map((o, k) => o + rd[k] * s);
        if (q.some((x, k) => x < lower[k] || x >= upper[k])) continue;
        const ijk = q.map((x, k) => Math.floor((x - lower[k]) / (upper[k] - lower[k]) * dims[k]));
        dense = Math.max(dense, V.data[ijk[0] + dims[0] * (ijk[1] + dims[1] * ijk[2])]);
      }
      assert.ok(got >= dense, `map ${m} ray ${r}: marcher ${got} < brute force ${dense}`);
      total++; if (got === dense) equal++;
    }
  }
  // the marcher may also count a voxel a ray only grazes (a corner the samples straddle); that must be rare
  assert.ok(equal / total > 0.98, `${equal}/${total} agree`);
});

test('the cutaway and the depth limit clip the ray exactly', () => {
  const {t, V} = map([10, 1, 1], [0, 0, 0], [10, 1, 1], d => { d[3] = 100; d[7] = 250; });
  const ray = (tmax, cut) => volumeRayCPU(V, t, [-5, 0.5, 0.5], [1, 0, 0], tmax, 'mip', 0, cut);
  assert.equal(ray(Infinity), 250);
  assert.equal(ray(11.9), 100, 'the ray stops before x = 7');
  assert.equal(ray(12.1), 250);
  assert.equal(ray(Infinity, {axis: 0, at: 7, side: -1}), 250, 'the cut removes x < 7; voxel 7 starts on the cut');
  assert.equal(ray(Infinity, {axis: 0, at: 7.001, side: -1}), 250);
  assert.equal(ray(Infinity, {axis: 0, at: 7, side: 1}), 100, 'the cut removes x > 7');
  assert.equal(ray(Infinity, {axis: 0, at: 3.5, side: 1}), 100);
  assert.equal(ray(Infinity, {axis: 0, at: 2.9, side: 1}), 0);
});

test('Surface returns the first voxel at the level, not the brightest', () => {
  const {t, V} = map([10, 1, 1], [0, 0, 0], [10, 1, 1], d => { d[3] = 120; d[7] = 250; });
  assert.equal(volumeRayCPU(V, t, [-5, 0.5, 0.5], [1, 0, 0], Infinity, 'iso', 100), 120);
  assert.equal(volumeRayCPU(V, t, [-5, 0.5, 0.5], [1, 0, 0], Infinity, 'iso', 200), 250);
  assert.equal(volumeRayCPU(V, t, [-5, 0.5, 0.5], [1, 0, 0], Infinity, 'iso', 251), 0);
});

test('maps too big to march exactly are refused with a reason, not drawn with gaps', () => {
  assert.equal(volumeRefusal({dims: [256, 256, 256]}, 2048), '');
  assert.equal(volumeRefusal({dims: [2048, 1, 1]}, 2048), '');
  assert.match(volumeRefusal({dims: [2048, 2048, 2]}, 2048), /too fine to march every voxel/);
  assert.match(volumeRefusal({dims: [300, 10, 10]}, 256), /stop at 256 a side/);
});

if (failed) { console.log(`test_volume_view: ${failed} FAILED`); process.exit(1); }
console.log('test_volume_view: PASS');
