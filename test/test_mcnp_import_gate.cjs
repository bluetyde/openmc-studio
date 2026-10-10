// Import MCNP decks Studio didn't write (Convert > Import MCNP deck...), end to end, through the page's own code:
//   1. studio/openmc_studio/mcnp_import.py reads each deck in test/fixtures/mcnp (openmc_mcnp_adapter), flattens
//      universes, lattices and fill transforms into imported-CSG cells and checks them against OpenMC;
//   2. commitMcnpImport (index.html) commits the report as a new project, which must validate with no errors;
//   3. that project's model.py is compared with the deck, as OpenMC reads each, at thousands of points
//      (test/mcnp_import_check.py): the material (by atom density) must be the same everywhere.
// Needs OPENMC_PYTHON (with openmc and openmc_mcnp_adapter) and OPENMC_CROSS_SECTIONS, as the Python host sees them.
// On Windows the Python steps run in WSL (the page runs here), so WSL's interop is not needed.
// Run: node test/test_mcnp_import_gate.cjs
const fs = require('fs'), vm = require('vm'), path = require('path'), os = require('os'), assert = require('assert');
const {spawnSync, execFileSync} = require('child_process');

const REPO = path.resolve(__dirname, '..');
const WIN = process.platform === 'win32';
const PY = process.env.OPENMC_PYTHON, XS = process.env.OPENMC_CROSS_SECTIONS;
if (!PY || !XS) { console.error('test_mcnp_import_gate: set OPENMC_PYTHON and OPENMC_CROSS_SECTIONS (paths as the Python host sees them).'); process.exit(2); }
const host = p => WIN ? execFileSync('wsl.exe', ['wslpath', '-a', p.split(path.sep).join('/')]).toString().trim() : p;
const q = s => `'${String(s).replace(/'/g, `'\\''`)}'`;
function py(args, cwd) {
  const cmd = `export PATH="$(dirname ${q(PY)}):$PATH" OPENMC_CROSS_SECTIONS=${q(XS)}; cd ${q(host(cwd))} && ${q(PY)} ${args.map(q).join(' ')}`;
  const r = spawnSync(WIN ? 'wsl.exe' : 'bash', [...(WIN ? ['-e', 'bash'] : []), '-lc', cmd], {encoding:'utf8', maxBuffer:1 << 28, timeout:30 * 60 * 1000});
  if (r.status !== 0) throw new Error(`python ${args.join(' ')} failed:\n${(r.stdout || '') + (r.stderr || '')}`.slice(-3000));
  return r.stdout;
}

const html = fs.readFileSync(path.join(REPO, 'studio', 'openmc_studio', 'static', 'index.html'), 'utf8');
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

let failed = 0;
const check = (name, fn) => { try { fn(); console.log(`  [PASS] ${name}`); } catch (e) { failed++; console.log(`  [FAIL] ${name}\n${e.stack}`); } };
const work = fs.mkdtempSync(path.join(os.tmpdir(), 'studio-mcnp-import-'));
const FIX = path.join(REPO, 'test', 'fixtures', 'mcnp');

function importDeck(name) {
  const dir = path.join(work, name.replace(/\W+/g, '_'));
  fs.mkdirSync(dir, {recursive:true});
  py(['-m', 'openmc_studio.mcnp_import', host(path.join(FIX, name)), host(path.join(dir, 'report.json'))], path.join(REPO, 'studio'));
  const report = JSON.parse(fs.readFileSync(path.join(dir, 'report.json'), 'utf8'));
  return {dir, report};
}
function commitAndCompare(name, {cells} = {}) {
  const {dir, report} = importDeck(name);
  assert.ok(report.ok, report.error);
  assert.equal(report.check.agree, report.check.points, 'the import checked itself against OpenMC');
  if (cells !== undefined) assert.equal(report.cells, cells);
  sb.__report = report; sb.__name = name;
  run('S = normalizeProject(sampleModel()); window.__log = []; commitMcnpImport(__report, __name);');
  assert.ok(run('validProject(JSON.parse(JSON.stringify(S)))'), 'the project validates');
  const errors = run("problems().filter(p => p.sev === 'error').map(p => p.text)");
  assert.deepEqual(errors, [], 'no Problems errors');
  fs.writeFileSync(path.join(dir, 'model.py'), run('generate(problems())'));
  const verdict = JSON.parse(py([host(path.join(REPO, 'test', 'mcnp_import_check.py')), host(path.join(FIX, name)),
    host(path.join(dir, 'report.json')), host(dir)], dir).trim().split('\n').pop());
  assert.ok(!verdict.error, verdict.error);
  assert.ok(verdict.compared > 2000, `${verdict.compared} points compared`);
  assert.equal(verdict.differ, 0, JSON.stringify(verdict.examples));
  return report;
}

check('shielding demo: 4 material cells, materials by name, what isn\'t imported is listed', () => {
  const r = commitAndCompare('shielding_demo.mcnp', {cells:4});
  assert.deepEqual(run('S.materials.filter(m => /^MCNP M/.test(m.ref)).map(m => m.name).sort()'),
    ['Concrete, ordinary (NIST)', 'He-3 detector gas (4 atm)', 'Lead', 'Polyethylene, non-borated']);
  assert.deepEqual(r.not_imported.map(x => x.card), ['F34:N']);
  assert.ok(run('window.__log').some(([k, m]) => k === 'warn' && /Not imported: F34:N/.test(m)));
  const src = run('S.sources');
  assert.equal(src.length, 1);
  assert.deepEqual([src[0].space, src[0].energy, src[0].lines], ['point', 'lines', '14.1:1']);
  assert.deepEqual(run('S.tallies.map(t => [t.kind, t.name])'),
    [['cell', 'Detector spectrum (flux)'], ['cell', 'Detector spectrum ((n,p))'], ['mesh', 'FMESH24']]);
  assert.ok(run('S.tallies.filter(t => t.kind === "cell").every(t => t.cells.length === 1)'));
});

check('aperture block: a translated LAT=1 fill laid out element by element', () => {
  const r = commitAndCompare('aperture_block.mcnp');
  assert.ok(r.cells > 200, r.cells);
  assert.ok(run('S.csg.components.every(k => k.cells.length <= 1000)'));
});

check('hand-written deck: a tilted TRCL fill, nested universes, an explicit LAT=1 array, RCC, LIKE n BUT', () => {
  const r = commitAndCompare('outside_features.mcnp', {cells:4});
  assert.ok(r.components.some(k => k.surfaces.some(s => s.type === 'quadric')), 'the tilted rod is a quadric');
});

check('a deck saved by Studio (it carries its project) opens as that project instead', () => {
  const text = run(`(() => { S = normalizeProject(sampleModel()); return withProject('Title\\n1 0 -1\\n\\n1 so 5\\n\\nMODE N\\n', 'c '); })()`);
  sb.__text = text;
  let opened = null;
  run('openProjectText = (t, n) => { window.__opened = n; };');
  run("importMcnpDeck(__text, 'saved.mcnp')");
  opened = run('window.__opened');
  assert.equal(opened, 'saved.mcnp');
});

check('a hexagonal lattice (LAT=2) is laid out element by element and the generated model.py agrees with the deck', () => {
  const r = commitAndCompare('hex_array.mcnp');
  assert.ok(r.cells > 40, r.cells);
  assert.ok(r.notes.some(n => /Hexagonal lattice \(LAT=2\)/.test(n)), JSON.stringify(r.notes));
});

if (failed) { console.log(`test_mcnp_import_gate: ${failed} FAILED`); process.exit(1); }
console.log('test_mcnp_import_gate: PASS');
