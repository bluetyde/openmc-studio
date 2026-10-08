// Settings > Depletion on the page: what the generated model.py says about burnable materials and their volumes, the settings an
// older project gets, and which Settings fields show. Server side: test/test_depletion_run.py; the shared errors: test_prerun_check_page.js.
// Run: node test/test_depletion_page.js
const fs = require('fs'), vm = require('vm'), path = require('path'), assert = require('assert');

const html = fs.readFileSync(path.join(__dirname, '..', 'studio', 'openmc_studio', 'static', 'index.html'), 'utf8');
const listeners = [];
const writes = [];
const el = {addEventListener(type, fn) { listeners.push([type, fn]); }, insertAdjacentHTML() {}, querySelector: () => el, querySelectorAll: () => [], style: {}, dataset: {},
  classList: {add() {}, remove() {}, toggle() {}}, setAttribute() {}, appendChild() {}, append() {}, add() {}, remove() {}, getContext: () => null, parentElement: {}};
const sb = {console, URLSearchParams, btoa, atob, TextEncoder, escape, unescape, Option: class {}, window: {}, location: {protocol: 'http:', search: ''},
  document: {querySelector: () => el, querySelectorAll: () => [], getElementById: () => el, createElement: () => el, createTextNode: () => el, addEventListener() {}},
  fetch: () => Promise.resolve({ok: false}), ResizeObserver: class { observe() {} disconnect() {} },
  requestAnimationFrame() {}, setTimeout() {}, setInterval: () => 1, clearInterval() {}};
Object.defineProperty(el, 'innerHTML', {set(v) { writes.push(String(v)); }, get() { return writes[writes.length - 1] || ''; }});
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
    const shown = dep.fields.filter(f => f.key && (!f.show || f.show())).map(f => f.key);
    const box = specFor('material', S.materials[0]).flatMap(s => s.fields).filter(f => f.key === 'burnable' && (!f.show || f.show()));
    return {shown, burnableBox: box.length}; })())`));
  const off = sections(false), on = sections(true);
  assert.deepEqual(off.shown, ['depletion']);
  assert.deepEqual(on.shown, ['depletion', 'depPower', 'depSteps', 'depIntegrator', 'depReduce']);
  assert.equal(off.burnableBox, 0);
  assert.equal(on.burnableBox, 1);
});

// ── the Results page for a run that burned fuel ──
const REC = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures', 'depletion', 'pin_record.json'), 'utf8'));
const render = D => { sb.__D = D; return run(`renderDepletion(__D)`); };
const dep = (rec = REC, extra = {}) => ({record: rec, note: null, wall_s: 95.5, ...extra});

test('the table lists every point with its day, burnup and k', () => {
  const h = render(dep());
  const rows = [...h.matchAll(/<tr><td class="num">(\d)<\/td><td class="num">([\d.]+)<\/td><td class="num">([\d.]+)<\/td><td class="num">([^<]+)<\/td><\/tr>/g)].map(m => m.slice(1));
  assert.equal(rows.length, 3);
  assert.deepEqual(rows.map(r => r[0]), ['0', '1', '2']);
  assert.deepEqual(rows.map(r => r[1]), ['0', '1', '5'], 'days are the running sum of the step lengths');
  assert.deepEqual(rows.map(r => +r[2]), [0, 38, 190], 'burnup from the record, 0 at the start');
  assert.match(rows[1][3], /^1\.3\d{4} ± 0\.00\d{3}$/);
});

test('the header names the region, heavy-metal mass, steps, integrator, chain level, power and the record id', () => {
  const h = render(dep());
  assert.match(h, /UO2 3\.5% · 6\.09\d g heavy metal · 2 steps · Predictor · chain level 3 · 38 W\/g · 95\.5 s · record <code>/);
  assert.ok(h.includes(`<code>${REC.id.slice(0, 12)}</code>`), 'the id the record carries');
});

test('both charts are drawn: k with its bars, and the inventory with the main nuclides', () => {
  const h = render(dep());
  assert.match(h, /<svg class="dep-k"/);
  assert.ok((h.match(/<circle/g) || []).length > 0);
  const inv = h.slice(h.indexOf('class="dep-inv"'));
  for (const n of ['U235', 'U236', 'Pu239', 'Xe135', 'Sm149']) assert.match(inv, new RegExp(`>${n}</text>`), n + ' is labelled');
  assert.doesNotMatch(inv, />Pu241</, 'a nuclide the record does not hold is not drawn');
  assert.match(inv, />1e-2</, 'a log axis');
});

test('an incomplete run is said to be incomplete, a complete one is not', () => {
  const partial = JSON.parse(JSON.stringify(REC));
  partial.provenance.complete = false; partial.provenance.steps_done = 2; partial.provenance.steps_planned = 5;
  assert.match(render(dep(partial)), /incomplete<\/span> 2 of 5 steps finished before the run stopped/);
  assert.doesNotMatch(render(dep()), /incomplete/);
});

test('a bookkeeping check outside its tolerance is shown, one inside is not', () => {
  const bad = JSON.parse(JSON.stringify(REC));
  bad.provenance.checks['UO2 3.5%'].inventory.ok = false;
  bad.provenance.notes = ['region UO2 3.5%: the inventory check is 2.0, outside 1 +/- 0.05'];
  assert.match(render(dep(bad)), /warn">check<\/span> region UO2 3\.5%: the inventory check is 2\.0/);
  assert.doesNotMatch(render(dep()), />check</);
});

test('with no record the reason is shown, and a run that did not burn shows nothing', () => {
  assert.match(render({record: null, note: 'No depletion record: 2 burnable materials', wall_s: null}), /id="depNote">No depletion record: 2 burnable materials</);
  assert.equal(render(null), '');
  assert.equal(render(undefined), '');
});

test('the record text is escaped', () => {
  const evil = JSON.parse(JSON.stringify(REC));
  evil.regions[0].name = '<img src=x>';
  evil.isotopics['<img src=x>'] = evil.isotopics['UO2 3.5%']; delete evil.isotopics['UO2 3.5%'];
  const h = render(dep(evil));
  assert.doesNotMatch(h, /<img/);
  assert.match(h, /&lt;img src=x&gt;/);
});

test('the Save button is there and its click saves the record', () => {
  assert.match(render(dep()), /id="depExportBtn"/);
  run('window.__saved = []; saveDepletionRecord = () => window.__saved.push("save"); exportParaview = () => {}; saveRunReport = () => {}; checkRunRecord = () => {};');
  const click = id => { run('window.__saved = []'); for (const [t, fn] of listeners) if (t === 'click' && fn.toString().includes('#depExportBtn')) fn({target: {closest: sel => sel === id ? {} : null}}); return JSON.parse(JSON.stringify(run('window.__saved'))); };
  assert.deepEqual(click('#depExportBtn'), ['save']);
  assert.deepEqual(click('#reportBtn'), []);
});

test('results with a depletion payload put the section after the checks and before the charts of the last solve', () => {
  const R = {summary: {run_mode: 'eigenvalue', particles: 2000, batches: 15, seed: 1, runtime_s: 5, keff: [1.3, 0.005], k_generation: [1.3, 1.31], inactive: 5, n_inactive: 5}, tallies: [], tracks: [], tracks_truncated: false,
    findings: [{level: 'info', code: 'k-estimate', message: 'k = 1.30 +/- 0.01', detail: {}}], depletion: dep()};
  sb.__R = R; writes.length = 0;
  run('LOCAL.results = __R; LOCAL.resultsRun = "r1"; renderResults();');
  const h = writes[0];
  assert.ok(h.indexOf('Checks on this run') < h.indexOf('<h4>Depletion</h4>'));
  assert.ok(h.indexOf('<h4>Depletion</h4>') < h.indexOf('Eigenvalue Convergence'));
});

test('the inventory is drawn per starting heavy-metal atom: thorium to curium count, fission products do not', () => {
  assert.equal(run(`depHeavyStart({Th232: [5], Pa233: [1], U235: [1], U238: [2], Np237: [4], Pu239: [8], Am241: [16], Cm244: [32], Xe135: [100], Sm149: [100]})`), 69);
});

test('every point of the inventory chart is inside the plot, and a record with no heavy metal draws no inventory', () => {
  const inv = render(dep()).split('class="dep-inv"')[1].split('</svg>')[0];
  const cy = [...inv.matchAll(/<circle cx="[\d.]+" cy="([\d.]+)"/g)].map(m => +m[1]);
  assert.ok(cy.length > 5);
  assert.ok(cy.every(v => v >= 14 && v <= 160), 'inside the axes: ' + cy.join(' '));
  const none = JSON.parse(JSON.stringify(REC));
  none.isotopics = {'UO2 3.5%': {Xe135: [0, 1e15, 2e15]}};
  const h = render(dep(none));
  assert.doesNotMatch(h, /dep-inv/);
  assert.doesNotMatch(h, /NaN/);
});

test('the Depletion settings carry the estimate as a note, only when depletion is on', () => {
  const notes = on => JSON.parse(run(`JSON.stringify((() => { S = JSON.parse(${JSON.stringify(JSON.stringify(pin({depletion: on})))});
    return specFor('settings', S.settings).find(s => s.title === 'Depletion').fields.filter(f => f.type === 'note').map(f => f.html); })())`));
  assert.equal(notes(false).length, 0);
  const on = notes(true);
  assert.equal(on.length, 1);
  assert.match(on[0], /^About 3 transport solves/);
});

// ── the estimate before a run ──
const withStore = (v, fn) => { sb.localStorage = {getItem: () => v === null ? null : JSON.stringify(v), setItem: (k, x) => { sb.__stored = JSON.parse(x); }}; try { return fn(); } finally { delete sb.localStorage; } };
const estimate = (o = {}) => { sb.__st = JSON.stringify(o); sb.__pin = JSON.stringify(pin()); return run(`(() => { S = JSON.parse(__pin); Object.assign(S.settings, JSON.parse(__st)); return depEstimateHtml(); })()`); };

test('the solve count follows the integrator: steps x 1, 2 or 4, and one more at the end', () => {
  withStore(null, () => {
    assert.match(estimate({depIntegrator: 'PredictorIntegrator', depSteps: '1, 4'}), /^About 3 transport solves \(2 steps\)\./);
    assert.match(estimate({depIntegrator: 'CECMIntegrator', depSteps: '1, 4, 10'}), /^About 7 transport solves \(3 steps\)\./);
    assert.match(estimate({depIntegrator: 'CF4Integrator', depSteps: '1'}), /^About 5 transport solves \(1 step\)\./);
    assert.match(estimate({depIntegrator: 'SICELIIntegrator'}), /not estimated/);
  });
});

test('with no earlier run there is no time estimate, and the page says why', () => {
  withStore(null, () => assert.match(estimate(), /unknown until a depletion run has finished on this machine, so there is no time estimate yet/));
});

test('with an earlier run the time scales with particles x batches, and is called a guess', () => {
  withStore({s: 30, solves: 3, wall: 90, particles: 2000, batches: 15, chain: 3}, () => {
    const t = estimate({depIntegrator: 'PredictorIntegrator', depSteps: '1, 4', particles: 4000, batches: 15});
    assert.match(t, /Last depletion run here: 3 solves in 90 s \(30 s each at 2000 × 15\)/);
    assert.match(t, /roughly 3\.0 min if a solve scales with particles × batches/, '3 solves x 30 s x 2 = 180 s');
    assert.match(t, /That is a guess/);
  });
});

test('a finished depletion run stores how long a solve took; an incomplete one does not', () => {
  withStore(null, () => {
    sb.__stored = null; sb.__R2 = {depletion: dep()};
    run('noteDepletionTiming(__R2)');
    assert.equal(sb.__stored.solves, 3);
    assert.equal(sb.__stored.wall, 95.5);
    assert.ok(Math.abs(sb.__stored.s - 95.5 / 3) < 1e-9);
    assert.equal(sb.__stored.particles, 2000);
    const partial = JSON.parse(JSON.stringify(REC)); partial.provenance.complete = false;
    sb.__stored = null; sb.__R2 = {depletion: dep(partial)};
    run('noteDepletionTiming(__R2)');
    assert.equal(sb.__stored, null);
    sb.__R2 = {depletion: null};
    run('noteDepletionTiming(__R2)');
    assert.equal(sb.__stored, null);
  });
});

test('without browser storage the estimate still works', () => {
  assert.match(estimate({depIntegrator: 'PredictorIntegrator', depSteps: '1'}), /^About 2 transport solves/);
});

(async () => {
  for (const [name, fn] of tests) {
    try { await fn(); console.log('  [PASS]', name); }
    catch (e) { failed++; console.log('  [FAIL]', name, '\n   ', e.message); }
  }
  console.log(failed ? `test_depletion_page: ${failed} FAILED` : 'test_depletion_page: PASS');
  process.exit(failed ? 1 : 0);
})();
