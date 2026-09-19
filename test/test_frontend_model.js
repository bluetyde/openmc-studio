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
if (!/FM\d+ \(-1 1 107\)/.test(mcnp1)) {
  console.error('FAILED: MCNP Tally 1 missing FM (-1 1 107)');
  process.exit(1);
}

const mcnp2 = sandbox.mcnpTally(S_test.tallies[1]);
console.log('MCNP Tally 2:\n' + mcnp2);
if (!/FM\d+ \(-1 2 103\)/.test(mcnp2)) {
  console.error('FAILED: MCNP Tally 2 missing FM (-1 2 103)');
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
if (!mcnpMuir.includes('Muir fusion spectrum')) {
  console.error('FAILED: MCNP Muir source missing diagnostic card');
  process.exit(1);
}

console.log('\nAll frontend model generation & MCNP translation tests PASSED!');

