// Flux map controls (plans: mesh maps, stage 1) and the geometry check's Problems entries, against
// the real functions in index.html: Map round trips, Thickness, Resolution, "Add the other two planes",
// the size-and-noise line, the edge-on and out-of-range hints, layer labels, a 3D map in model.py and
// in MCNP, and geometry-check results turning into Problems that go stale when the geometry changes.
// Run: node test/test_mesh_maps.js
const fs = require('fs'), vm = require('vm'), path = require('path'), assert = require('assert');

const html = fs.readFileSync(path.join(__dirname, '..', 'studio', 'openmc_studio', 'static', 'index.html'), 'utf8');
const code = html.match(/<script>([\s\S]*?)<\/script>/)[1];
const el = {addEventListener() {}, insertAdjacentHTML() {}, querySelector: () => el, querySelectorAll: () => [], style: {}, dataset: {},
  classList: {add() {}, remove() {}, toggle() {}}, setAttribute() {}, appendChild() {}, append() {}, add() {}, getContext: () => null,
  checked: true, value: '0'};
const sb = {console, URLSearchParams, Option: class {}, window: {}, location: {protocol: 'http:', search: ''},
  document: {querySelector: () => el, querySelectorAll: () => [], getElementById: () => el, createElement: () => el, createTextNode: () => el, addEventListener() {}},
  fetch: () => Promise.resolve({ok: false}), ResizeObserver: class { observe() {} disconnect() {} },
  requestAnimationFrame() {}, setTimeout() {}, setInterval() {}};
vm.createContext(sb);
vm.runInContext(code, sb);
const run = s => vm.runInContext(s, sb);

let failed = 0;
const test = (name, fn) => {
  try { run("S = normalizeProject(sampleModel()); S.tallies = []; LOCAL.results = null; GEOM.res = null; view.plane = 'xz'; view.slice = 0;"); fn(); console.log(`  [PASS] ${name}`); }
  catch (e) { failed++; console.log(`  [FAIL] ${name}\n${e.stack}`); }
};
const corners = t => ['nx', 'ny', 'nz', 'lx', 'ly', 'lz', 'ux', 'uy', 'uz'].map(k => t[k]);
const addMap = () => run("addTally('mesh'); S.tallies[S.tallies.length - 1]");

test('a new map in the XZ view is an XZ slab', () => {
  const t = addMap();
  assert.equal(sb.meshMapMode(t), 'xz');
  assert.deepEqual([t.ny, t.ly, t.uy], [1, -1, 1]);
});

test('XZ slab -> 3D box -> XZ slab gives back the same bins and corners', () => {
  const t = addMap();
  run('S.tallies[0].ly = 3; S.tallies[0].uy = 7;');  // a slab that is not at the origin
  const before = corners(t);
  sb.setMeshMap(t, '3d');
  assert.equal(sb.meshMapMode(t), '3d');
  assert.deepEqual([t.ny, t.ly, t.uy], [t.nx, t.lx, t.ux], 'the flat axis takes the larger other axis');
  sb.setMeshMap(t, 'xz');
  assert.deepEqual(corners(t), before);
});

test('XZ slab -> YZ slab faces x and keeps the bins in the plane', () => {
  const t = addMap();
  run('view.plane = "yz"; view.slice = 12;');
  sb.setMeshMap(t, 'yz');
  assert.equal(sb.meshMapMode(t), 'yz');
  assert.deepEqual([t.nx, t.lx, t.ux], [1, 11, 13], 'a new slab centres on the slice when it faces the view');
  assert.ok(t.ny > 1 && t.nz > 1);
});

test('Thickness changes only the flat axis, about its centre', () => {
  const t = addMap();
  const other = [t.nx, t.lx, t.ux, t.nz, t.lz, t.uz];
  sb.setSlabThickness(t, 10);
  assert.deepEqual([t.ly, t.uy, t.ny], [-5, 5, 1]);
  assert.deepEqual([t.nx, t.lx, t.ux, t.nz, t.lz, t.uz], other);
});

test('Centre on the current slice works only for a slab facing the view', () => {
  const t = addMap();
  run('view.plane = "xy"; view.slice = 30;');
  assert.equal(sb.centreSlabOnSlice(t), false);
  assert.deepEqual([t.ly, t.uy], [-1, 1]);
  run('view.plane = "xz"; view.slice = 30;');
  assert.equal(sb.centreSlabOnSlice(t), true);
  assert.deepEqual([t.ly, t.uy], [29, 31]);
});

test('Resolution sets N along the longest side, the rest in proportion', () => {
  const t = addMap();
  sb.setMeshMap(t, '3d');
  run('S.tallies[0].lz = -50; S.tallies[0].uz = 50;');  // z is half as long as x and y
  sb.setMeshResolution(t, 40);
  assert.deepEqual([t.nx, t.ny, t.nz], [40, 40, 20]);
});

test('Add the other two planes: three maps, one per plane, through one point', () => {
  const t = addMap();
  run("S.tallies[0].name = 'Flux'; S.tallies[0].ly = 4; S.tallies[0].uy = 6;");
  const made = sb.addOtherPlanes(t);
  assert.equal(made.length, 2);
  const all = run('S.tallies');
  assert.deepEqual(all.map(x => x.name), ['Flux (XZ)', 'Flux (XY)', 'Flux (YZ)']);
  assert.deepEqual(all.map(x => sb.meshMapMode(x)), ['xz', 'xy', 'yz']);
  const xy = all[1], yz = all[2];
  assert.deepEqual([xy.lz, xy.uz], [-1, 1], 'XY slab at z = the XZ map\'s z centre, same thickness');
  assert.deepEqual([yz.lx, yz.ux], [-1, 1]);
  assert.deepEqual([xy.ny, xy.ly, xy.uy], [t.nx, t.lx, t.ux], 'the old flat axis spans like the others');
  assert.ok(new Set(all.map(x => x.id)).size === 3);
});

test('the size line counts voxels and estimates the noise', () => {
  const t = addMap();  // 50 x 1 x 50 = 2,500 voxels; sample settings give particles x batches histories
  const st = run('S.settings'), H = st.particles * st.batches;
  const e = sb.meshErrorEstimate(t);
  assert.ok(Math.abs(e.rel - Math.sqrt(2500 / H)) < 1e-12);
  assert.match(sb.meshInfoText(t), /^2,500 voxels, each 4 × 2 × 4 cm/);
  sb.setMeshMap(t, '3d');
  assert.ok(Math.abs(sb.meshErrorEstimate(t).rel / e.rel - Math.sqrt(50)) < 1e-9, '50x the voxels, sqrt(50)x the error');
});

test('with a previous run, the estimate scales from that run\'s map', () => {
  const t = addMap();
  const st = run('S.settings');
  run(`LOCAL.results = {summary:{particles:${st.particles}, batches:${st.batches}, run_mode:'fixed source'},
    tallies:[{kind:'mesh', name:${JSON.stringify(t.name)}, dims:[50, 1, 50], scores:['flux'], rel_err:{flux:[0.02, 0.04, 0.03, 0]}}]}`);
  assert.ok(Math.abs(sb.meshErrorEstimate(t).rel - 0.03) < 1e-12, 'same map and histories: the median error');
  run('S.settings.particles *= 4');
  assert.ok(Math.abs(sb.meshErrorEstimate(t).rel - 0.015) < 1e-12, '4x the histories halves it');
  assert.match(sb.meshErrorEstimate(t).basis, /last run/);
});

test('the million-voxel warning carries the numbers', () => {
  const t = addMap();
  sb.setMeshMap(t, '3d');
  sb.setMeshResolution(t, 120);
  const w = run('problems()').find(p => /over a million/.test(p.text));
  assert.ok(w, 'warning present');
  assert.match(w.text, /1,728,000 voxels/);
  assert.match(w.text, /error per voxel/);
});

test('layer labels and viewport hints', () => {
  const R = {kind: 'mesh', name: 'Flux map', mesh_type: 'regular', dims: [50, 1, 50], lower: [-100, -5, -100], upper: [100, 5, 100], scores: ['flux'], values: {flux: []}};
  assert.equal(sb.meshLayerLabel(R), 'XZ slab · y = 0 ± 5 cm');
  assert.equal(sb.meshLayerLabel({...R, dims: [100, 100, 100]}), '3D box · 100³ voxels');
  run(`LOCAL.results = {tallies:[${JSON.stringify(R)}]}`);
  el.checked = true; el.value = '0';  // the mock DOM shares one element: "Flux map" ticked, first map picked
  run('view.plane = "xy"; view.slice = 0;');
  assert.equal(sb.meshViewHint(), 'Flux map (XZ) is edge-on here. Switch to the XZ view, or give it thickness.');
  run('view.plane = "xz"; view.slice = 0;');
  assert.equal(sb.meshViewHint(), '');
  run('view.plane = "xz"; view.slice = 40;');
  assert.equal(sb.meshViewHint(), 'Flux map (XZ) covers y = -5 to 5 cm; this slice is at y = 40 cm.');
  run(`LOCAL.results.tallies[0].name = 'Flux map (XZ)'; view.plane = 'xy';`);
  assert.equal(sb.meshViewHint(), 'Flux map (XZ) is edge-on here. Switch to the XZ view, or give it thickness.', 'no doubled plane');
});

test('a 3D map builds a 3D mesh in model.py and an FMESH with three bin counts', () => {
  const t = addMap();
  sb.setMeshMap(t, '3d');
  sb.setMeshResolution(t, 20);
  const py = run('generate(problems())');
  assert.match(py, /\.dimension = \[20, 20, 20\]/);
  const card = sb.mcnpTally(t);
  assert.match(card, /FMESH\d+/);
  assert.match(card, /IINTS=20/); assert.match(card, /JINTS=20/); assert.match(card, /KINTS=20/);
});

test('geometry check results become Problems, and go stale when the geometry changes', () => {
  const [a, b] = run('S.parts.slice(0, 2)');
  run(`GEOM.res = {seconds:1, cells:{"1":{kind:'part', id:${JSON.stringify(a.id)}}, "2":{kind:'part', id:${JSON.stringify(b.id)}}},
    points:{points:100000, gaps:0, overlaps:3, overlap_pairs:[[1, 2]], overlap_examples:[{p:[1, 2, 3], cells:[1, 2]}], gap_examples:[]},
    transport:{ran:true, particles:1000, lost:0, overlap:null}}; GEOM.key = geomKey();`);
  const e = run('problems()').find(p => p.geom && p.sev === 'error');
  assert.ok(e, 'an overlap error');
  assert.ok(e.text.startsWith(`${a.name} and ${b.name} overlap`), e.text);
  assert.deepEqual(e.at, [1, 2, 3]);
  assert.deepEqual(e.sel, {kind: 'part', id: a.id});
  run('S.materials[0].name = "renamed"; S.parts[0].name = "renamed part";');
  assert.ok(run('problems()').some(p => p.geom), 'names and materials don\'t change the geometry');
  run('S.parts[0].x += 1;');
  assert.ok(!run('problems()').some(p => p.geom), 'moving a part makes the result stale');
});

test('a clean geometry check is one info line', () => {
  run(`GEOM.res = {seconds:1, cells:{}, points:{points:100000, gaps:0, overlaps:0, overlap_pairs:[], overlap_examples:[], gap_examples:[]},
    transport:{ran:true, particles:1000, lost:0, overlap:null}}; GEOM.key = geomKey();`);
  const g = run('problems()').filter(p => p.geom);
  assert.equal(g.length, 1);
  assert.equal(g[0].sev, 'info');
  assert.match(g[0].text, /^Geometry check passed: 100,000 points/);
});

if (failed) { console.log(`test_mesh_maps: ${failed} FAILED`); process.exit(1); }
console.log('test_mesh_maps: PASS');
