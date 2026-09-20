// Integration test verifying that index.html buildScript produces valid models
// for B-10, He-3 presets and multi-nuclide custom detector tallies.
const fs = require('fs');
const vm = require('vm');
const path = require('path');

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

// Execute inline script
vm.runInContext(scriptMatch[1], sandbox);

// Set up mock test state
const S_test = {
  settings: {
    ...sandbox.DEFAULT_SETTINGS,
    runMode: 'fixed source',
    seed: 12345,
    worldR: 100,
    worldShape: 'box',
    worldFill: 'm_air',
    maxTracks: 0,
    track: ''
  },
  parts: [],
  groups: [],
  sources: [],
  materials: [
    { id: 'm_bf3', name: 'BF3 gas', comps: 'B10: 0.96, B11: 0.04, F19: 3.0', density: 0.00268 },
    { id: 'm_he3', name: 'He3 gas', comps: 'He3: 1.0', density: 0.0005 },
    { id: 'm_air', name: 'Air', comps: 'N14: 0.78, O16: 0.22', density: 0.0012 }
  ],
  tallies: [
    { id: 't1', name: 'B10 Det', kind: 'cell', cells: ['world'], scores: ['flux'], detector: 'b10', responseMat: '', responseScale: 'macro', ebins: '' },
    { id: 't2', name: 'He3 Det', kind: 'cell', cells: ['world'], scores: ['flux'], detector: 'he3', responseMat: '', responseScale: 'macro', ebins: '' },
    { id: 't3', name: 'Custom Det', kind: 'cell', cells: ['world'], scores: ['flux'], detector: 'custom', responseMat: 'm_bf3', responseNuc: 'all', responseScore: '(n,a)', responseScale: 'macro', ebins: '' }
  ]
};

// Normalize project and test detector resolution
sandbox.normalizeProject(S_test);
vm.runInContext("S = " + JSON.stringify(S_test) + ";", sandbox);

// Test resolveDetector helper
const d1 = sandbox.resolveDetector(S_test.tallies[0]);
console.log('Tally 1 (B-10 preset) resolved:', d1);
if (d1.respNuc !== 'B10' || d1.mt !== '107' || d1.respScore !== '(n,a)' || d1.respMatId !== 'm_bf3') {
  console.error('FAILED: B-10 preset resolution mismatch');
  process.exit(1);
}

const d2 = sandbox.resolveDetector(S_test.tallies[1]);
console.log('Tally 2 (He-3 preset) resolved:', d2);
if (d2.respNuc !== 'He3' || d2.mt !== '103' || d2.respScore !== '(n,p)' || d2.respMatId !== 'm_he3') {
  console.error('FAILED: He-3 preset resolution mismatch');
  process.exit(1);
}

const d3 = sandbox.resolveDetector(S_test.tallies[2]);
console.log('Tally 3 (Custom Det) resolved:', d3);
if (d3.respNuc !== 'all' || d3.mt !== '107' || d3.respScore !== '(n,a)' || d3.respMatId !== 'm_bf3') {
  console.error('FAILED: Custom Det resolution mismatch');
  process.exit(1);
}

// Generate model.py
const py = sandbox.generate([]);
console.log('Generated Python script length:', py.length);
py.split('\n').filter(l => l.includes('_get_detector_filter') || l.includes('mat_')).forEach(l => console.log('PY LINE:', l));
// Assertions on generated Python
if (!py.includes('eff_b10_det = _get_detector_filter(mat_bf3_gas, "B10", 107, "macro")')) {
  console.error("FAILED: Missing or incorrect B-10 filter call in Python export");
  process.exit(1);
}
if (!py.includes('eff_he3_det = _get_detector_filter(mat_he3_gas, "He3", 103, "macro")')) {
  console.error("FAILED: Missing or incorrect He-3 filter call in Python export");
  process.exit(1);
}
if (!py.includes('eff_custom_det = _get_detector_filter(mat_bf3_gas, "all", 107, "macro")')) {
  console.error("FAILED: Missing or incorrect Custom filter call in Python export");
  process.exit(1);
}
if (!py.includes("mat_bf3_gas = openmc.Material(name=\"BF3 gas\")")) {
  console.error("FAILED: BF3 material not declared in Python export");
  process.exit(1);
}
if (!py.includes("mat_he3_gas = openmc.Material(name=\"He3 gas\")")) {
  console.error("FAILED: He3 material not declared in Python export");
  process.exit(1);
}

// Generate MCNP cards
const mcnp1 = sandbox.mcnpTally(S_test.tallies[0]);
console.log('MCNP Tally 1:\n' + mcnp1);
// Macroscopic response: C is the detector material's atom density (N), not -1 (the tallied cell's own)
if (!/FM\d+ \(N 1 107\)/.test(mcnp1)) {
  console.error('FAILED: MCNP Tally 1 missing FM (N 1 107)');
  process.exit(1);
}

const mcnp2 = sandbox.mcnpTally(S_test.tallies[1]);
console.log('MCNP Tally 2:\n' + mcnp2);
if (!/FM\d+ \(N 2 103\)/.test(mcnp2)) {
  console.error('FAILED: MCNP Tally 2 missing FM (N 2 103)');
  process.exit(1);
}

// ── Test Phases 5-8 Physics Core & Capabilities ──
console.log('\nTesting Phases 5-8 physics and modeling extensions...');

// Configure advanced physics
S_test.settings.photon = true;
S_test.settings.photonCutoff = 1500;
S_test.settings.temperatureDefault = 600.0;
S_test.settings.temperatureMethod = 'interpolation';
S_test.settings.worldBC = 'periodic';
S_test.settings.runMode = 'eigenvalue';
S_test.settings.entropyMesh = true;
S_test.settings.entropyNx = 8;
S_test.settings.entropyNy = 8;
S_test.settings.entropyNz = 8;

S_test.materials[0].temperature = 800.0; // BF3 at 800 K

S_test.sources.push({
  id: 's_muir',
  name: 'Fusion source',
  particle: 'neutron',
  strength: 1.0,
  space: 'point',
  x: 0, y: 0, z: 0,
  angle: 'isotropic',
  energy: 'muir',
  muir_e0: 14.08,
  muir_mrat: 5.0,
  muir_kt: 25000.0
});

S_test.tallies.push({
  id: 't_photon',
  name: 'Gamma flux',
  kind: 'cell',
  particle: 'photon',
  cells: ['world'],
  scores: ['flux'],
  detector: 'none',
  ebins: ''
});

sandbox.normalizeProject(S_test);
vm.runInContext("S = " + JSON.stringify(S_test) + ";", sandbox);

const py2 = sandbox.generate([]);
console.log('Advanced Python script length:', py2.length);

// Verify Material Temperature
if (!py2.includes('mat_bf3_gas.temperature = 800')) {
  console.error('FAILED: Missing material temperature 800 in Python export');
  process.exit(1);
}

// Verify Global Settings Temperature
if (!py2.includes("settings.temperature = {'default': 600.0, 'method': \"interpolation\"}")) {
  console.error('FAILED: Missing settings.temperature in Python export');
  process.exit(1);
}

// Verify Photon Transport & Cutoff
if (!py2.includes('settings.photon_transport = True')) {
  console.error('FAILED: Missing settings.photon_transport = True in Python export');
  process.exit(1);
}
if (!py2.includes("settings.cutoff = {'energy_photon': 1500.0}")) {
  console.error('FAILED: Missing settings.cutoff in Python export');
  process.exit(1);
}

// Verify Shannon Entropy Mesh
if (!py2.includes('openmc.RegularMesh(name="Shannon entropy mesh")') ||
    !py2.includes('.dimension = [8, 8, 8]') ||
    !py2.includes('settings.entropy_mesh = ')) {
  console.error('FAILED: Missing or incorrect Shannon entropy mesh in Python export');
  process.exit(1);
}

// Verify Muir Fusion Spectrum
console.log('Muir lines in py2:');
py2.split('\n').filter(l => l.includes('muir')).forEach(l => console.log('  ', l));
if (!py2.includes('openmc.stats.muir(e0=1.408e7, m_rat=5.0, kt=25000.0)')) {
  console.error('FAILED: Missing or incorrect openmc.stats.muir call in Python export');
  process.exit(1);
}

// Verify Periodic Boundary Surface Linking
if (!py2.includes('.periodic_surface = ')) {
  console.error('FAILED: Periodic surface pairing missing in Python export');
  process.exit(1);
}

// Verify Particle Filter on Tallies
if (!py2.includes('openmc.ParticleFilter(["photon"])')) {
  console.error('FAILED: Missing openmc.ParticleFilter(["photon"]) in Python export');
  process.exit(1);
}

// Verify MCNP Photon Tally
const mcnpPhoton = sandbox.mcnpTally(S_test.tallies[3]);
console.log('MCNP Photon Tally:\n' + mcnpPhoton);
if (!mcnpPhoton.includes(':P')) {
  console.error('FAILED: MCNP Photon tally missing :P card specifier');
  process.exit(1);
}

// Verify MCNP Muir Source
const mcnpMuir = sandbox.mcnpSource(S_test.sources[0]);
console.log('MCNP Muir Source:\n' + mcnpMuir);
// Gaussian fusion spectrum SP -4 a b, a = sqrt(4*E0*kT/m_rat) MeV: sqrt(4*14.08*0.025/5) = 0.53066
if (!/^SP\d+ -4 0\.53066\d* 14\.08$/m.test(mcnpMuir) || /SDEF[^\n]* c /.test(mcnpMuir)) {
  console.error('FAILED: MCNP Muir source should be ERG=Dn with SPn -4 0.53066 14.08 and no comment inside SDEF');
  process.exit(1);
}

// ── Test Phases 9-11 Advanced Capabilities ──
console.log('\nTesting Phases 9-11 (HexLattice, CylindricalMesh, Ellipsoid Quadric)...');

// 1. Hexagonal Lattice
S_test.groups.push({
  id: 'g_hex',
  name: 'Hex Core',
  x: 0, y: 0, z: 0,
  lattice: {
    asLattice: true,
    type: 'hex',
    pitch: 1.4,
    rings: 3,
    orientation: 'x',
    fill: 'm_air',
    dz: 20,
    nz: 1
  }
});
for (let x = -2; x <= 2; x++) for (let a = -2; a <= 2; a++) {
  if (Math.max(Math.abs(x), Math.abs(a), Math.abs(x + a)) > 2) continue;
  S_test.parts.push({ id: `p_pin_${x}_${a}`, name: `Fuel Pin ${x},${a}`, shape: 'cylinder', axis: 'z', group: 'g_hex',
    x: +((x + 0.5 * a) * 1.4).toFixed(12), y: +(Math.sqrt(3) / 2 * 1.4 * a).toFixed(12), z: 0, r: 0.4, h: 20, rx: 0, ry: 0, rz: 0, material: 'm_bf3' });
}

// The hex array sits in its own box of air (a lattice box must lie inside one part that no cell tally counts)
S_test.parts.push({ id: 'p_hexbox', name: 'Hex box', shape: 'box', x: 0, y: 0, z: 0, sx: 12, sy: 12, sz: 24, rx: 0, ry: 0, rz: 0, material: 'm_air' });

// 2. Ellipsoids (Axis-aligned and Rotated)
S_test.parts.push({
  id: 'p_ellip1',
  name: 'Ellipsoid Aligned',
  shape: 'ellipsoid',
  x: 40, y: 40, z: 40,  // clear of the hex lattice (a lattice box must sit inside one host part)
  a: 10, b: 15, c: 20,
  rx: 0, ry: 0, rz: 0,
  material: 'm_bf3'
});
S_test.parts.push({
  id: 'p_ellip2',
  name: 'Ellipsoid Rotated',
  shape: 'ellipsoid',
  x: -40, y: 0, z: 0,
  a: 8, b: 12, c: 16,
  rx: 30, ry: 45, rz: 0,
  material: 'm_bf3'
});

// 3. Cylindrical Mesh Tally
S_test.tallies.push({
  id: 't_cylmesh',
  name: 'Cylindrical Mesh Flux',
  kind: 'mesh',
  meshGeom: 'cylindrical',
  scores: ['flux'],
  nr: 10,
  nphi: 8,
  nz: 15,
  rmin: 0,
  rmax: 20,
  phimin: 0,
  phimax: 6.283185307179586,
  zmin: -25,
  zmax: 25,
  ox: 0, oy: 0, oz: 0,
  ebins: '',
  particle: 'neutron'
});

sandbox.normalizeProject(S_test);
vm.runInContext("S = " + JSON.stringify(S_test) + ";", sandbox);

const py3 = sandbox.generate([]);
console.log('Phases 9-11 Python script length:', py3.length);

// Verify HexLattice Python emission
if (!py3.includes('openmc.HexLattice(name="Hex Core")')) {
  console.error('FAILED: Missing openmc.HexLattice in Python export');
  process.exit(1);
}
if (!py3.includes('.pitch = [1.4, 20.0]')) {
  console.error('FAILED: Missing HexLattice pitch in Python export');
  process.exit(1);
}
if (!py3.includes('.orientation = "x"')) {
  console.error('FAILED: Missing HexLattice orientation in Python export');
  process.exit(1);
}
if (!py3.includes('.universes = [')) {
  console.error('FAILED: Missing HexLattice universes array in Python export');
  process.exit(1);
}

// Verify Ellipsoid Quadric Python emission
const quadricLines = py3.split('\n').filter(l => l.includes('openmc.Quadric('));
console.log('Quadric declarations:', quadricLines);
if (quadricLines.length < 2) {
  console.error('FAILED: Expected at least 2 openmc.Quadric declarations for ellipsoids');
  process.exit(1);
}
if (!py3.includes('shape_ellipsoid_aligned = -')) {
  console.error('FAILED: Missing shape_ellipsoid_aligned definition in Python export');
  process.exit(1);
}
if (!py3.includes('shape_ellipsoid_rotated = -')) {
  console.error('FAILED: Missing shape_ellipsoid_rotated definition in Python export');
  process.exit(1);
}

// Verify CylindricalMesh Python emission
if (!py3.includes('openmc.CylindricalMesh(')) {
  console.error('FAILED: Missing openmc.CylindricalMesh declaration in Python export');
  process.exit(1);
}
if (!py3.includes('r_grid=np.linspace(0.0, 20.0, 11)')) {
  console.error('FAILED: Missing CylindricalMesh r_grid in Python export');
  process.exit(1);
}
if (!py3.includes('z_grid=np.linspace(-25.0, 25.0, 16)')) {
  console.error('FAILED: Missing CylindricalMesh z_grid in Python export');
  process.exit(1);
}

// Verify CylindricalMesh MCNP Tally emission
const mcnpCyl = sandbox.mcnpTally(S_test.tallies[S_test.tallies.length - 1]);
console.log('MCNP Cylindrical Mesh Tally:\n' + mcnpCyl);
// GEOM=CYL: I = radius, J = height from ORIGIN (at the bottom), K = angle in revolutions
if (!mcnpCyl.includes('GEOM=CYL ORIGIN=0 0 -25') || !mcnpCyl.includes('IMESH=20 IINTS=10') || !mcnpCyl.includes('JMESH=50 JINTS=15') || !mcnpCyl.includes('KMESH=1 KINTS=8')) {
  console.error('FAILED: MCNP Cylindrical mesh tally missing expected GEOM=CYL cards');
  process.exit(1);
}

// Verify Thermal Scattering S(alpha, beta) support
console.log('\nTesting Thermal Neutron Scattering S(alpha, beta) integration...');
if (!sandbox.THERMAL_SCATTERING_TABLES || sandbox.THERMAL_SCATTERING_TABLES.length < 30) {
  console.error('FAILED: THERMAL_SCATTERING_TABLES missing or incomplete:', sandbox.THERMAL_SCATTERING_TABLES?.length);
  process.exit(1);
}
const testSabMatches = [
  ['Water, liquid', 'H:2, O:1', 'c_H_in_H2O'],
  ['Heavy Water', 'H2:2, O:1', 'c_D_in_D2O'],
  ['Graphite', 'C:1', 'c_Graphite'],
  ['Polyethylene', 'H:2, C:1', 'c_H_in_CH2'],
  ['Beryllium', 'Be:1', 'c_Be'],
  ['Uranium Dioxide', 'U:1, O:2', 'c_U_in_UO2'],
  ['Silicon Dioxide', 'Si:1, O:2', 'c_SiO2_alpha']
];
testSabMatches.forEach(([name, comps, expected]) => {
  const got = sandbox.sabFor(name, comps);
  if (got !== expected) {
    console.error(`FAILED: sabFor("${name}", "${comps}") expected "${expected}", got "${got}"`);
    process.exit(1);
  }
});

// Test material with thermal scattering in mcnpMaterial
const matGraphite = { id: 'm_grph', name: 'Graphite', comps: 'C: 1.0', density: 1.7, frac: 'ao', sab: 'c_Graphite' };
const mcnpMat = sandbox.mcnpMaterial(matGraphite);
console.log('MCNP Material equivalent:\n' + mcnpMat);
if (!mcnpMat.includes('MT') || !mcnpMat.includes('grph.40t')) {
  console.error('FAILED: mcnpMaterial missing MT card with grph.40t');
  process.exit(1);
}

// model.mcnp tally numbers come from the deck's FC cards, not from the tally order: a surface-current tally takes
// one number per (surface, part) bin, so the cell tally after it isn't F14
vm.runInContext("S.tallies = " + JSON.stringify([
  {id: 't_cur', name: 'current out', kind: 'surface', scores: ['current']},
  {id: 't_cell', name: 'Cell flux', kind: 'cell', scores: ['flux', 'absorption']},
  {id: 't_mesh', name: 'Flux map', kind: 'mesh', scores: ['flux']},
  {id: 't_long', name: 'a very long tally name that the exporter has to cut short on its FC card', kind: 'surface', scores: ['current']}]) + ";", sandbox);
const deckTallies = ['F1:N 13', 'FC1 current out [S 13 C 2 SEG 12 COS 1 X-1]', 'C1 0 1', 'F11:N 14',
  'FC11 current out [S 14 C 2 SEG 12-17 COS 2 X+1]', 'F24:N 3', 'FC24 Cell flux (flux)', 'SD24 1', 'F34:N 3',
  'FC34 Cell flux (absorption)', 'FMESH44:N GEOM=XYZ ORIGIN=0 0 0', 'F51:N 7', 'FC51 a very long tally name that the [S 7 C 1 SEG 7 COS 2 X+1]'].join('\n');
const byNum = sandbox.mcnpTallyNumbers(deckTallies);
const wantNum = {1: 't_cur', 11: 't_cur', 24: 't_cell', 34: 't_cell', 44: 't_mesh', 51: 't_long'};
for (const [n, id] of Object.entries(wantNum)) {
  if (!byNum[n] || byNum[n].id !== id) {
    console.error(`FAILED: mcnpTallyNumbers: tally ${n} should belong to ${id}, got ${byNum[n] && byNum[n].id}`);
    process.exit(1);
  }
}

// Verify PNNL Materials Compendium Presets Library
console.log('\nTesting PNNL Materials Compendium Preset Library...');

if (!sandbox.PNNL_PRESET_GROUPS || !Array.isArray(sandbox.PNNL_PRESET_GROUPS)) {
  console.error('FAILED: PNNL_PRESET_GROUPS array is missing');
  process.exit(1);
}
const expectedGroups = [
  'All',
  'Shielding Concretes',
  'Borated Polymers',
  'Structural Alloys',
  'Control Absorbers',
  'Moderators & Coolants',
  'Nuclear Fuels',
  'Gases & Detectors'
];
expectedGroups.forEach(g => {
  if (!sandbox.PNNL_PRESET_GROUPS.includes(g)) {
    console.error(`FAILED: Missing PNNL preset group "${g}"`);
    process.exit(1);
  }
});

if (!sandbox.PRESETS || sandbox.PRESETS.length < 35) {
  console.error('FAILED: PRESETS array missing or contains too few entries:', sandbox.PRESETS?.length);
  process.exit(1);
}
console.log(`Found ${sandbox.PRESETS.length} presets in catalog.`);

// Verify every preset has valid properties, valid density, and clean composition parsing
const requiredKeys = [
  'concrete', 'barytes_concrete', 'magnetite_concrete', 'magnetite_steel_concrete', 'boron_baryte_concrete', 'colemanite_baryte_concrete',
  'poly', 'bpoly5', 'bpoly', 'bpoly30', 'lith_poly', 'paraffin',
  'zircaloy2', 'zircaloy4', 'ss304', 'ss316', 'ss316l', 'inconel600', 'inconel718', 'aluminum', 'al6061', 'lead', 'iron', 'tungsten',
  'b4c', 'cadmium', 'hafnium', 'aic', 'gadolinia', 'pyrex', 'bss1',
  'water', 'heavywater', 'graphite', 'beryllium', 'beo',
  'uo2', 'uo2_4p5', 'uo2_haleu', 'mox',
  'air', 'helium', 'he3', 'bf3'
];
const presentKeys = new Set(sandbox.PRESETS.map(p => p.key));
requiredKeys.forEach(k => {
  if (!presentKeys.has(k)) {
    console.error(`FAILED: Preset key "${k}" is missing from PRESETS`);
    process.exit(1);
  }
});

sandbox.PRESETS.forEach(p => {
  if (!p.key || !p.name || !p.comps || !p.color || !p.group) {
    console.error(`FAILED: Preset "${p.name || p.key}" is missing required metadata`);
    process.exit(1);
  }
  if (!Number.isFinite(p.density) || p.density <= 0) {
    console.error(`FAILED: Preset "${p.key}" has non-positive or invalid density: ${p.density}`);
    process.exit(1);
  }
  if (p.frac !== 'ao' && p.frac !== 'wo') {
    console.error(`FAILED: Preset "${p.key}" has invalid fraction type: ${p.frac}`);
    process.exit(1);
  }
  const parsed = sandbox.parseComps(p.comps);
  if (parsed.errs && parsed.errs.length > 0) {
    console.error(`FAILED: Preset "${p.key}" composition parsing error: ${parsed.errs.join(', ')}`);
    process.exit(1);
  }
  if (!parsed.out || parsed.out.length === 0) {
    console.error(`FAILED: Preset "${p.key}" has empty parsed composition`);
    process.exit(1);
  }
  parsed.out.forEach(c => {
    if (!c.sym || typeof c.amt !== 'number' || c.amt <= 0) {
      console.error(`FAILED: Preset "${p.key}" invalid component: ${JSON.stringify(c)}`);
      process.exit(1);
    }
  });
  if (p.sab) {
    const validSab = sandbox.THERMAL_SCATTERING_TABLES.some(t => t.id === p.sab);
    if (!validSab) {
      console.error(`FAILED: Preset "${p.key}" specifies unknown S(a,b) table: "${p.sab}"`);
      process.exit(1);
    }
  }
});

// Test in-place applyPresetToMat
console.log('Testing in-place applyPresetToMat...');
const mockMat = { id: 'm_test', name: 'Custom 1', density: 1.0, frac: 'ao', comps: 'H: 1', color: '#ff0000', pristine: 'old' };
const testProj = {
  settings: { ...sandbox.DEFAULT_SETTINGS, runMode: 'fixed source', seed: 42, worldR: 50, worldShape: 'box', worldFill: mockMat.id, maxTracks: 0, track: '' },
  parts: [],
  groups: [],
  sources: [{ id: 's1', name: 'Point', shape: 'point', ptype: 'neutron', strength: 1.0, eType: 'watt', x: 0, y: 0, z: 0 }],
  materials: [mockMat],
  tallies: []
};
sandbox.normalizeProject(testProj);
vm.runInContext("S = " + JSON.stringify(testProj) + ";", sandbox);
const liveMat = vm.runInContext("S.materials[0]", sandbox);
sandbox.HISTORY = { boundary: false };
sandbox.sel = { kind: 'material', id: 'm_test' };
sandbox.renderProps = () => {};
sandbox.renderTree = () => {};
sandbox.schedule = () => {};
sandbox.log = () => {};

// 1. Apply Barytes Concrete
sandbox.applyPresetToMat(liveMat, 'barytes_concrete');
if (liveMat.name !== 'Concrete, barytes-limonite (high-density)' || liveMat.density !== 3.36 || liveMat.frac !== 'wo' || liveMat.ref !== 'PNNL #77' || !liveMat.comps.includes('Ba:')) {
  console.error('FAILED: applyPresetToMat failed for barytes_concrete:', liveMat);
  process.exit(1);
}

// 2. Apply Borated Polyethylene 5%
sandbox.applyPresetToMat(liveMat, 'bpoly5');
if (liveMat.name !== 'Polyethylene, borated (5% B)' || liveMat.density !== 0.95 || liveMat.sab !== 'c_H_in_CH2' || liveMat.ref !== 'Derived (5 wt% B in PE; cf. PNNL #247)') {
  console.error('FAILED: applyPresetToMat failed for bpoly5:', liveMat);
  process.exit(1);
}

// 3. Apply Inconel 718
sandbox.applyPresetToMat(liveMat, 'inconel718');
if (liveMat.name !== 'Inconel-718' || liveMat.density !== 8.19 || liveMat.ref !== 'PNNL #156' || !liveMat.comps.includes('Ni:') || !liveMat.comps.includes('Nb:')) {
  console.error('FAILED: applyPresetToMat failed for inconel718:', liveMat);
  process.exit(1);
}

// 4. Verify OpenMC Python script generation with applied PNNL material
const pyOutput = sandbox.generate([]);
if (!pyOutput.includes('openmc.Material(name="Inconel-718")') || !pyOutput.includes('.set_density("g/cm3", 8.19)')) {
  console.error('FAILED: Python export missing Inconel-718 definitions:\n', pyOutput);
  process.exit(1);
}

console.log('PNNL Materials Compendium Preset Library tests PASSED!');

// ── Physics tab: surface tally button, the fission-neutron switch and the two Problems checks ──
const physics = vm.runInContext("RIBBON.Physics.flatMap(g => (g.btns || []).map(b => typeof b[1] === 'function' ? b[1]() : b[1]))", sandbox);
['Surface', 'Eigenvalue', 'Photons', 'Fission neutrons', 'Delete', 'Clear tallies', 'Clear sources'].forEach(label => {
  if (!physics.includes(label)) {
    console.error(`FAILED: the Physics ribbon has no "${label}" button (found ${physics.join(', ')})`);
    process.exit(1);
  }
});

const S_phys = {
  settings: {...vm.runInContext('DEFAULT_SETTINGS', sandbox), runMode: 'fixed source', worldR: 50, worldShape: 'box', worldFill: 'void'},
  parts: [{id:'p1', name:'Fuel', shape:'sphere', x:0, y:0, z:0, r:5, material:'m_heu'},
          {id:'p2', name:'Block', shape:'box', x:20, y:0, z:0, sx:10, sy:10, sz:10, material:'m_gr'}],
  groups: [], sources: [{id:'s1', name:'Source', particle:'neutron', strength:1, space:'point', x:0, y:0, z:0,
    angle:'isotropic', energy:'lines', lines:'2:1'}],
  materials: [{id:'m_heu', name:'HEU', comps:'U235: 0.9, U238: 0.1', density:18.7},
              {id:'m_gr', name:'Graphite', comps:'C: 1.0', density:1.7}],
  tallies: [{id:'t1', name:'Flux', kind:'cell', cells:['p2'], scores:['flux'], ebins:''}]
};
sandbox.normalizeProject(S_phys);
vm.runInContext("S = " + JSON.stringify(S_phys) + ";", sandbox);

const warnText = () => sandbox.problems().map(p => p.text).join(' | ');
if (!/chains multiply/.test(warnText())) {
  console.error('FAILED: a fixed-source model with fuel should warn about multiplying chains');
  process.exit(1);
}
if (/create_fission_neutrons/.test(sandbox.generate([]))) {
  console.error('FAILED: create_fission_neutrons should not be written while fission neutrons are on');
  process.exit(1);
}

vm.runInContext("S.settings.fissionNeutrons = false;", sandbox);
if (/chains multiply/.test(warnText())) {
  console.error('FAILED: the multiplying warning should go away once fission neutrons are off');
  process.exit(1);
}
if (!sandbox.generate([]).includes('settings.create_fission_neutrons = False')) {
  console.error('FAILED: model.py should set create_fission_neutrons = False when the switch is off');
  process.exit(1);
}

vm.runInContext("S.settings.runMode = 'eigenvalue'; S.settings.inactive = 2;", sandbox);
if (!/need fission neutrons/.test(warnText())) {
  console.error('FAILED: an eigenvalue run with fission neutrons off should be an error');
  process.exit(1);
}
if (sandbox.generate([]).includes('create_fission_neutrons')) {
  console.error('FAILED: eigenvalue runs must never write create_fission_neutrons');
  process.exit(1);
}

vm.runInContext("S.settings.runMode = 'fixed source'; S.settings.fissionNeutrons = true; sel = {kind:'part', id:'p2'}; addTally('surface');", sandbox);
const surfT = JSON.parse(vm.runInContext('JSON.stringify(S.tallies[S.tallies.length - 1])', sandbox));
if (surfT.kind !== 'surface' || surfT.name !== 'Surface tally' || surfT.scores[0] !== 'current' || surfT.surfaces[0] !== 'p2') {
  console.error('FAILED: addTally("surface") should make a current tally on the selected part, got ' + JSON.stringify(surfT));
  process.exit(1);
}
vm.runInContext("clearPhysics('tallies');", sandbox);
if (vm.runInContext('S.tallies.length', sandbox) !== 0) {
  console.error('FAILED: clearPhysics("tallies") should empty the tally list');
  process.exit(1);
}

console.log('\nAll frontend model generation & MCNP translation tests PASSED!');



