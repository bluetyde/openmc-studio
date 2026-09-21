const fs=require('fs'), vm=require('vm'), path=require('path'), assert=require('assert');
const harness=fs.readFileSync(path.join(__dirname,'test_frontend_model.js'),'utf8').split('// Set up mock test state')[0];
const checks = `
function marker(type,n,o,inline=false){
 const payload=encodeURIComponent(JSON.stringify(o)), chunks=payload.match(/.{1,64}/g);
 return chunks.map((c,i)=>(inline?'$':'c')+' @studio-v1 '+type+' '+n+' '+(i+1)+'/'+chunks.length+' '+c).join('\\n');
}
const a={id:'a',name:'Same name',ebins:'0, 1, 2'}, b={id:'b',name:'Same name',ebins:'0, 3, 4'};
const ctx={requireIds:true,objects:{tally:[a,b],part:[{id:'p'}],group:[{id:'g'}],material:[{id:'m'}]},tallyScores:[a,b],materials:[{id:'m',density:1}],cells:[],surfaces:[],groups:[]};
const deck='Title\\nc @studio-map-v1\\n'+marker('cell',70,{kind:'part',id:'p'})+'\\n70 0 -9\\n\\n'+marker('surface',9,{kind:'group',id:'g'})+'\\n9 RPP 0 1 0 1 0 1\\n\\n'+marker('tally',4,{kind:'tally',id:'b'})+'\\nF4:N 70\\nFC4 Same name\\nE4 3 $ not a value 999\\n     4\\n';
const view=sandbox.annotateMcnp(deck,ctx,true);
assert.equal(view.refs.length,2); assert.equal(view.refs[0].obj,b); assert.equal(view.refs[1].index,2);
assert.equal(sandbox.applyEdit(view.refs[1],'8'),null); assert.equal(b.ebins,'0, 3, 8'); assert.equal(a.ebins,'0, 1, 2');
assert.ok(view.owners.some(o=>o && o.kind==='group' && o.id==='g'));
const unmarked=deck.split('\\n').filter(l=>!l.startsWith('c @studio')).join('\\n');
assert.equal(sandbox.annotateMcnp(unmarked,ctx,true).refs.length,0);
const duplicate=deck+'\\n'+marker('tally',4,{kind:'tally',id:'a'});
assert.equal(sandbox.annotateMcnp(duplicate,ctx,true).refs.length,0);
assert.equal(sandbox.annotateMcnp(deck+'\\nc @studio-v1 tally 4 broken',ctx,true).refs.length,0);
const inline='Title\\nF4:N 70 '+marker('tally',4,{kind:'tally',id:'b'},true);
assert.equal(sandbox.readMcnpIds(inline).records.get('tally:4').id,'b');
const long={kind:'tally',id:'weird \\n$ λ / '.repeat(30)};
assert.equal(sandbox.readMcnpIds('Title\\n'+marker('tally',14,long)).records.get('tally:14').id,long.id);
const truncated=('Title\\n'+marker('tally',14,long)).split('\\n').slice(0,-1).join('\\n');
assert.equal(sandbox.readMcnpIds(truncated).records.size,0);
const built=vm.runInContext('buildScript([],false)',sandbox);
assert.ok(built.text.includes('studio_ids = {'));
assert.ok(built.text.includes('.id: _studio_json.loads('));
console.log('Stable IDs: duplicate names, shuffled IDs, c/$ comments, continuations, malformed/absent metadata and edit round trip PASSED');
`;
vm.runInNewContext(harness+checks,{require,console,URLSearchParams,__dirname,process,assert});
