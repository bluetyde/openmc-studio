// Test committing imported MCNP physics (sources, settings, cell/mesh tallies, refusals)
// into OpenMC Studio via commitMcnpImport.
// Run: node test/test_mcnp_import_physics.js
const fs = require('fs'), vm = require('vm'), path = require('path'), assert = require('assert');

const html = fs.readFileSync(path.join(__dirname, '..', 'studio', 'openmc_studio', 'static', 'index.html'), 'utf8');
const el = {addEventListener() {}, insertAdjacentHTML() {}, querySelector: () => el, querySelectorAll: () => [], style: {}, dataset: {},
  classList: {add() {}, remove() {}, toggle() {}}, setAttribute() {}, appendChild() {}, append() {}, add() {}, remove() {}, getContext: () => null};
const sb = {console, URLSearchParams, btoa, atob, TextEncoder, escape, unescape, Option: class {}, window: {}, location: {protocol: 'http:', search: ''},
  document: {querySelector: () => el, querySelectorAll: () => [], getElementById: () => el, createElement: () => el, createTextNode: () => el, addEventListener() {}},
  fetch: () => Promise.resolve({ok: false}), ResizeObserver: class { observe() {} disconnect() {} },
  requestAnimationFrame() {}, setTimeout() {}, setInterval() {}};
vm.createContext(sb);
vm.runInContext(html.match(/<script>([\s\S]*?)<\/script>/)[1], sb);
const run = s => vm.runInContext(s, sb);
run('window.__log = []; log = (kind, msg) => window.__log.push([kind, msg]); setOutTab = () => {}; renderAll = () => {};');

const reset = () => {
  run('S = normalizeProject(sampleModel()); window.__log = [];');
};

let failed = 0;
const tests = [];
const test = (name, fn) => tests.push([name, fn]);

test('commitMcnpImport imports sources, settings, tallies and logs refusals', () => {
  reset();
  const report = {
    ok: true,
    source_sha256: 'deadbeef1234',
    adapter: 'openmc_mcnp_adapter',
    bounds_cm: [-20, -20, -20, 20, 20, 20],
    cells: 3,
    check: {agree: 100, points: 100, overlaps: 0},
    materials: [
      {mcnp: 1, name: 'Water', color: '#4a8fd6', density: 1.0, frac: 'ao', comps: 'H:2, O:1', sab: ''}
    ],
    components: [
      {
        key: 'comp_single',
        name: 'Component with cell 5',
        bounds_cm: [-10, -10, -10, 10, 10, 10],
        surfaces: [{id: 1, type: 'sphere', coeffs: {x0: 0, y0: 0, z0: 0, r: 10}}],
        cells: [{name: 'c5', region: {half: '-', s: 1}, mcnp_cell: 5, material_mcnp: 1}],
        display: null
      },
      {
        key: 'comp_lattice',
        name: 'Component with lattice cell 7',
        bounds_cm: [-20, -20, -20, 20, 20, 20],
        surfaces: [{id: 2, type: 'sphere', coeffs: {x0: 0, y0: 0, z0: 0, r: 20}}],
        cells: [
          {name: 'c7_elem1', region: {half: '-', s: 2}, mcnp_cell: 7, material_mcnp: 1},
          {name: 'c7_elem2', region: {half: '-', s: 2}, mcnp_cell: 7, material_mcnp: 1}
        ],
        display: null
      }
    ],
    sources: [
      {
        name: 'Deck Source',
        particle: 'neutron',
        strength: 1,
        space: 'point',
        x: 1.5,
        y: 2.5,
        z: 3.5,
        angle: 'isotropic',
        energy: 'lines',
        lines: '14.1:1'
      }
    ],
    run_settings: {
      nps: 50000,
      photon: false
    },
    tallies: [
      {
        kind: 'cell',
        name: 'Tally on 5',
        mcnp_card: 'F4',
        cells_mcnp: [5],
        particle: 'neutron',
        scores: ['flux'],
        ebins: ''
      },
      {
        kind: 'cell',
        name: 'Tally on 7',
        mcnp_card: 'F14',
        cells_mcnp: [7],
        particle: 'neutron',
        scores: ['flux'],
        ebins: ''
      },
      {
        kind: 'cell',
        name: 'Tally on 9',
        mcnp_card: 'F24',
        cells_mcnp: [9],
        particle: 'neutron',
        scores: ['flux'],
        ebins: ''
      },
      {
        kind: 'mesh',
        name: 'FMESH4',
        nx: 10,
        ny: 10,
        nz: 10,
        lx: -5,
        ly: -5,
        lz: -5,
        ux: 5,
        uy: 5,
        uz: 5,
        particle: 'neutron',
        scores: ['flux'],
        ebins: ''
      }
    ],
    not_imported: [
      {card: 'WWN1:N', line: 42, reason: 'not imported (Studio has no equivalent yet)'},
      {card: 'FM34', line: 55, reason: 'FM34 multiplier isn\'t supported'}
    ],
    import_notes: ['F4: MCNP divides by the cell volume; Studio\'s cell tallies are integrated over the cell (like SD 1)']
  };

  sb.__report = report;
  run('commitMcnpImport(__report, "test_synthetic.mcnp");');

  // 1. Source replaced the old ones with the given fields
  const sources = run('S.sources');
  assert.equal(sources.length, 1, 'Should have exactly 1 source');
  assert.equal(sources[0].name, 'Deck Source');
  assert.equal(sources[0].particle, 'neutron');
  assert.equal(sources[0].space, 'point');
  assert.equal(sources[0].x, 1.5);
  assert.equal(sources[0].y, 2.5);
  assert.equal(sources[0].z, 3.5);
  assert.equal(sources[0].energy, 'lines');
  assert.equal(sources[0].lines, '14.1:1');

  // 2. particles computed from nps (batches = 10 from sampleModel DEFAULT_SETTINGS, so 50000 / 10 = 5000)
  const particles = run('S.settings.particles');
  const batches = run('S.settings.batches');
  assert.equal(particles, Math.max(1, Math.round(50000 / batches)));

  // 3. Tally on 5 maps to the right Studio cell id
  const tallies = run('S.tallies');
  const cellTally = tallies.find(t => t.name === 'Tally on 5');
  assert.ok(cellTally, 'Tally on 5 should be present');
  const comp5 = run('S.csg.components.find(k => k.name === "Component with cell 5")');
  const expectedCellId = comp5.cells[0].id;
  assert.deepEqual(cellTally.cells, [expectedCellId]);
  assert.strictEqual(cellTally.cells_mcnp, undefined, 'cells_mcnp should be dropped');
  assert.strictEqual(cellTally.fm_material, undefined, 'fm_material should be dropped');
  assert.strictEqual(cellTally.mcnp_card, undefined, 'mcnp_card should be dropped');

  // 4. Tallies on 7 and 9 are refused with the two reasons and logged
  assert.ok(!tallies.some(t => t.name === 'Tally on 7'), 'Tally on 7 should be refused');
  assert.ok(!tallies.some(t => t.name === 'Tally on 9'), 'Tally on 9 should be refused');

  const logs = run('window.__log');
  const warnLogs = logs.filter(([k]) => k === 'warn').map(([, m]) => m);

  assert.ok(
    warnLogs.some(m => m.includes('Tally F14 ("Tally on 7") not imported: ') && m.includes("cell 7 is repeated in a lattice or universe (2 times); tallies over repeated cells aren't imported yet")),
    'Refusal for repeated cell 7 must be logged'
  );
  assert.ok(
    warnLogs.some(m => m.includes('Tally F24 ("Tally on 9") not imported: ') && m.includes("cell 9 isn't an imported material cell (void, outside, or not in the deck)")),
    'Refusal for missing cell 9 must be logged'
  );

  // 5. Mesh tally is present
  const meshTally = tallies.find(t => t.name === 'FMESH4');
  assert.ok(meshTally, 'Mesh tally FMESH4 should be present');
  assert.equal(meshTally.kind, 'mesh');
  assert.equal(meshTally.nx, 10);

  // 6. validProject is true
  assert.ok(run('validProject(S)'), 'Project must be valid according to validProject');

  // 7. Each not_imported entry is logged as warn
  assert.ok(
    warnLogs.some(m => m.includes('Not imported: WWN1:N (line 42): not imported (Studio has no equivalent yet)')),
    'not_imported entry WWN1:N must be logged'
  );
  assert.ok(
    warnLogs.some(m => m.includes('Not imported: FM34 (line 55): FM34 multiplier isn\'t supported')),
    'not_imported entry FM34 must be logged'
  );

  // 8. import_notes logged as info
  const infoLogs = logs.filter(([k]) => k === 'info').map(([, m]) => m);
  assert.ok(
    infoLogs.some(m => m.includes('F4: MCNP divides by the cell volume; Studio\'s cell tallies are integrated over the cell (like SD 1)')),
    'import_notes entry must be logged as info'
  );
});

test('no sources in report: keeps old source and logs info', () => {
  reset();
  const oldSource = run('S.sources[0]');

  const reportNoSrc = {
    ok: true,
    source_sha256: 'feedface5678',
    adapter: 'openmc_mcnp_adapter',
    bounds_cm: [-10, -10, -10, 10, 10, 10],
    cells: 1,
    check: {agree: 10, points: 10, overlaps: 0},
    materials: [{mcnp: 1, name: 'Water', color: '#4a8fd6', density: 1.0, frac: 'ao', comps: 'H:2, O:1', sab: ''}],
    components: [
      {
        key: 'comp1',
        name: 'Comp 1',
        bounds_cm: [-10, -10, -10, 10, 10, 10],
        surfaces: [{id: 1, type: 'sphere', coeffs: {x0: 0, y0: 0, z0: 0, r: 10}}],
        cells: [{name: 'c5', region: {half: '-', s: 1}, mcnp_cell: 5, material_mcnp: 1}],
        display: null
      }
    ],
    sources: [],
    run_settings: {},
    tallies: [],
    not_imported: []
  };

  sb.__report = reportNoSrc;
  run('commitMcnpImport(__report, "nosrc.mcnp");');

  const curSources = run('S.sources');
  assert.equal(curSources.length, 1);
  assert.equal(curSources[0].id, oldSource.id, 'Old source must be preserved');

  const logs = run('window.__log');
  assert.ok(
    logs.some(([k, m]) => k === 'info' && m.includes("The deck's source wasn't imported; the project keeps its current source.")),
    'Info message about keeping current source must be logged'
  );
  assert.ok(run('validProject(S)'), 'Project must be valid');
});

for (const [name, fn] of tests) {
  try {
    fn();
    console.log(`  [PASS] ${name}`);
  } catch (e) {
    failed++;
    console.log(`  [FAIL] ${name}\n${e.stack}`);
  }
}

if (failed) {
  console.log(`test_mcnp_import_physics: ${failed} FAILED`);
  process.exit(1);
}
console.log('test_mcnp_import_physics: PASS');
