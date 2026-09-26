// Dose rates, page side (plans/dose-rates-plan.md, stage 1): presets, Problems, model.py, the MCNP script
// leaving dose tallies out for now, the Results table's units, and source strengths scaled to sum to 1.
// The physics is checked against a hand calculation in test/test_dose_rates.py.
// Run: node test/test_dose_page.js
const fs = require('fs'), vm = require('vm'), path = require('path'), assert = require('assert');

const html = fs.readFileSync(path.join(__dirname, '..', 'studio', 'openmc_studio', 'static', 'index.html'), 'utf8');
const el = {addEventListener() {}, insertAdjacentHTML() {}, querySelector: () => el, querySelectorAll: () => [], style: {}, dataset: {},
  classList: {add() {}, remove() {}, toggle() {}}, setAttribute() {}, appendChild() {}, append() {}, add() {}, getContext: () => null,
  getBoundingClientRect: () => ({left: 0, bottom: 0})};
const sb = {console, URLSearchParams, btoa, atob, TextEncoder, Option: class {}, window: {innerWidth: 1000}, location: {protocol: 'http:', search: ''},
  document: {querySelector: () => el, querySelectorAll: () => [], getElementById: () => el, createElement: () => el, createTextNode: () => el, addEventListener() {}},
  fetch: () => Promise.resolve({ok: false}), ResizeObserver: class { observe() {} disconnect() {} },
  requestAnimationFrame() {}, setTimeout() {}, setInterval() {}};
vm.createContext(sb);
vm.runInContext(html.match(/<script>([\s\S]*?)<\/script>/)[1], sb);
const run = s => vm.runInContext(s, sb);

let failed = 0;
const test = (name, fn) => {
  try { run("S = normalizeProject(sampleModel()); S.tallies = []; sel = {kind:'part', id:S.parts[0].id}; S.settings.runMode = 'fixed source'; S.settings.photon = false; S.settings.sourceRate = null; UNITS.system = 'metric';"); fn(); console.log(`  [PASS] ${name}`); }
  catch (e) { failed++; console.log(`  [FAIL] ${name}\n${e.stack}`); }
};
const doseProblems = () => run('problems()').filter(p => p.sel && p.sel.kind === 'tally' || /source emission rate/i.test(p.text)).map(p => [p.sev, p.text]);

test('the Detector menu presets make dose tallies on the selected part', () => {
  run("addDetectorTally('dose_n')");
  const t = run('S.tallies[0]');
  assert.deepEqual([t.kind, t.dose, t.doseData, t.doseGeom, t.detector, t.scores], ['cell', 'n', 'icrp116', 'AP', 'none', ['flux']]);
  assert.deepEqual(t.cells, [run('S.parts[0].id')]);
});

test('Problems: no rate is info; eigenvalue, photons off and a detector response are errors', () => {
  run("addDetectorTally('dose_np')");
  let P = doseProblems();
  assert.ok(P.some(([s, t]) => s === 'error' && /photon dose needs photon transport/.test(t)), JSON.stringify(P));
  assert.ok(P.some(([s, t]) => s === 'info' && /per source particle \(pSv\)/.test(t)));
  assert.ok(!P.some(([, t]) => /model\.mcnp/.test(t)), 'dose tallies are in the MCNP deck now');
  run("S.settings.photon = true; S.settings.sourceRate = 1e8;");
  P = doseProblems();
  assert.ok(!P.some(([s]) => s === 'error'), JSON.stringify(P));
  assert.ok(!P.some(([, t]) => /per source particle \(pSv\)/.test(t)));
  run("S.settings.runMode = 'eigenvalue';");
  assert.ok(doseProblems().some(([s, t]) => s === 'error' && /fixed-source run/.test(t)));
  run("S.settings.runMode = 'fixed source'; S.tallies[0].detector = 'he3';");
  assert.ok(doseProblems().some(([s, t]) => s === 'error' && /dose or a detector response, not both/.test(t)));
});

test('model.py: one tally per particle, padded log-log coefficients, volumes and the source rate', () => {
  run("S.settings.photon = true; S.settings.sourceRate = 2.5e7; S.settings.photonCutoff = 2000; addDetectorTally('dose_np');");
  const py = run('generate(problems())');
  assert.match(py, /def _dose_filter\(particle, geometry, data, lowest\):/);
  assert.match(py, /interpolation="log-log"/);
  assert.match(py, /openmc\.ParticleFilter\(\["neutron"\]\), _dose_filter\("neutron", "AP", "icrp116", 1e-5\)\]/);
  assert.match(py, /openmc\.ParticleFilter\(\["photon"\]\), _dose_filter\("photon", "AP", "icrp116", 2000\.0\)\]/);
  assert.match(py, /SOURCE_RATE = 2\.5e7 /);
  assert.match(py, /dose_cells = \[\(str\((cell_\w+)\.id\), \1, \([^)]*\), \([^)]*\), None\)\]/);
  assert.match(py, /model\.calculate_volumes\(output=False\)/);
  assert.match(py, /"dose\.json"/);
});

test('the MCNP script carries the dose tallies and their description for the exporter', () => {
  run("S.settings.photon = true; S.settings.sourceRate = 5e7; addDetectorTally('dose_np'); addTally('cell');");
  const mc = run('mcnpScript(problems())');
  assert.match(mc, /_dose_filter\("neutron"/); assert.match(mc, /_dose_filter\("photon"/);
  assert.match(mc, /dose_tallies = \{/); assert.match(mc, /dose_cells = \[/); assert.match(mc, /SOURCE_RATE = 5e7 /);
  assert.match(mc, /openmc\.Tally\(name="Cell tally"\)/);
});

test('the MCNP preview: F4:N and F14:P, FC, FM rate factor; later tallies number after both', () => {
  run("S.settings.photon = true; S.settings.sourceRate = 5e7; addDetectorTally('dose_np'); addTally('cell');");
  const p = run('mcnpTally(S.tallies[0])');
  assert.match(p, /^F4:N /m); assert.match(p, /^F14:P /m);
  assert.match(p, /^FC4 .*: neutron effective dose, Sv\/h \(ICRP-116 AP\)$/m);
  assert.match(p, /^FM4 0\.18$/m);
  assert.match(p, /^c SD4: each cell's volume/m);
  assert.match(run('mcnpTally(S.tallies[1])'), /^F24:N /m, 'the next tally is 24: the dose tally took 4 and 14');
  run("S.settings.sourceRate = null;");
  assert.doesNotMatch(run('mcnpTally(S.tallies[0])'), /^FM4/m, 'no rate: per source particle, no multiplier');
});

test('a model without dose tallies is unchanged: no helper, no volume step', () => {
  run("addTally('cell');");
  const py = run('generate(problems())');
  assert.doesNotMatch(py, /_dose_filter|calculate_volumes|dose\.json/);
});

test('source strengths are scaled to sum to 1 only when they need to be', () => {
  let py = run('generate(problems())');
  assert.equal(run('S.sources.length'), 1);
  assert.doesNotMatch(py, /_total_strength/, 'one source of strength 1: nothing to do');
  run("S.sources.push({...clone(S.sources[0]), id:'s9', name:'Second', strength:3});");
  py = run('generate(problems())');
  assert.match(py, /_total_strength = sum\(s\.strength for s in settings\.source\)\nfor _s in settings\.source:\n    _s\.strength \/= _total_strength/);
  assert.match(py, /\.strength = 3\b/, 'the typed value stays as written (and editable)');
});

test('Results: µSv/h, or mrem/h in imperial, or pSv per source particle without a rate', () => {
  const t = {name: 'Det', kind: 'dose', data: 'icrp116', geometry: 'AP', particles: ['neutron', 'photon'], source_rate: 1e8,
    rows: [{cell: 'He-3 detector', volume: [33.5, 0.07], neutron: {pSv_per_source: 0.0224, sv_per_h: 8.067e-3, rel_err: 0.024},
      photon: {pSv_per_source: 2.35e-4, sv_per_h: 8.45e-5, rel_err: 0.03}, total: {pSv_per_source: 0.02264, sv_per_h: 8.151e-3, rel_err: 0.024}}]};
  sb.__t = t;
  let h = run('renderDose(__t)');
  assert.match(h, /Dose rate \(µSv\/h\)/); assert.match(h, /<b>8151<\/b>/); assert.match(h, /84\.5/);
  run("UNITS.system = 'imperial'");
  h = run('renderDose(__t)');
  assert.match(h, /Dose rate \(mrem\/h\)/); assert.match(h, /<b>815\.1<\/b>/);
  run("__t.source_rate = null; UNITS.system = 'metric'");
  h = run('renderDose(__t)');
  assert.match(h, /pSv per source particle/); assert.match(h, /<b>0\.02264<\/b>/);
});

test('dose maps: a mesh tally with Dose writes mesh x particle x dose tallies and no volume calculation', () => {
  run("addTally('mesh'); Object.assign(S.tallies[0], {dose:'n', doseData:'icrp116', doseGeom:'PA'}); S.settings.sourceRate = 1e9;");
  const py = run('generate(problems())');
  assert.match(py, /filters = \[openmc\.MeshFilter\(mesh_\w+\), openmc\.ParticleFilter\(\["neutron"\]\), _dose_filter\("neutron", "PA", "icrp116", 1e-5\)\]/);
  assert.match(py, /"mesh": True/);
  assert.match(py, /dose_cells = \[\]/);
  assert.equal((py.match(/= openmc\.RegularMesh\(/g) || []).length, 1, 'one mesh, shared');
  assert.match(run('mcnpScript(problems())'), /_dose_filter\("neutron", "PA"/);
  const p = run('mcnpTally(S.tallies[0])');
  assert.match(p, /^FMESH4:N GEOM=XYZ/m); assert.match(p, /^     FACTOR=3\.6$/m); assert.doesNotMatch(p, /SD4/);
});

test('dose maps: colorbar and Results line in µSv/h, mrem/h or pSv per source particle', () => {
  assert.deepEqual(run("meshDisplay({unit:'Sv/h'})"), {f: 1e6, unit: 'µSv/h'});
  run("UNITS.system = 'imperial'");
  assert.deepEqual(run("meshDisplay({unit:'Sv/h'})"), {f: 1e5, unit: 'mrem/h'});
  assert.deepEqual(run("meshDisplay({unit:'pSv/source'})"), {f: 1, unit: 'pSv per source particle'});
  assert.deepEqual(run("meshDisplay({})"), {f: 1, unit: ''}, 'flux maps are untouched');
});

test('dose on parts inside a lattice: no Problems error, (cell, instance) bins and a "cell/instance" volume each', () => {
  run(`S.groups = [{id:'g', name:'Rods', parent:null, x:0, y:0, z:0, lattice:{nx:2, ny:1, nz:1, dx:10, dy:10, dz:10, fill:'auto', asLattice:true}}];
    S.parts = [{...S.parts[0], id:'r0', name:'Rod A', shape:'cylinder', r:1, h:4, x:-5, y:0, z:0, group:'g', material:S.materials[0].id},
      {...S.parts[0], id:'r1', name:'Rod B', shape:'cylinder', r:1, h:4, x:5, y:0, z:0, group:'g', material:S.materials[0].id},
      {...S.parts[0], id:'tank', name:'Tank', shape:'box', sx:40, sy:40, sz:40, x:0, y:0, z:0, group:undefined, material:S.materials[1].id}];
    normalizeProject(S); sel = {kind:'part', id:'r1'}; addDetectorTally('dose_n');`);
  assert.deepEqual(run('S.tallies[0].cells'), ['r1']);
  assert.ok(!doseProblems().some(([s]) => s === 'error'), JSON.stringify(doseProblems()));
  const py = run('generate(problems())');
  assert.match(py, /openmc\.CellInstanceFilter\(\[\(cell_unit_\w+, _instance\(cell_unit_\w+, lattice_\w+, \(5\.0, 0\.0, 0\.0\)\)\)\]\)/);
  assert.match(py, /dose_cells = \[\(f"\{cell_unit_\w+\.id\}\/\{_instance\([^"]*\)\}", cell_unit_\w+, \(3\.99\d+, -1\.0\d+, -2\.0\d+\), \(6\.0\d+, 1\.0\d+, 2\.0\d+\), "Rod B"\)\]/);
  assert.match(py, /"labels": \{k: label for k, _, _, _, label in dose_cells if label\}/);
  const panel = run('mcnpTally(S.tallies[0])');
  assert.match(panel, /^c F4: the export writes each part inside a lattice as a bin/m, panel);
  assert.match(panel, /^c F4:N \(Rod B in its lattice\)$/m, panel);
  assert.match(panel, /^FC4 /m);
});

test('a material filter on a dose tally is an error, not silently dropped (review), from a preset or a converted tally', () => {
  run("addDetectorTally('dose_n')");
  assert.equal(run('S.tallies[0].materialFilter'), '', 'the preset starts with no material filter');
  // an ordinary flux tally with a material filter, then turned into a dose tally
  run("S.tallies[0].dose = ''; S.tallies[0].materialFilter = S.materials[1].id; S.tallies[0].dose = 'n';");
  const P = doseProblems();
  assert.ok(P.some(([s, t]) => s === 'error' && /can't use a material filter/.test(t)), JSON.stringify(P));
  run("S.tallies[0].materialFilter = ''");
  assert.ok(!doseProblems().some(([, t]) => /material filter/.test(t)));
});

if (failed) { console.log(`test_dose_page: ${failed} FAILED`); process.exit(1); }
console.log('test_dose_page: PASS');
