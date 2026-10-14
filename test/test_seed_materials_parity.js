// The composition grammar of the SEED material export (studio/openmc_studio/seed_materials.py `tokens`) against the page's own parseComps, on the same cases
// (test/fixtures/seed/parse_comps_cases.json; the Python side is test/test_seed_materials.py). If the page's parser changes, this fails until the Python one follows.
// Run: node test/test_seed_materials_parity.js
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

const CASES = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures', 'seed', 'parse_comps_cases.json'), 'utf8'));
assert.ok(CASES.length >= 15, 'the case table is there');
let n = 0;
for (const c of CASES) {
  sb.__text = c.text;
  const got = JSON.parse(vm.runInContext('JSON.stringify(parseComps(__text))', sb));
  assert.deepStrictEqual(got.out.map(t => [t.sym, t.amt]), c.tokens, `tokens of ${JSON.stringify(c.text)}`);
  assert.deepStrictEqual(got.errs, c.errors, `unreadable parts of ${JSON.stringify(c.text)}`);
  n++;
}
console.log(`${n} composition strings read the same way by the page and by the table`);
