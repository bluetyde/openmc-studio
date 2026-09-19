const fs = require('fs'), vm = require('vm'), path = require('path'), assert = require('assert');
const harness = fs.readFileSync(path.join(__dirname, 'test_frontend_model.js'), 'utf8').split('// Set up mock test state')[0];
const checks = `
const ctx={cells:[],surfaces:[],materials:[],tallyScores:[],groups:[]};
const deck=['MCNP column guide test','c '+'.'.repeat(126),'c '+'.'.repeat(127),'c\\t'+'.'.repeat(121)].join('\\n');
const view=sandbox.annotateMcnp(deck,ctx,false);
assert.equal((view.html.match(/data-overlong/g)||[]).length,2);
assert.ok(!view.html.includes('\\t'));
assert.equal(sandbox.mcnpDisplayLine('12345678\\tX'),'12345678        X');
assert.equal(sandbox.mcnpDisplayLine('c\\tX'),'c       X');
assert.equal((sandbox.annotateMcnp(deck.replaceAll('\\n','\\r\\n'),ctx,false).html.match(/data-overlong/g)||[]).length,2);
assert.ok(deck.includes('\\t'),'source deck stays unchanged');
const data=sandbox.annotateMcnp('title\\n1 0 -1 '+' '.repeat(121)+'1',ctx,false);
assert.ok(data.html.includes('data-overlong'));
if(process.env.MCNP_GUIDE_PREVIEW){
 const css=content.match(/<style>([\\s\\S]*?)<\\/style>/)[1];
 fs.writeFileSync(process.env.MCNP_GUIDE_PREVIEW,'<meta charset="utf-8"><style>'+css+'</style><p>MCNP: dashed guide after column 128. Row 2 is valid; rows 3 and 4 exceed it.</p><div class="codewrap" style="height:300px"><pre class="code" id="mcnpCode">'+view.html+'</pre></div>');
}
console.log('MCNP 128/129-column boundaries, tabs, CRLF and source preservation PASSED');
`;
vm.runInNewContext(harness+checks,{require,console,URLSearchParams,__dirname,process,assert});
