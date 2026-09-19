// Writes the model.py files OpenMC Studio generates for a set of fixtures into test/generated/, so
// test_generated_models.py can run the real output (not a copy of its logic) in OpenMC.
//   node test/generate_fixtures.js
// Lattice fixtures also get a "_flat" twin (arrays written cell by cell, as the MCNP export does); the Python
// test checks that both describe the same geometry.
const fs = require('fs');
const vm = require('vm');
const path = require('path');

const html = fs.readFileSync(path.join(__dirname, '..', 'studio', 'openmc_studio', 'static', 'index.html'), 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
const el = {addEventListener() {}, insertAdjacentHTML() {}, querySelector: () => el, querySelectorAll: () => [], style: {}, dataset: {},
  classList: {add() {}, remove() {}, toggle() {}}, setAttribute() {}, appendChild() {}, append() {}, add() {}, getContext: () => null};
const sandbox = {console, URLSearchParams, Option: class {}, window: {}, location: {protocol: 'http:', search: ''},
  document: {querySelector: () => el, querySelectorAll: () => [], getElementById: () => el, createElement: () => el, addEventListener() {}},
  fetch: () => Promise.resolve({ok: false}), ResizeObserver: class { observe() {} disconnect() {} },
  requestAnimationFrame() {}, setTimeout() {}, setInterval() {}};
vm.createContext(sandbox);
vm.runInContext(script, sandbox);

const out = path.join(__dirname, 'generated');
fs.mkdirSync(out, {recursive: true});
function write(name, project, {flatTwin = false} = {}) {
  sandbox.normalizeProject(project);
  sandbox.__p = project;
  vm.runInContext('S = __p;', sandbox);
  const P = vm.runInContext('problems()', sandbox);
  const errors = P.filter(p => p.sev === 'error');
  if (errors.length) throw new Error(`${name}: ${errors.map(e => e.text).join('; ')}`);
  const save = (file, flat) => fs.writeFileSync(path.join(out, file), vm.runInContext(`buildScript(problems(), false, {flat:${flat}}).text`, sandbox));
  save(`${name}.py`, false);
  if (flatTwin) save(`${name}_flat.py`, true);
  const notes = P.filter(p => p.sev !== 'info').map(p => `${p.sev}: ${p.text}`);
  console.log(`${name}${flatTwin ? ' (+ flat twin)' : ''}${notes.length ? '  ' + notes.join(' | ') : ''}`);
}

const settings = extra => ({name: 'fixture', runMode: 'fixed source', particles: 2000, batches: 2, inactive: 0, seed: 7, maxTracks: 0,
  track: '', photon: false, worldShape: 'box', worldR: 60, worldBC: 'vacuum', worldFill: 'void', ...extra});
const water = {id: 'm_water', name: 'Water', color: '#4a8fd6', density: 1.0, frac: 'ao', comps: 'H:2, O:1', sab: 'c_H_in_H2O', ref: ''};
const steel = {id: 'm_steel', name: 'Iron', color: '#888888', density: 7.87, frac: 'ao', comps: 'Fe:1', sab: '', ref: ''};
const he3 = {id: 'm_he3', name: 'He-3 gas', color: '#8fe0c4', density: 0.000502, frac: 'ao', comps: 'He3:1', sab: '', ref: ''};
const bf3 = {id: 'm_bf3', name: 'BF3 gas', color: '#e0c48f', density: 0.00276, frac: 'ao', comps: 'B10:0.96, B11:0.04, F19:3', sab: '', ref: ''};
const pointSource = (x = 0, y = 0, z = 0) => ({id: 's1', name: 'Source', particle: 'neutron', strength: 1, space: 'point', x, y, z,
  rin: 0, r: 1, h: 1, x0: -1, x1: 1, y0: -1, y1: 1, z0: -1, z1: 1, angle: 'isotropic', u: 0, v: 0, w: 1,
  energy: 'lines', lines: '2:1', wa: 0.988, wb: 2.249, theta: 1.3, emin: 0.1, emax: 11});
const part = (id, shape, x, y, z, dims, material, group) => ({id, name: id, shape, x, y, z, r: 1, h: 1, axis: 'z',
  sx: 1, sy: 1, sz: 1, rx: 0, ry: 0, rz: 0, ...dims, material, ...(group ? {group} : {})});
const cellTally = (id, cells, extra = {}) => ({id, name: id, kind: 'cell', cells, scores: ['flux'], ebins: '', ...extra});

// 1. The NE403 graphite pile example (a 12 x 1 x 11 RectLattice of tilted boxes)
write('graphite_pile', JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'examples', 'ne403-graphite-pile', 'graphite-pile.openmc-studio.json'), 'utf8')), {flatTwin: true});

// 2. A 3 x 2 x 1 array of steel rods in water, off the origin in z, with one site deleted (ix 2, iy 0):
//    checks z placement of a one-layer lattice and the top-row-first y order of RectLattice.universes
{
  const parts = [];
  for (let ix = 0; ix < 3; ix++) for (let iy = 0; iy < 2; iy++) {
    if (ix === 2 && iy === 0) continue;
    parts.push(part(`rod_${ix}_${iy}`, 'cylinder', -10 + 10 * ix, -5 + 10 * iy, 20, {r: 2, h: 12}, 'm_steel', 'g_rods'));
  }
  parts.push(part('tank', 'box', 0, 0, 20, {sx: 50, sy: 40, sz: 30}, 'm_water'));
  write('rect_array', {materials: [water, steel], parts, sources: [pointSource(0, 0, 20)],
    groups: [{id: 'g_rods', name: 'Rods', parent: null, x: 0, y: 0, z: 20, lattice: {nx: 3, ny: 2, nz: 1, dx: 10, dy: 10, dz: 12, fill: 'auto', asLattice: true}}],
    tallies: [cellTally('t_tank', ['tank'])], settings: settings({worldR: 40})}, {flatTwin: true});
}

// 3. Hex arrays of pins (3 rings), 'y' orientation with the centre site empty and 'x' orientation full
for (const [orientation, skipCentre] of [['y', true], ['x', false]]) {
  const parts = [], p = 3;
  for (let x = -2; x <= 2; x++) for (let a = -2; a <= 2; a++) {
    if (Math.max(Math.abs(x), Math.abs(a), Math.abs(x + a)) > 2 || (skipCentre && !x && !a)) continue;
    const ox = orientation === 'x' ? (x + 0.5 * a) * p : Math.sqrt(3) / 2 * p * x;
    const oy = orientation === 'x' ? Math.sqrt(3) / 2 * p * a : (0.5 * x + a) * p;
    parts.push(part(`pin_${x}_${a}`, 'cylinder', +(5 + ox).toFixed(12), +(-4 + oy).toFixed(12), 3, {r: 1.1, h: 30}, 'm_steel', 'g_hex'));
  }
  parts.push(part('pool', 'box', 5, -4, 3, {sx: 40, sy: 40, sz: 40}, 'm_water'));
  write(`hex_array_${orientation}`, {materials: [water, steel], parts, sources: [pointSource(5, -4, 3)],
    groups: [{id: 'g_hex', name: 'Hex pins', parent: null, x: 5, y: -4, z: 3, lattice: {type: 'hex', rings: 3, pitch: p, orientation, fill: 'auto', asLattice: true}}],
    tallies: [cellTally('t_pool', ['pool'])], settings: settings({worldR: 30})}, {flatTwin: true});
}

// 4. Detector responses on the flux in a water cell: He-3 macro and micro, BF3 macro over all nuclides
write('detectors', {materials: [water, he3, bf3],
  parts: [part('ball', 'sphere', 0, 0, 0, {r: 8}, 'm_water'), part('slab', 'box', 0, 0, 20, {sx: 30, sy: 30, sz: 10}, 'm_water')],
  sources: [pointSource()], groups: [],
  tallies: [
    cellTally('t_flux', ['slab']),
    cellTally('t_he3_macro', ['slab'], {detector: 'he3', responseMat: 'm_he3', responseScale: 'macro'}),
    cellTally('t_he3_micro', ['slab'], {detector: 'he3', responseMat: 'm_he3', responseScale: 'micro'}),
    cellTally('t_bf3_macro', ['slab'], {detector: 'custom', responseMat: 'm_bf3', responseNuc: 'all', responseScore: '(n,a)', responseScale: 'macro'})],
  settings: settings({worldR: 40})});

// 5. Current leaving a sphere through its surface (OpenMC only: MCNP export of surface tallies isn't done yet)
write('surface_current', {materials: [water],
  parts: [part('ball', 'sphere', 0, 0, 0, {r: 8}, 'm_water'), part('shell', 'box', 0, 0, 0, {sx: 30, sy: 30, sz: 30}, 'm_water')],
  sources: [pointSource()], groups: [],
  tallies: [{id: 't_current', name: 't_current', kind: 'surface', surfaces: ['ball'], cells: [], scores: ['current'], ebins: ''}],
  settings: settings({worldR: 40})});
