// The PLOW fusion-source record reader and the ring source (index.html: parseFusionSourceRecord, fusionSourcesOf, addFusionSource, space 'ring'): what it accepts, what it refuses and why,
// what model.py says, how the model reacts. The records are built in fusion_records.js; set PLOW_SAMPLE_FUSION_SOURCE to a real record to read that one too.
// Run: node test/test_fusion_source.js
const fs = require('fs'), vm = require('vm'), path = require('path'), assert = require('assert');
const {fusionRecord} = require('./fusion_records.js');

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
const parse = rec => { sb.__t = typeof rec === 'string' ? rec : JSON.stringify(rec); return J(run('parseFusionSourceRecord(__t)')); };
const sources = parsed => { sb.__p = parsed; return J(run('fusionSourcesOf(__p)')); };
const sigmaOf = s => Math.sqrt(2 * s.muir_e0 * 1e6 * s.muir_kt / s.muir_mrat) / 1e6;     // OpenMC's muir(): sigma = sqrt(2 e0 kt / m_rat)

test('a record as PLOW writes it is accepted: cells in centimetres, shares add to 1, the numbers it carries', () => {
  const rec = fusionRecord(), r = parse(rec);
  assert.ok(r.ok, JSON.stringify(r.errors));
  assert.strictEqual(r.cells.length, 320);
  assert.ok(Math.abs(r.cells.reduce((s, c) => s + c.share, 0) - 1) < 1e-12);
  assert.ok(Math.abs(r.cells[5].rCm - rec.cells[5].r_m * 100) < 1e-9 && Math.abs(r.cells[5].zCm - rec.cells[5].z_m * 100) < 1e-9, 'metres to centimetres');
  assert.strictEqual(r.totalRate, 4.0e19);
  assert.ok(Math.abs(r.info.powerCheck) < 1e-12);
});
test('one ring source per cell: radius, height, share, isotropic, and the Muir width is the record\'s sigma', () => {
  const rec = fusionRecord(), r = parse(rec), ss = sources(r);
  assert.strictEqual(ss.length, 320);
  ss.forEach((s, i) => {
    assert.strictEqual(s.space, 'ring');
    assert.ok(Math.abs(s.r - rec.cells[i].r_m * 100) < 1e-6 && Math.abs(s.z - rec.cells[i].z_m * 100) < 1e-6 && s.x === 0 && s.y === 0);
    assert.ok(Math.abs(s.strength - rec.cells[i].rate_n_s / rec.total_rate_n_per_s) < 1e-12);
    assert.strictEqual(s.angle, 'isotropic');
    assert.ok(Math.abs(s.muir_e0 - 14.071) < 1e-12);
    assert.ok(Math.abs(sigmaOf(s) / rec.cells[i].energy_std_mev - 1) < 1e-12, 'cell ' + i + ': ' + sigmaOf(s) + ' against ' + rec.cells[i].energy_std_mev);
  });
});
test('a cell with a rate of zero is left out and counted; the others keep their shares', () => {
  const rec = fusionRecord(); rec.cells[3].rate_n_s = 0;
  rec.total_rate_n_per_s = rec.cells.reduce((s, c) => s + c.rate_n_s, 0); rec.power_neutron_mw = rec.total_rate_n_per_s * 14.071 * 1.602176634e-13 * 1e-6;
  const r = parse(rec);
  assert.ok(r.ok && r.cells.length === 319 && r.info.zeroCells === 1);
  assert.ok(Math.abs(r.cells.reduce((s, c) => s + c.share, 0) - 1) < 1e-12);
});
test('refusals, each with the unbroken record as its good twin', () => {
  assert.ok(parse(fusionRecord()).ok);
  const refused = (mut, re, what) => { const rec = fusionRecord(); mut(rec); const r = parse(rec); assert.ok(!r.ok, 'accepted: ' + what); assert.ok(re.test(r.errors[0]), what + ': ' + r.errors[0]); };
  let r = parse('{nope'); assert.ok(!r.ok && /not JSON/.test(r.errors[0]));
  r = parse('[1]'); assert.ok(!r.ok && /not a record/.test(r.errors[0]));
  refused(x => { x.schema = 'plow.fusion-source/0.2'; }, /knows plow\.fusion-source\/0\.1 only/, 'another schema');
  refused(x => { delete x.schema; }, /schema/, 'no schema');
  refused(x => { x.reaction = 'D-D'; }, /D-T neutrons only/, 'D-D');
  refused(x => { delete x.neutron; }, /energy_mean_mev/, 'no neutron block');
  refused(x => { x.neutron.energy_mean_mev = 0; }, /energy_mean_mev/, 'mean energy zero');
  refused(x => { x.neutron.energy_mean_mev = 40; }, /energy_mean_mev/, 'mean energy 40 MeV');
  refused(x => { x.neutron.energy_mean_mev = '14.07'; }, /energy_mean_mev/, 'a string energy');
  refused(x => { x.neutron.direction = 'beam'; }, /isotropic emission only/, 'a beam');
  refused(x => { x.neutron.spread = 'uniform'; }, /Gaussian only/, 'a uniform spread');
  refused(x => { delete x.total_rate_n_per_s; }, /total_rate_n_per_s/, 'no total');
  refused(x => { x.total_rate_n_per_s = -1; }, /total_rate_n_per_s/, 'negative total');
  refused(x => { delete x.cells; }, /no "cells"/, 'no cells');
  refused(x => { x.cells = []; }, /no "cells"/, 'empty cells');
  refused(x => { x.cells = Array.from({length: 5001}, () => ({...x.cells[0]})); }, /at most 5000/, 'too many cells');
  refused(x => { x.cells[7].r_m = '1.9'; }, /Cell 7 needs numbers/, 'a string radius');
  refused(x => { x.cells[7].z_m = null; }, /Cell 7 needs numbers/, 'a null height');
  refused(x => { x.cells[7].rate_n_s = NaN; x.cells[7].rate_n_s = undefined; }, /Cell 7 needs numbers/, 'a missing rate');
  refused(x => { x.cells[9].r_m = 0; }, /Cell 9 has r_m at or below zero/, 'a radius of zero');
  refused(x => { x.cells[9].r_m = -2; }, /Cell 9 has r_m at or below zero/, 'a negative radius');
  refused(x => { x.cells[9].rate_n_s = -1; }, /negative rate/, 'a negative rate');
  refused(x => { x.cells[9].energy_std_mev = 0; }, /energy_std_mev at or below zero/, 'a width of zero');
  refused(x => { x.cells.forEach(c => { c.rate_n_s = 0; }); }, /rate of zero/, 'every rate zero');
  refused(x => { x.total_rate_n_per_s *= 1.01; x.power_neutron_mw *= 1.01; }, /disagrees with itself/, 'cell rates 1 % off the total');
  refused(x => { x.power_neutron_mw *= 1.05; }, /neutron power is/, 'power 5 % off');
  refused(x => { x.power_neutron_mw = -3; }, /power_neutron_mw/, 'negative power');
  const near = fusionRecord(); near.total_rate_n_per_s *= 1.0005; near.power_neutron_mw *= 1.0005;
  assert.ok(parse(near).ok, 'within 0.1 % of the total passes');
});
test('model.py: one ring per cell, the Discrete radius, the Muir line, relative strengths normalised, and the comment with the total rate', () => {
  run('S = sampleModel();');
  sb.__p = parse(fusionRecord());
  run('addFusionSource(__p, {replace: true})');
  const text = run('buildScript(problems(), false).text');
  assert.strictEqual((text.match(/openmc\.stats\.CylindricalIndependent\(/g) || []).length, 320);
  assert.ok(/r=openmc\.stats\.Discrete\(\[[0-9.]+\], \[1\.0\]\),  # a ring: zero thickness/.test(text));
  assert.ok(/z=openmc\.stats\.Discrete\(\[0\.0\], \[1\.0\]\)/.test(text));
  assert.strictEqual((text.match(/\.energy = openmc\.stats\.muir\(/g) || []).length, 320);
  assert.ok(/_total_strength = sum\(s\.strength for s in settings\.source\)/.test(text), 'strengths are normalised');
  assert.ok(/# Plasma source \(PLOW\): 4\.0000e\+19 neutrons per second in total\./.test(text), 'the comment carries the total rate');
});
test('addFusionSource: one group with the total rate, the other sources kept or replaced, no Problems, one undo removes it', () => {
  run('S = sampleModel(); HISTORY.undo.length = 0; HISTORY.redo.length = 0; HISTORY.current = JSON.stringify(S); HISTORY.boundary = false; HISTORY.last = Date.now();');
  const before = run('S.sources.length');
  sb.__p = parse(fusionRecord());
  run('addFusionSource(__p, {})');
  assert.strictEqual(run('S.sources.length'), before + 320);
  assert.strictEqual(run('S.groups.length'), 1);
  assert.strictEqual(run('S.groups[0].sourceRate_n_s'), 4.0e19);
  assert.deepStrictEqual(J(run("problems().filter(p => p.sev === 'error').map(p => p.text)")), [], 'the ring sources fit in the world');
  run('historyTrack(JSON.stringify(S))');
  run('undo()');
  assert.strictEqual(run('S.sources.length'), before);
  assert.strictEqual(run('S.groups.length'), 0);
  run('addFusionSource(__p, {replace: true})');
  assert.strictEqual(run('S.sources.length'), 320, 'replace takes the other sources out');
});
test('a refused record adds nothing to the model', () => {
  run('S = sampleModel();');
  const n = run('S.sources.length + S.groups.length');
  const bad = fusionRecord(); bad.reaction = 'D-D';
  assert.ok(!parse(bad).ok);
  assert.strictEqual(run('S.sources.length + S.groups.length'), n);
});
test('the ring source in the model: validation, bounds, rotation, and the MCNP notation', () => {
  run('S = sampleModel();');
  const ring = o => Object.assign(run("newSource('r1', 'Ring', 'neutron')"), {space: 'ring', x: 0, y: 0, z: 10, r: 50}, o);
  const errors = src => { sb.__src = src; run('S.sources = [__src]'); return J(run("problems().filter(p => p.sev === 'error').map(p => p.text)")).filter(t => /Ring|ring/.test(t)); };
  assert.deepStrictEqual(errors(ring()), [], 'a ring inside the world');
  assert.ok(errors(ring({r: 0})).some(t => /ring radius must be above 0/.test(t)));
  assert.ok(errors(ring({r: -5})).some(t => /ring radius must be above 0/.test(t)));
  assert.ok(errors(ring({r: 1e6})).some(t => /past the world boundary/.test(t)), 'a ring wider than the world');
  sb.__r = ring();
  assert.deepStrictEqual(J(run("itemBounds('source', __r)")), [[-50, -50, 10], [50, 50, 10]]);
  const Rx = [[1, 0, 0], [0, 0, -1], [0, 1, 0]], Rz = [[0, -1, 0], [1, 0, 0], [0, 0, 1]];
  sb.__items = [{kind: 'source', o: ring()}]; sb.__before = [ring()];
  assert.ok(/ring source/.test(run('rotateItems(__items, __before, ' + JSON.stringify(Rx) + ', [0, 0, 0], false)')), 'a ring cannot turn about x');
  assert.strictEqual(run('rotateItems(__items, __before, ' + JSON.stringify(Rz) + ', [0, 0, 0], false)'), null, 'a ring can turn about z');
  const m = run('mcnpSource(__r)');
  assert.ok(/POS=0 0 10 AXS=0 0 1 RAD=D1 EXT=0/.test(m) && /SI1 L 50/.test(m) && /SP1 D 1/.test(m), m);
});
if (process.env.PLOW_SAMPLE_FUSION_SOURCE) {
  test('the real PLOW record (PLOW_SAMPLE_FUSION_SOURCE) is accepted with its power and total consistent', () => {
    const r = parse(fs.readFileSync(process.env.PLOW_SAMPLE_FUSION_SOURCE, 'utf8'));
    assert.ok(r.ok, JSON.stringify(r.errors));
    assert.ok(Math.abs(r.info.powerCheck) < 1e-6);
    const ss = sources(r);
    const raw = JSON.parse(fs.readFileSync(process.env.PLOW_SAMPLE_FUSION_SOURCE, 'utf8')).cells.filter(c => c.rate_n_s > 0);
    assert.ok(ss.every((s, i) => s.space === 'ring' && Math.abs(sigmaOf(s) / raw[i].energy_std_mev - 1) < 1e-9 && Math.abs(s.r - raw[i].r_m * 100) < 1e-6), 'every cell: a ring at its centroid with the width the record gives');
    console.log(`     real record: ${r.cells.length} cells, ${r.totalRate.toPrecision(5)} n/s, R ${r.info.rMin.toFixed(3)} to ${r.info.rMax.toFixed(3)} m`);
  });
}

let failed = 0;
for (const [name, fn] of tests) {
  try { fn(); console.log('ok   ' + name); } catch (e) { failed++; console.log('FAIL ' + name + '\n     ' + String(e.stack || e).split('\n').slice(0, 4).join('\n     ')); }
}
console.log(failed ? `${failed} FAILED of ${tests.length}` : `${tests.length} passed`);
process.exit(failed ? 1 : 0);
