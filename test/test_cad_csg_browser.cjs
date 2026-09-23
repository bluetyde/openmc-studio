// Stage-4 browser gate: real converted fixtures, analytical slices, mesh pixels,
// cut-cap picking, materials/tallies, persistence and visible preview failures.
const {chromium} = require('playwright');
const fs = require('fs'), path = require('path'), assert = require('assert');
const root = path.resolve(__dirname, '..');
const report = n => JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures/cad/expected/csg_report_' + n + '.json')));
(async () => {
  const browser = await chromium.launch({headless:true, channel:process.env.BROWSER_CHANNEL || 'msedge'});
  try {
    const page = await browser.newPage({viewport:{width:1440,height:1000}});
    const errors = []; page.on('pageerror', e => errors.push(e.message));
    await page.route('**/*', r => r.fulfill({status:404, body:''}));
    await page.setContent(fs.readFileSync(path.join(root, 'studio/openmc_studio/static/index.html'),'utf8'));
    await page.evaluate(() => { clearTimeout(LIVE.timer); stopMcnpProgress(); liveMcnpTick=()=>{}; window.BLANK=JSON.stringify(S); });
    const layers=report('triso_layers');
    const result=await page.evaluate(rep => {
      commitCsgImport(rep,'triso_layers.step',{});
      const ks=csgComponents();
      const positions=[0,.03,.037,.041,.044,.06];
      const names=positions.map(x => {const n=csgCellAt(x,0,0);return n<0?null:csgCellList()[n].c.name;});
      const pending=problems().filter(p=>p.sev==='error' && /needs a material/.test(p.text)).length;
      ks.forEach((k,i)=> k.cells.forEach(c=>{c.material=S.materials[i%S.materials.length].id;delete c.materialPending;}));
      select('component',ks[3].id); addTally('cell');
      const tally=S.tallies.at(-1), built=buildScript(problems(),false);
      const saved=JSON.parse(JSON.stringify(S)); S=normalizeProject(saved);
      return {names,pending,cells:ks.map(k=>k.cells[0].id), tally:tally.cells,
        tallyErrors:problems().filter(p=>p.sev==='error' && /deleted/.test(p.text)),
        script:built.text, valid:validProject(S), plan:csgPreviewPlan().problems};
    },layers);
    assert.equal(result.pending,5); assert.equal(result.names[5],null);
    assert.match(result.names[0],/kernel/); assert.match(result.names[1],/buffer/);
    assert.match(result.names[2],/IPyC/); assert.match(result.names[3],/SiC/); assert.match(result.names[4],/OPyC/);
    assert.deepEqual(result.tally,[result.cells[3]]); assert.deepEqual(result.tallyErrors,[]);
    assert.ok(result.valid); assert.deepEqual(result.plan,[]);
    await page.evaluate(() => {
      view.mode='3d'; view.plane='xy'; view.slice=0;
      CAM.target=[0,0,0]; CAM.dist=.18; CAM.yaw=-.9; CAM.pitch=.7;
      document.querySelector('#cutaway').checked=true; select('settings'); renderAll(); drawViewport();
    });
    const pixels=await page.evaluate(() => {
      draw3D(); const gl=V3.gl, p=new Uint8Array(gl.drawingBufferWidth*gl.drawingBufferHeight*4);
      gl.readPixels(0,0,gl.drawingBufferWidth,gl.drawingBufferHeight,gl.RGBA,gl.UNSIGNED_BYTE,p);
      const colors=new Set(); for(let i=0;i<p.length;i+=4) if(p[i]>40 || p[i+1]>40 || p[i+2]>40) colors.add(`${p[i]},${p[i+1]},${p[i+2]}`);
      const point=project3(V3.geom.B,[.041,0,0]); const pick=pickComponent3(point[0],point[1]);
      return {ok:V3.ok,error:V3.err,glError:gl.getError(),colors:colors.size,pick:pick&&pick.id,want:csgComponents()[3].id};
    });
    assert.ok(pixels.ok,pixels.error); assert.equal(pixels.glError,0); assert.ok(pixels.colors>=4,JSON.stringify(pixels));
    assert.equal(pixels.pick,pixels.want,'cut cap picks the SiC layer');
    if(process.env.CAD_SCREENSHOT) await page.screenshot({path:process.env.CAD_SCREENSHOT});
    const malformed=await page.evaluate(() => {
      const d=csgComponents()[0].display, original=d.triangles[0]; d.triangles[0]=999999999;
      const invalid=csgPreviewPlan().problems; d.triangles[0]=original;
      const conversion=d.conversion; d.conversion='stale'; const stale=csgPreviewPlan().problems; d.conversion=conversion;
      const limit=CSG_LIMITS.triangles; CSG_LIMITS.triangles=1; draw3D();
      const budget={plan:csgPreviewPlan(),notice:V3.previewNotice}; CSG_LIMITS.triangles=limit;
      return {invalid,stale,budget};
    });
    assert.match(malformed.invalid.join(' '),/invalid preview mesh/);
    assert.match(malformed.stale.join(' '),/another conversion/);
    assert.equal(malformed.budget.plan.draw.length,0); assert.ok(malformed.budget.notice.length);
    const guards=await page.evaluate(()=>{
      const saved=JSON.parse(JSON.stringify(S)); const bad=JSON.parse(JSON.stringify(S));
      bad.csg.components[0].cells[0].region={half:'-',s:999999};
      exportSTL();return {valid:validProject(saved),bad:validProject(bad),log:document.querySelector('#log').innerText};
    });
    assert.ok(guards.valid);assert.equal(guards.bad,false);assert.match(guards.log,/Nothing was exported/);
    assert.deepEqual(errors,[]);
    console.log('test_cad_csg_browser: PASS (slices, materials, tally, reload, WebGL, cut-cap pick, preview failures)');
  } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
