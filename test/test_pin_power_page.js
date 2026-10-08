// The Pin power panel on the Results page: the button on a pin-resolved mesh tally, the map, the numbers under it, the selectors and the CSV.
// The numbers come from the server (test/test_pin_power_view.py, fixture test/fixtures/pin_power/analysis.json made by it); this checks what the page draws.
// Run: node test/test_pin_power_page.js
const fs = require('fs'), vm = require('vm'), path = require('path'), assert = require('assert');

const html = fs.readFileSync(path.join(__dirname, '..', 'studio', 'openmc_studio', 'static', 'index.html'), 'utf8');
const listeners = [];
const writes = [];
const el = {addEventListener(type, fn) { listeners.push([type, fn]); }, insertAdjacentHTML() {}, querySelector: () => el, querySelectorAll: () => [], style: {}, dataset: {},
  classList: {add() {}, remove() {}, toggle() {}}, setAttribute() {}, appendChild() {}, append() {}, add() {}, remove() {}, getContext: () => null, parentElement: {}};
const sb = {console, URLSearchParams, btoa, atob, TextEncoder, TextDecoder, escape, unescape, Option: class {}, window: {}, location: {protocol: 'http:', search: ''},
  document: {querySelector: () => el, querySelectorAll: () => [], getElementById: () => el, createElement: () => el, createTextNode: () => el, addEventListener() {}},
  fetch: () => Promise.resolve({ok: false}), ResizeObserver: class { observe() {} disconnect() {} },
  requestAnimationFrame() {}, setTimeout() {}, setInterval: () => 1, clearInterval() {}};
Object.defineProperty(el, 'innerHTML', {set(v) { writes.push(String(v)); }, get() { return writes[writes.length - 1] || ''; }});
vm.createContext(sb);
vm.runInContext(html.match(/<script>([\s\S]*?)<\/script>/)[1], sb);
const run = s => vm.runInContext(s, sb);
const fx = f => JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures', 'pin_power', f), 'utf8'));
const A = fx('analysis.json'), TALLY = fx('tally.json');

let failed = 0;
const tests = [];
const test = (name, fn) => tests.push([name, fn]);

const panel = (a = A, tally = TALLY) => { sb.__a = a; sb.__t = tally; return run('pinPowerHtml({data: __a}, __t)'); };
const resultsFor = (tallies, pins) => {
  sb.__R = {summary: {run_mode: 'eigenvalue', particles: 1000, batches: 10, seed: 1, runtime_s: 5, keff: [1.3, 0.005], k_generation: [1.3, 1.31], inactive: 5, n_inactive: 5},
    tallies, tracks: [], tracks_truncated: false, findings: []};
  sb.__pins = pins || null; writes.length = 0;
  run('LOCAL.results = __R; LOCAL.resultsRun = "r1"; LOCAL.pins = __pins; renderResults();');
  return writes[0];
};

test('a regular mesh with more than one cell each way gets a Pin power button, others do not', () => {
  assert.match(resultsFor([TALLY]), /class="tbtn pinBtn"[^>]*data-tally="Pin power"/);
  const flat = JSON.parse(JSON.stringify(TALLY)); flat.dims = [4, 1, 1]; flat.name = 'row';
  assert.doesNotMatch(resultsFor([flat]), /pinBtn/, 'a line of cells is not a pin map');
  const cyl = JSON.parse(JSON.stringify(TALLY)); cyl.mesh_type = 'cylindrical'; cyl.r_grid = [0, 1]; cyl.phi_grid = [0, 1]; cyl.z_grid = [0, 1];
  assert.doesNotMatch(resultsFor([cyl]), /pinBtn/, 'a cylindrical mesh is not a pin map');
  const dose = JSON.parse(JSON.stringify(TALLY)); dose.dose = {data: 'icrp116', geometry: 'AP', source_rate: 1};
  assert.doesNotMatch(resultsFor([dose]), /pinBtn/, 'a dose map is not a power map');
});

test('the panel opens under its own tally only, for the run it was made for', () => {
  const other = JSON.parse(JSON.stringify(TALLY)); other.name = 'Second';
  const h = resultsFor([TALLY, other], {rid: 'r1', tally: 'Pin power', data: A});
  assert.equal((h.match(/id="pinPanel"/g) || []).length, 1);
  assert.ok(h.indexOf('id="pinPanel"') < h.indexOf('Second'), 'right after the tally it belongs to');
  assert.doesNotMatch(resultsFor([TALLY], {rid: 'another-run', tally: 'Pin power', data: A}), /id="pinPanel"/);
});

test('the map has a cell for every pin, the hot one outlined, the one that scored nothing greyed, and iy = 0 at the bottom', () => {
  const h = panel();
  const svg = h.slice(h.indexOf('<svg class="pin-map"'), h.indexOf('</svg>'));
  assert.equal((svg.match(/<rect /g) || []).length, 12);
  const hot = svg.match(/<rect x="(\d+)" y="(\d+)" width="(\d+)" height="\d+" fill="rgb[^"]*" stroke="#fff" stroke-width="2">/);
  assert.ok(hot, 'one outlined cell');
  const cs = +hot[3];
  assert.equal(+hot[1], 3 * cs, 'ix = 3 is the right-hand column');
  assert.equal(+hot[2], (3 - 1 - 1) * cs, 'iy = 1 of 3 rows counted from the bottom: the middle row');
  const yOf = ix => +svg.match(new RegExp(`<rect x="\\d+" y="(\\d+)"[^>]*><title>pin \\(${ix}\\)`))[1];
  assert.equal(yOf('0, 0'), 2 * cs, 'the first row (iy = 0) is drawn at the bottom');
  assert.equal(yOf('0, 2'), 0, 'the last row is at the top');
  assert.equal((svg.match(/fill="#2a2d33"/g) || []).length, 1, 'the pin that scored nothing');
  assert.match(svg, /<title>pin \(2, 1\) at x [\d.]+, y [\d.]+ cm: scored nothing, left out of the mean<\/title>/);
});

test('the numbers under the map: the highest pin and its place, the pins used, the noise allowance, the top five', () => {
  const h = panel();
  assert.match(h, /Highest: <b>1\.434<\/b> of the mean, at pin \(3, 1\) · 11 pins in the mean, 1 left out \(scored nothing\)/);
  assert.match(h, /Noise alone would lift the largest of 11 equal pins by about 0\.0\d\d here/);
  assert.match(h, /not a correction/);
  const top = h.slice(h.indexOf('id="pinTop"'));
  assert.equal((top.match(/<tr><td>/g) || []).length, 5);
  assert.match(top, /<tr><td>\(3, 1\)<\/td><td class="num">[\d.]+, [\d.]+<\/td><td class="num">1\.434<\/td>/);
});

test('the symmetry line is a warning when the loading is not symmetric, a plain note when it is', () => {
  assert.match(panel(), /<span class="sev warn">not symmetric<\/span> pins that a four-fold symmetric layout would make equal differ by up to [\d.]+ sigma/);
  const sym = JSON.parse(JSON.stringify(A)); sym.symmetry = {max_deviation: 0.001, max_z: 0.4, within_noise: true};
  const h = panel(sym);
  assert.doesNotMatch(h, /not symmetric/);
  assert.match(h, /it is: pins that should match differ by at most 0\.4 of their own sigma/);
});

test('the panel says what it assumes and that the lattice is not checked', () => {
  const h = panel();
  assert.match(h, /id="pinAssumes">Assumes each cell of the mesh is one pin/);
  assert.match(h, /Lattice alignment is not checked/);
});

test('score and layer selectors show only when there is a choice, with the current one chosen', () => {
  const h = panel();
  assert.match(h, /<select class="pinScore"><option value="kappa-fission" selected>kappa-fission<\/option><option value="fission">fission<\/option><\/select>/);
  assert.match(h, /<select class="pinLayer"><option value="0" selected>1 of 2<\/option><option value="1">2 of 2<\/option><\/select>/);
  const one = JSON.parse(JSON.stringify(A)); one.layers = 1;
  const t1 = JSON.parse(JSON.stringify(TALLY)); t1.scores = ['kappa-fission'];
  assert.doesNotMatch(panel(one, t1), /pinScore|pinLayer/);
});

test('loading and an error are said, an error with a way to close it', () => {
  assert.match(run('pinPowerHtml({loading: true}, {})'), /Reading the pin map/);
  const e = run('pinPowerHtml({error: "the tally has no score x"}, {})');
  assert.match(e, /<span class="sev warn">pin map<\/span> the tally has no score x/);
  assert.match(e, /pinClose/);
});

test('the text from the server is escaped', () => {
  const evil = JSON.parse(JSON.stringify(A)); evil.score = '<img src=x onerror=alert(1)>';
  assert.doesNotMatch(panel(evil), /<img src=x/);
  assert.doesNotMatch(run('pinPowerHtml({error: "<script>x</script>"}, {})'), /<script>x/);
});

test('clicking the button asks the server for that tally, a layer or score change asks again, Close removes the panel', async () => {
  const urls = [];
  sb.fetch = url => { urls.push(url); return Promise.resolve({ok: true, headers: {get: () => 'application/json'}, json: () => Promise.resolve(A)}); };
  run('LOCAL.on = true; LOCAL.token = "tok"; LOCAL.results = {summary: {}, tallies: [], tracks: [], tracks_truncated: false, findings: []}; LOCAL.resultsRun = "r1";');
  const click = (sel, extra = {}) => { for (const [t, fn] of listeners) if (t === 'click' && fn.toString().includes('.pinBtn')) fn({target: {closest: s => s === sel ? extra : null}}); };
  click('.pinBtn', {dataset: {tally: 'Pin power'}});
  await new Promise(r => setImmediate(r));
  assert.equal(urls.length, 1);
  assert.match(urls[0], /^\/api\/runs\/r1\/pin-power\?tally=Pin%20power&layer=0$/);
  assert.equal(run('LOCAL.pins.data && LOCAL.pins.data.peak.ix'), 3);
  // a change of layer
  const picks = {'.pinScore': {value: 'fission'}, '.pinLayer': {value: '1'}};
  const panelEl = {querySelector: s => picks[s]};
  for (const [t, fn] of listeners) if (t === 'change' && fn.toString().includes('pinScore')) fn({target: {closest: s => s === '#pinPanel' || s === '.pinLayer' ? panelEl : null}});
  await new Promise(r => setImmediate(r));
  assert.match(urls[1], /tally=Pin%20power&layer=1&score=fission$/);
  click('.pinClose');
  assert.equal(run('LOCAL.pins'), null);
});

test('a refusal from the server shows as the panel text', async () => {
  sb.fetch = () => Promise.resolve({ok: false, status: 422, headers: {get: () => 'application/json'}, json: () => Promise.resolve({error: 'a pin map needs a regular (box) mesh; this one is cylindrical'})});
  run('LOCAL.pins = null; loadPinPower("Cyl", undefined, 0)');
  await new Promise(r => setImmediate(r));
  assert.equal(run('LOCAL.pins.error'), 'a pin map needs a regular (box) mesh; this one is cylindrical');
});

test('Save CSV hands the server\'s text to the file saver', async () => {
  const saved = [];
  run('saveFile = (name, data, note) => { window.__csv = [name, new TextDecoder().decode(data)]; }');
  sb.__a = A; run('LOCAL.pins = {rid: "r1", tally: "Pin power", data: __a}; savePinCsv()');
  await new Promise(r => setImmediate(r));
  const [name, text] = JSON.parse(JSON.stringify(run('window.__csv')));
  assert.equal(name, 'pin-power-r1.csv');
  assert.equal(text, A.csv);
  assert.equal(text.split('\n')[0], 'ix,iy,x_cm,y_cm,value,sigma,included,relative_power,relative_sigma');
});

(async () => {
  for (const [name, fn] of tests) {
    try { await fn(); console.log('  [PASS]', name); }
    catch (e) { failed++; console.log('  [FAIL]', name, '\n   ', e.message); }
  }
  console.log(failed ? `test_pin_power_page: ${failed} FAILED` : 'test_pin_power_page: PASS');
  process.exit(failed ? 1 : 0);
})();
