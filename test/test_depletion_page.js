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
const pin = ({depletion = true, burnable = true, steps = '1, 4', slices = false} = {}) => JSON.parse(run(`JSON.stringify((() => {
  const p = sampleModel();
  const mat = (id, name, density, comps, sab, extra) => Object.assign({id, name, color:'#999999', density, frac:'ao', comps, sab:sab || ''}, extra || {});
  p.materials = [mat('m1', 'UO2 3.5%', 10.4, 'U235:0.035, U238:0.965, O16:2', '', ${burnable ? '{burnable:true}' : '{}'}), mat('m2', 'Zircaloy', 6.55, 'Zr:1'), mat('m3', 'Water', 0.74, 'H:2, O:1', 'c_H_in_H2O')];
  const cyl = (id, name, r, material) => Object.assign(newPart(id, name, 'cylinder'), {x:0, y:0, z:0, r, h:1.26, axis:'z', material});
  p.parts = [cyl('p1', 'Fuel', 0.4096, 'm1'), cyl('p2', 'Cladding', 0.475, 'm2')];
  ${slices ? `p.materials.push(mat('m4', 'UO2 5%', 10.4, 'U235:0.05, U238:0.95, O16:2', '', {burnable:true}));
  p.parts[0].h = 0.63; p.parts[0].z = -0.315;
  p.parts.push(Object.assign(cyl('p3', 'Fuel upper', 0.4096, 'm4'), {h: 0.63, z: 0.315}));` : ''}
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
  assert.match(r.text, /^def prepare_depletion\(model, measure_volumes=True\):$/m);
  assert.match(r.text, /mat\.volume = sum\(vc\.volumes\[c\.id\]\.nominal_value for \(c, _, _\), vc in zip\(cells, results\)\)/, 'cells first, so the iterator is not over-read');
});

test('two burnable materials get a kappa-fission tally of their own, one does not', () => {
  const two = scriptFor(pin({slices: true}));
  assert.deepEqual(two.errors, []);
  assert.equal((two.text.match(/\.depletable = True/g) || []).length, 2);
  assert.match(two.text, /^depletion_materials = \[\(mat_uo2_3_5, \[.*\]\), \(mat_uo2_5, \[.*\]\)\]$/m);
  assert.match(two.text, /t = openmc\.Tally\(name="Depletion power split \(kappa-fission per burnable material\)"\)/);
  assert.match(two.text, /t\.filters = \[openmc\.MaterialFilter\(\[m for m, _ in depletion_materials\]\)\]/);
  assert.match(two.text, /t\.scores = \["kappa-fission"\]/);
  assert.match(two.text, /model\.tallies\.append\(t\)/);
  assert.ok(two.text.indexOf('model.tallies.append(t)') < two.text.indexOf('model.calculate_volumes'), 'before the volume calculation, whose model.xml the transport run reads');
  assert.doesNotMatch(scriptFor(pin()).text, /kappa-fission/, 'one burnable material: the whole source rate is its power');
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

const SLICES = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures', 'depletion', 'slices_record.json'), 'utf8'));
test('the record of a real two-slice run is drawn: both regions, both inventories, the average', () => {
  const h = render(dep(SLICES));
  assert.match(h, /2 burnable regions \(UO2 3\.5%, UO2 5%\) · 6\.0\d+ g heavy metal/);
  assert.match(h, /UO2 3\.5%, MWd\/tU<\/th><th class="num">UO2 5%, MWd\/tU<\/th><th class="num">Average, MWd\/tU/);
  assert.equal((h.match(/class="dep-inv"/g) || []).length, 2);
  const last = [...h.matchAll(/<tr><td class="num">2<\/td><td class="num">5<\/td><td class="num">([\d.]+)<\/td><td class="num">([\d.]+)<\/td><td class="num">([\d.]+)<\/td>/g)][0];
  assert.ok(last, 'the last row');
  const [lo, hi, avg] = last.slice(1).map(Number);
  assert.ok(lo < avg && avg < hi, `the average ${avg} lies between ${lo} and ${hi}`);
});

// a record of two burnable regions: slice A at 30 % of the power, slice B at 70 %
const TWO = (() => {
  const r = JSON.parse(JSON.stringify(REC));
  const a = r.regions[0], b = JSON.parse(JSON.stringify(a));
  a.name = 'slice A'; b.name = 'slice B'; b.heavy_metal_mass_kg = a.heavy_metal_mass_kg * 3; b.burnup_mwd_per_tu = a.burnup_mwd_per_tu.map(x => x / 3);
  r.regions = [a, b];
  const iso = r.isotopics[REC.regions[0].name];
  r.isotopics = {'slice A': iso, 'slice B': JSON.parse(JSON.stringify(iso))};
  return r;
})();

test('several regions: a burnup column for each, the mass-weighted average, and the k chart against the average', () => {
  const h = render(dep(TWO));
  assert.match(h, /<th class="num">slice A, MWd\/tU<\/th><th class="num">slice B, MWd\/tU<\/th><th class="num">Average, MWd\/tU<\/th>/);
  const rows = [...h.matchAll(/<tr><td class="num">(\d)<\/td><td class="num">[\d.]+<\/td><td class="num">([\d.]+)<\/td><td class="num">([\d.]+)<\/td><td class="num">([\d.]+)<\/td>/g)].map(m => m.slice(1).map(Number));
  assert.equal(rows.length, 3);
  assert.deepEqual(rows[2].slice(1).map(x => +x.toFixed(1)), [190, 63.3, 95], 'A at 190, B at a third of that, the average weighted 1 : 3');
  assert.match(h, /k-eff against average burnup/);
  assert.match(h, /2 burnable regions \(slice A, slice B\) · /);
});

test('several regions: one inventory chart for each, named; one region keeps the plain wording', () => {
  const h = render(dep(TWO));
  assert.equal((h.match(/class="dep-inv"/g) || []).length, 2);
  assert.match(h, /Inventory against burnup in slice A:/);
  assert.match(h, /Inventory against burnup in slice B:/);
  const one = render(dep());
  assert.doesNotMatch(one, /Average, MWd/);
  assert.doesNotMatch(one, /Inventory against burnup in/);
  assert.match(one, /k-eff against burnup \(MWd\/tU\)/);
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
  delete none.provenance.heavy_metal_atoms_start;   // an older record, without the total: the listed heavy nuclides are all there is to divide by
  const h = render(dep(none));
  assert.doesNotMatch(h, /dep-inv/);
  assert.doesNotMatch(h, /NaN/);
  // with the total in the record the chart is drawn: the fission product against the heavy metal the record says there was
  none.provenance.heavy_metal_atoms_start = {'UO2 3.5%': 1e24};
  assert.match(render(dep(none)), /dep-inv/);
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


test('the inventory chart divides by the record\'s own starting heavy metal when it has one, by the listed heavy nuclides when it does not', () => {
  // thorium fuel with a little U-235: Th-232 is not a listed nuclide, so the listed heavy metal is 1e22 of the 1e24 that is really there
  const th = JSON.parse(JSON.stringify(REC));
  const name = th.regions[0].name;
  th.isotopics[name] = {U235: [1e22, 9e21, 8e21], Xe135: [0, 1e18, 2e18]};
  const withTotal = JSON.parse(JSON.stringify(th)); withTotal.provenance.heavy_metal_atoms_start = {[name]: 1e24};
  const labels = h => [...h.matchAll(/<text x="44" y="[\d.]+"[^>]*>(1e-?\d+)<\/text>/g)].map(m => +m[1].replace('1e', ''));
  const old = render(dep(th)), now = render(dep(withTotal));
  assert.ok(Math.max(...labels(old)) >= 0, 'without the total the starting U-235 is "1": the listed heavy metal is only U-235');
  assert.ok(Math.max(...labels(now)) <= -2 + 1, 'with it the starting U-235 is 0.01 of the heavy metal');
  assert.ok(Math.max(...labels(now)) < Math.max(...labels(old)));
});

test('the Results button of a stopped or failed run is enabled (its finished steps are a record), only a running one is not', async () => {
  const runs = [{id: 'r-done', name: 'a', status: 'done', started: 1}, {id: 'r-stopped', name: 'b', status: 'stopped', started: 2},
    {id: 'r-failed', name: 'c', status: 'failed', started: 3}, {id: 'r-running', name: 'd', status: 'running', started: 4}];
  sb.fetch = () => Promise.resolve({ok: true, headers: {get: () => 'application/json'}, json: () => Promise.resolve({runs})});
  run('LOCAL.on = true; LOCAL.token = "tok"');
  writes.length = 0;
  await run('refreshRuns()');
  const h = writes.join('');
  const state = id => (h.match(new RegExp(`data-results="${id}" ([^>]*)>Results`)) || [])[1];
  assert.equal(state('r-done'), '');
  assert.equal(state('r-stopped'), '');
  assert.equal(state('r-failed'), '');
  assert.equal(state('r-running'), 'disabled');
});

// a run that ends: the stream's "end" event decides what the page does with the run's results
const endOf = async (status, depletion) => {
  const handlers = {};
  sb.EventSource = class { constructor() { this.readyState = 1; } addEventListener(t, fn) { handlers[t] = fn; } close() {} };
  run('window.__loaded = []; loadResults = async (id) => { window.__loaded.push(id); }; refreshRuns = () => {}; setRunning = () => {}; setOutTab = () => {}; LOCAL.token = "tok"');
  sb.__dep = depletion; run('S.settings.depletion = __dep');
  run('streamRun("r9")');
  await handlers.end({data: JSON.stringify({status, returncode: status === 'done' ? 0 : 1, started: 1, ended: 3})});
  return JSON.parse(JSON.stringify(run('window.__loaded')));
};
test('when a run ends, its results are loaded if it finished, and for a stopped or failed burn too (its steps are a record), not for another kind of run that stopped', async () => {
  assert.deepEqual(await endOf('done', false), ['r9']);
  assert.deepEqual(await endOf('done', true), ['r9']);
  assert.deepEqual(await endOf('stopped', true), ['r9'], 'a stopped burn');
  assert.deepEqual(await endOf('failed', true), ['r9'], 'a failed burn');
  assert.deepEqual(await endOf('stopped', false), [], 'a transport run that was stopped has no record to show');
  assert.deepEqual(await endOf('failed', false), []);
});

test('Open model on a stopped burn loads its results; on a stopped transport run it does not; a running one never', async () => {
  const mk = depletion => ({materials: [], parts: [], groups: [], sources: [], tallies: [], settings: {name: 'x', depletion}});
  const runs = {'r-stopped': 'stopped', 'r-done': 'done', 'r-running': 'running'};
  let depletion = true;
  sb.fetch = url => Promise.resolve({ok: true, headers: {get: () => 'application/json'}, json: () => Promise.resolve(/\/project$/.test(url) ? mk(depletion) : {runs: Object.entries(runs).map(([id, status]) => ({id, status, name: id, started: 1}))})});
  run('validProject = () => true; normalizeProject = () => {}; renderAll = () => {}; clearResults = () => { window.__cleared = true; }; window.__loaded = []; loadResults = (id) => { window.__loaded.push(id); }; LOCAL.on = true; LOCAL.token = "tok"');
  const open = async id => {
    run('window.__loaded = []');
    for (const [t, fn] of listeners) if (t === 'click' && fn.toString().includes('data-load')) await fn({target: {closest: sel => sel === '[data-load]' ? {dataset: {load: id}} : null}});
    await new Promise(r => setImmediate(r));
    return JSON.parse(JSON.stringify(run('window.__loaded')));
  };
  assert.deepEqual(await open('r-done'), ['r-done']);
  assert.deepEqual(await open('r-stopped'), ['r-stopped'], 'a burn: its finished steps');
  assert.deepEqual(await open('r-running'), [], 'running: nothing to load yet');
  depletion = false;
  assert.deepEqual(await open('r-stopped'), [], 'a stopped transport run');
});

test('the labels at the ends of the inventory lines do not print over each other, and every label is still inside the plot', () => {
  const rec = JSON.parse(JSON.stringify(REC)), name = rec.regions[0].name, iso = rec.isotopics[name];
  iso.Pu239 = [0, 1e19, 1e20]; iso.U236 = [0, 1e19, 1e20];   // two series that end on the same value
  const inv = render(dep(rec)).split('class="dep-inv"')[1].split('</svg>')[0];
  const ys = [...inv.matchAll(/<text x="[\d.]+" y="([\d.]+)" fill="#[0-9a-f]{6}" font-size="10" font-family="sans-serif">([A-Za-z0-9]+)<\/text>/g)].map(m => [+m[1], m[2]]);
  assert.ok(ys.length >= 5, 'the series labels: ' + ys.map(v => v[1]).join(' '));
  const sorted = ys.map(v => v[0]).sort((a, b) => a - b);
  for (let i = 1; i < sorted.length; i++) assert.ok(sorted[i] - sorted[i - 1] >= 10.99, `labels ${sorted[i - 1]} and ${sorted[i]} are too close`);
  assert.ok(sorted[sorted.length - 1] <= 190, 'inside the plot');
});

// the same pin as above, its fuel repeated as a 2 x 1 lattice (two parts of one group that is marked as a lattice)
const latticed = () => {
  const p = pin();
  p.parts = p.parts.filter(x => x.name !== 'Cladding');   // the lattice's box must lie in one host: here the world
  p.settings.worldR = 5;
  const fuel = p.parts.find(x => x.name === 'Fuel'), second = Object.assign({}, fuel, {id: 'p9', name: 'Fuel B', x: 0.63});
  fuel.x = -0.63;
  fuel.group = second.group = 'g1';
  p.parts.push(second);
  p.groups = [{id: 'g1', name: 'Pins', parent: null, x: 0, y: 0, z: 0, lattice: {nx: 2, ny: 1, nz: 1, dx: 1.26, dy: 1.26, dz: 1.26, fill: 'm3', asLattice: true}}];
  return p;
};
test('a burnable material used by parts inside a lattice is refused by the page and, for any other client, by model.py before any transport', () => {
  const r = scriptFor(latticed());
  assert.match(r.errors.join(' | '), /burnable material in a part inside a lattice/, 'the page refuses it');
  assert.match(r.text, /^depletion_in_lattices = \{"UO2 3\.5%": \["Fuel", "Fuel B"\]\}$/m);
  assert.match(r.text, /^def prepare_depletion\(model, measure_volumes=True\):\n    if depletion_in_lattices:\n        name, parts = next\(iter\(depletion_in_lattices\.items\(\)\)\)\n        raise RuntimeError\(/m);
  assert.ok(r.text.indexOf('raise RuntimeError(f"{name} is marked Burnable') < r.text.indexOf('model.calculate_volumes'), 'before the volumes are measured');
});

test('without a lattice the guard is an empty table and nothing is raised', () => {
  assert.match(scriptFor(pin()).text, /^depletion_in_lattices = \{\}$/m);
  const lat = latticed(); lat.groups[0].lattice.asLattice = false;   // an array written cell by cell is not a lattice
  const r = scriptFor(lat);
  assert.match(r.text, /^depletion_in_lattices = \{\}$/m);
  assert.doesNotMatch(r.errors.join(' | '), /inside a lattice/);
});

test('prepare_depletion can skip the volumes for a resume: the tally is still added, the early return comes before the volume calculation', () => {
  const two = scriptFor(pin({slices: true}));
  const i = {tally: two.text.indexOf('model.tallies.append(t)'), early: two.text.indexOf('    if not measure_volumes:\n        return'), calc: two.text.indexOf('model.calculate_volumes')};
  assert.ok(i.tally > 0 && i.early > i.tally && i.calc > i.early, JSON.stringify(i));
  assert.match(two.text, /^def prepare_depletion\(model, measure_volumes=True\):$/m);
});

(async () => {
  for (const [name, fn] of tests) {
    try { await fn(); console.log('  [PASS]', name); }
    catch (e) { failed++; console.log('  [FAIL]', name, '\n   ', e.message); }
  }
  console.log(failed ? `test_depletion_page: ${failed} FAILED` : 'test_depletion_page: PASS');
  process.exit(failed ? 1 : 0);
})();
