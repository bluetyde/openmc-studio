// Helper for test/test_mcnp_import.py: commits an MCNP import report the way the page does (commitMcnpImport) and
// prints JSON {script, problems, components, materials, log} for the Python test to run in OpenMC.
// Usage: node test/mcnp_import_page.cjs <report.json> <deck name>
const fs = require('fs'), vm = require('vm'), path = require('path');
const html = fs.readFileSync(path.join(__dirname, '..', 'studio', 'openmc_studio', 'static', 'index.html'), 'utf8');
const el = {addEventListener() {}, insertAdjacentHTML() {}, querySelector: () => el, querySelectorAll: () => [], style: {}, dataset: {},
  classList: {add() {}, remove() {}, toggle() {}}, setAttribute() {}, appendChild() {}, append() {}, add() {}, remove() {}, getContext: () => null};
const sb = {console, URLSearchParams, btoa, atob, TextEncoder, escape, unescape, Option: class {}, window: {}, location: {protocol: 'http:', search: ''},
  document: {querySelector: () => el, querySelectorAll: () => [], getElementById: () => el, createElement: () => el, createTextNode: () => el, addEventListener() {}},
  fetch: () => Promise.resolve({ok: false}), ResizeObserver: class { observe() {} disconnect() {} },
  requestAnimationFrame() {}, setTimeout() {}, setInterval() {}};
vm.createContext(sb);
vm.runInContext(html.match(/<script>([\s\S]*?)<\/script>/)[1], sb);
const run = s => vm.runInContext(s, sb);
run('window.__log = []; log = (kind, msg) => window.__log.push([kind, msg]); setOutTab = () => {}; renderAll = () => {};');
sb.__report = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
sb.__name = process.argv[3];
run('S = normalizeProject(sampleModel()); commitMcnpImport(__report, __name);');
const out = run(`({script: generate(problems()), problems: problems().map(p => [p.sev, p.text]),
  components: S.csg.components.length, materials: S.materials.map(m => m.name), valid: validProject(JSON.parse(JSON.stringify(S))),
  log: window.__log})`);
process.stdout.write(JSON.stringify(out));
