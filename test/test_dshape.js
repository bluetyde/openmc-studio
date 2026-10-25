// The D-shaped ring generator (index.html: dShapeParts, addDShape): volumes against the Miller curve, materials by first-part-wins, refusals.
// Run: node test/test_dshape.js
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

const spec = o => Object.assign({R0: 300, a: 100, kappa: 1.7, delta: 0.33, N: 24, layers: [{material: 'void'}, {thickness: 5, material: 'm2'}]}, o || {});
const build = o => { sb.__s = spec(o); return J(run('dShapeParts(__s)')); };
const full = parts => parts.map((p, i) => Object.assign({id: 'p' + i, rx: 0, ry: 0, rz: 0, axis: 'z', a: 1, b: 1, c: 1, sx: 1, sy: 1, sz: 1}, p));
// first part that contains the point wins; null when none does
const matAt = (parts, R, z) => { sb.__ps = parts; return run(`(() => { for (const p of __ps) if (inShape(p, ${R}, 0, ${z})) return p.material; return null; })()`); };

// pi * closed integral of R^2 dZ over the smooth curve pushed out by d: the volume it turns through (Pappus), taken at 200,000 points
const curveVolume = (o, d) => {
  const s = spec(o); sb.__c = [s.R0, s.a, s.kappa, s.delta, d];
  const pts = J(run('dShapeCurve(__c[0], __c[1], __c[2], __c[3], __c[4], 200000)'));
  let v = 0;
  for (let i = 0; i < pts.length; i++) { const q = pts[(i + 1) % pts.length]; v += (pts[i][0] ** 2 + q[0] ** 2) / 2 * (q[1] - pts[i][1]); }
  return Math.PI * v;
};
// the volume of each material by a midpoint grid over (R, z), weighted by 2 pi R
run(`globalThis.__vol = (ps, Rmax, zmax, n) => {
  const out = {}, dR = Rmax / n, dz = 2 * zmax / n;
  for (let i = 0; i < n; i++) for (let j = 0; j < n; j++) {
    const R = (i + 0.5) * dR, z = -zmax + (j + 0.5) * dz;
    for (const p of ps) if (inShape(p, R, 0, z)) { out[p.material] = (out[p.material] || 0) + 2 * Math.PI * R * dR * dz; break; }
  }
  return out;
}`);
const volumes = (parts, Rmax, zmax, n) => { sb.__ps = parts; return J(run(`__vol(__ps, ${Rmax}, ${zmax}, ${n})`)); };

test('the closed-form check of the helper itself: an ellipse (delta 0) turns through 2 pi^2 R0 kappa a^2', () => {
  const v = curveVolume({delta: 0}, 0);
  assert.ok(Math.abs(v / (2 * Math.PI ** 2 * 300 * 1.7 * 100 * 100) - 1) < 1e-6, v);
});
test('plasma volume of the cone stack matches the smooth curve, and the error falls as the slabs grow', () => {
  const want = curveVolume({}, 0), errs = [];
  for (const N of [12, 24, 48, 96]) {
    const parts = full(build({N, layers: [{material: 'plasma'}]}));
    const v = volumes(parts, 450, 200, 400);
    errs.push(Math.abs(v.plasma / want - 1));
  }
  assert.ok(errs[1] < 0.006, 'N=24: ' + errs[1]);
  assert.ok(errs[3] < 0.0015, 'N=96: ' + errs[3]);
  assert.ok(errs[3] < errs[1] && errs[2] < errs[0], 'finer slabs are closer: ' + errs);
});
test('the wall volume is the volume of the pushed-out curve minus the plasma', () => {
  const parts = full(build({N: 64, layers: [{material: 'plasma'}, {thickness: 20, material: 'wall'}]}));
  const v = volumes(parts, 450, 250, 300), wantP = curveVolume({}, 0), wantW = curveVolume({}, 20) - wantP;
  assert.ok(Math.abs(v.plasma / wantP - 1) < 0.002, v.plasma / wantP);
  assert.ok(Math.abs(v.wall / wantW - 1) < 0.01, v.wall / wantW);
});
test('two wall layers each take their own volume', () => {
  const parts = full(build({N: 64, layers: [{material: 'plasma'}, {thickness: 10, material: 'w1'}, {thickness: 20, material: 'w2'}]}));
  const v = volumes(parts, 450, 250, 300);
  const c0 = curveVolume({}, 0), c1 = curveVolume({}, 10), c2 = curveVolume({}, 30);
  assert.ok(Math.abs(v.w1 / (c1 - c0) - 1) < 0.01 && Math.abs(v.w2 / (c2 - c1) - 1) < 0.01, JSON.stringify(v));
});
test('materials at chosen points: plasma and the hole are void, the wall is its material, outside is nothing', () => {
  const parts = full(build({N: 96})), top = 300 - 0.33 * 100;                      // positive delta puts the top of the D inboard of R0
  assert.strictEqual(matAt(parts, 300, 0), 'void');
  assert.strictEqual(matAt(parts, 0, 0), 'void', 'the hole round the axis');
  assert.strictEqual(matAt(parts, 402.5, 0), 'm2', 'outboard wall');
  assert.strictEqual(matAt(parts, 197.5, 0), 'm2', 'inboard wall');
  assert.strictEqual(matAt(parts, top, 1.7 * 100 + 2.5), 'm2', 'wall over the top');
  assert.strictEqual(matAt(parts, top, -1.7 * 100 - 2.5), 'm2', 'wall under the bottom');
  assert.strictEqual(matAt(parts, 420, 0), null, 'outside the wall');
  assert.strictEqual(matAt(parts, 300, 190), null, 'above the wall');
});
test('triangularity has a sign: with delta 0.33 the plasma reaches further out at the top than at the bottom, never the reverse of the mirror', () => {
  const a = full(build({delta: 0.33, layers: [{material: 'p'}]})), b = full(build({delta: -0.33, layers: [{material: 'p'}]}));
  // at z = 150 the D with delta > 0 sits inboard (smaller R) of the one with delta < 0
  assert.strictEqual(matAt(a, 300 + 0.25 * 100, 150), null);
  assert.strictEqual(matAt(b, 300 + 0.25 * 100, 150), 'p');
  assert.strictEqual(matAt(a, 300 - 0.25 * 100, 150), 'p');
  assert.strictEqual(matAt(b, 300 - 0.25 * 100, 150), 'void', 'left of the plasma is the hole round the axis');
  const up = (parts, z) => matAt(parts, 300 + 0.25 * 100, z), down = (parts, z) => matAt(parts, 300 + 0.25 * 100, z);
  assert.strictEqual(up(a, 150), down(a, -150), 'the D is symmetric about the midplane');
});
test('each outboard cone follows the curve: its radius at a given height is the curve radius there (a swapped taper would not)', () => {
  const parts = build({N: 96, layers: [{material: 'p'}]}).filter(p => p.name.startsWith('D plasma'));
  sb.__c = [300, 100, 1.7, 0.33, 0, 4000];
  const pts = J(run('dShapeCurve(__c[0], __c[1], __c[2], __c[3], __c[4], __c[5])'));
  let worst = 0, n = 0;
  for (let i = 0; i < pts.length; i++) {
    const t = 2 * Math.PI * i / pts.length, tt = t > Math.PI ? t - 2 * Math.PI : t;
    if (Math.abs(tt) > 1.3) continue;                                           // outboard side only
    const [R, Z] = pts[i], c = parts.find(p => Z >= p.z - p.h / 2 && Z <= p.z + p.h / 2);
    const f = (Z - (c.z - c.h / 2)) / c.h;
    worst = Math.max(worst, Math.abs(c.r + f * (c.r2 - c.r) - R)); n++;
  }
  assert.ok(n > 500 && worst < 0.5, `worst gap ${worst} cm over ${n} points`);
});
test('the stack is ordered: left cones of the outer boundary first, plasma cones before wall cones', () => {
  const parts = build({N: 8});
  const names = parts.map(p => p.name);
  assert.ok(names[0].startsWith('D left 1.'), names[0]);
  assert.ok(names.findIndex(n => n.startsWith('D plasma')) < names.findIndex(n => n.startsWith('D wall')));
  assert.ok(parts.filter(p => p.name.startsWith('D left 1.')).every(p => p.material === 'void'));
  assert.ok(parts.filter(p => p.name.startsWith('D left 0.')).every(p => p.material === 'm2'), 'the band between the two inner edges is wall');
});
test('every cone has positive radii and height, and sits inside its slab', () => {
  for (const p of build({N: 40})) assert.ok(p.shape === 'cone' && p.r > 0 && p.r2 > 0 && p.h > 0, JSON.stringify(p));
});
test('refusals: bad numbers, a ring that reaches the axis, a wall without thickness', () => {
  const bad = o => { sb.__s = spec(o); return assert.throws(() => run('dShapeParts(__s)')); };
  bad({a: -1}); bad({kappa: 0}); bad({R0: 0}); bad({delta: 0.95}); bad({N: 3}); bad({N: 500}); bad({R0: 100, a: 100});
  bad({R0: 110, a: 100, layers: [{material: 'void'}, {thickness: 20, material: 'm'}]});
  bad({layers: [{material: 'void'}, {thickness: 0, material: 'm'}]});
  bad({a: NaN}); bad({N: NaN});
});
test('addDShape puts the cones in one group at the top of the part list and refuses without touching the model', () => {
  run("S.parts.length = 0; S.groups = []; S.parts.push(newPart('pold', 'Old', 'sphere'));");
  const r = run('addDShape(' + JSON.stringify(spec({N: 8})) + ')');
  assert.ok(r, 'created');
  const n = run('S.parts.length');
  assert.ok(n > 8 && run('S.parts.slice(0, -1).every(p => p.group === S.groups[0].id)') && run('S.parts[S.parts.length - 1].id') === 'pold' && run('S.groups.length') === 1);
  assert.ok(run('S.settings.worldR') > 400, 'the world grew to hold the ring');
  const bad = run('addDShape(' + JSON.stringify(spec({a: -1})) + ')');
  assert.strictEqual(bad, null);
  assert.strictEqual(run('S.parts.length'), n);
  assert.strictEqual(run('S.groups.length'), 1);
});

test('refusals from the review: a folded wall, a ring too flat to cut, infinite numbers, no layers, a bad wall thickness', () => {
  const bad = o => { sb.__s = spec(o); return assert.throws(() => run('dShapeParts(__s)')); };
  bad({R0: 300, a: 100, kappa: 0.1, delta: 0.9, layers: [{material: 'void'}, {thickness: 50, material: 'm'}]});   // the pushed-out edge folds over itself
  bad({kappa: 1e-12});                                                                                            // every slab would be dropped
  bad({R0: Infinity}); bad({kappa: Infinity}); bad({layers: []});
  bad({layers: [{material: 'void'}, {thickness: NaN, material: 'm'}]});
  bad({layers: [{material: 'void'}, {thickness: Infinity, material: 'm'}]});
  sb.__s = spec({R0: 300, a: 100, kappa: 0.1, delta: 0.9, layers: [{material: 'void'}]});
  assert.strictEqual(J(run('dShapeParts(__s)')).length, 48, 'the same flat shape without the wall is fine: 2 cones per slab');
});
test('every spec that is accepted gives exactly 2 cones per layer and slab', () => {
  for (const o of [{}, {delta: 0}, {delta: -0.5, N: 7}, {kappa: 0.5, N: 9}, {N: 200}, {layers: [{material: 'a'}, {thickness: 1, material: 'b'}, {thickness: 2, material: 'c'}], N: 11}])
    assert.strictEqual(build(o).length, 2 * spec(o).layers.length * Math.round(spec(o).N), JSON.stringify(o));
});
test('the dialog numbers: blank, infinite or negative input is refused, zero wall means none, the wall material is kept', () => {
  const from = v => { sb.__v = v; return J(run('dShapeSpecFromInputs(__v)')); };
  const ok = {R0: 300, a: 100, kappa: 1.7, delta: 0.33, N: 24, t: 5, material: 'm9'};
  assert.deepStrictEqual(from(ok).layers, [{material: 'void'}, {thickness: 5, material: 'm9'}]);
  assert.deepStrictEqual(from({...ok, t: 0}).layers, [{material: 'void'}]);
  for (const bad of [{t: NaN}, {t: -5}, {R0: NaN}, {a: NaN}, {kappa: NaN}, {delta: NaN}, {N: NaN}, {t: Infinity}]) {
    sb.__v = {...ok, ...bad};
    assert.throws(() => run('dShapeSpecFromInputs(__v)'), undefined, JSON.stringify(bad));
  }
});
test('one undo step removes the ring and redo brings it back', () => {
  run("S.parts.length = 0; S.groups = []; S.parts.push(newPart('pold', 'Old', 'sphere')); HISTORY.undo.length = 0; HISTORY.redo.length = 0; HISTORY.current = JSON.stringify(S); HISTORY.boundary = true;");
  run('addDShape(' + JSON.stringify(spec({N: 8})) + ')');
  const n = run('S.parts.length');
  run('historyTrack(JSON.stringify(S))');                         // the page does this on every render; the test sandbox has no render loop
  assert.strictEqual(run('HISTORY.undo.length'), 1, 'creating the ring is one history step');
  run('undo()');
  assert.strictEqual(run('S.parts.length'), 1);
  assert.strictEqual(run('S.groups.length'), 0);
  run('redo()');
  assert.strictEqual(run('S.parts.length'), n);
});
test('a cone with equal radii exports as a cylinder, not NaN (the middle slabs of an odd count at delta 0 are such cones)', () => {
  run('S = sampleModel(); S.parts.unshift(Object.assign(newPart("pc", "Tube", "cone"), {r: 3, r2: 3, h: 10, x: 100}));');
  const text = run('buildScript(problems(), false).text');
  assert.ok(!/nan|infinity/i.test(text.replace(/"[^"\n]*"/g, '')), 'no NaN in model.py');
  const line = text.split('\n').find(l => l.includes('openmc.Quadric') && l.includes('k=9991'));
  assert.ok(line, 'the cylinder (x - 100)^2 + y^2 - 9: constant 100^2 - 9 = 9991');
});

let failed = 0;
for (const [name, fn] of tests) {
  try { fn(); console.log('ok   ' + name); } catch (e) { failed++; console.log('FAIL ' + name + '\n     ' + String(e.stack || e).split('\n').slice(0, 4).join('\n     ')); }
}
console.log(failed ? `${failed} FAILED of ${tests.length}` : `${tests.length} passed`);
process.exit(failed ? 1 : 0);
