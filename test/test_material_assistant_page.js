// The material editor's "From engineering inputs" helper: the JavaScript port of material_assistant.py against its golden cases (made by the Python module),
// the section in the editor, and what applying it does to a material. Python side: test/test_material_assistant.py and test_material_assistant_golden.py.
// Run: node test/test_material_assistant_page.js
const fs = require('fs'), vm = require('vm'), path = require('path'), assert = require('assert');

const html = fs.readFileSync(path.join(__dirname, '..', 'studio', 'openmc_studio', 'static', 'index.html'), 'utf8');
const el = {addEventListener() {}, insertAdjacentHTML() {}, querySelector: () => el, querySelectorAll: () => [], style: {}, dataset: {},
  classList: {add() {}, remove() {}, toggle() {}}, setAttribute() {}, appendChild() {}, append() {}, add() {}, remove() {}, getContext: () => null, parentElement: {}};
const sb = {console, URLSearchParams, btoa, atob, TextEncoder, escape, unescape, Option: class {}, window: {}, location: {protocol: 'http:', search: ''},
  document: {querySelector: () => el, querySelectorAll: () => [], getElementById: () => el, createElement: () => el, createTextNode: () => el, addEventListener() {}},
  fetch: () => Promise.resolve({ok: false}), ResizeObserver: class { observe() {} disconnect() {} },
  requestAnimationFrame() {}, setTimeout() {}, setInterval: () => 1, clearInterval() {}};
vm.createContext(sb);
vm.runInContext(html.match(/<script>([\s\S]*?)<\/script>/)[1], sb);
const run = s => vm.runInContext(s, sb);
run('window.__logs = []; log = (level, text) => window.__logs.push([level, text]); renderProps = () => {}; renderTree = () => {}; schedule = () => {};');
const logs = () => JSON.parse(JSON.stringify(run('window.__logs')));
const CASES = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures', 'material_assistant', 'cases.json'), 'utf8'));

let failed = 0;
const tests = [];
const test = (name, fn) => tests.push([name, fn]);

const close = (a, b, what) => assert.ok(Math.abs(a - b) <= 1e-12 * Math.max(1, Math.abs(b)), `${what}: ${a} against ${b}`);
test('the port gives the module\'s numbers on every golden case, and refuses the same arguments', () => {
  assert.ok(CASES.length >= 25);
  for (const c of CASES) {
    sb.__args = c.args.map(a => a === null ? NaN : a);
    const out = JSON.parse(run(`JSON.stringify(MA.${c.fn}(...__args))`));
    if (c.error_arg) { assert.ok(out.error && out.error.includes(`'${c.error_arg}'`), `${c.fn}(${c.args}) should refuse ${c.error_arg}, got ${JSON.stringify(out)}`); continue; }
    assert.ok(!out.error, `${c.fn}(${c.args}): ${out.error}`);
    close(out.density_g_cm3, c.expect.density_g_cm3, 'density');
    for (const part of ['mass_fractions', 'atom_density_per_b_cm'])
      for (const [k, v] of Object.entries(c.expect[part])) close(out[part][k], v, `${c.fn}(${c.args}) ${part}.${k}`);
    assert.deepEqual(Object.keys(out.mass_fractions), Object.keys(c.expect.mass_fractions));
  }
});

test('a hand check of both: UO2 at 3.5 wt % and 95 % of 10.96, and 1000 ppm boron in water at 0.7', () => {
  const u = run('MA.uranium_dioxide(3.5, 95, 10.96)');
  close(u.density_g_cm3, 10.412, 'density');
  close(u.atom_density_per_b_cm.O16 / (u.atom_density_per_b_cm.U235 + u.atom_density_per_b_cm.U238), 2, 'O to U');
  const w = run('MA.borated_water(1000, 0.7)');
  close(w.mass_fractions.B10 + w.mass_fractions.B11, 1e-3, 'boron mass fraction');
  close(w.atom_density_per_b_cm.B10 / (w.atom_density_per_b_cm.B10 + w.atom_density_per_b_cm.B11), 0.1982, 'natural B-10');
});

const material = (extra = {}) => { sb.__m = Object.assign({id: 'm9', name: 'Fuel', color: '#999999', density: 1, frac: 'ao', comps: 'H:2, O:1', sab: '', pristine: 'x', lib: 'k'}, extra); run('globalThis.__mat = __m'); return run('__mat'); };
const setEng = o => { sb.__e = o; run('Object.assign(ENG, __e)'); };

test('the editor has the section, and which fields show follows the choice', () => {
  setEng({kind: 'uo2'});
  material();
  const secs = run('specFor("material", __mat)');
  const sec = secs.find(s => s.title === 'From engineering inputs');
  assert.ok(sec, 'the section is there');
  assert.ok(secs.indexOf(sec) < secs.findIndex(s => s.title === 'MCNP equivalent'), 'before the MCNP equivalent');
  const shown = () => run('specFor("material", __mat)').find(s => s.title === 'From engineering inputs').fields.filter(f => !f.show || f.show()).map(f => f.label || (f.btns ? 'button' : '?'));
  assert.deepEqual(shown(), ['Calculate', 'Enrichment', 'Density', 'Theoretical density', 'Result', 'button']);
  setEng({kind: 'borated'});
  assert.deepEqual(shown(), ['Calculate', 'Boron', 'Water density', 'Hydrogen as H-2', 'B-10 in boron', 'Result', 'button']);
  setEng({kind: 'uo2'});
});

test('no density is supplied by Studio: with the theoretical density or the water density blank, the result is a refusal naming it', () => {
  setEng({kind: 'uo2', enrich: 3.5, td: 95, tdDensity: NaN});
  assert.match(run('engResult()').error, /theoretical_density_g_cm3/);
  setEng({kind: 'borated', ppm: 500, rho: NaN, dFrac: 0, b10: NaN});
  assert.match(run('engResult()').error, /solution_density_g_cm3/);
});

test('applying UO2 sets density, weight fractions and a note on where they came from, and the material is no longer an untouched preset', () => {
  setEng({kind: 'uo2', enrich: 3.5, td: 95, tdDensity: 10.96});
  material({sab: 'c_Something'});
  assert.equal(run('applyEngineering(__mat)'), true);
  const m = run('JSON.parse(JSON.stringify(__mat))');
  close(m.density, 10.412, 'density');
  assert.equal(m.frac, 'wo');
  const parsed = run('parseComps(__mat.comps)');
  assert.deepEqual(parsed.errs, []);
  assert.deepEqual(parsed.out.map(c => c.sym), ['U235', 'U238', 'O16']);
  close(parsed.out.reduce((a, c) => a + c.amt, 0), 1, 'mass fractions add up to 1');
  close(parsed.out[0].amt / (parsed.out[0].amt + parsed.out[1].amt), 0.035, 'U-235 is 3.5 wt % of the uranium');
  assert.match(m.ref, /^Engineering inputs: UO2, 3\.5 wt % U-235, 95 % of 10\.96 g\/cm³$/);
  assert.equal(m.pristine, undefined);
  assert.equal(m.lib, '');
  assert.equal(m.sab, 'c_Something', 'UO2 has no thermal scattering table to set or clear here');
  assert.ok(logs().some(([l, t]) => l === 'ok' && /Oxygen is taken as pure O-16/.test(t)));
});

test('applying light borated water sets the light-water thermal table, drops zero fractions, and parses as a composition', () => {
  setEng({kind: 'borated', ppm: 1000, rho: 0.7, dFrac: 0, b10: NaN});
  material();
  assert.equal(run('applyEngineering(__mat)'), true);
  const m = run('JSON.parse(JSON.stringify(__mat))');
  assert.equal(m.density, 0.7);
  assert.equal(m.sab, 'c_H_in_H2O');
  const parsed = run('parseComps(__mat.comps)');
  assert.deepEqual(parsed.errs, []);
  assert.deepEqual(parsed.out.map(c => c.sym), ['H1', 'O16', 'B10', 'B11'], 'no H2 at zero deuterium');
  setEng({ppm: 0});
  material();
  run('applyEngineering(__mat)');
  assert.deepEqual(run('parseComps(__mat.comps)').out.map(c => c.sym), ['H1', 'O16'], 'no boron at 0 ppm');
});

test('heavy water: the deuterium is there and no thermal table is chosen for it, with a message saying so', () => {
  setEng({kind: 'borated', ppm: 0, rho: 1.1, dFrac: 1, b10: NaN});
  material({sab: 'c_Old'});
  run('window.__logs = []');
  assert.equal(run('applyEngineering(__mat)'), true);
  const m = run('JSON.parse(JSON.stringify(__mat))');
  assert.deepEqual(run('parseComps(__mat.comps)').out.map(c => c.sym), ['H2', 'O16']);
  assert.equal(m.sab, 'c_Old', 'left alone');
  assert.ok(logs().some(([, t]) => /Choose the thermal scattering table for the deuterium yourself/.test(t)));
});

test('a boron fraction of B-10 given in atom percent is used, blank is natural', () => {
  setEng({kind: 'borated', ppm: 2000, rho: 0.75, dFrac: 0, b10: 50});
  material(); run('applyEngineering(__mat)');
  const c = run('parseComps(__mat.comps)').out, b10 = c.find(x => x.sym === 'B10').amt, b11 = c.find(x => x.sym === 'B11').amt;
  // 50 atom percent B-10: the mass ratio B10 : B11 is the ratio of their atomic masses
  close(b10 / b11, 10.012936862 / 11.009305166, 'B10 to B11 by mass');
});

test('invalid inputs change nothing and say why', () => {
  setEng({kind: 'uo2', enrich: 150, td: 95, tdDensity: 10.96});
  material();
  run('window.__logs = []');
  assert.equal(run('applyEngineering(__mat)'), false);
  const m = run('JSON.parse(JSON.stringify(__mat))');
  assert.deepEqual([m.density, m.frac, m.comps, m.pristine], [1, 'ao', 'H:2, O:1', 'x']);
  assert.ok(logs().some(([l, t]) => l === 'warn' && /enrichment_wt_pct/.test(t)));
});

test('the result line shows density, mass fractions and atom densities, or the refusal; text is escaped', () => {
  setEng({kind: 'uo2', enrich: 3.5, td: 95, tdDensity: 10.96});
  const line = run('engSummary(engResult())');
  assert.match(line, /^10\.412 g\/cm³ · U235 0\.0308\d+, U238 0\.8\d+, O16 0\.118\d+ \(mass fractions\) · U235 [\d.e-]+, U238 [\d.e-]+, O16 [\d.e-]+ atoms\/\(b·cm\)$/);
  assert.match(run('engSummary({error: "<b>x</b>"})'), /&lt;b&gt;/);
});

(async () => {
  for (const [name, fn] of tests) {
    try { await fn(); console.log('  [PASS]', name); }
    catch (e) { failed++; console.log('  [FAIL]', name, '\n   ', e.message); }
  }
  console.log(failed ? `test_material_assistant_page: ${failed} FAILED` : 'test_material_assistant_page: PASS');
  process.exit(failed ? 1 : 0);
})();
