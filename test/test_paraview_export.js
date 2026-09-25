// Export for ParaView, page side: geometry is grouped into one binary STL per material, taken from the
// run's own project; the Export ribbon button needs a run's results. (The VTK files themselves are checked
// by test/test_vtk_export.py with VTK's own reader.)
// Run: node test/test_paraview_export.js
const fs = require('fs'), vm = require('vm'), path = require('path'), assert = require('assert');

const html = fs.readFileSync(path.join(__dirname, '..', 'studio', 'openmc_studio', 'static', 'index.html'), 'utf8');
const el = {addEventListener() {}, insertAdjacentHTML() {}, querySelector: () => el, querySelectorAll: () => [], style: {}, dataset: {},
  classList: {add() {}, remove() {}, toggle() {}}, setAttribute() {}, appendChild() {}, append() {}, add() {}, getContext: () => null};
const sb = {console, URLSearchParams, btoa, atob, TextEncoder, Option: class {}, window: {}, location: {protocol: 'http:', search: ''},
  document: {querySelector: () => el, querySelectorAll: () => [], getElementById: () => el, createElement: () => el, createTextNode: () => el, addEventListener() {}},
  fetch: () => Promise.resolve({ok: false}), ResizeObserver: class { observe() {} disconnect() {} },
  requestAnimationFrame() {}, setTimeout() {}, setInterval() {}};
vm.createContext(sb);
vm.runInContext(html.match(/<script>([\s\S]*?)<\/script>/)[1], sb);
const run = s => vm.runInContext(s, sb);

run('S = normalizeProject(sampleModel());');
const project = run('JSON.parse(JSON.stringify(S))');
const files = sb.paraviewStl(project);
const byMat = {};
project.parts.forEach(p => {
  const m = project.materials.find(x => x.id === p.material);
  const k = m ? m.name : 'void';
  byMat[k] = (byMat[k] || 0) + 1;
});
assert.deepEqual(Object.keys(files).sort(), Object.keys(byMat).map(k => `geometry_${k}.stl`).sort(), 'one STL per material');
for (const [name, b64] of Object.entries(files)) {
  const buf = Buffer.from(b64, 'base64');
  const n = buf.readUInt32LE(80);  // binary STL: 80-byte header, triangle count, 50 bytes per triangle
  assert.equal(buf.length, 84 + 50 * n, `${name} is a well-formed binary STL`);
  assert.ok(n > 0, `${name} has triangles`);
}
console.log(`  [PASS] one binary STL per material (${Object.keys(files).length} files)`);

run('LOCAL.on = true; LOCAL.resultsRun = null;');
const btn = () => run("RIBBON.Export.find(g => g.label === '3D Mesh').btns.find(b => b[1] === 'ParaView (VTK)')");
assert.equal(btn()[3](), false, 'disabled without results');
run("LOCAL.resultsRun = '20260925-000000-demo';");
assert.equal(btn()[3](), true, 'enabled once a run has results');
console.log('  [PASS] the ribbon button needs a run');
console.log('test_paraview_export: PASS');
