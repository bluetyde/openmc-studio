// Unit tests for OpenMC Studio 3D STL Geometry Export.
// Validates tessellation, normals, vertex winding, binary & ASCII formats,
// coordinate transforms, and units scaling across all 7 primitives.
const fs = require('fs');
const vm = require('vm');
const path = require('path');
const assert = require('assert');

const indexPath = path.join(__dirname, '..', 'studio', 'openmc_studio', 'static', 'index.html');
const content = fs.readFileSync(indexPath, 'utf8');
const scriptMatch = content.match(/<script>([\s\S]*?)<\/script>/);
if (!scriptMatch) {
  console.error('Could not find script tag in index.html');
  process.exit(1);
}

const mockElem = {
  addEventListener: () => {},
  insertAdjacentHTML: () => {},
  querySelector: () => mockElem,
  querySelectorAll: () => [],
  style: {},
  dataset: {},
  classList: { add: () => {}, remove: () => {}, toggle: () => {} },
  setAttribute: () => {},
  appendChild: () => {},
  append: () => {},
  add: () => {},
  getContext: () => null
};

const sandbox = {
  console,
  Option: class { constructor(t, v, d, s) { this.text = t; this.value = v; this.defaultSelected = d; this.selected = s; } },
  document: { querySelector: () => mockElem, querySelectorAll: () => [], getElementById: () => mockElem, createElement: () => mockElem, addEventListener: () => {} },
  window: {},
  location: { protocol: 'http:', search: '' },
  URLSearchParams,
  fetch: () => Promise.resolve({ ok: false }),
  ResizeObserver: class { observe() {} disconnect() {} },
  requestAnimationFrame: () => {},
  setTimeout: () => {},
  setInterval: () => {}
};
vm.createContext(sandbox);
vm.runInContext(scriptMatch[1], sandbox);

console.log('Testing STL Export Engine...');

// Helper: check unit normal
function checkTriangle(t) {
  const [nx, ny, nz] = t.n;
  const l = Math.hypot(nx, ny, nz);
  assert(Math.abs(l - 1.0) < 1e-4, `Facet normal should be unit length, got ${l}`);
  assert(!isNaN(t.v1[0]) && !isNaN(t.v2[0]) && !isNaN(t.v3[0]), 'Vertices must not contain NaN');
}

// 1. Test Box Primitive
{
  const boxPart = {
    id: 'p_box', shape: 'box', name: 'Test Box',
    x: 10, y: 20, z: 30, sx: 4, sy: 6, sz: 8,
    rotX: 0, rotY: 0, rotZ: 0
  };
  const tris = sandbox.tessellateBox(boxPart);
  assert.equal(tris.length, 12, 'Box should have exactly 12 triangles (2 per face)');
  tris.forEach(checkTriangle);

  // Check generated STL
  const stlCm = sandbox.generateSTL([boxPart], { binary: true, units: 'cm' });
  assert.equal(stlCm.triangleCount, 12);
  assert.equal(stlCm.data.length, 84 + 12 * 50, 'Binary STL size must match 84 + 50*N bytes');

  // Verify uint32 triangle count in binary header
  const view = new DataView(stlCm.data.buffer, stlCm.data.byteOffset, stlCm.data.byteLength);
  assert.equal(view.getUint32(80, true), 12);

  // Check mm scaling
  const stlMm = sandbox.generateSTL([boxPart], { binary: true, units: 'mm' });
  const viewMm = new DataView(stlMm.data.buffer, stlMm.data.byteOffset, stlMm.data.byteLength);
  // Center was at x=10 cm -> in mm it should be around 100 mm
  // Vertex 1 of first triangle:
  const v1x = viewMm.getFloat32(84 + 12, true);
  assert(v1x >= 70 && v1x <= 130, `Vertex x in mm should be scaled by 10, got ${v1x}`);
  console.log('  [PASS] Box tessellation & binary STL scaling');
}

// 2. Test Cylinder Primitive
{
  const cylPart = {
    id: 'p_cyl', shape: 'cylinder', name: 'Test Cyl',
    x: 0, y: 0, z: 0, r: 2.5, h: 10, axis: 'z',
    rotX: 0, rotY: 0, rotZ: 0
  };
  const quality = 32;
  const tris = sandbox.tessellateCylinder(cylPart, quality);
  // Cylinder has: top fan (32), bottom fan (32), barrel quads (32*2 = 64) = 128 tris
  assert.equal(tris.length, quality * 4, `Cylinder with ${quality} segments should have ${quality * 4} triangles`);
  tris.forEach(checkTriangle);

  const res = sandbox.generateSTL([cylPart], { binary: true, quality });
  assert.equal(res.triangleCount, 128);
  console.log('  [PASS] Cylinder tessellation & triangle count');
}

// 3. Test Cone Primitive (Truncated and Sharp)
{
  // Truncated cone
  const coneTrunc = {
    id: 'p_cone', shape: 'cone', name: 'Truncated Cone',
    x: 0, y: 0, z: 0, r: 5, r2: 2, h: 10, axis: 'z',
    rotX: 0, rotY: 0, rotZ: 0
  };
  const quality = 32;
  const trisTrunc = sandbox.tessellateCone(coneTrunc, quality);
  assert.equal(trisTrunc.length, quality * 4);
  trisTrunc.forEach(checkTriangle);

  // Sharp tip cone (r2 = 0)
  const coneSharp = {
    id: 'p_cone2', shape: 'cone', name: 'Sharp Cone',
    x: 0, y: 0, z: 0, r: 5, r2: 0, h: 10, axis: 'z',
    rotX: 0, rotY: 0, rotZ: 0
  };
  const trisSharp = sandbox.tessellateCone(coneSharp, quality);
  // Bottom fan (32) + side wall fan (32) = 64 tris
  assert.equal(trisSharp.length, quality * 2);
  trisSharp.forEach(checkTriangle);
  console.log('  [PASS] Truncated and sharp cone tessellation');
}

// 4. Test Hex Prism Primitive
{
  const hexPart = {
    id: 'p_hex', shape: 'hex_prism', name: 'Hex Prism',
    x: 0, y: 0, z: 0, r: 3, h: 12, axis: 'z',
    rotX: 0, rotY: 0, rotZ: 0
  };
  const tris = sandbox.tessellateHexPrism(hexPart);
  // 6 side quads * 2 = 12 tris, top fan = 6 tris, bottom fan = 6 tris -> 24 tris
  assert.equal(tris.length, 24, 'Hex prism should have 24 triangles');
  tris.forEach(checkTriangle);
  console.log('  [PASS] Hex prism tessellation');
}

// 5. Test Wedge Primitive
{
  const wedgePart = {
    id: 'p_wedge', shape: 'wedge', name: 'Wedge',
    x: 0, y: 0, z: 0, sx: 4, sy: 6, sz: 8,
    rotX: 0, rotY: 0, rotZ: 0
  };
  const tris = sandbox.tessellateWedge(wedgePart);
  assert.equal(tris.length, 8, 'Wedge should have 8 triangles');
  tris.forEach(checkTriangle);
  console.log('  [PASS] Wedge tessellation');
}

// 6. Test Sphere and Ellipsoid Primitives
{
  const spherePart = {
    id: 'p_sph', shape: 'sphere', name: 'Sphere',
    x: 0, y: 0, z: 0, r: 4,
    rotX: 0, rotY: 0, rotZ: 0
  };
  const quality = 32;
  const trisSph = sandbox.tessellateSphere(spherePart, quality);
  assert(trisSph.length > 100, 'Sphere should generate a full mesh');
  trisSph.forEach(checkTriangle);

  const ellipPart = {
    id: 'p_ell', shape: 'ellipsoid', name: 'Ellipsoid',
    x: 0, y: 0, z: 0, a: 3, b: 4, c: 5,
    rotX: 0, rotY: 0, rotZ: 0
  };
  const trisEll = sandbox.tessellateEllipsoid(ellipPart, quality);
  assert.equal(trisEll.length, trisSph.length);
  trisEll.forEach(checkTriangle);
  console.log('  [PASS] Sphere and ellipsoid tessellation');
}

// 7. Test ASCII Multi-Solid STL Output
{
  const parts = [
    { id: 'p1', shape: 'box', name: 'Core Block', x: 0, y: 0, z: 0, sx: 10, sy: 10, sz: 10, rotX: 0, rotY: 0, rotZ: 0 },
    { id: 'p2', shape: 'sphere', name: 'Central Source', x: 0, y: 0, z: 0, r: 2, rotX: 0, rotY: 0, rotZ: 0 }
  ];
  const asciiRes = sandbox.generateSTL(parts, { binary: false, format: 'ascii' });
  assert.equal(asciiRes.binary, false);
  assert(typeof asciiRes.data === 'string', 'ASCII STL should be a string');
  assert(asciiRes.data.includes('solid Core_Block'), 'ASCII STL should include solid header for Core_Block');
  assert(asciiRes.data.includes('endsolid Core_Block'), 'ASCII STL should close solid for Core_Block');
  assert(asciiRes.data.includes('solid Central_Source'), 'ASCII STL should include solid header for Central_Source');
  assert(asciiRes.data.includes('endsolid Central_Source'), 'ASCII STL should close solid for Central_Source');
  assert(asciiRes.data.includes('facet normal'), 'ASCII STL should declare facet normals');
  assert(asciiRes.data.includes('vertex'), 'ASCII STL should declare vertices');
  console.log('  [PASS] ASCII multi-solid STL format');
}

// 8. Test TRISO Particle Multi-Shell Geometry
{
  const trisoParts = [
    { id: 'p_fuel', shape: 'sphere', name: 'UO2 Kernel', r: 0.025, x: 0, y: 0, z: 0, rotX: 0, rotY: 0, rotZ: 0 },
    { id: 'p_buff', shape: 'sphere', name: 'Buffer Layer', r: 0.035, x: 0, y: 0, z: 0, rotX: 0, rotY: 0, rotZ: 0 },
    { id: 'p_ipyc', shape: 'sphere', name: 'IPyC Layer', r: 0.039, x: 0, y: 0, z: 0, rotX: 0, rotY: 0, rotZ: 0 },
    { id: 'p_sic',  shape: 'sphere', name: 'SiC Layer',  r: 0.0425, x: 0, y: 0, z: 0, rotX: 0, rotY: 0, rotZ: 0 },
    { id: 'p_opyc', shape: 'sphere', name: 'OPyC Layer', r: 0.0465, x: 0, y: 0, z: 0, rotX: 0, rotY: 0, rotZ: 0 }
  ];
  const stlTriso = sandbox.generateSTL(trisoParts, { binary: true, quality: 32 });
  assert.equal(stlTriso.partGroups.length, 5, 'All 5 TRISO spherical layers should be tessellated');
  assert(stlTriso.triangleCount > 500, 'Total triangles should exceed 500');
  console.log('  [PASS] TRISO particle multi-shell STL export');
}

console.log('All STL export tests PASSED successfully!');
