// Real browser identity/edit test; no exporter API or shared gateway needed.
const {chromium}=require('playwright'), fs=require('fs'),path=require('path'),assert=require('assert');
(async()=>{
 const browser=await chromium.launch({headless:true,channel:process.env.BROWSER_CHANNEL || 'msedge'});
 try {
  const page=await browser.newPage(); const errors=[]; page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/*',r=>r.fulfill({status:404,body:''}));
  await page.setContent(fs.readFileSync(path.join(__dirname,'../studio/openmc_studio/static/index.html'),'utf8'));
  await page.evaluate(()=>{
   clearTimeout(LIVE.timer); liveMcnpTick=()=>{}; LOCAL.on=true;
   S.tallies[0].name=S.tallies[1].name='Duplicate name';
   S.tallies[0].ebins='0, 1, 2'; S.tallies[1].ebins='0, 3, 4';
   const record=encodeURIComponent(JSON.stringify({kind:'tally',id:S.tallies[1].id}));
   const pieces=record.match(/.{1,64}/g);
   window.idDeck=['Title','c @studio-map-v1','1 0 -1','','1 so 10','',
    ...pieces.map((s,i)=>`c @studio-v1 tally 4 ${i+1}/${pieces.length} ${s}`),
    'F4:N 1','FC4 Duplicate name','E4 3 $ keep comment 999','     4'].join('\n');
   LIVE.ctx=mcnpContext(problems(),buildScript(problems(),false));
   LIVE.sentScript=mcnpScript(problems()); LIVE.report={deck:idDeck,ok:true,seconds:1};
   setDocTab('mcnp'); renderMcnp(problems());
  });
  assert.equal(await page.locator('#mcnpCode .ed').count(),2);
  await page.locator('#mcnpCode .ed').last().click();
  assert.equal(await page.evaluate(()=>sel.id),await page.evaluate(()=>S.tallies[1].id));
  await page.locator('#mcnpCode .edin').fill('8'); await page.keyboard.press('Enter');
  assert.deepEqual(await page.evaluate(()=>S.tallies.map(t=>t.ebins)),['0, 1, 2','0, 3, 8']);
  assert.ok((await page.locator('#mcnpCode').textContent()).includes('$ keep comment 999'));
  await page.evaluate(()=>{
   LIVE.report.deck=idDeck.split('\n').filter(s=>!s.startsWith('c @studio')).join('\n');
   LIVE.sentScript=mcnpScript(problems()); renderMcnp(problems());
  });
  assert.equal(await page.locator('#mcnpCode .ed').count(),0);
  assert.deepEqual(errors,[]); console.log('Browser duplicate-name stable selection/edit and missing-ID read-only PASSED');
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
