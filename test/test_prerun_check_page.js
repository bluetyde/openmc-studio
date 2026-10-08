// The page's own list of errors (problems() in static/index.html) against the golden file test/fixtures/prerun/cases.json that
// the Python list (studio/openmc_studio/prerun_check.py) is held to by test/test_prerun_check.py. Each case is a project and the
// errors the page gives it, as sorted "kind:id" keys. This test runs the page on every case and fails if the golden file is out
// of date; `node test/test_prerun_check_page.js --write` rewrites it after a deliberate change to the page's rules.
// Run: node test/test_prerun_check_page.js
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
const base = () => JSON.parse(vm.runInContext('JSON.stringify(sampleModel())', sb));
const pageErrors = project => {
  sb.__p = JSON.stringify(project);
  return JSON.parse(vm.runInContext(`S = JSON.parse(__p); JSON.stringify(problems().filter(p => p.sev === 'error').map(p => p.sel ? p.sel.kind + ':' + (p.sel.id ?? '') : '-'))`, sb)).sort();
};

const eig = p => {   // an eigenvalue run with fuel in a part
  p.settings.runMode = 'eigenvalue'; p.settings.batches = 20; p.settings.inactive = 5;
  p.materials.push({id: 'm9', name: 'UO2', color: '#aaa', density: 10.4, frac: 'ao', comps: 'U235:0.035, U238:0.965, O16:2', sab: ''});
  p.parts.push({...p.parts[0], id: 'p9', name: 'Fuel', material: 'm9', shape: 'sphere', r: 3, x: 0, y: 0, z: 0});
  return p;
};
const src = (p, o) => { Object.assign(p.sources[0], o); return p; };
const tal = (p, o, i = 0) => { Object.assign(p.tallies[i], o); return p; };
const part = (p, o) => { Object.assign(p.parts[0], o); return p; };
const mat = (p, o) => { Object.assign(p.materials[0], o); return p; };
const set = (p, o) => { Object.assign(p.settings, o); return p; };

// [name, mutate]. A case with no errors is as important as one with: it is what stops the Python list from refusing a run the page allows.
const CASES = [
  ['baseline: the demo model', p => p],
  ['eigenvalue with fuel', eig],
  ['world size zero', p => set(p, {worldR: 0})],
  ['periodic boundary on a sphere world', p => set(p, {worldBC: 'periodic', worldShape: 'sphere'})],
  ['world fill points at a deleted material', p => set(p, {worldFill: 'm99'})],
  ['particles zero', p => set(p, {particles: 0})],
  ['batches not whole', p => set(p, {batches: 1.5})],
  ['seed zero', p => set(p, {seed: 0})],
  ['tracks to write negative', p => set(p, {maxTracks: -1})],
  ['track entry unreadable', p => set(p, {track: 'abc'})],
  ['eigenvalue without fuel', p => set(p, {runMode: 'eigenvalue', batches: 20, inactive: 5})],
  ['eigenvalue, inactive not below batches', p => set(eig(p), {inactive: 20})],
  ['eigenvalue with fission neutrons off', p => set(eig(p), {fissionNeutrons: false})],
  ['eigenvalue with a photon source', p => src(eig(p), {particle: 'photon'})],
  ['eigenvalue with a dose tally', p => tal(eig(p), {dose: 'n'})],
  ['material density zero', p => mat(p, {density: 0})],
  ['material composition unreadable', p => mat(p, {comps: 'H;2'})],
  ['material composition empty', p => mat(p, {comps: ''})],
  ['material amount zero', p => mat(p, {comps: 'H:0, C:1'})],
  ['used material with an element that has no natural isotopes', p => { p.materials[1].comps = 'Pu:1'; return p; }],
  ['part center not a number', p => part(p, {x: null})],
  ['part rotation not a number', p => part(p, {rx: 'a'})],
  ['part size zero', p => part(p, {r: 0})],
  ['part material deleted', p => part(p, {material: 'm99'})],
  ['part material pending', p => part(p, {materialPending: true})],
  ['no source', p => { p.sources = []; return p; }],
  ['box source inverted', p => src(p, {space: 'box', x0: 5, x1: -5})],
  ['point source outside the world', p => src(p, {x: 500})],
  ['point source center not a number', p => src(p, {y: null})],
  ['point source exactly on the world boundary', p => src(p, {x: 100})],
  ['sphere source radius zero', p => src(p, {space: 'sphere', r: 0})],
  ['cylinder source height zero', p => src(p, {space: 'cylinder', h: 0})],
  ['beam direction zero', p => src(p, {angle: 'mono', u: 0, v: 0, w: 0})],
  ['source lines unreadable', p => src(p, {lines: '14.1;1'})],
  ['source lines empty', p => src(p, {lines: ''})],
  ['source line energy zero', p => src(p, {lines: '0:1'})],
  ['Watt parameter zero', p => src(p, {energy: 'watt', wa: 0})],
  ['Maxwell temperature zero', p => src(p, {energy: 'maxwell', theta: 0})],
  ['uniform energy range inverted', p => src(p, {energy: 'uniform', emin: 2, emax: 1})],
  ['tabulated edges unreadable', p => src(p, {energy: 'tabulated', tab_e: 'a, b'})],
  ['tabulated probabilities wrong count', p => src(p, {energy: 'tabulated', tab_p: '0.5, 0.5'})],
  ['source strength zero', p => src(p, {strength: 0})],
  ['cell tally with no cells', p => tal(p, {cells: []})],
  ['cell tally lists a deleted part', p => tal(p, {cells: ['p99']})],
  ['surface tally with no parts', p => tal(p, {kind: 'surface', surfaces: [], scores: ['current']})],
  ['surface tally scoring flux', p => tal(p, {kind: 'surface', surfaces: ['p1'], scores: ['flux']})],
  ['surface tally lists a deleted part', p => tal(p, {kind: 'surface', surfaces: ['p99'], scores: ['current']})],
  ['mesh bins zero', p => tal(p, {nx: 0}, 1)],
  ['mesh corners inverted', p => tal(p, {lx: 50, ux: -50}, 1)],
  ['cylindrical mesh bins zero', p => tal(p, {meshGeom: 'cylindrical', nr: 0, nphi: 4, nz: 4, rmin: 0, rmax: 5, zmin: 0, zmax: 5}, 1)],
  ['cylindrical mesh radius range inverted', p => tal(p, {meshGeom: 'cylindrical', nr: 2, nphi: 4, nz: 4, rmin: 5, rmax: 1, zmin: 0, zmax: 5}, 1)],
  ['cylindrical mesh z range inverted', p => tal(p, {meshGeom: 'cylindrical', nr: 2, nphi: 4, nz: 4, rmin: 0, rmax: 5, zmin: 5, zmax: 1}, 1)],
  ['photon dose with photons off', p => tal(p, {dose: 'np'})],
  ['dose with a detector response', p => tal(p, {dose: 'n', detector: 'he3', responseMat: 'm3', scores: ['flux']})],
  ['dose with a material filter', p => tal(p, {dose: 'n', materialFilter: 'm1'})],
  ['macroscopic detector without a material', p => tal(p, {detector: 'custom', responseScale: 'macro', responseMat: '', scores: ['flux']})],
  ['microscopic detector without a nuclide', p => tal(p, {detector: 'custom', responseScale: 'micro', responseNuc: '', scores: ['flux']})],
  ['detector with a score other than flux', p => tal(p, {detector: 'he3', responseMat: 'm3'})],
  ['tally with no scores', p => tal(p, {scores: []})],
  ['energy bins not rising', p => tal(p, {ebins: '5, 1'})],
  ['several errors at once', p => set(src(part(p, {r: 0}), {strength: 0}), {particles: 0})],
  ['he-3 detector with no material named: the page picks the He-3 one', p => tal(p, {detector: 'he3', responseMat: '', scores: ['flux']})],
  ['he-3 detector and no He-3 material to pick', p => { p.materials = p.materials.filter(m => m.id !== 'm3'); p.parts = p.parts.filter(x => x.material !== 'm3'); p.tallies[0].cells = []; return tal(p, {detector: 'he3', responseMat: '', scores: ['flux'], cells: ['world']}); }],
  ['tabulated source with a leading zero probability', p => src(p, {energy: 'tabulated', tab_p: '0, 0.2, 0.5, 0.3'})],
  ['depletion with a burnable fuel in an eigenvalue run', p => { eig(p); set(p, {depletion: true}); p.materials.find(m => m.id === 'm9').burnable = true; return p; }],
  ['depletion in a fixed-source run', p => { eig(p); set(p, {depletion: true, runMode: 'fixed source'}); p.materials.find(m => m.id === 'm9').burnable = true; return p; }],
  ['depletion with no burnable material', p => set(eig(p), {depletion: true})],
  ['burnable material with no heavy metal', p => { eig(p); set(p, {depletion: true}); p.materials.find(m => m.id === 'm9').burnable = true; p.materials[0].burnable = true; return p; }],
  ['burnable material that fills the world', p => { eig(p); set(p, {depletion: true, worldFill: 'm9'}); p.materials.find(m => m.id === 'm9').burnable = true; return p; }],
  ['depletion power zero', p => { eig(p); set(p, {depletion: true, depPower: 0}); p.materials.find(m => m.id === 'm9').burnable = true; return p; }],
  ['depletion time steps unreadable', p => { eig(p); set(p, {depletion: true, depSteps: 'a, b'}); p.materials.find(m => m.id === 'm9').burnable = true; return p; }],
  ['depletion time step of zero', p => { eig(p); set(p, {depletion: true, depSteps: '1, 0'}); p.materials.find(m => m.id === 'm9').burnable = true; return p; }],
  ['depletion with no time steps', p => { eig(p); set(p, {depletion: true, depSteps: ''}); p.materials.find(m => m.id === 'm9').burnable = true; return p; }],
  ['depletion with an unknown integrator', p => { eig(p); set(p, {depletion: true, depIntegrator: 'Bogus'}); p.materials.find(m => m.id === 'm9').burnable = true; return p; }],
  ['depletion chain level zero', p => { eig(p); set(p, {depletion: true, depReduce: 0}); p.materials.find(m => m.id === 'm9').burnable = true; return p; }],
  ['burnable material in imported CAD geometry', p => { eig(p); set(p, {depletion: true}); p.materials.find(m => m.id === 'm9').burnable = true;
    p.csg = {components: [{id: 'k1', name: 'Block', bounds: [40, 40, 40, 50, 50, 50], cells: [{id: 'k1c1', name: 'block cell', material: 'm9'}]}]}; return p; }],
  ['burnable thorium fuel', p => { eig(p); set(p, {depletion: true}); const m = p.materials.find(x => x.id === 'm9'); m.comps = 'Th:1, O:2'; m.burnable = true; return p; }],
  ['burnable flag with depletion off changes nothing', p => { eig(p); p.materials.find(m => m.id === 'm9').burnable = true; p.materials[0].burnable = true; return p; }],
  // runs the page allows
  ['he-3 detector tally, flux only', p => tal(p, {detector: 'he3', responseMat: 'm3', scores: ['flux']})],
  ['surface tally, current', p => tal(p, {kind: 'surface', surfaces: ['p1'], scores: ['current']})],
  ['cylindrical mesh, valid', p => tal(p, {meshGeom: 'cylindrical', nr: 2, nphi: 4, nz: 4, rmin: 0, rmax: 5, zmin: 0, zmax: 5}, 1)],
  ['tabulated source, valid', p => src(p, {energy: 'tabulated'})],
  ['Watt source, valid', p => src(p, {energy: 'watt'})],
  ['uniform source, valid', p => src(p, {energy: 'uniform'})],
  ['box source, valid', p => src(p, {space: 'box'})],
  ['sphere source, valid', p => src(p, {space: 'sphere', r: 5, rin: 1})],
  ['dose tally in a fixed-source run', p => tal(p, {dose: 'n'})],
];

// The cases the page lets through: Python must let them through too.
const ALLOWED = new Set(['baseline: the demo model', 'eigenvalue with fuel', 'he-3 detector tally, flux only', 'surface tally, current', 'cylindrical mesh, valid',
  'tabulated source, valid', 'Watt source, valid', 'uniform source, valid', 'box source, valid', 'sphere source, valid', 'dose tally in a fixed-source run',
  'he-3 detector with no material named: the page picks the He-3 one', 'tabulated source with a leading zero probability',
  'depletion with a burnable fuel in an eigenvalue run', 'burnable thorium fuel', 'burnable flag with depletion off changes nothing']);
const build = () => CASES.map(([name, mutate]) => { const project = mutate(base()); return {name, project, errors: pageErrors(project)}; });

if (process.argv.includes('--write')) {
  const out = path.join(__dirname, 'fixtures', 'prerun', 'cases.json');
  fs.mkdirSync(path.dirname(out), {recursive: true});
  fs.writeFileSync(out, JSON.stringify(build(), null, 1) + '\n');
  console.log(`wrote ${out}`);
  process.exit(0);
}

let failed = 0;
const tests = [];
const test = (name, fn) => tests.push([name, fn]);

test('every error case gives the page at least one error, every "allowed" case none', () => {
  for (const c of build()) {
    const expectOk = ALLOWED.has(c.name);
    if (expectOk) assert.deepEqual(c.errors, [], `${c.name}: the page should allow this`);
    else assert.ok(c.errors.length > 0, `${c.name}: the page should refuse this`);
  }
});

test('the golden file is what the page gives now', () => {
  const golden = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures', 'prerun', 'cases.json'), 'utf8'));
  const now = build();
  assert.equal(golden.length, now.length, 'a case was added or removed: rerun with --write');
  golden.forEach((g, i) => {
    assert.equal(g.name, now[i].name);
    assert.deepEqual(g.project, now[i].project, `${g.name}: the project changed: rerun with --write`);
    assert.deepEqual(g.errors, now[i].errors, `${g.name}: the page's errors changed: rerun with --write, then make prerun_check.py agree`);
  });
});

(async () => {
  for (const [name, fn] of tests) {
    try { await fn(); console.log('  [PASS]', name); }
    catch (e) { failed++; console.log('  [FAIL]', name, '\n   ', e.message); }
  }
  console.log(failed ? `test_prerun_check_page: ${failed} FAILED` : 'test_prerun_check_page: PASS');
  process.exit(failed ? 1 : 0);
})();
