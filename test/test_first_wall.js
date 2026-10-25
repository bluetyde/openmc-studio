// The PLOW first-wall record reader (index.html: parseFirstWallRecord, dShapeParts with a polygon, addFirstWall): what it accepts, what it refuses and why, volumes against the polygon.
// The records are built here (a Miller D at 120 points, as PLOW writes it); set PLOW_SAMPLE_RECORD to a real first-wall-geometry record to read that one too.
// Run: node test/test_first_wall.js
const fs = require('fs'), vm = require('vm'), path = require('path'), assert = require('assert');

const html = fs.readFileSync(path.join(__dirname, '..', 'studio', 'openmc_studio', 'static', 'index.html'), 'utf8');
const el = {addEventListener() {}, insertAdjacentHTML() {}, querySelector: () => el, querySelectorAll: () => [], style: {}, dataset: {},
  classList: {add() {}, remove() {}, toggle() {}}, setAttribute() {}, appendChild() {}, append() {}, add() {}, remove() {}, getContext: () => null, parentElement: {}};
const nodes = {'#propFilter': {...el, value: ''}, '#otCore': {...el, hidden: true}, '#runs': {...el, innerHTML: ''}, '#core': {...el, innerHTML: ''}};
const sb = {console, URLSearchParams, btoa, atob, TextEncoder, escape, unescape, Option: class {}, window: {}, location: {protocol: 'http:', search: ''},
  document: {querySelector: s => nodes[s] || el, querySelectorAll: () => [], getElementById: () => el, createElement: () => el, createTextNode: () => el, addEventListener() {}},
  fetch: () => Promise.resolve({ok: false}), ResizeObserver: class { observe() {} disconnect() {} },
  requestAnimationFrame() {}, setTimeout() {}, setInterval: () => 1, clearInterval() {}};
vm.createContext(sb);
vm.runInContext(html.match(/<script>([\s\S]*?)<\/script>/)[1], sb);

const run = s => vm.runInContext(s, sb);
const J = v => JSON.parse(JSON.stringify(v));
const tests = [];
const test = (name, fn) => tests.push([name, fn]);

// a record as PLOW writes it: Miller D (R0 2.0 m, a 0.6 m, kappa 1.7, delta 0.33) in metres, 120 points, counter-clockwise, first point not repeated
const miller = (n = 120, o = {}) => { sb.__m = [200 * (o.R0 || 1), 60, o.kappa || 1.7, o.delta === undefined ? 0.33 : o.delta, 0, n]; return J(run('dShapeCurve(__m[0], __m[1], __m[2], __m[3], __m[4], __m[5])')).map(p => [p[0] / 100, p[1] / 100]); };
const record = (poly, o = {}) => {
  const n = poly.length, segs = poly.map((a, i) => { const b = poly[(i + 1) % n], len = Math.hypot(b[0] - a[0], b[1] - a[1]); return {index: i, length_m: len, area_m2: 2 * Math.PI * (a[0] + b[0]) / 2 * len}; });
  return Object.assign({schema: 'plow.first-wall-geometry/0.1', name: 'test D', gap_m: 0.03, polygon: poly, orientation: 'counter-clockwise in (R, Z), first point not repeated', segments: segs,
                        total_area_m2: segs.reduce((s, x) => s + x.area_m2, 0)}, o);
};
const parse = rec => { sb.__t = typeof rec === 'string' ? rec : JSON.stringify(rec); return J(run('parseFirstWallRecord(__t)')); };
const parts = (poly, N, layers) => { sb.__s = {polygon: poly, N, layers: layers || [{material: 'p'}]}; return J(run('dShapeParts(__s)')); };
const frusta = ps => ps.reduce((v, p) => v + Math.PI * p.h / 3 * (p.r * p.r + p.r * p.r2 + p.r2 * p.r2), 0);
const plasmaVolume = ps => frusta(ps.filter(p => p.name.startsWith('D plasma'))) - frusta(ps.filter(p => p.name.startsWith('D left 0.')));

run(`globalThis.__vol = (ps, Rmax, zmax, n) => {
  const out = {}, dR = Rmax / n, dz = 2 * zmax / n;
  for (let i = 0; i < n; i++) for (let j = 0; j < n; j++) {
    const R = (i + 0.5) * dR, z = -zmax + (j + 0.5) * dz;
    for (const p of ps) if (inShape(p, R, 0, z)) { out[p.material] = (out[p.material] || 0) + 2 * Math.PI * R * dR * dz; break; }
  }
  return out;
}`);
const full = ps => ps.map((p, i) => Object.assign({id: 'p' + i, rx: 0, ry: 0, rz: 0, axis: 'z', a: 1, b: 1, c: 1, sx: 1, sy: 1, sz: 1}, p));
const raster = (ps, Rmax, zmax, n) => { sb.__ps = full(ps); return J(run(`__vol(__ps, ${Rmax}, ${zmax}, ${n})`)); };

test('a record as PLOW writes it is accepted and read in centimetres, with the numbers it carries', () => {
  const r = parse(record(miller()));
  assert.ok(r.ok, JSON.stringify(r.errors));
  assert.strictEqual(r.polygonCm.length, 120);
  assert.ok(Math.abs(r.polygonCm[0][0] - 260) < 1e-9 && Math.abs(r.polygonCm[0][1]) < 1e-9, 'metres to centimetres: the first point is (2.6 m, 0)');
  assert.strictEqual(r.info.points, 120);
  assert.ok(Math.abs(r.info.areaCheck) < 1e-9 && r.info.areaM2 > 0);
  assert.ok(Math.abs(r.info.rMax - 2.6) < 1e-9 && Math.abs(r.info.rMin - 1.4) < 1e-3);
});
test('the record\'s own total area is checked against the area of revolution of its polygon', () => {
  assert.ok(parse(record(miller(), {total_area_m2: record(miller()).total_area_m2 * 1.004})).ok, 'within 0.5 % passes');
  const bad = parse(record(miller(), {total_area_m2: record(miller()).total_area_m2 * 1.02}));
  assert.ok(!bad.ok && /disagrees with itself/.test(bad.errors[0]), JSON.stringify(bad));
});
test('refusals, each with the unbroken record as its good twin', () => {
  const good = record(miller());
  assert.ok(parse(good).ok);
  const refused = (rec, re, what) => { const r = parse(rec); assert.ok(!r.ok, 'accepted: ' + what); assert.ok(re.test(r.errors[0]), what + ': ' + r.errors[0]); };
  refused('{not json', /not JSON/, 'not JSON');
  refused('[1, 2]', /not a record/, 'an array');
  refused({...good, schema: 'plow.first-wall-geometry/0.2'}, /knows plow\.first-wall-geometry\/0\.1 only/, 'another schema version');
  refused({...good, schema: undefined}, /schema/, 'no schema');
  refused({...good, polygon: undefined}, /no "polygon"/, 'no polygon');
  refused({...good, polygon: good.polygon.slice(0, 5), segments: undefined, total_area_m2: undefined}, /at least 8/, 'five points');
  refused({...good, polygon: good.polygon.map((p, i) => (i === 3 ? [p[0], '0.1'] : p))}, /pair of finite numbers/, 'a string coordinate');
  refused({...good, polygon: good.polygon.map((p, i) => (i === 3 ? [p[0], null] : p))}, /pair of finite numbers/, 'a null coordinate');
  refused({...good, orientation: 'clockwise in (R, Z)'}, /counter-clockwise/, 'orientation clockwise');
  const rev = [...good.polygon].reverse();
  refused({...good, polygon: rev}, /runs clockwise/, 'a clockwise polygon');
  refused({...good, polygon: [...good.polygon, good.polygon[0]], segments: undefined, total_area_m2: undefined}, /repeats the first/, 'the first point repeated');
  refused({...good, polygon: good.polygon.flatMap((p, i) => (i === 7 ? [p, [...p]] : [p])), segments: undefined, total_area_m2: undefined}, /coincide/, 'a doubled point');
  refused({...good, polygon: good.polygon.map(p => [p[0] - 1.45, p[1]]), segments: undefined, total_area_m2: undefined}, /axis/, 'R at or below zero');
  refused({...good, segments: good.segments.slice(1)}, /segments/, 'a segment list of the wrong length');
  // a bow tie: swap two points on opposite sides so that edges cross
  const bow = good.polygon.map(p => [...p]); [bow[10], bow[70]] = [bow[70], bow[10]];
  refused({...good, polygon: bow, segments: undefined, total_area_m2: undefined}, /crosses itself|clockwise/, 'a self-crossing polygon');
});
test('a contour that folds back in height is refused (a C opening upward: four crossings at some heights); a notch on one side is single-valued and accepted', () => {
  const c = [[2, -1], [3, -1], [3, 1], [2.7, 1], [2.7, -0.5], [2.3, -0.5], [2.3, 1], [2, 1]];
  const r = parse({schema: 'plow.first-wall-geometry/0.1', polygon: c});
  assert.ok(!r.ok && /not single-valued in height/.test(r.errors[0]), JSON.stringify(r));
  const notch = [[2, -1], [3, -1], [3, -0.2], [2.4, -0.2], [2.4, 0.2], [3, 0.2], [3, 1], [2, 1]];
  assert.ok(parse({schema: 'plow.first-wall-geometry/0.1', polygon: notch}).ok, 'a notch in the outboard side is fine');
  assert.ok(!parse({schema: 'plow.first-wall-geometry/0.1', polygon: [[2, -1], [3, -1], [3.5, 0], [3, 1], [2, 1], [1.5, 0]]}).ok, 'six points are too few for the reader');
});
test('exact mode on a polygon with a notch and flat edges: the stack has the hand-computed volume (cylinders and a cone of equal radii)', () => {
  const notch = [[200, -100], [300, -100], [300, -20], [240, -20], [240, 20], [300, 20], [300, 100], [200, 100]];
  const ps = parts(notch, 'exact');
  assert.strictEqual(ps.length, 2 * 3, 'three slabs');
  assert.ok(ps.some(p => p.r === p.r2), 'the middle slab is a cylinder');
  const want = Math.PI * (80 * (300 ** 2 - 200 ** 2) + 40 * (240 ** 2 - 200 ** 2) + 80 * (300 ** 2 - 200 ** 2));
  assert.ok(Math.abs(plasmaVolume(ps) / want - 1) < 1e-12, plasmaVolume(ps) / want);
});
test('exact mode: a hexagon with flat top and bottom turns through the closed form 15 pi m3, and so does the cone stack', () => {
  const hexa = [[200, -100], [300, -100], [350, 0], [300, 100], [200, 100], [150, 0]];
  const ps = parts(hexa, 'exact');
  assert.strictEqual(ps.length, 2 * 2, 'two slabs, a right and a left cone each');
  assert.ok(Math.abs(plasmaVolume(ps) / (15 * Math.PI * 1e6) - 1) < 1e-12, plasmaVolume(ps));
});
test('exact mode on a 120-point D: the cone stack is the polygon, to rounding', () => {
  const r = parse(record(miller())), ps = parts(r.polygonCm, 'exact');
  assert.ok(ps.length > 100, ps.length);          // the left and right sides share their heights: about 60 slabs, a right and a left cone each
  assert.ok(Math.abs(plasmaVolume(ps) / (r.info.volumeM3 * 1e6) - 1) < 1e-10, plasmaVolume(ps) / (r.info.volumeM3 * 1e6));
});
test('inscribed mode: the error falls as the slabs grow', () => {
  const r = parse(record(miller())), want = r.info.volumeM3 * 1e6, errs = [12, 24, 48, 96].map(N => Math.abs(plasmaVolume(parts(r.polygonCm, N)) / want - 1));
  assert.ok(errs[1] < 0.01 && errs[3] < 0.002 && errs[3] < errs[1], errs.join(' '));
});
test('wall layers: the mitre offset of a square grows every side by the thickness, and the wall and plasma volumes match the offset polygon (raster, first part wins)', () => {
  sb.__sq = [[100, -100], [300, -100], [300, 100], [100, 100]];
  const o = J(run('offsetPolygon(__sq, 10)'));
  assert.deepStrictEqual(o.map(p => p.map(x => Math.round(x * 1e9) / 1e9)), [[90, -110], [310, -110], [310, 110], [90, 110]]);
  const r = parse(record(miller())), ps = parts(r.polygonCm, 'exact', [{material: 'p'}, {thickness: 20, material: 'w'}]);
  sb.__poly = r.polygonCm;
  const vPlasma = J(run('polygonRevolveVolume(__poly)')), vWall = J(run('polygonRevolveVolume(offsetPolygon(__poly, 20))')) - vPlasma;
  const v = raster(ps, 340, 160, 260);
  assert.ok(Math.abs(v.p / vPlasma - 1) < 0.01, 'plasma ' + v.p / vPlasma);
  assert.ok(Math.abs(v.w / vWall - 1) < 0.02, 'wall ' + v.w / vWall);
});
test('a wall thicker than the contour allows is refused: it closes a notch (the edge folds), or it reaches the axis', () => {
  const notch = [[200, -100], [300, -100], [300, -20], [240, -20], [240, 20], [300, 20], [300, 100], [200, 100]];
  sb.__s = {polygon: notch, N: 'exact', layers: [{material: 'p'}, {thickness: 5, material: 'w'}]};
  assert.ok(J(run('dShapeParts(__s)')).length > 0, 'a thin wall follows the notch');
  sb.__s = {polygon: notch, N: 'exact', layers: [{material: 'p'}, {thickness: 30, material: 'w'}]};
  assert.throws(() => run('dShapeParts(__s)'), /folds over itself/);
  sb.__s = {polygon: parse(record(miller())).polygonCm, N: 24, layers: [{material: 'p'}, {thickness: 400, material: 'w'}]};
  assert.throws(() => run('dShapeParts(__s)'), /reach the axis/);
});
test('addFirstWall writes one group, the wall material is the chosen one, and one undo removes it', () => {
  run("S.parts.length = 0; S.groups = []; S.parts.push(newPart('pold', 'Old', 'sphere')); HISTORY.undo.length = 0; HISTORY.redo.length = 0; HISTORY.current = JSON.stringify(S); HISTORY.boundary = false; HISTORY.last = Date.now();");
  sb.__parsed = parse(record(miller()));
  const res = run("addFirstWall(__parsed, {thickness: 5, material: 'm9', exact: false, N: 24})");
  assert.ok(res);
  assert.strictEqual(run('S.groups.length'), 1);
  assert.strictEqual(run("S.groups[0].name"), 'First wall (PLOW)');
  assert.strictEqual(run('S.parts.length'), 1 + 96);
  assert.deepStrictEqual([...new Set(J(run("S.parts.filter(p => p.name.startsWith('D wall')).map(p => p.material)")))], ['m9']);
  assert.strictEqual(run("S.parts[S.parts.length - 1].id"), 'pold', 'the ring sits on top, the old part stays last');
  run('historyTrack(JSON.stringify(S))');
  run('undo()');
  assert.strictEqual(run('S.parts.length'), 1);
  assert.strictEqual(run('S.groups.length'), 0);
});
test('a record the reader refuses adds nothing to the model', () => {
  run("S.parts.length = 0; S.groups = [];");
  sb.__t = JSON.stringify(record(miller(), {schema: 'something/1'}));
  const r = J(run('parseFirstWallRecord(__t)'));
  assert.ok(!r.ok);
  assert.strictEqual(run('S.parts.length') + run('S.groups.length'), 0);
});
if (process.env.PLOW_SAMPLE_RECORD) {
  test('the real PLOW record (PLOW_SAMPLE_RECORD) is accepted, its area agrees, and the exact stack is its polygon', () => {
    const r = parse(fs.readFileSync(process.env.PLOW_SAMPLE_RECORD, 'utf8'));
    assert.ok(r.ok, JSON.stringify(r.errors));
    assert.ok(Math.abs(r.info.areaCheck) < 0.005);
    const ps = parts(r.polygonCm, 'exact');
    assert.ok(Math.abs(plasmaVolume(ps) / (r.info.volumeM3 * 1e6) - 1) < 1e-10);
    console.log(`     real record: ${r.info.points} points, wall ${r.info.areaM2.toFixed(3)} m2, ${ps.length} cones in exact mode`);
  });
}

let failed = 0;
for (const [name, fn] of tests) {
  try { fn(); console.log('ok   ' + name); } catch (e) { failed++; console.log('FAIL ' + name + '\n     ' + String(e.stack || e).split('\n').slice(0, 4).join('\n     ')); }
}
console.log(failed ? `${failed} FAILED of ${tests.length}` : `${tests.length} passed`);
process.exit(failed ? 1 : 0);
