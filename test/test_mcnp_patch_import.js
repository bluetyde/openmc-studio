// Round trips, part 2: an edited model.mcnp imported as a patch onto its project. The fixture is a real deck
// from the exporter (test/fixtures/mcnp/shielding_demo.mcnp, with its @studio-v1 records) and the project it was
// exported from; the test stands in for the live model.mcnp tab by setting LIVE to that deck.
// Regenerate the fixture with Claude Code Test\mcnp-bundle\tools (make_shielding.js, then build.py) if the
// project format changes.
// Run: node test/test_mcnp_patch_import.js
const fs = require('fs'), vm = require('vm'), path = require('path'), assert = require('assert');

const html = fs.readFileSync(path.join(__dirname, '..', 'studio', 'openmc_studio', 'static', 'index.html'), 'utf8');
const FIX = path.join(__dirname, 'fixtures', 'mcnp');
const deck = fs.readFileSync(path.join(FIX, 'shielding_demo.mcnp'), 'utf8');
const project = fs.readFileSync(path.join(FIX, 'shielding_demo.openmc-studio.json'), 'utf8');
const el = {addEventListener() {}, insertAdjacentHTML() {}, querySelector: () => el, querySelectorAll: () => [], style: {}, dataset: {},
  classList: {add() {}, remove() {}, toggle() {}}, setAttribute() {}, appendChild() {}, append() {}, add() {}, getContext: () => null};
const sb = {console, URLSearchParams, btoa, atob, TextEncoder, Option: class {}, window: {}, location: {protocol: 'http:', search: ''},
  document: {querySelector: () => el, querySelectorAll: () => [], getElementById: () => el, createElement: () => el, createTextNode: () => el, addEventListener() {}},
  fetch: () => Promise.resolve({ok: false}), ResizeObserver: class { observe() {} disconnect() {} },
  requestAnimationFrame() {}, setTimeout() {}, setInterval() {}};
vm.createContext(sb);
vm.runInContext(html.match(/<script>([\s\S]*?)<\/script>/)[1], sb);
const run = s => vm.runInContext(s, sb);
run('window.__log = []; log = (kind, msg) => window.__log.push([kind, msg]); setOutTab = () => {};');
sb.__deck = deck; sb.__project = project;

let failed = 0;
const test = (name, fn) => {
  try {
    // the project, and the live model.mcnp tab showing its freshly translated deck
    run(`S = normalizeProject(JSON.parse(__project)); window.__log = []; LOCAL.on = true;
      (() => { const P = problems(); LIVE.report = {deck: __deck}; LIVE.sentScript = mcnpScript(P); LIVE.failure = null;
        LIVE.pending = false; LIVE.ctx = mcnpContext(P, buildScript(P, false, MCNP_OPTS)); })();`);
    fn(); console.log(`  [PASS] ${name}`);
  } catch (e) { failed++; console.log(`  [FAIL] ${name}\n${e.stack}`); }
};
// The deck with chosen editable numbers replaced, as a user editing model.mcnp would.
function editedDeck(changes) {
  sb.__changes = changes;
  return run(`(() => {
    const m = markedMcnp(LIVE.report.deck, LIVE.ctx);
    return m.lines.map(l => l.replace(MARK_RE, (x, i, text) => { const c = __changes.find(c => c.pick(m.refs[+i])); return c ? c.to : text; })).join('\\n') + '\\n';
  })()`);
}
const lead = () => run("S.materials.find(m => /Lead/.test(m.name))");

test('the rendered deck reads back line for line, with its dotted numbers marked', () => {
  const m = run('markedMcnp(LIVE.report.deck, LIVE.ctx)');
  assert.equal(m.lines.length, deck.replace(/\n+$/, '').split('\n').length);
  assert.equal(m.lines.map(l => l.replace(/\u0001\d+\u0002([^\u0003]*)\u0003/g, '$1').trimEnd()).join('\n'),
    deck.replace(/\n+$/, '').split('\n').map(l => run(`mcnpDisplayLine(${JSON.stringify(l)})`).trimEnd()).join('\n'));
  assert.ok(m.refs.length > 10, 'the deck has editable numbers');
});

test('an untouched deck changes nothing', () => {
  const r = sb.importScriptPatch(deck, 'shielding_demo.mcnp');
  assert.deepEqual([r.refused, r.edits.length, r.skipped.length], [undefined, 0, 0]);
});

test('a density on a cell card and a sphere radius on a surface card come back', () => {
  const rho0 = lead().density, sph = run("S.parts.find(p => p.shape === 'sphere')"), r0 = sph.r;  // sph is live: keep r
  const text = editedDeck([
    {pick: r => r && r.t === 'field' && r.key === 'density' && r.obj && /Lead/.test(r.obj.name), to: '-11.0'},
    {pick: r => r && r.t === 'sphere' && r.which === 'r' && Math.abs(r.r - r0) < 1e-9, to: String(r0 + 1.5)}]);
  const r = sb.importScriptPatch(text, 'shielding_demo.mcnp');
  assert.equal(r.failed.length, 0, JSON.stringify(r.failed));
  assert.ok(r.applied.length >= 2, JSON.stringify(run('window.__log')));
  assert.equal(lead().density, 11, `was ${rho0}; MCNP writes mass density negative`);
  assert.equal(run(`S.parts.find(p => p.id === ${JSON.stringify(sph.id)}).r`), r0 + 1.5);
  assert.match(run('window.__log')[0][1], /changes applied \(one Undo step\)/);
});

test('rewritten cards and new cards are listed, not applied', () => {
  const lines = deck.split('\n');
  const i = lines.findIndex(l => /^MODE /.test(l));
  lines[i] = 'MODE N P';
  lines.splice(i + 1, 0, 'PRDMP 2J 1');
  const r = sb.importScriptPatch(lines.join('\n'), 'shielding_demo.mcnp');
  assert.equal(r.applied.length, 0);
  const why = r.skipped.map(x => x.why).join(' | ');
  assert.match(why, /changed outside the numbers/); assert.match(why, /a new line/);
});

test('a deck that names objects this project lacks is refused', () => {
  run("S.parts.splice(S.parts.findIndex(p => p.shape === 'sphere'), 1);");
  const r = sb.importScriptPatch(deck, 'shielding_demo.mcnp');
  assert.match(r.refused, /this project doesn't have/);
});

test('a deck without Studio records is refused', () => {
  const r = sb.importScriptPatch('Plain deck\n1 0 -1\n\n1 so 5\n\nMODE N\nNPS 10\n', 'other.mcnp');
  assert.match(r.refused, /no OpenMC Studio records/);
});

test('an out-of-date model.mcnp tab is refused, since the deck is lined up against it', () => {
  run('LIVE.sentScript = "stale";');
  const r = sb.importScriptPatch(deck, 'shielding_demo.mcnp');
  assert.match(r.refused, /isn't up to date/);
});

if (failed) { console.log(`test_mcnp_patch_import: ${failed} FAILED`); process.exit(1); }
console.log('test_mcnp_patch_import: PASS');
