// Round trips, part 3: the whole project inside a saved model.py / model.mcnp, and Open project reading it back
// (then taking back hand edits made to the file).
// Run: node test/test_embed_project.js
const fs = require('fs'), vm = require('vm'), path = require('path'), assert = require('assert');

const html = fs.readFileSync(path.join(__dirname, '..', 'studio', 'openmc_studio', 'static', 'index.html'), 'utf8');
const FIX = path.join(__dirname, 'fixtures', 'mcnp');
const el = {addEventListener() {}, insertAdjacentHTML() {}, querySelector: () => el, querySelectorAll: () => [], style: {}, dataset: {},
  classList: {add() {}, remove() {}, toggle() {}}, setAttribute() {}, appendChild() {}, append() {}, add() {}, getContext: () => null};
const sb = {console, URLSearchParams, btoa, atob, TextEncoder, escape, unescape, Option: class {}, window: {}, location: {protocol: 'http:', search: ''},
  document: {querySelector: () => el, querySelectorAll: () => [], getElementById: () => el, createElement: () => el, createTextNode: () => el, addEventListener() {}},
  fetch: () => Promise.resolve({ok: false}), ResizeObserver: class { observe() {} disconnect() {} },
  requestAnimationFrame() {}, setTimeout() {}, setInterval() {}};
vm.createContext(sb);
vm.runInContext(html.match(/<script>([\s\S]*?)<\/script>/)[1], sb);
const run = s => vm.runInContext(s, sb);
run('window.__log = []; log = (kind, msg) => window.__log.push([kind, msg]); setOutTab = () => {}; renderAll = () => {};');

let failed = 0;
const tests = [];
const test = (name, fn) => tests.push([name, fn]);
const reset = () => run("S = normalizeProject(sampleModel()); S.settings.name = 'Shield µSv demo'; window.__log = [];");
const projectJson = () => run('JSON.stringify(S)');

test('the block round-trips the project exactly, with non-ASCII names', () => {
  const want = projectJson(), text = run("withProject(generate(problems()), '# ')");
  assert.equal(JSON.stringify(sb.readProjectBlock(text)), want);
});

test('block lines are Python comments and MCNP comment cards within 128 columns', () => {
  const py = run("projectBlock('# ')"), mc = run("projectBlock('c ')");
  assert.ok(py.every(l => l.startsWith('# @studio-project-v1')));
  assert.ok(mc.every(l => l.startsWith('c @studio-project-v1') && l.length <= 128), Math.max(...mc.map(l => l.length)));
  assert.ok(py.length > 3);
});

test('Open project restores the project saved inside a model.py', async () => {
  const want = projectJson(), text = run("savedScript()");
  run("S = normalizeProject(sampleModel()); S.parts.pop(); S.settings.particles = 1;");  // a different project open now
  await sb.openProjectText(text, 'model.py');
  assert.equal(projectJson(), want);
  assert.ok(run('window.__log').some(([k, m]) => k === 'ok' && /project saved inside model.py/.test(m)));
});

test('...and takes back numbers edited in the file after it was saved', async () => {
  const text = run("savedScript()").replace(/settings\.particles = \d+/, 'settings.particles = 23456');
  run("S = normalizeProject(sampleModel()); S.parts.pop();");
  await sb.openProjectText(text, 'model.py');
  assert.equal(run('S.settings.particles'), 23456);
  assert.equal(run('S.settings.name'), 'Shield µSv demo', 'the rest is the embedded project');
  assert.ok(run('window.__log').some(([, m]) => /1 change applied/.test(m)), JSON.stringify(run('window.__log')));
});

test('the patch import ignores the embedded block', () => {
  const r = sb.importScriptPatch(run('savedScript()'), 'model.py');
  assert.deepEqual([r.edits.length, r.skipped.length], [0, 0]);
});

test('a saved deck carries the project too, and its import ignores the block', async () => {
  sb.__deck = fs.readFileSync(path.join(FIX, 'shielding_demo.mcnp'), 'utf8');
  sb.__project = fs.readFileSync(path.join(FIX, 'shielding_demo.openmc-studio.json'), 'utf8');
  run(`S = normalizeProject(JSON.parse(__project)); LOCAL.on = true;
    (() => { const P = problems(); LIVE.report = {deck: __deck}; LIVE.sentScript = mcnpScript(P); LIVE.failure = null;
      LIVE.pending = false; LIVE.ctx = mcnpContext(P, buildScript(P, false, MCNP_OPTS)); })();`);
  const want = projectJson(), saved = run("withProject(__deck, 'c ')");
  assert.equal(JSON.stringify(sb.readProjectBlock(saved)), want);
  const r = sb.planMcnpPatch(saved);
  assert.deepEqual([r.refused, r.edits.length, r.skipped.length], [undefined, 0, 0]);
});

// Review: Save .mcnp paired the last deck with the project as it is now, so saving while an edit was still
// translating (or after it failed) wrote a deck and a project from different revisions.
async function translateWithEditDuringIt(edit) {
  sb.__deck = fs.readFileSync(path.join(FIX, 'shielding_demo.mcnp'), 'utf8');
  sb.__project = fs.readFileSync(path.join(FIX, 'shielding_demo.openmc-studio.json'), 'utf8');
  run(`S = normalizeProject(JSON.parse(__project)); LOCAL.on = true; LIVE.report = null; LIVE.deckProject = null;
    renderMcnp = () => {}; setMcnpStatus = () => {}; pollMcnpProgress = () => {}; stopMcnpProgress = () => {}; liveMcnpTick = () => {};
    api = () => new Promise(res => { window.__answer = res; });`);
  const sent = sb.sendLive(true), want = projectJson();
  run(edit);                                                       // the user edits while MCNPy works
  run(`window.__answer({ok: true, deck: __deck, name: 'shielding_demo'})`);
  await sent;
  return want;
}
test('a deck saved while newer edits are translating carries the project it was made from', async () => {
  const want = await translateWithEditDuringIt('S.settings.particles = 333;');
  run('LIVE.pending = true;');                                     // the next translation is under way
  const s = sb.savedMcnp(), st = sb.readProjectBlock(s.text).settings;
  assert.equal(JSON.stringify(sb.readProjectBlock(s.text)), want);
  assert.notEqual(st.particles, 333);
  assert.equal(st.particles * st.batches, +s.text.match(/^NPS\s+(\d+)/m)[1], 'the deck and its project agree (NPS = particles x batches)');
  assert.equal(s.current, false);
  assert.match(s.note, /before your latest changes/);
});
test('...and after that translation failed', async () => {
  const want = await translateWithEditDuringIt('S.settings.particles = 333;');
  run("LIVE.pending = false; LIVE.failure = {error: 'MCNPy stopped'};");
  const s = sb.savedMcnp();
  assert.equal(JSON.stringify(sb.readProjectBlock(s.text)), want);
  assert.match(s.note, /translation failed/);
});
test('a deck saved when it is up to date carries the current project, with no note', async () => {
  await translateWithEditDuringIt('');
  const s = sb.savedMcnp();
  assert.equal(JSON.stringify(sb.readProjectBlock(s.text)), projectJson());
  assert.deepEqual([s.current, s.note], [true, '']);
});

test('damaged or missing blocks are reported, and the open project is left alone', async () => {
  const before = projectJson();
  const text = run('savedScript()').replace(/(@studio-project-v1: )(\S)/, '$1!');
  await sb.openProjectText(text, 'model.py');
  assert.equal(projectJson(), before);
  assert.ok(run('window.__log').some(([k, m]) => k === 'error' && /embedded project is damaged/.test(m)));
  await sb.openProjectText(run('generate(problems())'), 'old_model.py');
  assert.ok(run('window.__log').some(([k, m]) => k === 'error' && /has no project inside/.test(m)));
});

test('the block the server writes into Export > MCNP input decks reads back in the page', () => {
  const {spawnSync} = require('child_process');
  const want = projectJson();
  const py = process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
  const r = spawnSync(py, ['-c', 'import json, sys; sys.path.insert(0, sys.argv[1]); from openmc_studio.server import project_block; ' +
    'print("\\n".join(project_block(json.loads(sys.stdin.buffer.read().decode("utf-8")), "c ")))', path.join(__dirname, '..', 'studio')],
    {input: want, encoding: 'utf8'});
  assert.equal(r.status, 0, r.stderr);
  const deck = 'Title\n1 0 -1\n\n1 so 5\n\nMODE N\n' + r.stdout;
  assert.ok(r.stdout.split('\n').filter(Boolean).every(l => l.startsWith('c @studio-project-v1') && l.length <= 128));
  assert.equal(JSON.stringify(sb.readProjectBlock(deck)), want, 'Python and the page agree on the format');
});

test('a project file still opens as before', async () => {
  const want = projectJson(), json = JSON.stringify(run('S'));
  run("S = normalizeProject(sampleModel());");
  await sb.openProjectText(json, 'p.openmc-studio.json');
  assert.equal(projectJson(), want);
});

(async () => {
  for (const [name, fn] of tests) {
    try { reset(); await fn(); console.log(`  [PASS] ${name}`); }
    catch (e) { failed++; console.log(`  [FAIL] ${name}\n${e.stack}`); }
  }
  if (failed) { console.log(`test_embed_project: ${failed} FAILED`); process.exit(1); }
  console.log('test_embed_project: PASS');
})();
