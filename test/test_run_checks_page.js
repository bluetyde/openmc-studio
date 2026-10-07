// The Results page shows the checks on a run, the figure of merit, and the two record actions.
// Server side of this: test/test_run_checks.py. The page script runs in a vm with the network stubbed.
// Run: node test/test_run_checks_page.js
const fs = require('fs'), vm = require('vm'), path = require('path'), assert = require('assert');

const html = fs.readFileSync(path.join(__dirname, '..', 'studio', 'openmc_studio', 'static', 'index.html'), 'utf8');
const listeners = [];
const el = {addEventListener(type, fn) { listeners.push([type, fn]); }, insertAdjacentHTML() {}, querySelector: () => el, querySelectorAll: () => [], style: {}, dataset: {},
  classList: {add() {}, remove() {}, toggle() {}}, setAttribute() {}, appendChild() {}, append() {}, add() {}, remove() {}, getContext: () => null,
  parentElement: {}};
// Every write to a stub's innerHTML is recorded: renderResults writes the results box first and other boxes after it.
const writes = [];
Object.defineProperty(el, 'innerHTML', {set(v) { writes.push(String(v)); }, get() { return writes[writes.length - 1] || ''; }});
const sb = {console, URLSearchParams, btoa, atob, TextEncoder, escape, unescape, Option: class {}, window: {}, location: {protocol: 'http:', search: ''},
  document: {querySelector: () => el, querySelectorAll: () => [], getElementById: () => el, createElement: () => el, createTextNode: () => el, addEventListener() {}},
  fetch: () => Promise.resolve({ok: false}), ResizeObserver: class { observe() {} disconnect() {} },
  requestAnimationFrame() {}, setTimeout() {}, setInterval: () => 1, clearInterval() {}};
vm.createContext(sb);
vm.runInContext(html.match(/<script>([\s\S]*?)<\/script>/)[1], sb);
const run = s => vm.runInContext(s, sb);
const json = x => JSON.parse(JSON.stringify(x));

let failed = 0;
const tests = [];
const test = (name, fn) => tests.push([name, fn]);

const findings = [
  {level: 'info', code: 'k-estimate', message: 'k = 1.3062 +/- 0.0005 (1 sigma, standard uncertainty)', detail: {}},
  {level: 'not-compared', code: 'active-batches', message: 'no threshold with a source was supplied for min_active_batches', detail: {}},
  {level: 'warning', code: 'lost-particles', message: '3 lost particles', detail: {}},
  {level: 'error', code: 'x', message: '<b>bad</b> & worse', detail: {}},
];

test('findings are listed worst first, with the not-compared label, and escaped', () => {
  sb.__f = findings;
  const h = run('renderFindings(__f)');
  const order = [...h.matchAll(/<span class="sev ([a-z]*)">([a-z ]+)<\/span>/g)].map(m => m[2]);
  assert.deepEqual(order, ['error', 'warning', 'info', 'not compared']);
  assert.match(h, /&lt;b&gt;bad&lt;\/b&gt; &amp; worse/);
  assert.doesNotMatch(h, /<b>bad<\/b>/);
  assert.match(h, /Checks on this run/);
});

test('no findings, nothing printed', () => {
  assert.equal(run('renderFindings(undefined)'), '');
  assert.equal(run('renderFindings([])'), '');
});

const results = fom => ({summary: {run_mode: 'eigenvalue', particles: 20000, batches: 120, seed: 1, runtime_s: 50, keff: [1.30622, 0.00052]},
  findings, tracks: [], tracks_truncated: false,
  tallies: [{name: 'flux', kind: 'table', filters: ['CellFilter'], scores: ['flux'],
    rows: [{labels: ['fuel'], score: 'flux', mean: 2, std: 0.02, rel_err: 0.01, ...(fom ? {fom} : {})},
           {labels: ['gap'], score: 'flux', mean: 0, std: 0, rel_err: null}]}]});

test('the table gets a FOM column only when a row has one', () => {
  sb.__r = results(100);
  writes.length = 0; run('LOCAL.results = __r; LOCAL.resultsRun = "r1"; renderResults();');
  let h = writes[0];
  assert.match(h, /<th class="num" title="Figure of merit[^"]*">FOM<\/th>/);
  assert.match(h, /<td class="num">100<\/td>/);
  assert.match(h, /<td class="num">—<\/td><\/tr>/, 'the empty bin shows a dash');
  sb.__r = results(null);
  writes.length = 0; run('LOCAL.results = __r; renderResults();');
  assert.doesNotMatch(writes[0], />FOM</);
});

test('the results header offers the report and the record check, then the checks', () => {
  sb.__r = results(100);
  writes.length = 0; run('LOCAL.results = __r; renderResults();');
  const h = writes[0];
  assert.match(h, /id="reportBtn"/);
  assert.match(h, /id="recordBtn"/);
  assert.ok(h.indexOf('id="recordBtn"') < h.indexOf('Checks on this run'));
});

test('the record check says what differs', () => {
  const log = r => json(run(`recordCheckLog("r1", ${JSON.stringify(r)})`));
  assert.deepEqual(log({status: 'match', counts: {}}).slice(0, 1), ['ok']);
  assert.equal(log({status: 'no-record'})[0], 'warn');
  assert.equal(log({status: 'bad-record', notes: ['cannot access provenance.json']})[0], 'error');
  const [sev, text] = log({status: 'differences', counts: {files_changed: 2, files_missing: 1, files_other: 0, environment_warnings: 1, environment_info: 3},
    environment: [{path: 'openmc.python', recorded: '0.15.2', current: '0.15.3', level: 'warning'}]});
  assert.equal(sev, 'warn');
  assert.match(text, /2 files changed, 1 missing, 1 environment difference to look at, 3 minor/);
  assert.match(text, /openmc\.python: 0\.15\.2 then, 0\.15\.3 now/);
});

test('the Results buttons call the report and the record check, and only those', () => {
  run('window.__calls = []; saveRunReport = () => window.__calls.push("report"); checkRunRecord = () => window.__calls.push("record"); exportParaview = () => window.__calls.push("vtk");');
  const click = id => { run('window.__calls = []'); for (const [t, fn] of listeners) if (t === 'click' && fn.toString().includes('#reportBtn')) fn({target: {closest: sel => sel === id ? {} : null}}); return json(run('window.__calls')); };
  assert.deepEqual(click('#reportBtn'), ['report']);
  assert.deepEqual(click('#recordBtn'), ['record']);
  assert.deepEqual(click('#paraviewBtn'), ['vtk']);
});

(async () => {
  for (const [name, fn] of tests) {
    try { await fn(); console.log('  [PASS]', name); }
    catch (e) { failed++; console.log('  [FAIL]', name, '\n   ', e.message); }
  }
  console.log(failed ? `test_run_checks_page: ${failed} FAILED` : 'test_run_checks_page: PASS');
  process.exit(failed ? 1 : 0);
})();
