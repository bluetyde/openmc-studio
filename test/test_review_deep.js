// Codex's deep review (2026-09-25), page side:
//  - a tabulated spectrum's bin probabilities reach OpenMC as densities, so unequal bins keep their share
//    (sampled with OpenMC itself, in WSL, when it is there);
//  - the offline MCNP script keeps a positive lower energy edge (E cards list upper bounds from 0);
//  - opening a deck waits for its translation, but not on behalf of a project opened meanwhile, and not over
//    edits made while it waited.
// Run: node test/test_review_deep.js   (OPENMC_WSL_PYTHON overrides the WSL interpreter)
const fs = require('fs'), vm = require('vm'), path = require('path'), assert = require('assert');
const {spawnSync} = require('child_process');

const html = fs.readFileSync(path.join(__dirname, '..', 'studio', 'openmc_studio', 'static', 'index.html'), 'utf8');
const FIX = path.join(__dirname, 'fixtures', 'mcnp');
const el = {addEventListener() {}, insertAdjacentHTML() {}, querySelector: () => el, querySelectorAll: () => [], style: {}, dataset: {},
  classList: {add() {}, remove() {}, toggle() {}}, setAttribute() {}, appendChild() {}, append() {}, add() {}, getContext: () => null};
const timers = [];
const sb = {console, URLSearchParams, btoa, atob, TextEncoder, escape, unescape, Option: class {}, window: {}, location: {protocol: 'http:', search: ''},
  document: {querySelector: () => el, querySelectorAll: () => [], getElementById: () => el, createElement: () => el, createTextNode: () => el, addEventListener() {}},
  fetch: () => Promise.resolve({ok: false}), ResizeObserver: class { observe() {} disconnect() {} },
  requestAnimationFrame() {}, setTimeout: fn => { timers.push(fn); return timers.length; }, clearTimeout() {}, setInterval() {}};
vm.createContext(sb);
vm.runInContext(html.match(/<script>([\s\S]*?)<\/script>/)[1], sb);
const run = s => vm.runInContext(s, sb);
run('window.__log = []; log = (kind, msg) => window.__log.push([kind, msg]); setOutTab = () => {}; renderAll = () => {};');

let failed = 0;
const tests = [];
const test = (name, fn) => tests.push([name, fn]);

test('a tabulated spectrum is written as bin probabilities through _histogram', () => {
  run(`S = normalizeProject(sampleModel()); const s = S.sources[0]; s.energy = 'tabulated'; s.tab_e = '0, 1, 3'; s.tab_p = '0.5, 0.5';`);
  const py = run('generate(problems())');
  assert.match(py, /def _histogram\(edges, probs\):/);
  assert.match(py, /\.energy = _histogram\(\[0\.0, 1e6, 3e6\], \[0\.5, 0\.5\]\)/);
  assert.match(py, /p \/ \(hi - lo\) for p, lo, hi in zip\(probs, edges, edges\[1:\]\)/);
});

test('...and OpenMC samples it 50/50, not by bin width (0-1-3 MeV)', () => {
  const py = run('generate(problems())');
  const helper = py.slice(py.indexOf('def _histogram'), py.indexOf('\n\n', py.indexOf('def _histogram')));
  const script = ['import numpy as np, openmc', helper,
    'd = _histogram([0.0, 1e6, 3e6], [0.5, 0.5])',
    'e = d.sample(200000, seed=7)',
    'print(float(np.mean(e < 1e6)))'].join('\n');
  const exe = process.env.OPENMC_WSL_PYTHON || '/root/miniconda3/envs/openmc-mcnp/bin/python';
  const r = spawnSync('wsl', ['-e', exe, '-c', script], {encoding: 'utf8', timeout: 120000});
  if (r.status !== 0 || !r.stdout.trim()) { console.log(`    (no OpenMC in WSL here, skipped: ${(r.stderr || r.error || '').toString().trim().split('\n').pop()})`); return; }
  const below = +r.stdout.trim();
  assert.ok(Math.abs(below - 0.5) < 0.005, `fraction below 1 MeV ${below}`);
});

test('the MCNP equivalent panel keeps a positive lower energy edge (cells and meshes)', () => {
  run(`S = normalizeProject(sampleModel()); S.tallies = [{id:'t9', name:'bins', kind:'cell', cells:[S.parts[0].id], scores:['flux'], ebins:'1, 2, 3'}];
    normalizeProject(S);`);
  const eCards = () => run('mcnpTally(S.tallies[0])').split('\n').filter(l => /^(E\d|\s+EMESH=)/.test(l)).map(l => l.trim());
  assert.deepEqual(eCards(), ['E4 1 2 3'], 'MCNP bins run from 0: the 1 MeV edge must be written');
  run(`S.tallies[0].ebins = '0, 2, 3'`);
  assert.deepEqual(eCards(), ['E4 2 3']);
  run(`S.tallies[0].kind = 'mesh'; S.tallies[0].ebins = '1, 2'`);
  assert.deepEqual(eCards(), ['EMESH=1 2']);
});

// Opening a deck saved by Studio: the project inside it loads, then (once model.mcnp has translated it) the hand
// edits in the deck come back. The translation is controlled here: fresh() turns true when we say.
async function openDeckWhileSomethingHappens(during) {
  const deckA = fs.readFileSync(path.join(FIX, 'shielding_demo.mcnp'), 'utf8');
  sb.__projA = JSON.parse(fs.readFileSync(path.join(FIX, 'shielding_demo.openmc-studio.json'), 'utf8'));
  sb.__projA.settings.name = 'Project A';
  sb.__deckA = deckA;
  // A's saved deck, with a hand edit: Lead's density changed in the deck
  run(`S = normalizeProject(JSON.parse(JSON.stringify(__projA)));`);
  const lead = run("S.materials.find(m => /lead/i.test(m.name))");
  assert.ok(lead, 'the fixture has lead');
  const saved = run(`withProject(__deckA, 'c ')`);
  const dens = String(lead.density);
  // edit the density on Lead's cell cards: the deck writes it as a negative number (g/cm3)
  const edited = saved.replace(new RegExp(`(^\\d+\\s+\\d+\\s+)-${dens.replace('.', '\\.')}(\\s)`, 'm'), '$1-12.5$2');
  assert.notEqual(edited, saved, 'the density was edited in the deck');
  // the model.mcnp tab: translate = hand back __deckA for whatever project is open, when we release it
  run(`LOCAL.on = true; LIVE.report = null; LIVE.sentScript = null; LIVE.failure = null; LIVE.pending = false;
    renderMcnp = () => {}; setMcnpStatus = () => {}; pollMcnpProgress = () => {}; stopMcnpProgress = () => {}; liveMcnpTick = () => {};
    window.__release = []; api = () => new Promise(res => window.__release.push(res));`);
  const opening = sb.openProjectText(edited, 'Project A.mcnp');
  await new Promise(r => setImmediate(r));
  await during();
  // the translation (of A, requested when A opened) comes back; then let the wait loop tick
  run(`window.__release.forEach(res => res({ok: true, deck: __deckA, name: 'shielding_demo'}))`);
  for (let k = 0; k < 5; k++) { await new Promise(r => setImmediate(r)); timers.splice(0).forEach(f => f()); await new Promise(r => setImmediate(r)); }
  await opening;
  return {leadName: lead.name};
}

test('opening project B while A\'s deck waits: A\'s hand edits never touch B (review: B\'s lead density overwritten)', async () => {
  const {leadName} = await openDeckWhileSomethingHappens(async () => {
    // B: the same model with the same IDs, only its lead differs, and its own translation comes back fresh
    const b = JSON.parse(JSON.stringify(sb.__projA));
    b.materials.find(m => /lead/i.test(m.name)).density = 10.5;
    await sb.openProjectText(JSON.stringify(b), 'Project B.openmc-studio.json');
    run('S.settings.name = "Project A"; sendLive(true);');  // named alike, so nothing but the open itself tells them apart
  });
  const d = run(`S.materials.find(m => m.name === ${JSON.stringify(leadName)}).density`);
  assert.equal(d, 10.5, 'B keeps its own lead density');
  assert.ok(!run('window.__log').some(([k, m]) => k === 'ok' && /Imported Project A/.test(m)), JSON.stringify(run('window.__log')));
});

test('editing A while its deck waits: the wait gives up with a note instead of undoing the edit', async () => {
  const {leadName} = await openDeckWhileSomethingHappens(async () => { run('S.settings.particles = 4321;'); });
  assert.equal(run('S.settings.particles'), 4321);
  assert.equal(run(`S.materials.find(m => m.name === ${JSON.stringify(leadName)}).density`), 11.35);
  assert.ok(run('window.__log').some(([k, m]) => k === 'warn' && /project changed while Project A\.mcnp waited/.test(m)), JSON.stringify(run('window.__log')));
});

test('with nothing in between, the deck\'s hand edit comes back as before', async () => {
  const {leadName} = await openDeckWhileSomethingHappens(async () => {});
  assert.equal(run(`S.materials.find(m => m.name === ${JSON.stringify(leadName)}).density`), 12.5, JSON.stringify(run('window.__log')));
});

let done = false;  // a wait that never ends would otherwise leave Node with nothing to do, and exit 0
process.on('exit', () => { if (!done) { console.log('test_review_deep: did not finish (a wait never ended)'); process.exitCode = 1; } });
(async () => {
  for (const [name, fn] of tests) {
    try { run('window.__log = [];'); await fn(); console.log(`  [PASS] ${name}`); }
    catch (e) { failed++; console.log(`  [FAIL] ${name}\n${e.stack}`); }
  }
  done = true;
  if (failed) { console.log(`test_review_deep: ${failed} FAILED`); process.exit(1); }
  done = true;
  console.log('test_review_deep: PASS');
})();
