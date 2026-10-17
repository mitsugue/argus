import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
const read = p => fs.readFileSync(new URL(`../../${p}`,import.meta.url),'utf8');
function step(text,name){const block=text.split(/\n\s+- (?=(?:name|id):)/).find(b=>b.includes(`name: ${name}\n`));assert.ok(block,name);return block;}
function evaluate(expression,mode,sealed,success=true){
 let s=expression.replaceAll('inputs.owner-auth',JSON.stringify(mode)).replaceAll('vars.ARGUS_ACCEPTANCE_OWNER_AUTH',JSON.stringify(mode))
  .replace(/steps\.protect_(?:profile|evidence|mobile)\.outcome/g,JSON.stringify(sealed?'success':'failure'))
  .replaceAll('always()','true').replaceAll('success()',String(success)).replace(/\$\{\{|\}\}/g,'');
 // Evaluate only the checked-in closed Boolean/string publication expression.
 assert.doesNotMatch(s,/inputs\.|vars\.|steps\.|hashFiles/);
 return Function(`"use strict"; return (${s});`)();
}
for(const [file,label,outcomeKind] of [
 ['.github/actions/warm-profile-seed/action.yml','Publish bounded seed evidence','seed'],
 ['.github/actions/warm-profile-consumer/action.yml','Publish bounded consumer evidence','consumer'],
 ['.github/actions/warm-profile-seed/action.yml','Publish canonical warm profile','profile'],
 ['.github/workflows/deploy-pages.yml','Publish reproducible public acceptance evidence','mobile'],
])test(`${outcomeKind} actual publication conditions have no ON plaintext fallback`,()=>{
 const b=step(read(file),label),condition=b.match(/^\s+if: (.*)$/m)[1],p=b.match(/^\s+path: (.*)$/m)[1];
 assert.equal(evaluate(condition,'1',false),false);
 assert.equal(evaluate(condition,'invalid',false),false);
 assert.equal(evaluate(condition,'1',true),true);
 assert.match(evaluate(p,'1',true),/^artifacts\/protected-/);
 assert.equal(evaluate(condition,'0',false),true);
 assert.doesNotMatch(evaluate(p,'0',false),/protected-/);
});
test('every shared action caller supplies a dedicated key and explicit-run binding is retained',()=>{
 for(const file of ['.github/workflows/deploy-pages.yml','.github/workflows/market-public-acceptance.yml']){
  const chunks=read(file).split(/\n      - /).filter(b=>b.includes('uses: ./.github/actions/warm-profile-'));
  assert.ok(chunks.length);
  for(const b of chunks)assert.match(b,/owner-artifact-key: \$\{\{ secrets\.ARGUS_OWNER_ARTIFACT_KEY \}\}/);
 }
 const c=read('.github/actions/warm-profile-consumer/action.yml');
 assert.ok(c.indexOf('owner-artifact-envelope.mjs check')<c.indexOf('actions/download-artifact'));
 assert.ok(c.indexOf('owner-artifact-envelope.mjs unseal')<c.indexOf('node scripts/warm-profile-contract.mjs validate'));
 assert.match(c,/ARTIFACT_SOURCE_RUN: \$\{\{ inputs\.source-run-id \|\| github\.run_id \}\}/);
 assert.match(c,/node scripts\/public-market-acceptance.mjs/);
 const s=read('.github/actions/warm-profile-seed/action.yml');
 assert.ok(s.indexOf('owner-artifact-envelope.mjs check')<s.indexOf('run-warm-profile-seed.sh'));
});
