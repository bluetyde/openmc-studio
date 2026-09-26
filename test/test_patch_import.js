// Round trips, part 1: an edited model.py imported as a patch onto its project (TODO: Conversion, round trips).
// The edits are made to the text a user would save (generate()), then imported with importScriptPatch().
// Run: node test/test_patch_import.js
const fs = require('fs'), vm = require('vm'), path = require('path'), assert = require('assert');

const html = fs.readFileSync(path.join(__dirname, '..', 'studio', 'openmc_studio', 'static', 'index.html'), 'utf8');
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

let failed = 0;
const test = (name, fn) => {
  try { run("S = normalizeProject(sampleModel()); window.__log = [];"); fn(); console.log(`  [PASS] ${name}`); }
  catch (e) { failed++; console.log(`  [FAIL] ${name}\n${e.stack}`); }
};
// The saved model.py, and a copy with chosen marked numbers replaced (as a user editing the file would).
const saved = () => run('generate(problems())');
function editedScript(changes) {
  sb.__changes = changes;
  return run(`(() => {
    const b = buildScript(problems(), true);
    return b.text.replace(MARK_RE, (m, i, text) => { const c = __changes.find(c => c.pick(b.map[+i])); return c ? c.to : text; });
  })()`);
}
const isParticles = r => r.t === 'field' && r.key === 'particles' && r.obj === run('S.settings');
const isDensity = name => r => r.t === 'field' && r.key === 'density' && r.obj && r.obj.name === name;

test('an untouched model.py changes nothing', () => {
  const r = sb.importScriptPatch(saved());
  assert.deepEqual([r.edits.length, r.skipped.length, r.applied.length], [0, 0, 0]);
  assert.match(run('window.__log')[0][1], /matches the project: nothing to change/);
});

test('edited numbers come back to the objects they came from', () => {
  const mat = run('S.materials.find(m => S.parts.some(p => p.material === m.id)).name');
  const before = run('JSON.stringify(S.parts)');
  const text = editedScript([{pick: isParticles, to: '25000'}, {pick: isDensity(mat), to: '2.5'}]);
  const r = sb.importScriptPatch(text);
  assert.equal(r.applied.length, 2, JSON.stringify(run('window.__log')));
  assert.equal(r.skipped.length, 0);
  assert.equal(run('S.settings.particles'), 25000);
  assert.equal(run(`S.materials.find(m => m.name === ${JSON.stringify(mat)}).density`), 2.5);
  assert.equal(run('JSON.stringify(S.parts)'), before, 'nothing else moved');
  assert.match(run('window.__log')[0][1], /2 changes applied \(one Undo step\)/);
});

test('a part dimension comes back (a sphere radius in model.py)', () => {
  const p = run("S.parts.find(p => p.shape === 'sphere')");
  const r0 = p.r;
  const text = editedScript([{pick: r => r.t === 'sphere' && r.which === 'r' && Math.abs(r.r - r0) < 1e-9, to: String(r0 + 1.5)}]);
  const r = sb.importScriptPatch(text);
  assert.ok(r.applied.length >= 1, JSON.stringify(run('window.__log')));
  assert.equal(run(`S.parts.find(p => p.id === ${JSON.stringify(p.id)}).r`), r0 + 1.5);
});

test('a sphere\'s centre and radius edited together both apply (review: the second lost its target)', () => {
  run("S.parts.find(p => p.shape === 'sphere').x = 3;");  // off the origin, so model.py writes an x0 to edit
  const p = run("S.parts.find(p => p.shape === 'sphere')"), {x, r: r0} = p;
  const text = editedScript([
    {pick: r => r.t === 'sphere' && r.which === 'x' && Math.abs(r.r - r0) < 1e-9, to: String(x + 4)},
    {pick: r => r.t === 'sphere' && r.which === 'r' && Math.abs(r.r - r0) < 1e-9, to: String(r0 + 1)}]);
  const r = sb.importScriptPatch(text);
  assert.equal(r.failed.length, 0, JSON.stringify(r.failed.map(f => f.err)));
  const q = run(`S.parts.find(p => p.id === ${JSON.stringify(p.id)})`);
  assert.deepEqual([q.x, q.r], [x + 4, r0 + 1]);
});

// A box alone on its x planes, at x in [-1, 1]: model.py writes XPlane(-1) and XPlane(1) for it.
function loneBox() {
  run(`(() => { const b = S.parts.find(p => p.shape === 'box'); b.x = 0; b.sx = 2; b.rot = [0, 0, 0]; b.rx = b.ry = b.rz = 0;
    S.parts.filter(p => p !== b && p.shape === 'box').forEach(p => { p.x = 40; }); })()`);
  return run("S.parts.find(p => p.shape === 'box').id");
}
const xPlane = v => r => r.t === 'plane' && r.ax === 'x' && Math.abs(r.value - v) < 1e-9;
for (const [lo, hi] of [[2, 4], [-4, -2], [-3, 5]]) {
  test(`a box moved in model.py to x in [${lo}, ${hi}] keeps both faces (review: one face applied alone)`, () => {
    const id = loneBox(), q0 = run(`JSON.stringify(S.parts.find(p => p.id === '${id}'))`);
    const text = editedScript([{pick: xPlane(-1), to: String(lo)}, {pick: xPlane(1), to: String(hi)}]);
    const r = sb.importScriptPatch(text);
    assert.deepEqual([r.applied.length, r.failed.length], [2, 0], JSON.stringify(r.failed.map(f => f.err)));
    const q = run(`S.parts.find(p => p.id === '${id}')`), was = JSON.parse(q0);
    assert.deepEqual([q.x, q.sx], [(lo + hi) / 2, hi - lo]);
    assert.deepEqual([q.y, q.z, q.sy, q.sz], [was.y, was.z, was.sy, was.sz], 'the other axes stay put');
  });
}
test('faces that would cross leave the box as it was, and both edits are listed', () => {
  const id = loneBox(), before = run(`JSON.stringify(S.parts.find(p => p.id === '${id}'))`);
  const r = sb.importScriptPatch(editedScript([{pick: xPlane(-1), to: '3'}, {pick: xPlane(1), to: '2'}]));
  assert.deepEqual([r.applied.length, r.failed.length], [0, 2]);
  assert.match(r.failed[0].err, /faces would cross/);
  assert.equal(run(`JSON.stringify(S.parts.find(p => p.id === '${id}'))`), before);
});

test('what can\'t come back is listed, and the rest still applies', () => {
  let text = editedScript([{pick: isParticles, to: '777'}]);
  const lines = text.split('\n');
  const i = lines.findIndex(l => l.startsWith('import openmc'));
  lines[i] = 'import openmc as omc  # renamed';               // rewritten text
  lines.splice(i + 1, 0, 'print("hello")');                // a new line
  const j = lines.findIndex(l => /^settings\.seed = /.test(l));
  lines.splice(j, 1);                                        // a deleted line
  const r = sb.importScriptPatch(lines.join('\n'));
  assert.equal(run('S.settings.particles'), 777);
  const why = r.skipped.map(x => x.why).join(' | ');
  assert.match(why, /changed outside the numbers/); assert.match(why, /a new line/); assert.match(why, /deleted/);
  assert.ok(run('window.__log').some(([k, m]) => k === 'warn' && /import openmc as omc/.test(m)));
});

test('a number Studio works out rather than stores is not taken back', () => {
  // The header's cell count is worked out from the parts; it isn't a stored value, so it can't be taken back.
  const text = saved(), edited = text.replace(/(run: )(\d+)( cells)/, (m, a, n, b) => a + (+n + 3) + b);
  assert.notEqual(edited, text);
  const r = sb.importScriptPatch(edited);
  assert.equal(r.applied.length, 0);
  assert.equal(r.skipped.length, 1);
  assert.match(r.skipped[0].why, /changed outside the numbers/);
  assert.match(r.skipped[0].text, /run: \d+ cells/);
});

test('a file from another project, or not from Studio, is refused', () => {
  const other = saved().replace(/\\"id\\":\\"[^\\"]*\\"/, '\\"id\\":\\"p_from_elsewhere\\"');
  let r = sb.importScriptPatch(other);
  assert.match(r.refused, /doesn't have \(p_from_elsewhere\)/);
  r = sb.importScriptPatch('import openmc\nmodel = openmc.Model()\n');
  assert.match(r.refused, /not a model.py written by OpenMC Studio/);
  assert.equal(run('window.__log').filter(([k]) => k === 'error').length, 2);
});

test('Windows line endings and trailing spaces don\'t count as changes', () => {
  const r = sb.importScriptPatch(saved().split('\n').map(l => l + '  ').join('\r\n'));
  assert.deepEqual([r.edits.length, r.skipped.length], [0, 0]);
});

test('the Convert ribbon has the button', () => {
  assert.ok(run("RIBBON.Convert.some(g => g.label === 'Round trip' && g.btns.some(b => b[1] === 'Import edited model.py / .mcnp…'))"));
});

if (failed) { console.log(`test_patch_import: ${failed} FAILED`); process.exit(1); }
console.log('test_patch_import: PASS');
