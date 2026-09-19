const fs = require('fs'), vm = require('vm'), path = require('path'), assert = require('assert');
const harness = fs.readFileSync(path.join(__dirname, 'test_frontend_model.js'), 'utf8').split('// Set up mock test state')[0];
const checks = `
const deck = ['Title', '1 1 -1 (-1:2) #2 imp:n=1', '2 0 1 -2', '',
 '1 so 10', '2 so 20', '', 'M1 1001.80c 1', 'F4:N 1', '     2 &', 'c intervening comment', '1',
 'c '+ 'x'.repeat(127)].join('\\n');
const idx = sandbox.indexMcnp(deck);
assert.equal(idx.definitions.get('surface:1'), 4);
assert.equal(idx.definitions.get('material:1'), 7);
assert.equal(idx.byLine[11], idx.byLine[8], 'ampersand across comment');
assert.deepEqual(Array.from(idx.links[1], x => x.kind), ['material','surface','surface','cell']);
assert.equal(idx.links[1][3].target, 2);
assert.equal(idx.links[9][0].target, 2);
assert.equal(sandbox.indexMcnp('Title\\n1 0 -1\\n\\n1 so 10\\n1 so 11').links[1].length, 0, 'duplicate definition is not linked');
const warnings = sandbox.mcnpDiagnostics(idx,{validation:'FAIL: surface 2 mismatch\\nERROR: line 9 incorrect\\nFAIL: line 999 absent',notes:['A general note']});
assert.ok(warnings.some(w => w.line === 12));
assert.ok(warnings.some(w => w.line === 5));
assert.ok(warnings.some(w => w.line === 8));
assert.ok(warnings.some(w => w.line === null && w.text.includes('999')));
assert.equal(sandbox.mcnpFindMatches(idx.lines,'SO').length, 2);
assert.equal(sandbox.mcnpFindMatches(idx.lines,'').length, 0);
const diff = sandbox.mcnpChanges('a\\nb\\nc', 'a\\nx\\nb\\nc');
assert.deepEqual(Array.from(diff.changed), [1]); assert.equal(diff.removed,0);
assert.equal(sandbox.mcnpChanges('a\\nb\\nc', 'a\\nc').removed,1);
assert.equal(sandbox.mcnpChanges(null,deck).baseline,false);
assert.equal(sandbox.mcnpChanges(deck,deck).changed.size,0);
const ctx={cells:[],surfaces:[],materials:[],tallyScores:[],groups:[]};
assert.ok(sandbox.annotateMcnp(deck,ctx,false).html.includes('t-mcom'));
console.log('MCNP navigation, continuations, diagnostics, search and export diffs PASSED');
`;
vm.runInNewContext(harness+checks,{require,console,URLSearchParams,__dirname,process,assert});
