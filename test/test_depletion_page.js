// Settings > Depletion on the page: what the generated model.py says about burnable materials and their volumes, the settings an
// older project gets, and which Settings fields show. Server side: test/test_depletion_run.py; the shared errors: test_prerun_check_page.js.
// Run: node test/test_depletion_page.js
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

// the pin cell of test/generate_depletion_pin.cjs, with depletion on or off and the fuel flagged or not
const pin = ({depletion = true, burnable = true, steps = '1, 4'} = {}) => JSON.parse(run(`JSON.stringify((() => {
  const p = sampleModel();
  const mat = (id, name, density, comps, sab, extra) => Object.assign({id, name, color:'#999999', density, frac:'ao', comps, sab:sab || ''}, extra || {});
  p.materials = [mat('m1', 'UO2 3.5%', 10.4, 'U235:0.035, U238:0.965, O16:2', '', ${burnable ? '{burnable:true}' : '{}'}), mat('m2', 'Zircaloy', 6.55, 'Zr:1'), mat('m3', 'Water', 0.74, 'H:2, O:1', 'c_H_in_H2O')];
  const cyl = (id, name, r, material) => Object.assign(newPart(id, name, 'cylinder'), {x:0, y:0, z:0, r, h:1.26, axis:'z', material});
  p.parts = [cyl('p1', 'Fuel', 0.4096, 'm1'), cyl('p2', 'Cladding', 0.475, 'm2')];
  p.groups = []; p.tallies = [];
  p.sources = [Object.assign({}, p.sources[0], {id:'s1', space:'box', x0:-0.4, x1:0.4, y0:-0.4, y1:0.4, z0:-0.6, z1:0.6, energy:'watt'})];
  Object.assign(p.settings, {runMode:'eigenvalue', particles:2000, batches:15, inactive:5, maxTracks:0, worldShape:'box', worldR:0.63, worldBC:'reflective', worldFill:'m3',
    depletion:${depletion}, depPower:38, depSteps:${JSON.stringify(steps)}, depIntegrator:'PredictorIntegrator', depReduce:3});
  return p;
})())`));
const scriptFor = project => { sb.__p = JSON.stringify(project); return JSON.parse(run(`(() => { S = JSON.parse(__p); const P = problems(); return JSON.stringify({errors: P.filter(x => x.sev === 'error').map(x => x.text), infos: P.filter(x => x.sev === 'info').map(x => x.text), text: generate(P)}); })()`)); };

let failed = 0;
const tests = [];
const test = (name, fn) => tests.push([name, fn]);

test('a burnable fuel is marked depletable and its cell and box are listed for the volume', () => {
  const r = scriptFor(pin());
  assert.deepEqual(r.errors, []);
  assert.match(r.text, /^mat_uo2_3_5\.depletable = True$/m);
  assert.equal((r.text.match(/\.depletable = True/g) || []).length, 1, 'only the burnable material');
  assert.match(r.text, /^depletion_materials = \[\(mat_uo2_3_5, \[\(cell_fuel, \(-0\.4096\d*, -0\.4096\d*, -0\.63\), \(0\.4096\d*, 0\.4096\d*, 0\.63\)\)\]\)\]$/m);
  assert.match(r.text, /^def prepare_depletion\(model\):$/m);
  assert.match(r.text, /mat\.volume = sum\(vc\.volumes\[c\.id\]\.nominal_value for \(c, _, _\), vc in zip\(cells, results\)\)/, 'cells first, so the iterator is not over-read');
});

test('with depletion off nothing about it is written, even if a material is flagged', () => {
  const r = scriptFor(pin({depletion: false}));
  assert.doesNotMatch(r.text, /depletable|prepare_depletion|depletion_materials/);
  assert.equal(r.infos.filter(t => /Depletion is set up for OpenMC only/.test(t)).length, 0);
});

test('with depletion on, the page says model.mcnp leaves it out', () => {
  assert.equal(scriptFor(pin()).infos.filter(t => /BURN card/.test(t)).length, 1);
});

test('depletion without a burnable material, or with a bad step list, is an error the page names', () => {
  assert.match(scriptFor(pin({burnable: false})).errors.join(' | '), /marked Burnable/);
  assert.match(scriptFor(pin({steps: '1, x'})).errors.join(' | '), /time steps/);
});

test('an older project gets the depletion settings with depletion off', () => {
  const o = JSON.parse(run(`JSON.stringify((() => { const o = {materials: [], parts: [], groups: [], sources: [], tallies: [], settings: {name: 'old', runMode: 'fixed source'}}; normalizeProject(o); return o.settings; })())`));
  assert.equal(o.depletion, false);
  assert.equal(o.depPower, 38);
  assert.equal(o.depSteps, '1, 4, 10, 25, 60');
  assert.equal(o.depIntegrator, 'CECMIntegrator');
  assert.equal(o.depReduce, 6);
});

test('a project that already has its own depletion settings keeps them', () => {
  const o = JSON.parse(run(`JSON.stringify((() => { const o = {materials: [], parts: [], groups: [], sources: [], tallies: [], settings: {name: 'x', depletion: true, depPower: 20, depSteps: '5', depIntegrator: 'CF4Integrator', depReduce: 4}}; normalizeProject(o); return o.settings; })())`));
  assert.deepEqual([o.depletion, o.depPower, o.depSteps, o.depIntegrator, o.depReduce], [true, 20, '5', 'CF4Integrator', 4]);
  const bad = JSON.parse(run(`JSON.stringify((() => { const o = {materials: [], parts: [], groups: [], sources: [], tallies: [], settings: {name: 'x', depIntegrator: 'Nope', depReduce: 2.5}}; normalizeProject(o); return o.settings; })())`));
  assert.deepEqual([bad.depIntegrator, bad.depReduce], ['CECMIntegrator', 6], 'unusable values fall back to the defaults');
});

test('the Depletion fields in Settings show only when depletion is on, and the Burnable box only then too', () => {
  const sections = on => JSON.parse(run(`JSON.stringify((() => { S = JSON.parse(${JSON.stringify(JSON.stringify(pin({depletion: on})))});
    const dep = specFor('settings', S.settings).find(s => s.title === 'Depletion');
    const shown = dep.fields.filter(f => !f.show || f.show()).map(f => f.key);
    const box = specFor('material', S.materials[0]).flatMap(s => s.fields).filter(f => f.key === 'burnable' && (!f.show || f.show()));
    return {shown, burnableBox: box.length}; })())`));
  const off = sections(false), on = sections(true);
  assert.deepEqual(off.shown, ['depletion']);
  assert.deepEqual(on.shown, ['depletion', 'depPower', 'depSteps', 'depIntegrator', 'depReduce']);
  assert.equal(off.burnableBox, 0);
  assert.equal(on.burnableBox, 1);
});

(async () => {
  for (const [name, fn] of tests) {
    try { await fn(); console.log('  [PASS]', name); }
    catch (e) { failed++; console.log('  [FAIL]', name, '\n   ', e.message); }
  }
  console.log(failed ? `test_depletion_page: ${failed} FAILED` : 'test_depletion_page: PASS');
  process.exit(failed ? 1 : 0);
})();
