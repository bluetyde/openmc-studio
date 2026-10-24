// The torus part (index.html): inside test, bounding box, ray spans, tessellation. Run: node test/test_torus_part.js
const fs = require('fs'), vm = require('vm'), path = require('path'), assert = require('assert');

const html = fs.readFileSync(path.join(__dirname, '..', 'studio', 'openmc_studio', 'static', 'index.html'), 'utf8');
const el = {addEventListener() {}, insertAdjacentHTML() {}, querySelector: () => el, querySelectorAll: () => [], style: {}, dataset: {},
  classList: {add() {}, remove() {}, toggle() {}}, setAttribute() {}, appendChild() {}, append() {}, add() {}, remove() {}, getContext: () => null, parentElement: {}};
const nodes = {'#otCore': {...el, hidden: true}, '#runs': {...el, innerHTML: ''}, '#core': {...el, innerHTML: ''}};      // the two elements these tests read back; every other selector is the shared stub
const sb = {console, URLSearchParams, btoa, atob, TextEncoder, escape, unescape, Option: class {}, window: {}, location: {protocol: 'http:', search: ''},
  document: {querySelector: s => nodes[s] || el, querySelectorAll: () => [], getElementById: () => el, createElement: () => el, createTextNode: () => el, addEventListener() {}},
  fetch: () => Promise.resolve({ok: false}), ResizeObserver: class { observe() {} disconnect() {} },
  requestAnimationFrame() {}, setTimeout() {}, setInterval: () => 1, clearInterval() {}};
vm.createContext(sb);
vm.runInContext(html.match(/<script>([\s\S]*?)<\/script>/)[1], sb);

const run = s => vm.runInContext(s, sb);
let failed = 0;
const tests = [];
const test = (name, fn) => tests.push([name, fn]);
const torus = o => Object.assign({id: 'p1', name: 'T', shape: 'torus', x: 0, y: 0, z: 0, a: 10, b: 2, c: 1, axis: 'z', rx: 0, ry: 0, rz: 0, material: 'void'}, o || {});
const J = v => JSON.parse(JSON.stringify(v));
const inShape = (p, x, y, z) => { sb.__p = p; return run(`inShape(__p, ${x}, ${y}, ${z})`); };
const spansOf = (lo, ld, a, b, c) => { sb.__lo = lo; sb.__ld = ld; return J(run(`torusSpans(__lo, __ld, ${a}, ${b}, ${c})`)); };

// small deterministic generator, so a failure is reproducible
let seed = 12345;
const rnd = () => (seed = (seed * 1664525 + 1013904223) % 4294967296) / 4294967296;

test('the inside test follows (sqrt(x^2+y^2) - a)^2/c^2 + z^2/b^2 < 1 with b along the axis', () => {
  const p = torus({a: 10, b: 2, c: 1});
  assert.ok(inShape(p, 10, 0, 0) && inShape(p, 0, -10, 1.9) && !inShape(p, 0, 0, 0));
  assert.ok(!inShape(p, 10, 0, 2.1), 'b = 2 reaches z = 2');
  assert.ok(inShape(p, 10.9, 0, 0) && !inShape(p, 11.1, 0, 0), 'c = 1 reaches 11 across');
  const q = torus({a: 10, b: 1, c: 2});
  assert.ok(!inShape(q, 10, 0, 1.1) && inShape(q, 11.9, 0, 0), 'with b and c swapped the shape is flat and wide');
});
test('the axis option points the torus along x or y', () => {
  const p = torus({axis: 'x', a: 10, b: 2, c: 1});
  assert.ok(inShape(p, 1.9, 10, 0) && !inShape(p, 2.1, 10, 0) && inShape(p, 0, 0, 10) && !inShape(p, 0, 0, 0));
  const q = torus({axis: 'y', a: 10, b: 2, c: 1});
  assert.ok(inShape(q, 0, 1.9, 10) && !inShape(q, 0, 2.1, 10));
});
test('volume by sampling matches 2 pi^2 a b c, and the |z| < h slab sees a swap of b and c', () => {
  const vol = (p, h) => { let n = 0; const N = 400000; for (let i = 0; i < N; i++) { const x = (rnd() * 2 - 1) * 14, y = (rnd() * 2 - 1) * 14, z = (rnd() * 2 - 1) * 3; if (Math.abs(z) < h && inShape(p, x, y, z)) n++; } return n / N * 28 * 28 * 6; };
  const w = 2 * Math.PI ** 2 * 10 * 2 * 1;
  const whole = vol(torus({a: 10, b: 2, c: 1}), 9);
  assert.ok(Math.abs(whole - w) / w < 0.02, `whole ${whole} vs ${w}`);
  const slab = 2 * Math.PI * 10 * 2 * 1 * 2 * (Math.asin(0.75) + 0.75 * Math.sqrt(1 - 0.5625));
  const got = vol(torus({a: 10, b: 2, c: 1}), 1.5), swapped = vol(torus({a: 10, b: 1, c: 2}), 1.5);
  assert.ok(Math.abs(got - slab) / slab < 0.02, `slab ${got} vs ${slab}`);
  assert.ok(Math.abs(swapped - w) / w < 0.02 && Math.abs(swapped - got) / got > 0.1, 'b and c swapped changes the slab volume by 17 %');
});
test('bounding box: a + c across the axis, b along it, and it follows the axis option', () => {
  sb.__p = torus({a: 10, b: 2, c: 1}); assert.deepStrictEqual(J(run('partHalfExtents(__p)')), [11, 11, 2]);
  sb.__p = torus({a: 10, b: 2, c: 1, axis: 'x'}); assert.deepStrictEqual(J(run('partHalfExtents(__p)')), [2, 11, 11]);
});
test('ray spans agree with the inside test on random rays (two spans through the hole)', () => {
  let twoSpans = 0, checked = 0;
  for (let n = 0; n < 3000; n++) {
    const b = 0.5 + rnd() * 3, c = 0.5 + rnd() * 3, a = c + 0.5 + rnd() * 10, p = torus({a, b, c});
    const o = [(rnd() - 0.5) * 40, (rnd() - 0.5) * 40, (rnd() - 0.5) * 40];
    const dv = [rnd() - 0.5, rnd() - 0.5, rnd() - 0.5], L = Math.hypot(...dv), d = dv.map(v => v / L);
    const spans = spansOf(o, d, a, b, c);
    if (spans.length === 2) twoSpans++;
    for (let i = 0; i < 160; i++) {
      const t = -40 + 80 * (i + 0.5) / 160;
      const near = spans.some(s => Math.abs(s.t0 - t) < 0.5 || Math.abs(s.t1 - t) < 0.5);   // a sample next to a span end may fall either way
      if (near) continue;
      const inside = inShape(p, o[0] + t * d[0], o[1] + t * d[1], o[2] + t * d[2]);
      assert.strictEqual(spans.some(s => s.t0 < t && t < s.t1), inside, `ray ${n} t=${t} a=${a} b=${b} c=${c}`);
      checked++;
    }
  }
  assert.ok(twoSpans > 20, 'rays through the hole must produce two spans: ' + twoSpans);
  assert.ok(checked > 100000, 'checked ' + checked);
});
test('span ends sit on the surface and the normals point out', () => {
  const a = 10, b = 2, c = 1;
  const spans = spansOf([-20, 0.3, 0.2], [1, 0, 0], a, b, c);
  assert.strictEqual(spans.length, 2);
  for (const s of spans) {
    for (const [t, n, sign] of [[s.t0, s.n0, -1], [s.t1, s.n1, 1]]) {
      const x = -20 + t, y = 0.3, z = 0.2, q = Math.hypot(x, y) - a;
      assert.ok(Math.abs(q * q / (c * c) + z * z / (b * b) - 1) < 1e-6, 'on the surface');
      assert.ok(Math.abs(Math.hypot(...n) - 1) < 1e-9);
      assert.ok(n[0] * sign > 0, 'outward along the ray axis');
    }
  }
  const top = spansOf([10, 0, 5], [0, 0, -1], a, b, c)[0];
  assert.ok(Math.abs(top.t0 - 3) < 1e-6 && top.n0[2] > 0.999, JSON.stringify(top));
  // the normal is the gradient of (q/c)^2 + (z/b)^2, so its components go as q/c^2 and z/b^2, not q/c and z/b
  const side = spansOf([-20, 0, 0.9], [1, 0, 0], a, b, c)[0];
  const px = side.t0 - 20 + a, want = [px / (c * c), 0.9 / (b * b)], wl = Math.hypot(...want);
  assert.ok(Math.abs(Math.abs(side.n0[0]) - Math.abs(want[0]) / wl) < 1e-6 && Math.abs(side.n0[2] - want[1] / wl) < 1e-6, JSON.stringify(side));
});
test('a ray that misses returns no span', () => {
  assert.deepStrictEqual(spansOf([-20, 30, 0], [1, 0, 0], 10, 2, 1), []);
  assert.deepStrictEqual(spansOf([-20, 0, 5], [1, 0, 0], 10, 2, 1), []);
});
test('tessellation: every vertex is on the surface, and the mesh volume is close to 2 pi^2 a b c', () => {
  sb.__p = torus({a: 10, b: 2, c: 1});
  const tris = J(run('tessellatePart(__p, 48)'));
  let vol = 0;
  for (const t of tris) {
    for (const v of [t.v1, t.v2, t.v3]) { const q = Math.hypot(v[0], v[1]) - 10; assert.ok(Math.abs(q * q + v[2] * v[2] / 4 - 1) < 1e-9, 'on the surface'); }
    vol += (t.v1[0] * (t.v2[1] * t.v3[2] - t.v2[2] * t.v3[1]) - t.v1[1] * (t.v2[0] * t.v3[2] - t.v2[2] * t.v3[0]) + t.v1[2] * (t.v2[0] * t.v3[1] - t.v2[1] * t.v3[0])) / 6;
  }
  const w = 2 * Math.PI ** 2 * 10 * 2;
  assert.ok(vol > 0 && Math.abs(vol - w) / w < 0.02, `mesh volume ${vol} vs ${w}`);
});

const withParts = list => {
  sb.__list = list;
  run("S = sampleModel(); S.groups = []; S.tallies = []; S.parts = __list.map((o, i) => Object.assign(newPart('p' + (i + 1), o.name || 'Ring', 'torus'), {material: S.materials[0].id}, o));");
};
const script = () => run('generate([])');
const problemsNow = () => J(run("problems().filter(p => p.sev !== 'info')"));

test('export: ZTorus(a, b, c) with b along the axis, XTorus and YTorus for the other axes, and the region is the inside', () => {
  withParts([{a: 10, b: 2, c: 1}, {name: 'Ring X', a: 20, b: 3, c: 4, axis: 'x', x: 5}, {name: 'Ring Y', a: 20, b: 3, c: 4, axis: 'y', z: -2}]);
  const py = script();
  assert.ok(/torus_a10 = openmc\.ZTorus\(x0=0\.0, y0=0\.0, z0=0\.0, a=10\.0, b=2\.0, c=1\.0\)/.test(py), py);
  assert.ok(/openmc\.XTorus\(x0=5\.0, y0=0\.0, z0=0\.0, a=20\.0, b=3\.0, c=4\.0\)/.test(py));
  assert.ok(/openmc\.YTorus\(x0=0\.0, y0=0\.0, z0=-2\.0, a=20\.0, b=3\.0, c=4\.0\)/.test(py));
  assert.ok(/shape_ring = -torus_a10\n/.test(py), 'inside = negative side');
  assert.deepStrictEqual(problemsNow(), []);
});
test('export: swapping b and c changes the written torus (the orientation guard)', () => {
  withParts([{a: 10, b: 1, c: 2}]);
  assert.ok(/a=10\.0, b=1\.0, c=2\.0\)/.test(script()));
});
test('a 90 degree turn moves the axis; a tilted torus and a ring that closes on itself are Problems errors', () => {
  withParts([{a: 10, b: 2, c: 1, rx: 90}]);
  assert.ok(/openmc\.YTorus\(/.test(script()), 'z axis turned 90 degrees about x lies along y');
  assert.deepStrictEqual(problemsNow(), []);
  withParts([{a: 10, b: 2, c: 1, rx: 30}]);
  let p = problemsNow();
  assert.strictEqual(p.length, 1); assert.strictEqual(p[0].sev, 'error'); assert.ok(/only point along x, y or z/.test(p[0].text), p[0].text);
  withParts([{a: 1, b: 2, c: 1}]);
  p = problemsNow(); assert.strictEqual(p.length, 1); assert.ok(/must be smaller than the major radius/.test(p[0].text), p[0].text);
  withParts([{a: 10, b: 0, c: 1}]);
  p = problemsNow(); assert.ok(p.some(q => q.sev === 'error' && /sizes must be above 0/.test(q.text)));
});
test('the explorer line and the 2D slice see the torus', () => {
  withParts([{a: 10, b: 2, c: 1}]);
  assert.ok(run('shapeMeta(S.parts[0])').includes('R 10') && run('shapeMeta(S.parts[0])').includes('b 2') && run('shapeMeta(S.parts[0])').includes('c 1'));
  assert.strictEqual(run('cellIndexAt(10, 0, 0)'), 0);
  assert.strictEqual(run('cellIndexAt(0, 0, 0)'), -1);
  assert.strictEqual(run('cellIndexAt(10, 0, 2.5)'), -1);
});

(async () => {
  for (const [name, fn] of tests) {
    try { await fn(); console.log('PASS', name); } catch (e) { failed++; console.log('FAIL', name, '\n  ', String(e.stack || e).split('\n').slice(0, 4).join('\n   ')); }
  }
  console.log(`${tests.length - failed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})();
