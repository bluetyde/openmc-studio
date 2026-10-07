// The model.mcnp tab shows the deck as soon as it is translated and gets the verdict of the check against OpenMC later.
// Page side of that (server side: test/test_mcnp_validation_bg.py): the status line of a deck in each state, the watcher
// that fetches the verdict, and what a saved deck says. The page script runs in a vm with the network and the timers
// stubbed, so each poll is one call to tick().
// Run: node test/test_mcnp_validation_page.js
const fs = require('fs'), vm = require('vm'), path = require('path'), assert = require('assert');

const html = fs.readFileSync(path.join(__dirname, '..', 'studio', 'openmc_studio', 'static', 'index.html'), 'utf8');
const el = {addEventListener() {}, insertAdjacentHTML() {}, querySelector: () => el, querySelectorAll: () => [], style: {}, dataset: {},
  classList: {add() {}, remove() {}, toggle() {}}, setAttribute() {}, appendChild() {}, append() {}, add() {}, remove() {}, getContext: () => null};
const timers = new Map();
let nextTimer = 1;
const sb = {console, URLSearchParams, btoa, atob, TextEncoder, escape, unescape, Option: class {}, window: {}, location: {protocol: 'http:', search: ''},
  document: {querySelector: () => el, querySelectorAll: () => [], getElementById: () => el, createElement: () => el, createTextNode: () => el, addEventListener() {}},
  fetch: () => Promise.resolve({ok: false}), ResizeObserver: class { observe() {} disconnect() {} },
  requestAnimationFrame() {}, setTimeout() {},
  setInterval: fn => { const id = nextTimer++; timers.set(id, fn); return id; },
  clearInterval: id => { timers.delete(id); }};
const tick = async () => { for (const fn of [...timers.values()]) await fn(); };
const calls = [], answers = [];
sb.__api = async p => {
  calls.push(p);
  const a = answers.shift();
  if (a instanceof Error) throw a;
  return a;
};
vm.createContext(sb);
vm.runInContext(html.match(/<script>([\s\S]*?)<\/script>/)[1], sb);
const run = s => vm.runInContext(s, sb);
run(`window.__status = []; window.__renders = 0;
  setMcnpStatus = (state, text) => window.__status.push([state, text]);
  renderMcnp = () => { window.__renders++; };
  problems = () => []; mcnpScript = () => 'script';
  api = p => __api(p);`);

let failed = 0;
const tests = [];
const test = (name, fn) => tests.push([name, fn]);
const pending = (extra = {}) => ({deck: 'c deck', ok: null, validation: '', validation_pending: true, validation_id: 7, seconds: 14.1, ...extra});
const fresh = r => { run('LIVE.sentScript = "script"; LIVE.pending = false; LIVE.failure = null;'); sb.__r = r; run('LIVE.report = __r;'); };
const reset = () => { timers.clear(); calls.length = 0; answers.length = 0; run('window.__status = []; window.__renders = 0; LIVE.loggedFor = null;'); };
const status = () => JSON.parse(JSON.stringify(run('window.__status')));
const liveStatus = r => { sb.__r = r; return JSON.parse(JSON.stringify(run('liveStatus(__r)'))); };

test('status line: each state of a current deck', () => {
  let [state, text] = liveStatus(pending());
  assert.equal(state, 'busy');
  assert.match(text, /checking against OpenMC/);
  assert.match(text, /isn't validated yet/);
  assert.doesNotMatch(text, /\(\d+ s\)/, 'no elapsed time before the first answer');
  assert.match(liveStatus(pending({validation_elapsed: 12.4}))[1], /\(12 s\)/);
  [state, text] = liveStatus({deck: 'x', ok: true, seconds: 14.1, validation_seconds: 29.9});
  assert.deepEqual([state, text], ['ok', '✓ Current · validated · 14.1 s + 29.9 s checking']);
  assert.match(liveStatus({deck: 'x', ok: true, seconds: 3, translation_cached: true})[1], /^✓ Current · validated · 3 s \(geometry unchanged\)$/, 'the old format still reads the same');
  assert.deepEqual(liveStatus({deck: 'x', ok: false, validation: 'FAIL'}), ['err', '⚠ Didn’t validate — see Log']);
  assert.deepEqual(liveStatus({deck: 'x', ok: false, error: 'Not exportable: x'}), ['err', '⚠ Not exportable — see the message below']);
  assert.deepEqual(liveStatus({deck: 'x', ok: false, validation_error: 'boom'}), ['err', '⚠ The check against OpenMC could not run — see Log']);
  assert.equal(liveStatus({deck: 'x', ok: null, validation_stopped: true})[0], 'warn');
  assert.match(liveStatus({deck: 'x', ok: null, validation_stopped: true})[1], /Not validated/);
});

test('the verdict arrives: only the status line changes while it runs, the pane is redrawn once at the end', async () => {
  reset();
  const r = pending();
  fresh(r);
  answers.push({id: 7, status: 'running', elapsed: 2.1}, {id: 7, status: 'running', elapsed: 3.4},
    {id: 7, status: 'done', ok: true, validation: '--- Validating ---\nValidation PASSED\n', seconds: 29.9});
  sb.__r = r; run('watchValidation(__r)');
  assert.equal(timers.size, 1);
  await tick();
  assert.match(status().at(-1)[1], /\(2 s\)/);
  await tick();
  assert.match(status().at(-1)[1], /\(3 s\)/);
  assert.equal(run('window.__renders'), 0, 'a 60 KB deck is not redrawn every second');
  assert.equal(r.validation_pending, true);
  await tick();
  assert.deepEqual([r.ok, r.validation_pending, r.validation_seconds], [true, false, 29.9]);
  assert.match(r.validation, /Validation PASSED/);
  assert.equal(run('window.__renders'), 1);
  assert.equal(timers.size, 0, 'the watcher stops when the verdict is in');
  assert.deepEqual(calls, Array(3).fill('/api/mcnp-validation?id=7'));
});

test('a failed check is a verdict, with the validator\'s text', async () => {
  reset();
  const r = pending();
  fresh(r);
  answers.push({id: 7, status: 'done', ok: false, validation: '  [ERROR] cell 3: density 10.4 g/cm3 in OpenMC but 9.9 g/cm3 in MCNP\n', seconds: 1.2});
  sb.__r = r; run('watchValidation(__r)');
  await tick();
  assert.deepEqual([r.ok, r.validation_pending], [false, false]);
  assert.match(r.validation, /density 10\.4/);
  assert.deepEqual(liveStatus(r), ['err', '⚠ Didn’t validate — see Log']);
});

test('a newer deck replaces this one: the old verdict is never fetched or applied', async () => {
  reset();
  const r = pending(), newer = pending({validation_id: 8});
  fresh(r);
  sb.__r = r; run('watchValidation(__r)');
  sb.__r = newer; run('LIVE.report = __r;');
  answers.push({id: 7, status: 'done', ok: true, validation: 'x', seconds: 1});
  await tick();
  assert.equal(r.validation_pending, true);
  assert.equal(r.ok, null);
  assert.equal(calls.length, 0, 'no request for a deck that is no longer on show');
  assert.equal(timers.size, 0);
});

test('a verdict that arrives after the deck was replaced is dropped', async () => {
  reset();
  const r = pending(), newer = pending({validation_id: 8});
  fresh(r);
  let release;
  sb.__api = p => { calls.push(p); return new Promise(res => { release = res; }); };
  sb.__r = r; run('watchValidation(__r)');
  const polling = tick();
  sb.__r = newer; run('LIVE.report = __r;');   // the user edited while the answer was on its way
  release({id: 7, status: 'done', ok: false, validation: 'FAIL', seconds: 1});
  await polling;
  assert.equal(r.validation_pending, true, 'not applied to the old deck');
  assert.equal(newer.ok, null, 'and never to the new one');
  assert.equal(run('window.__renders'), 0);
  sb.__api = async p => { calls.push(p); const a = answers.shift(); if (a instanceof Error) throw a; return a; };
});

test('the server dropped this deck\'s check ("superseded"): the page says it was stopped', async () => {
  reset();
  const r = pending();
  fresh(r);
  answers.push({id: 7, status: 'superseded'});
  sb.__r = r; run('watchValidation(__r)');
  await tick();
  assert.deepEqual([r.validation_stopped, r.validation_pending, r.ok], [true, false, null]);
  assert.equal(liveStatus(r)[0], 'warn');
});

test('a check that could not run says why', async () => {
  reset();
  const r = pending();
  fresh(r);
  answers.push({id: 7, status: 'error', error: 'The validation process stopped without a result (exit 3). boom'});
  sb.__r = r; run('watchValidation(__r)');
  await tick();
  assert.deepEqual([r.ok, r.validation_pending], [false, false]);
  assert.match(r.validation_error, /exit 3/);
  assert.equal(liveStatus(r)[0], 'err');
});

test('one missed poll is not the end: the watcher keeps going', async () => {
  reset();
  const r = pending();
  fresh(r);
  answers.push(new Error('network blip'), {id: 7, status: 'done', ok: true, validation: 'x\ny', seconds: 2});
  sb.__r = r; run('watchValidation(__r)');
  await tick();
  assert.equal(r.validation_pending, true);
  assert.equal(timers.size, 1);
  await tick();
  assert.equal(r.ok, true);
});

test('a saved deck says whether its check was done', () => {
  reset();
  const saved = r => { fresh({deck: 'Title\n', name: 'm', ...r}); return JSON.parse(JSON.stringify(run('savedMcnp()'))); };
  assert.match(saved({validation_pending: true, ok: null}).note, /still being checked against OpenMC when it was saved/);
  assert.match(saved({validation_error: 'boom', ok: false}).note, /could not run/);
  assert.match(saved({validation_stopped: true, ok: null}).note, /was stopped before it finished/);
  assert.match(saved({ok: false}).note, /did not validate/);
  assert.equal(saved({ok: true}).note, '', 'a validated deck carries no note');
  assert.equal(saved({ok: true}).name, 'm.mcnp');
});

(async () => {
  for (const [name, fn] of tests) {
    try { await fn(); console.log(`  [PASS] ${name}`); } catch (e) { failed++; console.log(`  [FAIL] ${name}\n${e.stack}`); }
  }
  console.log(failed ? `test_mcnp_validation_page: ${failed} FAILED` : 'test_mcnp_validation_page: PASS');
  process.exit(failed ? 1 : 0);
})();
