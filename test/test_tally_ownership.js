// Regression: ambiguous FC names must never expose edits for a different tally.
const fs = require('fs'), vm = require('vm'), path = require('path'), assert = require('assert');
const harness = fs.readFileSync(path.join(__dirname, 'test_frontend_model.js'), 'utf8').split('// Set up mock test state')[0];
const checks = `
const tally = (id,name) => ({id,name,kind:'cell',scores:['flux'],ebins:'0, 1, 2'});
const deck = (a,b) => ['title','1 0 -1','','1 SO 10','','F4:N 1','FC4 '+a+' (flux)','E4 1 2','F14:N 1','FC14 '+b+' (flux)','E14 1 2'].join('\\n');
function checkAmbiguous(names,labels) {
  const tallies=names.map((name,i)=>tally(String(i),name));
  const ctx={cells:[],surfaces:[],materials:[],tallyScores:tallies,groups:[]};
  const view=sandbox.annotateMcnp(deck(...labels),ctx,true);
  assert.equal(view.refs.length,0,'ambiguous cards must have no editable refs');
  assert.equal(Object.keys(ctx.tallyByNum).length,0);
  assert.equal(view.owners.filter(x=>x && x.kind==='tally').length,0);
  assert.deepEqual(tallies.map(t=>t.ebins),['0, 1, 2','0, 1, 2']);
}
checkAmbiguous(['Flux','Flux'],['Flux','Flux']);
checkAmbiguous(['Long shared prefix A','Long shared prefix B'],['Long shared prefix','Long shared prefix']);
checkAmbiguous(['Flux','Flux extended'],['Flux','Flux']);
checkAmbiguous(['Flux','Flux μ'],['Flux','Flux']);
checkAmbiguous(['Flux?','Flux μ'],['Flux?','Flux?']);
const a=tally('a','Left'),b=tally('b','Right');
const ctx={cells:[],surfaces:[],materials:[],tallyScores:[a,b],groups:[]};
const view=sandbox.annotateMcnp(deck('Left','Right'),ctx,true);
assert.equal(ctx.tallyByNum[4],a); assert.equal(ctx.tallyByNum[14],b);
const ref=view.refs.find(r=>r.obj===b && r.index===1);
assert.ok(ref); assert.equal(sandbox.applyEdit(ref,1.5),null);
assert.equal(b.ebins,'0, 1.5, 2'); assert.equal(a.ebins,'0, 1, 2');
// Multiple scores of one tally are not an ownership ambiguity.
assert.equal(sandbox.mcnpTallyNumbers('FC4 Left (flux)',[a,a])[4],a);
console.log('Tally ownership and edit-target round trips PASSED');
`;
vm.runInNewContext(harness+checks,{require,console,URLSearchParams,__dirname,process,assert});
