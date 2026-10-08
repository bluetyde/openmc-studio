// Writes test/generated/depletion_slices/project.json and model.py: the same pin cell cut into two axial slices of different enrichment, both burnable (3.5 % below, 5 % above) as Studio would
// save it with Settings > Depletion on and the fuel marked Burnable, and the model.py the page generates for it. The real depletion of
// that pin is test/manual_depletion_run.py, which takes minutes. This file only needs Node.
// Run: node test/generate_depletion_slices.cjs
const fs = require('fs'), vm = require('vm'), path = require('path');

const html = fs.readFileSync(path.join(__dirname, '..', 'studio', 'openmc_studio', 'static', 'index.html'), 'utf8');
const el = {addEventListener() {}, insertAdjacentHTML() {}, querySelector: () => el, querySelectorAll: () => [], style: {}, dataset: {},
  classList: {add() {}, remove() {}, toggle() {}}, setAttribute() {}, appendChild() {}, append() {}, add() {}, remove() {}, getContext: () => null, parentElement: {}};
const sb = {console, URLSearchParams, btoa, atob, TextEncoder, escape, unescape, Option: class {}, window: {}, location: {protocol: 'http:', search: ''},
  document: {querySelector: () => el, querySelectorAll: () => [], getElementById: () => el, createElement: () => el, createTextNode: () => el, addEventListener() {}},
  fetch: () => Promise.resolve({ok: false}), ResizeObserver: class { observe() {} disconnect() {} },
  requestAnimationFrame() {}, setTimeout() {}, setInterval: () => 1, clearInterval() {}};
vm.createContext(sb);
vm.runInContext(html.match(/<script>([\s\S]*?)<\/script>/)[1], sb);

const project = JSON.parse(vm.runInContext(`JSON.stringify((() => {
  const p = sampleModel();
  const mat = (id, name, density, comps, sab, extra) => Object.assign({id, name, color:'#999999', density, frac:'ao', comps, sab:sab || ''}, extra || {});
  p.materials = [mat('m1', 'UO2 3.5%', 10.4, 'U235:0.035, U238:0.965, O16:2', '', {burnable:true}), mat('m2', 'Zircaloy', 6.55, 'Zr:1'),
                 mat('m3', 'Water', 0.74, 'H:2, O:1', 'c_H_in_H2O'), mat('m4', 'UO2 5%', 10.4, 'U235:0.05, U238:0.95, O16:2', '', {burnable:true})];
  const cyl = (id, name, r, material) => Object.assign(newPart(id, name, 'cylinder'), {x:0, y:0, z:0, r, h:1.26, axis:'z', material});
  p.parts = [Object.assign(cyl('p1', 'Fuel lower', 0.4096, 'm1'), {h:0.63, z:-0.315}), Object.assign(cyl('p3', 'Fuel upper', 0.4096, 'm4'), {h:0.63, z:0.315}), cyl('p2', 'Cladding', 0.475, 'm2')];
  p.groups = [];
  p.sources = [Object.assign({}, p.sources[0], {id:'s1', name:'Fission source', space:'box', x0:-0.4, x1:0.4, y0:-0.4, y1:0.4, z0:-0.6, z1:0.6, energy:'watt', particle:'neutron', strength:1})];
  p.tallies = [];
  Object.assign(p.settings, {name:'Depletion slices', runMode:'eigenvalue', particles:2000, batches:15, inactive:5, seed:12345, maxTracks:0,
    worldShape:'box', worldR:0.63, worldBC:'reflective', worldFill:'m3', depletion:true, depPower:38, depSteps:'1, 4', depIntegrator:'PredictorIntegrator', depReduce:3});
  return p;
})())`, sb));

sb.__p = JSON.stringify(project);
const out = JSON.parse(vm.runInContext(`S = JSON.parse(__p); const P = problems(); JSON.stringify({errors: P.filter(x => x.sev === 'error').map(x => x.text), text: generate(P)})`, sb));
if (out.errors.length) { console.error('the page refuses this project:', out.errors); process.exit(1); }
const dir = path.join(__dirname, 'generated', 'depletion_slices');
fs.mkdirSync(dir, {recursive: true});
fs.writeFileSync(path.join(dir, 'project.json'), JSON.stringify(project, null, 1) + '\n');
fs.writeFileSync(path.join(dir, 'model.py'), out.text);
console.log(`wrote ${dir}/project.json and model.py (${out.text.split('\n').length} lines)`);
