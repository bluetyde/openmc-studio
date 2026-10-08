// Makes the screenshots in docs/images/ from the real app: Studio's page driven by Playwright against a running Studio server, with real OpenMC runs.
// Nothing is faked: each model is loaded into the page as a project, Run is pressed, and the page is photographed when the run has finished.
//
//   1. start a Studio server on a free port with a scratch runs folder (WSL):  OPENMC_STUDIO_PORT=8767 bash studio/start.sh --no-browser --runs ~/shots-runs
//   2. node test/generate_depletion_pin.cjs                                   (the depletion project, written to test/generated/)
//   3. NODE_PATH=<a node_modules with playwright> node test/make_screenshots.cjs "http://127.0.0.1:8767/?token=<token>" [only-this-name]
//
// The depletion run takes about two minutes. Browser: Microsoft Edge through Playwright (BROWSER_CHANNEL to change).
// Public repo: the models are the demo model and generic UO2 pins; the page shows no file paths or user names beyond the runs folder name in the log.
const {chromium} = require('playwright');
const fs = require('fs'), path = require('path'), vm = require('vm');

const url = process.argv[2], only = process.argv[3];
if (!url) { console.error('usage: node test/make_screenshots.cjs <studio url with ?token=…> [name]'); process.exit(2); }
const OUT = path.join(__dirname, '..', 'docs', 'images');
fs.mkdirSync(OUT, {recursive: true});

// The projects are built with the page's own functions, in a sandbox, so they are what the page would save.
const html = fs.readFileSync(path.join(__dirname, '..', 'studio', 'openmc_studio', 'static', 'index.html'), 'utf8');
const el = {addEventListener() {}, insertAdjacentHTML() {}, querySelector: () => el, querySelectorAll: () => [], style: {}, dataset: {},
  classList: {add() {}, remove() {}, toggle() {}}, setAttribute() {}, appendChild() {}, append() {}, add() {}, remove() {}, getContext: () => null, parentElement: {}};
const sb = {console, URLSearchParams, btoa, atob, TextEncoder, escape, unescape, Option: class {}, window: {}, location: {protocol: 'http:', search: ''},
  document: {querySelector: () => el, querySelectorAll: () => [], getElementById: () => el, createElement: () => el, createTextNode: () => el, addEventListener() {}},
  fetch: () => Promise.resolve({ok: false}), ResizeObserver: class { observe() {} disconnect() {} }, requestAnimationFrame() {}, setTimeout() {}, setInterval: () => 1, clearInterval() {}};
vm.createContext(sb);
vm.runInContext(html.match(/<script>([\s\S]*?)<\/script>/)[1], sb);
const build = code => JSON.parse(vm.runInContext(`JSON.stringify((() => { ${code} })())`, sb));

// A 9 x 9 array of UO2 pins in water with vacuum all round, one eigenvalue run: the pins nearest the water are hotter.
const assembly = () => build(`
  const p = sampleModel();
  const mat = (id, name, density, comps, sab) => ({id, name, color:'#999999', density, frac:'ao', comps, sab:sab || ''});
  p.materials = [Object.assign(mat('m1', 'UO2 3.5%', 10.4, 'U235:0.035, U238:0.965, O16:2'), {color:'#d9b44a'}), Object.assign(mat('m2', 'Water', 0.74, 'H:2, O:1', 'c_H_in_H2O'), {color:'#4a90d9'})];
  const N = 9, PITCH = 1.26, parts = [];
  for (let ix = 0; ix < N; ix++) for (let iy = 0; iy < N; iy++)
    parts.push(Object.assign(newPart('pin_' + ix + '_' + iy, 'Pin ' + ix + ',' + iy, 'cylinder'), {x:(ix - (N - 1) / 2) * PITCH, y:(iy - (N - 1) / 2) * PITCH, z:0, r:0.4096, h:40, axis:'z', material:'m1', group:'g1'}));
  p.parts = parts;
  p.groups = [{id:'g1', name:'Assembly', parent:null, x:0, y:0, z:0, lattice:{nx:N, ny:N, nz:1, dx:PITCH, dy:PITCH, dz:40, fill:'m2', asLattice:true}}];
  p.sources = [Object.assign({}, p.sources[0], {id:'s1', name:'Fission source', space:'box', x0:-5, x1:5, y0:-5, y1:5, z0:-10, z1:10, energy:'watt', particle:'neutron', strength:1})];
  const h = N * PITCH / 2;
  p.tallies = [{id:'t1', name:'Pin power', kind:'mesh', cells:[], scores:['kappa-fission'], ebins:'', nx:N, ny:N, nz:1, lx:-h, ly:-h, lz:-1, ux:h, uy:h, uz:1}];
  Object.assign(p.settings, {name:'Fuel assembly 9 x 9', runMode:'eigenvalue', particles:20000, batches:50, inactive:15, seed:12345, maxTracks:0,
    worldShape:'box', worldR:20, worldBC:'vacuum', worldFill:'m2'});
  return p;`);

const SHOTS = [
  {name: 'editor', file: 'editor.png', run: false, project: null, prep: async page => { await page.evaluate(() => { sel = {kind: 'settings'}; renderAll(); }); }},
  {name: 'results-flux', file: 'results-flux.png', run: true, project: null,
   prep: async page => { await page.evaluate(() => { document.querySelector('#showMesh').checked = true; }); }},
  {name: 'depletion', file: 'depletion.png', run: true, center: true, project: () => JSON.parse(fs.readFileSync(path.join(__dirname, 'generated', 'depletion_pin', 'project.json'), 'utf8')), long: true,
   prep: async page => { await page.evaluate(() => { const h = document.querySelector('#results h4:nth-of-type(1)'); const d = [...document.querySelectorAll('#results h4')].find(x => x.textContent === 'Depletion'); if (d) d.scrollIntoView(); }); }},
  {name: 'pin-power', file: 'pin-power.png', run: true, project: assembly, center: true,
   prep: async page => { await page.evaluate(() => { document.querySelector('[data-plane="xy"]').click(); document.querySelector('.pinBtn').click(); }); await page.waitForSelector('#pinPanel svg.pin-map', {timeout: 60000}); await page.evaluate(() => document.querySelector('#pinPanel').scrollIntoView()); }},
  {name: 'material-helper', file: 'material-helper.png', run: false, project: () => JSON.parse(fs.readFileSync(path.join(__dirname, 'generated', 'depletion_pin', 'project.json'), 'utf8')),
   prep: async page => { await page.evaluate(() => { sel = {kind: 'material', id: S.materials[0].id}; renderProps(); });
     const set = (k, v) => page.evaluate(([k, v]) => { const i = document.querySelector(`.eng-in[data-key="${k}"]`); i.value = v; i.dispatchEvent(new Event('input', {bubbles: true})); }, [k, v]);
     await set('enrich', '3.5'); await set('td', '95'); await set('tdDensity', '10.96');
     await page.evaluate(() => { [...document.querySelectorAll('#props button')].find(b => /Set this material/.test(b.textContent)).click(); });
     await page.evaluate(() => document.querySelector('#engKind').closest('.prow').scrollIntoView()); }},
];

(async () => {
  const browser = await chromium.launch({headless: true, channel: process.env.BROWSER_CHANNEL || 'msedge'});
  try {
    for (const shot of SHOTS) {
      if (only && shot.name !== only) continue;
      const page = await browser.newPage({viewport: {width: 1440, height: 900}, deviceScaleFactor: 1});
      const errors = []; page.on('pageerror', e => errors.push(e.message));
      await page.goto(url);
      await page.waitForFunction(() => typeof LOCAL !== "undefined" && LOCAL.on === true, null, {timeout: 30000});
      await page.evaluate(() => { try { localStorage.clear(); } catch (e) {} });
      if (shot.project) {
        const proj = shot.project();
        const colors = [[/UO2/i, '#d9b44a'], [/zirc/i, '#8a8f98'], [/water/i, '#4a90d9']];
        await page.evaluate(([p, colors]) => { normalizeProject(p); p.materials.forEach(m => { const c = colors.find(([re]) => new RegExp(re.slice(1, re.lastIndexOf('/')), 'i').test(m.name)); if (c) m.color = c[1]; }); S = p; sel = {kind: 'settings'}; renderAll(); }, [proj, colors.map(([re, c]) => [re.toString(), c])]);
      }
      if (shot.run) {
        await page.evaluate(() => document.querySelector('#runBtn').click());
        await page.waitForFunction(() => LOCAL.run, null, {timeout: 30000}).catch(() => {});
        await page.waitForFunction(() => !LOCAL.run && LOCAL.results, null, {timeout: shot.long ? 900000 : 300000, polling: 1000});
        await page.evaluate(() => setOutTab('results'));
      }
      if (shot.center) {   // a taller output pane, so the results show whole; the page's own layout is otherwise untouched
        await page.setViewportSize({width: 1440, height: 1300});
        await page.evaluate(() => { document.querySelector('.center').style.gridTemplateRows = 'auto minmax(0,1fr) 700px'; });
      }
      await shot.prep(page);
      await page.waitForTimeout(800);
      const file = path.join(OUT, shot.file);
      if (shot.center) await page.locator('.center').screenshot({path: file}); else await page.screenshot({path: file});
      console.log('wrote', file, errors.length ? 'page errors: ' + errors.join(' | ') : '');
      await page.close();
    }
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exit(1); });
