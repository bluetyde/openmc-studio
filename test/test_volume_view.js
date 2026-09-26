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

// Cylindrical maps: (r, phi, z) bins about an origin, r fastest in the data (as results.py lays them out).
const cylMap = (g, fill) => {
  const lin = (a, b, n) => Array.from({length: n + 1}, (_, i) => a + (b - a) * i / n);
  const t = {mesh_type: 'cylindrical', dims: [g.nr, g.np, g.nz], origin: g.o, r_grid: lin(g.r0, g.r1, g.nr),
    phi_grid: lin(g.p0, g.p1, g.np), z_grid: lin(g.z0, g.z1, g.nz)};
  const data = new Uint8Array(g.nr * g.np * g.nz);
  fill(data);
  return {t, V: {data}};
};
// the byte at a point by brute force (0 outside the map)
function cylAt(t, V, q) {
  const [nr, np, nz] = t.dims, o = t.origin, r = Math.hypot(q[0] - o[0], q[1] - o[1]);
  let phi = Math.atan2(q[1] - o[1], q[0] - o[0]); if (phi < 0) phi += 2 * Math.PI;
  const r0 = t.r_grid[0], r1 = t.r_grid[nr], p0 = t.phi_grid[0], p1 = t.phi_grid[np], z0 = t.z_grid[0], z1 = t.z_grid[nz];
  let rel = phi - p0; rel -= 2 * Math.PI * Math.floor(rel / (2 * Math.PI));
  if (r < r0 || r >= r1 || rel >= p1 - p0 || q[2] < z0 || q[2] >= z1) return 0;
  const i = Math.floor((r - r0) / (r1 - r0) * nr), j = Math.floor(rel / (p1 - p0) * np), k = Math.floor((q[2] - z0) / (z1 - z0) * nz);
  return V.data[i + nr * (j + np * k)];
}

test('cylindrical maps: every cell a ray crosses counts, against dense sampling (holes, part turns, off-axis origins)', () => {
  let seed = 11;
  const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
  let equal = 0, total = 0;
  for (let m = 0; m < 60; m++) {
    const full = rnd() < 0.5, p0 = full ? 0 : rnd() * Math.PI, p1 = full ? 2 * Math.PI : p0 + (0.3 + rnd() * 1.6) * Math.PI;
    const r0 = rnd() < 0.4 ? 0 : rnd() * 4, g = {o: [rnd() * 6 - 3, rnd() * 6 - 3, rnd() * 4 - 2], r0, r1: r0 + 3 + rnd() * 10,
      p0, p1, z0: -5 - rnd() * 5, z1: 2 + rnd() * 8, nr: 1 + Math.floor(rnd() * 8), np: 1 + Math.floor(rnd() * 12), nz: 1 + Math.floor(rnd() * 6)};
    const {t, V} = cylMap(g, d => { for (let i = 0; i < d.length; i++) d[i] = rnd() < 0.2 ? 1 + Math.floor(rnd() * 255) : 0; });
    for (let r = 0; r < 40; r++) {
      const origin = [g.o[0] + (rnd() - 0.5) * 60, g.o[1] + (rnd() - 0.5) * 60, (rnd() - 0.5) * 40];
      const ang = rnd() * 2 * Math.PI, rad = rnd() * g.r1;
      const target = [g.o[0] + rad * Math.cos(ang), g.o[1] + rad * Math.sin(ang), g.z0 + (g.z1 - g.z0) * rnd()];
      const dir = target.map((x, k) => x - origin[k]);
      const got = volumeRayCPU(V, t, origin, dir, Infinity, 'mip', 0);
      const len = Math.hypot(...dir), rd = dir.map(x => x / len);
      let dense = 0;
      for (let s = 0; s < 120; s += 120 / 40000) dense = Math.max(dense, cylAt(t, V, origin.map((o, k) => o + rd[k] * s)));
      assert.ok(got >= dense, `map ${m} ray ${r}: marcher ${got} < brute force ${dense}`);
      total++; if (got === dense) equal++;
    }
  }
  assert.ok(equal / total > 0.98, `${equal}/${total} agree`);
});

test('cylindrical maps: a thin hot ring, and the hole inside the smallest radius, are right', () => {
  // 200 rings 0.05 cm thick from r = 10 to 20; only ring 137 is hot. A ray along x through the axis crosses it twice.
  const g = {o: [0, 0, 0], r0: 10, r1: 20, p0: 0, p1: 2 * Math.PI, z0: -1, z1: 1, nr: 200, np: 1, nz: 1};
  const {t, V} = cylMap(g, d => { d[137] = 250; });
  assert.equal(volumeRayCPU(V, t, [-30, 0, 0], [1, 0, 0], Infinity, 'mip', 0), 250);
  assert.equal(volumeRayCPU(V, t, [-30, 0.3, 0.2], [1, 0.001, 0], Infinity, 'mip', 0), 250);
  // a stretch of ray that stays inside the hole (r < 10) sees nothing; carried on, it crosses the ring
  assert.equal(volumeRayCPU(V, t, [-9, -3, 0], [0, 1, 0], 6, 'mip', 0), 0);
  assert.equal(volumeRayCPU(V, t, [-9, -3, 0], [0, 1, 0], Infinity, 'mip', 0), 250);
  // a quarter-turn map: a ray through the missing three quarters sees nothing
  const q = cylMap({...g, p1: Math.PI / 2, np: 4}, d => d.fill(90));
  assert.equal(volumeRayCPU(q.V, q.t, [-30, -15, 0], [1, 0, 0], Infinity, 'mip', 0), 0);
  assert.equal(volumeRayCPU(q.V, q.t, [-30, 15, 0], [1, 0, 0], Infinity, 'mip', 0), 90);
});

test('glow: nothing gives nothing; brighter and longer paths glow more; a strong front voxel dims what is behind', () => {
  const {t, V} = map([10, 1, 1], [0, 0, 0], [10, 1, 1], d => { d[2] = 120; d[7] = 255; });
  const ray = (gain, tmax = Infinity) => volumeRayCPU(V, t, [-5, 0.5, 0.5], [1, 0, 0], tmax, 'glow', gain);
  const empty = map([4, 1, 1], [0, 0, 0], [4, 1, 1], () => {});
  assert.deepEqual(volumeRayCPU(empty.V, empty.t, [-5, 0.5, 0.5], [1, 0, 0], Infinity, 'glow', 30), [0, 0, 0, 0]);
  const weak = ray(10), strong = ray(60);
  assert.ok(strong[3] > weak[3] && weak[3] > 0, `${weak[3]} < ${strong[3]}`);
  assert.ok(ray(30, 8)[3] < ray(30)[3] + 1e-12 && ray(30, 6.5)[3] < ray(30, 12.5)[3], 'more of the ray, more glow');
  strong.slice(0, 3).forEach(c => assert.ok(c >= 0 && c <= strong[3] + 1e-9, 'premultiplied'));
  // alone, the back voxel is yellow (top of the ramp); behind a thick opaque front voxel it barely shows
  const front = map([2, 1, 1], [0, 0, 0], [20, 1, 1], d => { d[0] = 255; d[1] = 1; });
  const back = map([2, 1, 1], [0, 0, 0], [20, 1, 1], d => { d[1] = 255; });
  const f = volumeRayCPU(front.V, front.t, [-5, 0.5, 0.5], [1, 0, 0], Infinity, 'glow', 100);
  assert.ok(f[3] > 0.99, `opaque ${f[3]}`);
  const b = volumeRayCPU(back.V, back.t, [-5, 0.5, 0.5], [1, 0, 0], Infinity, 'glow', 100);
  assert.ok(b[3] > 0.99);
});

test('cylindrical maps are refused only when a ray could cross too many boundaries', () => {
  assert.equal(volumeRefusal({mesh_type: 'cylindrical', dims: [100, 64, 100]}, 2048), '');
  assert.match(volumeRefusal({mesh_type: 'cylindrical', dims: [2000, 10, 100]}, 2048), /too fine/);
});

if (failed) { console.log(`test_volume_view: ${failed} FAILED`); process.exit(1); }
console.log('test_volume_view: PASS');
