// The Core (nodal) tab of the page (index.html: CORE, renderCore, coreResultHtml, coreSolve, coreInit, the runs list): what it shows and what it sends, against a stubbed server.
// The solve itself is tested on the server side (test/test_nodal_route.py, test/nodal/test_nodal_route_run.py) and in the driver (test/nodal/test_nodal_driver.py).
// Run: node test/test_core_page.js
const fs = require('fs'), vm = require('vm'), path = require('path'), assert = require('assert');

const html = fs.readFileSync(path.join(__dirname, '..', 'studio', 'openmc_studio', 'static', 'index.html'), 'utf8');
const el = {addEventListener() {}, insertAdjacentHTML() {}, querySelector: () => el, querySelectorAll: () => [], style: {}, dataset: {},
  classList: {add() {}, remove() {}, toggle() {}}, setAttribute() {}, appendChild() {}, append() {}, add() {}, remove() {}, getContext: () => null, parentElement: {}};
const nodes = {'#otCore': {...el, hidden: true}, '#runs': {...el, innerHTML: ''}, '#core': {...el, innerHTML: ''}};      // the two elements these tests read back; every other selector is the shared stub
const sb = {console, URLSearchParams, btoa, atob, TextEncoder, escape, unescape, Option: class {}, window: {}, location: {protocol: 'http:', search: ''},
  document: {querySelector: s => nodes[s] || el, querySelectorAll: () => [], getElementById: () => el, createElement: () => el, createTextNode: () => el, addEventListener() {}},
  fetch: () => Promise.resolve({ok: false}), ResizeObserver: class { observe() {} disconnect() {} },
  requestAnimationFrame() {}, setTimeout() {}, setInterval: () => 1, clearInterval() {}};
vm.createContext(sb);
vm.runInContext(html.match(/<script>([\s\S]*?)<\/script>/)[1], sb);
const run = s => vm.runInContext(s, sb);
run('window.__logs = []; log = (level, text) => window.__logs.push([level, text]); renderProps = () => {}; renderTree = () => {}; schedule = () => {};');
const logs = () => JSON.parse(JSON.stringify(run('window.__logs')));

let failed = 0;
const tests = [];
const test = (name, fn) => tests.push([name, fn]);

const DOC = {k_eff: 0.95511, kernel: 'sanm', converged: true, node_size_cm: 6.3, height_cm: 10,
  layout: [['reflector#5', 'asm A#2', 'asm B#3'], ['reflector#5', 'asm B#3', '<b>x</b>#9']],
  power: [[0, 1.2, 0.8], [0, 0.9, 1.1]],
  boundaries: {x_min: 'reflective', x_max: 'vacuum', y_min: 'vacuum', y_max: 'vacuum'},
  faces: {x_min: {boundary: 'reflective', source: 'model', detail: 'a plane at -25.2 cm with boundary condition reflective'},
          x_max: {boundary: 'vacuum', source: 'assumed', detail: 'just outside the face at 25.2 cm the model has Water (cell tank)'},
          y_min: {boundary: 'vacuum', source: 'override', detail: 'set by the caller: vacuum'}, y_max: {boundary: 'vacuum', source: 'model', detail: 'a plane at 25.2 cm with boundary condition vacuum'}},
  kinds: {'asm A#2': {universe: 2, role: 'fuel'}, 'asm B#3': {universe: 3, role: 'fuel'}, 'reflector#5': {universe: 5, role: 'reflector'}, '<b>x</b>#9': {universe: 9, role: 'fuel'}},
  pieces: [{label: 'infinite asm A#2', role: 'infinite', k: 1.3027, k_std: 0.0012, seconds: 9.4}, {label: 'strip asm B#3 reflector#5', role: 'strip', k: 1.1231, k_std: 0.0011, seconds: 8}],
  warnings: ['The lattice is 10 cm tall, 1.6 node widths: <axial> leakage is large.'],
  provenance: {recipe: 'fuel: infinite lattice ...', versions: {openndm: '0.3.0', openmc: '0.15.3'}, settings: {particles: 6000, batches: 60, seed: 11}}};
const render = () => { sb.__doc = DOC; return run('coreResultHtml(__doc)'); };

test('the result shows k, the power map in the layout\'s row order, and escapes labels', () => {
  const h = render();
  assert.ok(h.includes('0.95511') && h.includes('sanm') && h.includes('node 6.3 cm'));
  const rows = h.match(/<tr>(?:(?!<\/tr>).)*<\/tr>/g).filter(r => r.includes('corecell'));
  assert.strictEqual(rows.length, 2, 'one table row per layout row');
  assert.ok(rows[0].indexOf('1.20') < rows[0].indexOf('0.80'), 'columns in layout order');
  assert.ok(rows[0].includes('nopow') && rows[1].includes('nopow'), 'reflector cells carry no power');
  assert.ok(rows[1].includes('0.90') && rows[1].includes('1.10'), 'second row is the second layout row');
  assert.ok(rows[0].includes('asm A: relative power 1.200') && rows[0].includes('asm B: relative power 0.800'), 'each number sits under its own kind (first row)');
  assert.ok(rows[1].includes('asm B: relative power 0.900'), 'and in the second row');
  assert.ok(!h.includes('<b>x</b>'), 'a kind name with markup is escaped');
  assert.ok(h.includes('&lt;b&gt;x&lt;/b&gt;'));
});

test('warnings about the model come first, escaped; a large difference from OpenMC is called what it is', () => {
  let h = render();
  assert.ok(h.indexOf('Read this first') > 0 && h.indexOf('Read this first') < h.indexOf('k-eff <b>'), 'before the k');
  assert.ok(h.includes('&lt;axial&gt; leakage'), 'escaped');
  sb.__noWarn = JSON.parse(JSON.stringify(DOC)); sb.__noWarn.warnings = [];
  assert.ok(!run('coreResultHtml(__noWarn)').includes('Read this first'), 'no box when there is nothing to say');
  run('LOCAL.results = {summary: {keff: [0.36087, 0.005]}}; LOCAL.resultsRun = "r"');
  h = render();
  assert.ok(h.includes('= <b>59424 pcm</b>') && h.includes('not a small error of the method'));
  run('LOCAL.results = {summary: {keff: [0.94469, 0.0004]}}; LOCAL.resultsRun = "r"');
  assert.ok(!render().includes('not a small error of the method'), 'a thousand pcm is not called large');
  run('LOCAL.results = null; LOCAL.resultsRun = null');
});

test('it states its assumptions, with the outer faces that were used', () => {
  const h = render();
  assert.ok(/left: <b>reflective<\/b> \(model\): a plane at -25.2 cm/.test(h), 'each face with what was used, where it came from and why');
  assert.ok(/right: <b>vacuum<\/b> \(assumed\): just outside the face at 25.2 cm the model has Water/.test(h), 'an assumed face says what is outside it');
  assert.ok(/bottom: <b>vacuum<\/b> \(override\)/.test(h) && /top: <b>vacuum<\/b> \(model\)/.test(h));
  assert.ok(!h.includes('not read from the model'), 'the faces are read from the model now');
  assert.ok(h.includes('no pass line'), 'no claim that it holds for this model');
  assert.ok(h.includes('Radial two-dimensional') && h.includes('discontinuity factors'));
  assert.ok(h.includes('openndm 0.3.0') && h.includes('6000 × 60'));
});

test('beside an OpenMC result it gives the difference in pcm, and says what it did not check', () => {
  run('LOCAL.results = {summary: {keff: [0.94469, 0.0004]}}; LOCAL.resultsRun = "20261014-run-x"');
  const h = render();
  assert.ok(h.includes('nodal minus OpenMC = <b>1042 pcm</b>'), 'nodal minus OpenMC: ' + h.match(/nodal minus OpenMC = [^<]*<b>[^<]*/));
  assert.ok(h.includes('20261014-run-x') && h.includes('does not check that run is of this model'));
  run('LOCAL.results = null; LOCAL.resultsRun = null');
  assert.ok(render().includes('No OpenMC run is open'));
});

test('the form shows each outer face as a choice, from the model by default, and Solve is off without the package', () => {
  run("CORE.on = true; CORE.run = null; CORE.doc = null; CORE.form.faces = CORE_AUTO()");
  run('renderCore()');
  let h = nodes['#core'].innerHTML;
  for (const f of ['x_min', 'x_max', 'y_min', 'y_max']) {
    const m = h.match(new RegExp(`<select data-core-face="${f}">(.*?)</select>`));
    assert.ok(m, f + ' has a select');
    assert.strictEqual((m[1].match(/<option/g) || []).length, 3, 'three choices');
    assert.ok(/<option value="auto" selected>from the model/.test(m[1]), 'the model is the default: ' + m[1]);
  }
  run("CORE.form.faces.x_min = 'reflective'; renderCore()");
  h = nodes['#core'].innerHTML;
  assert.ok(/data-core-face="x_min">.*?<option value="reflective" selected>/.test(h), 'the choice is shown');
  assert.ok(!/<button[^>]*id="coreSolve"[^>]*disabled/.test(h), 'Solve is on when the package is there');
  run("CORE.on = false; CORE.why = 'not here'; renderCore()");
  h = nodes['#core'].innerHTML;
  assert.ok(/<button[^>]*id="coreSolve"[^>]*disabled/.test(h) && h.includes('Needs the nodal package') && h.includes('not here'));
  run("CORE.on = true; CORE.form.faces = CORE_AUTO()");
});

test('the settings sent are the form\'s, and the handlers change the form', () => {
  run("CORE.form = {preset:'quick', particles:6000, batches:60, inactive:15, seed:1, kernel:'sanm', faces:CORE_AUTO()}; CORE.on = true; renderCore = () => {}");
  const chg = (dataset, value, checked) => { sb.__e = {target: {dataset, value, checked}}; run('coreChange(__e)'); };
  chg({core: 'preset'}, 'standard');
  assert.deepStrictEqual(JSON.parse(JSON.stringify(run('coreSettings()'))), {particles: 20000, batches: 150, inactive: 30, seed: 1, kernel: 'sanm', reflective: [], vacuum: []});
  chg({core: 'inactive'}, '0');
  assert.strictEqual(run('CORE.form.inactive'), 0, 'zero inactive batches can be asked for');
  assert.strictEqual(run('CORE.form.preset'), 'custom');
  chg({core: 'kernel'}, 'nem');
  chg({coreFace: 'y_max'}, 'reflective');
  chg({coreFace: 'x_min'}, 'reflective');
  chg({coreFace: 'y_max'}, 'vacuum');
  chg({coreFace: 'x_max'}, 'sideways');
  const s = JSON.parse(JSON.stringify(run('coreSettings()')));
  assert.strictEqual(s.kernel, 'nem');
  assert.deepStrictEqual(s.reflective, ['x_min'], 'faces set and reset');
  assert.deepStrictEqual(s.vacuum, ['y_max'], 'and the ones forced to vacuum');
  assert.strictEqual(run('CORE.form.faces.x_max'), 'auto', 'a value the select does not offer changes nothing');
  chg({core: 'particles'}, 'abc');
  assert.strictEqual(run('CORE.form.particles'), 20000, 'text that is not a number changes nothing');
});

test('Solve sends the script, the project and the settings; a project with errors sends nothing', async () => {
  run("window.__realRefresh = refreshRuns; CORE.on = true; CORE.run = null; LOCAL.run = null; setRunning = () => {}; refreshRuns = () => {}; streamCore = () => {}; generate = () => 'SCRIPT'; S = {settings:{name:'core', seed:3}}");
  run("window.__posts = []; api = async (p, o) => { window.__posts.push([p, JSON.parse(o.body)]); return {id:'20261014-000000-core-nodal', kind:'nodal'}; }");
  run("problems = () => [{sev:'error', message:'x'}]");
  await run('coreSolve()');
  assert.strictEqual(JSON.parse(JSON.stringify(run('window.__posts'))).length, 0, 'nothing is sent while the model has errors');
  run("problems = () => []");
  await run('coreSolve()');
  const posts = JSON.parse(JSON.stringify(run('window.__posts')));
  assert.strictEqual(posts.length, 1);
  assert.strictEqual(posts[0][0], '/api/nodal/run');
  assert.strictEqual(posts[0][1].script, 'SCRIPT');
  assert.strictEqual(posts[0][1].name, 'core');
  assert.deepStrictEqual(posts[0][1].settings.reflective, ['x_min']);
  assert.deepStrictEqual(posts[0][1].settings.vacuum, ['y_max']);
  assert.strictEqual(run('LOCAL.run'), '20261014-000000-core-nodal', 'the Stop button now stops it');
  run('LOCAL.run = "busy"');
  await run('coreSolve()');
  assert.strictEqual(JSON.parse(JSON.stringify(run('window.__posts'))).length, 1, 'no second solve while a run is going');
  run('LOCAL.run = null; CORE.run = null');
});

test('the tab is shown only when the server has the package, and the log says why when it does not', async () => {
  run("window.__logs = []");
  run("api = async () => ({available: true, reason: null})");
  await run('coreInit()');
  assert.strictEqual(nodes['#otCore'].hidden, false);
  run("api = async () => ({available: false, reason: 'The nodal package (openndm 0.3.x) is not installed in /x/python.'})");
  await run('coreInit()');
  assert.strictEqual(nodes['#otCore'].hidden, true);
  assert.ok(logs().some(([lv, t]) => lv === 'info' && t.includes('openndm 0.3.x')), 'the log names what is missing');
  run("api = async () => { throw new Error('down'); }");
  await run('coreInit()');
  assert.strictEqual(nodes['#otCore'].hidden, true, 'an unreachable status hides the tab');
});

test('the runs list gives a nodal run a Core result button and not Results; opening its model loads no tallies', async () => {
  run("LOCAL.on = true; refreshRuns = window.__realRefresh");
  run("api = async () => ({runs: [{id:'a', name:'plain', status:'done', started:1, kind:'openmc'}, {id:'b', name:'core nodal', status:'done', started:2, kind:'nodal'}, {id:'c', name:'old', status:'done', started:3}]})");
  await run('refreshRuns()');
  const h = nodes['#runs'].innerHTML;
  assert.ok(h.includes('data-results="a"') && h.includes('data-results="c"') && !h.includes('data-results="b"'));
  assert.ok(h.includes('data-core-result="b"') && !h.includes('data-core-result="a"'));
  const nodalBtn = h.match(/<button[^>]*data-core-result="b"[^>]*>/)[0];
  assert.ok(!nodalBtn.includes('disabled'));
  run("api = async () => ({runs: [{id:'b', name:'x', status:'running', started:2, kind:'nodal'}]})");
  await run('refreshRuns()');
  assert.ok(nodes['#runs'].innerHTML.match(/<button[^>]*data-core-result="b"[^>]*>/)[0].includes('disabled'), 'not while it runs');
});

test('opening the model of a nodal run loads no tallies, of an OpenMC run it does; Core result opens the Core tab', async () => {
  run("window.__loaded = []; loadResults = async (id) => { window.__loaded.push(id); }; clearResults = () => {}; renderAll = () => {}; validProject = () => true; normalizeProject = () => {}; showCoreRun = async (id) => { window.__shown = id; }");
  run("api = async (p) => p.endsWith('/project') ? {settings: {depletion: false}} : {runs: [{id: 'n1', status: 'done', kind: 'nodal'}, {id: 'o1', status: 'done', kind: 'openmc'}]}");
  const click = (attr, id) => ({target: {closest: sel => sel === attr ? {dataset: {[attr.slice(6, -1).replace(/-(\w)/g, (m, ch) => ch.toUpperCase())]: id}} : null}});
  await run('runsClick')(click('[data-load]', 'n1'));
  assert.deepStrictEqual(JSON.parse(JSON.stringify(run('window.__loaded'))), [], 'no tallies for a nodal run');
  await run('runsClick')(click('[data-load]', 'o1'));
  assert.deepStrictEqual(JSON.parse(JSON.stringify(run('window.__loaded'))), ['o1']);
  await run('runsClick')(click('[data-core-result]', 'n1'));
  assert.strictEqual(run('window.__shown'), 'n1');
});

test('the output tabs include Core, so the tab can be shown', () => {
  assert.ok(/\['core', '#otCore'\]/.test(html), 'setOutTab lists the Core tab');
  assert.ok(/id="otCore"[^>]*hidden/.test(html), 'the tab starts hidden');
  assert.ok(/id="core" hidden/.test(html), 'the pane starts hidden');
});

(async () => {
  for (const [name, fn] of tests) {
    try { await fn(); console.log('ok   ' + name); } catch (e) { failed++; console.log('FAIL ' + name + '\n     ' + (e && e.message || e)); }
  }
  console.log(failed ? `${failed} of ${tests.length} failed` : `${tests.length} passed`);
  process.exit(failed ? 1 : 0);
})();
