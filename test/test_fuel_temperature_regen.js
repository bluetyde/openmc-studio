// The return transfer `fuel-temperature` changes project.json; SEED refuses a model.py that differs from what the page regenerates from project.json.
// So the mapped project must regenerate model.py deterministically, and the only change must be the material's temperature line. The mapping runs as the
// real runner command (python -m openmc_studio.headless transfer, stdlib only) and the page's own generator regenerates the script.
// Also: the number writer of transfer.py against JavaScript's own Number toString, on many doubles.
// Run: node test/test_fuel_temperature_regen.js     (needs a python on PATH, or PYTHON)
const fs = require('fs'), vm = require('vm'), path = require('path'), assert = require('assert'), {spawnSync} = require('child_process');

const root = path.join(__dirname, '..');
const html = fs.readFileSync(path.join(root, 'studio', 'openmc_studio', 'static', 'index.html'), 'utf8');
const el = {addEventListener() {}, insertAdjacentHTML() {}, querySelector: () => el, querySelectorAll: () => [], style: {}, dataset: {},
  classList: {add() {}, remove() {}, toggle() {}}, setAttribute() {}, appendChild() {}, append() {}, add() {}, remove() {}, getContext: () => null, parentElement: {}};
const sb = {console, URLSearchParams, btoa, atob, TextEncoder, escape, unescape, Option: class {}, window: {}, location: {protocol: 'http:', search: ''},
  document: {querySelector: () => el, querySelectorAll: () => [], getElementById: () => el, createElement: () => el, createTextNode: () => el, addEventListener() {}},
  fetch: () => Promise.resolve({ok: false}), ResizeObserver: class { observe() {} disconnect() {} }, requestAnimationFrame() {}, setTimeout() {}, setInterval: () => 1, clearInterval() {}};
vm.createContext(sb);
vm.runInContext(html.match(/<script>([\s\S]*?)<\/script>/)[1], sb);
const python = process.env.PYTHON || 'python';
const env = {...process.env, PYTHONPATH: path.join(root, 'studio'), PYTHONDONTWRITEBYTECODE: '1'};
const py = (args, input) => { const r = spawnSync(python, args, {input, env, encoding: 'utf8', maxBuffer: 1 << 26}); assert.strictEqual(r.status, 0, r.stderr); return r.stdout; };

// the page's script for a project text
const scriptOf = text => { sb.__p = JSON.parse(text); sb.normalizeProject(sb.__p); vm.runInContext('S = __p;', sb); return vm.runInContext('buildScript(problems(), false).text', sb); };

const exampleText = fs.readFileSync(path.join(root, 'examples', 'triso-particle', 'triso-particle.openmc-studio.json'), 'utf8');
const recipe = materials => ({schema: 'seed.transfer-recipe/0.2', recipeId: 'pt-1', proposedBy: {kind: 'agent', name: 'x'}, proposedAt: '2026-10-25T00:00:00Z',
  source: {runId: 'r1', resultsSha256: '0'.repeat(64), quantity: 'fuel_temperature', dataSha256: '1'.repeat(64), unit: 'K', dimension: 'temperature', normalization: 'none', revisionPins: []},
  target: {app: 'openmc-studio', artifact: 'project', revision: '2'.repeat(64), field: 'fuel-temperature'}, units: {to: 'K'}, normalization: {kind: 'none', origin: 'absolute'},
  mapping: {spatial: {meaning: 'volume-mean', materials}, time: {kind: 'steady'}, extrapolation: 'refused'}, tolerance: {conservation: 0.01, fixedBefore: 'mapping'}});
const table = rows => ({schema: 'seed.quantity-data/0.2', quantity: 'fuel_temperature', kind: 'table', unit: 'K',
  columns: [{name: 'region', unit: '', role: 'label'}, {name: 'T', unit: 'K', role: 'value'}], rows});
const transfer = (rec, data, content) => JSON.parse(py(['-m', 'openmc_studio.headless', 'transfer'],
  JSON.stringify({schema: 'seed.transfer-request/0.2', recipe: rec, recipeDigest: 'd'.repeat(64), source: {data}, target: {artifact: 'project', revision: '2'.repeat(64), content}})).trim().split('\n').pop());

let failed = 0;
const tests = [];
const test = (name, fn) => tests.push([name, fn]);

test('the mapped project regenerates a model.py that differs from the old one only in the temperature line, and regenerates identically every time', () => {
  const rec = recipe([{material: 'triso_m0', region: 'kernel'}, {material: 'triso_m3', region: 'sic'}]);
  const data = table([['kernel', 900.0], ['sic', 873.15]]);
  const a = transfer(rec, data, exampleText), b = transfer(rec, data, exampleText);
  assert.ok(a.ok && b.ok, JSON.stringify(a));
  assert.strictEqual(a.output.content, b.output.content, 'the mapped project is the same bytes twice');
  const before = scriptOf(exampleText), after1 = scriptOf(a.output.content), after2 = scriptOf(b.output.content);
  assert.strictEqual(after1, after2, 'the regenerated script is the same bytes twice');
  assert.strictEqual(scriptOf(a.output.content), after1, 'and again from a fresh generation');
  const bl = before.split('\n'), al = after1.split('\n');
  const added = al.filter(l => !bl.includes(l)), removed = bl.filter(l => !al.includes(l));
  assert.deepStrictEqual(removed, [], 'no line of the old script is lost: ' + removed.join(' | '));
  assert.strictEqual(added.length, 2, added.join(' | '));
  assert.ok(added.every(l => /\.temperature = /.test(l)), added.join(' | '));
  assert.ok(added.some(l => /\.temperature = 900(\.0)?$/.test(l)) && added.some(l => /\.temperature = 873\.15$/.test(l)), added.join(' | '));
  // the lines are in the material blocks of the two named materials and in no other
  const named = added.map(l => l.split('.')[0].trim());
  assert.strictEqual(new Set(named).size, 2);
});

test('mapping the same temperature again changes neither the project nor the script (a loop pass that did not change the value)', () => {
  const rec = recipe([{material: 'triso_m0', region: 'kernel'}]);
  const once = transfer(rec, table([['kernel', 700.5]]), exampleText);
  const twice = transfer(rec, table([['kernel', 700.5]]), once.output.content);
  assert.strictEqual(twice.output.content, once.output.content);
  assert.strictEqual(scriptOf(twice.output.content), scriptOf(once.output.content));
});

test('a different temperature changes the script (the transfer is not a no-op)', () => {
  const rec = recipe([{material: 'triso_m0', region: 'kernel'}]);
  const lo = scriptOf(transfer(rec, table([['kernel', 600]]), exampleText).output.content), hi = scriptOf(transfer(rec, table([['kernel', 1200]]), exampleText).output.content);
  assert.notStrictEqual(lo, hi);
  assert.ok(/\.temperature = 600(\.0)?\n/.test(lo) && /\.temperature = 1200(\.0)?\n/.test(hi));
});

test('the output has no problems for the page (a mapped project still runs)', () => {
  const rec = recipe([{material: 'triso_m0', region: 'kernel'}]);
  const out = transfer(rec, table([['kernel', 900]]), exampleText).output.content;
  sb.__p = JSON.parse(out); sb.normalizeProject(sb.__p); vm.runInContext('S = __p;', sb);
  assert.deepStrictEqual(JSON.parse(JSON.stringify(vm.runInContext("problems().filter(p => p.sev === 'error')", sb))), []);
});

test("transfer.py writes numbers exactly as JavaScript's String(number) does (5000 doubles of every size)", () => {
  let seed = 987654321;
  const rnd = () => (seed = (seed * 1664525 + 1013904223) % 4294967296) / 4294967296;
  const nums = [0, 1, -1, 0.1 + 0.2, 1e21, 1e-7, 5e-7, 123456789012345680000, 1.7976931348623157e308, 5e-324, 2.2250738585072014e-308, 0.000001, 999999999999999900000];
  for (let i = 0; i < 5000; i++) {
    const e = Math.floor(rnd() * 80 - 40);
    nums.push((rnd() - 0.5) * 10 ** e, Math.round(rnd() * 1e6) / 100, Math.round((rnd() - 0.5) * 1e12));
  }
  const want = nums.map(String);
  const got = JSON.parse(py(['-c', 'import sys, json; sys.path.insert(0, ' + JSON.stringify(path.join(root, 'studio')) + ');\nfrom openmc_studio.transfer import js_number\nprint(json.dumps([js_number(v) for v in json.load(sys.stdin)]))'], JSON.stringify(nums)));
  const bad = nums.map((v, i) => [v, want[i], got[i]]).filter(([, w, g]) => w !== g);
  assert.deepStrictEqual(bad.slice(0, 5), [], `${bad.length} of ${nums.length} differ`);
});

for (const [name, fn] of tests) {
  try { fn(); console.log('PASS', name); } catch (e) { failed++; console.log('FAIL', name, '\n  ', String(e.stack || e).split('\n').slice(0, 5).join('\n   ')); }
}
console.log(`${tests.length - failed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
