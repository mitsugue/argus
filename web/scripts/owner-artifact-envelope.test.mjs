import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';
import { spawnSync } from 'node:child_process';
import { seal, unseal, LIMITS } from './owner-artifact-envelope.mjs';
const key = '21'.repeat(32);
const context = { repository: 'example/fixture', candidate: 'a'.repeat(40), run: '42', kind: 'profile' };
async function fixture(fn) {
 const root = await fs.mkdtemp(path.join(await fs.realpath(os.tmpdir()), 'owner-artifact-test-'));
 try {
  const source = path.join(root, 'source'), sealed = path.join(root, 'sealed'), output = path.join(root, 'output');
  await fs.mkdir(source); await fs.mkdir(path.join(source, '.hidden')); await fs.mkdir(path.join(source, 'empty'));
  await fs.writeFile(path.join(source, '.hidden', 'fixture'), 'synthetic-market-body\n日本語', {mode:0o600});
  await fs.writeFile(path.join(source, 'zero'), '', {mode:0o600});
  await fn({ root, source, sealed, output });
 } finally { await fs.rm(root, {recursive:true,force:true}); }
}
async function rejected(f, ctx=context, k=key) {
 await assert.rejects(unseal(f.sealed, f.output, k, ctx));
 await assert.rejects(fs.lstat(f.output), {code:'ENOENT'});
 assert.deepEqual((await fs.readdir(f.root)).filter(n=>n.startsWith('.owner-')), []);
}
test('binary/hidden/empty directory/empty file preserve exact bytes and private permissions', () => fixture(async f => {
 await fs.writeFile(path.join(f.source,'binary'), crypto.randomBytes(2*1024*1024));
 await seal(f.source,f.sealed,key,context); await unseal(f.sealed,f.output,key,context);
 for (const name of ['binary','.hidden/fixture','zero']) assert.deepEqual(await fs.readFile(path.join(f.source,name)),await fs.readFile(path.join(f.output,name)));
 assert.equal((await fs.stat(path.join(f.output,'empty'))).isDirectory(),true);
 assert.equal((await fs.stat(path.join(f.output,'.hidden/fixture'))).mode & 0o077,0);
 for(const name of await fs.readdir(f.sealed)) assert.equal((await fs.readFile(path.join(f.sealed,name))).includes(Buffer.from('synthetic-market-body')),false);
}));
for(const field of ['repository','candidate','run','kind']) test(`reject different ${field}`,()=>fixture(async f=>{
 await seal(f.source,f.sealed,key,context);
 const other={...context,[field]:{repository:'another/repo',candidate:'b'.repeat(40),run:'43',kind:'seed-evidence'}[field]};
 await rejected(f,other);
}));
test('wrong/missing key',()=>fixture(async f=>{await seal(f.source,f.sealed,key,context); await rejected(f,context,'22'.repeat(32)); await rejected(f,context,'');}));
for(const mode of ['flip','truncate','remove','extra','swap']) test(`reject ${mode} before exposing any files`,()=>fixture(async f=>{
 await seal(f.source,f.sealed,key,context);
 const names=(await fs.readdir(f.sealed)).filter(n=>n!=='manifest.bin'); const target=path.join(f.sealed,names[0]);
 const b=await fs.readFile(target);
 if(mode==='flip'){b[22]^=1;await fs.writeFile(target,b);}
 if(mode==='truncate')await fs.writeFile(target,b.subarray(0,b.length-1));
 if(mode==='remove')await fs.unlink(target);
 if(mode==='extra')await fs.writeFile(path.join(f.sealed,'extra'),'x');
 if(mode==='swap')await fs.copyFile(path.join(f.sealed,names[1]),target);
 await rejected(f);
}));
test('corrupt manifest and encrypted symlink rejected',()=>fixture(async f=>{
 await seal(f.source,f.sealed,key,context);
 const p=path.join(f.sealed,'manifest.bin'), saved=path.join(f.root,'manifest'); await fs.rename(p,saved); await fs.symlink(saved,p);
 await rejected(f); await fs.unlink(p); const b=await fs.readFile(saved); b[b.length-1]^=1; await fs.writeFile(p,b); await rejected(f);
}));
for(const type of ['symlink','hardlink','oversize'])test(`source ${type} rejected and originals remain`,()=>fixture(async f=>{
 const p=path.join(f.source,'bad');
 if(type==='symlink')await fs.symlink(f.source,p);
 if(type==='hardlink')await fs.link(path.join(f.source,'zero'),p);
 if(type==='oversize'){const h=await fs.open(p,'w');await h.truncate(LIMITS.bytes+1);await h.close();}
 await assert.rejects(seal(f.source,f.sealed,key,context)); await assert.rejects(fs.lstat(f.sealed),{code:'ENOENT'});
 assert.equal((await fs.lstat(p)).isSymbolicLink(),type==='symlink');
}));
test('existing destination is never replaced',()=>fixture(async f=>{
 await fs.mkdir(f.output);await fs.writeFile(path.join(f.output,'retained'),'original');
 await seal(f.source,f.sealed,key,context);await assert.rejects(unseal(f.sealed,f.output,key,context));
 assert.equal(await fs.readFile(path.join(f.output,'retained'),'utf8'),'original');
 await assert.rejects(seal(f.source,f.sealed,key,context));
}));
function forgedManifest(body) {
 const nonce=crypto.randomBytes(12), cipher=crypto.createCipheriv('aes-256-gcm',Buffer.from(key,'hex'),nonce);
 cipher.setAAD(Buffer.from(JSON.stringify(['argus-owner-artifact-v1',context.repository,context.candidate,context.run,context.kind])+'\nmanifest'));
 return Buffer.concat([Buffer.from('ARGUS-AE1'),nonce,cipher.update(JSON.stringify(body)),cipher.final(),cipher.getAuthTag()]);
}
for(const [label,entries] of Object.entries({
 traversal:[{path:'../escape',size:0,mode:384}], absolute:[{path:'/escape',size:0,mode:384}],
 duplicate:[{path:'one',directory:true},{path:'one',directory:true}],
 absentParent:[{path:'absent/file',size:0,mode:384}],
 excessive:[{path:'one',size:LIMITS.bytes+1,mode:384}],
 badMode:[{path:'one',size:0,mode:511}],
 alternateSeparator:[{path:'one\\two',size:0,mode:384}],
}))test(`authenticated but malformed ${label} is rejected`,()=>fixture(async f=>{
 await fs.mkdir(f.sealed);await fs.writeFile(path.join(f.sealed,'manifest.bin'),forgedManifest({schema:'argus-owner-artifact-v1',entries}));await rejected(f);
}));
test('CLI failure emits fixed code, never key/path/body/exception',()=>fixture(async f=>{
 const r=spawnSync(process.execPath,[new URL('./owner-artifact-envelope.mjs',import.meta.url).pathname,'unseal',f.source,f.output,'profile',context.candidate,context.run],
 {env:{...process.env,GITHUB_REPOSITORY:context.repository,ARGUS_OWNER_ARTIFACT_KEY:key},encoding:'utf8'});
 assert.equal(r.status,1);assert.equal(r.stdout,'');assert.equal(r.stderr,'owner_artifact_failed\n');
}));
for(const [mode,k,success] of [['0','',true],['1',key,true],['1','',false],['2',key,false],['',key,false]])
 test(`CLI preflight mode ${JSON.stringify(mode)} key ${!!k}`,()=>{
 const r=spawnSync(process.execPath,[new URL('./owner-artifact-envelope.mjs',import.meta.url).pathname,'check'],
 {env:{...process.env,ARGUS_ACCEPTANCE_OWNER_AUTH:mode,ARGUS_OWNER_ARTIFACT_KEY:k},encoding:'utf8'});
 assert.equal(r.status,success?0:1);assert.equal(r.stderr,success?'':'owner_artifact_failed\n');
 });
test('the existing complete profile contract validates after encrypted transport',()=>fixture(async f=>{
 const {writeWarmProfileManifest,validateWarmProfile}=await import('./warm-profile-contract.mjs');
 for(const directory of ['Default/IndexedDB/https_mitsugue.github.io_0.indexeddb.leveldb','Default/Service Worker/Database']){
  await fs.mkdir(path.join(f.source,directory),{recursive:true});
  await fs.writeFile(path.join(f.source,directory,'CURRENT'),'MANIFEST-000001\n');
  await fs.writeFile(path.join(f.source,directory,'000003.log'),'synthetic-snapshot-record');
 }
 const manifest=await writeWarmProfileManifest({profileDir:f.source,candidateSha:context.candidate,
  runtimeProof:{databaseNames:['argus-verified-snapshots'],serviceWorkerReady:true,verifiedSnapshotRecordCount:1},
  source:{backendSha:'b'.repeat(40),backendVersion:'13.7.51',frontendSha:context.candidate,frontendVersion:'13.7.51',publicUrl:'https://mitsugue.github.io/argus/#today',seededSnapshotId:'synthetic-snapshot'}});
 await seal(f.source,f.sealed,key,context);await unseal(f.sealed,f.output,key,context);
 assert.deepEqual(await validateWarmProfile({profileDir:f.output,expectedCandidateSha:context.candidate}),manifest);
 await fs.appendFile(path.join(f.output,'Default/IndexedDB/https_mitsugue.github.io_0.indexeddb.leveldb/CURRENT'),'bad');
 await assert.rejects(validateWarmProfile({profileDir:f.output,expectedCandidateSha:context.candidate}));
}));
