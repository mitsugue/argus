// Synthetic persistent Chromium profile transfer. No production or user profile.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';
import crypto from 'node:crypto';
import { chromium } from 'playwright';
import { seal, unseal } from './owner-artifact-envelope.mjs';
import { sanitizeWarmProfile, writeWarmProfileManifest, validateWarmProfile } from './warm-profile-contract.mjs';
const root=await fs.mkdtemp(path.join(await fs.realpath(os.tmpdir()),'owner-transport-browser-'));
const profile=path.join(root,'profile'), restored=path.join(root,'restored'), encrypted=path.join(root,'encrypted');
const sha='a'.repeat(40), key=crypto.randomBytes(32).toString('hex');
const binding={repository:'synthetic/fixture',candidate:sha,run:'1',kind:'profile'};
let browser;
const server=http.createServer((req,res)=>{
 if(req.url==='/sw.js') {res.setHeader('Content-Type','application/javascript');res.end("self.addEventListener('install',e=>e.waitUntil(caches.open('synthetic').then(c=>c.add('/')).then(()=>self.skipWaiting())));self.addEventListener('activate',e=>e.waitUntil(self.clients.claim()));self.addEventListener('fetch',e=>e.respondWith(caches.match(e.request).then(r=>r||fetch(e.request))));");}
 else {res.setHeader('Content-Type','text/html');res.end('<!doctype html><title>Synthetic profile transport</title><body>local fixture</body>');}
});
try {
 await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(0,'127.0.0.1',resolve);});
 const url=`http://127.0.0.1:${server.address().port}/`;
 async function launch(dir){const b=await chromium.launchPersistentContext(dir,{headless:true});await b.route('**/*',route=>new URL(route.request().url()).origin===new URL(url).origin?route.continue():route.abort());return b;}
 browser=await launch(profile);let page=browser.pages()[0];await page.goto(url);
 await page.evaluate(async()=>{
  await navigator.serviceWorker.register('/sw.js');await navigator.serviceWorker.ready;
  await new Promise((resolve,reject)=>{const r=indexedDB.open('argus-verified-snapshots',1);r.onupgradeneeded=()=>r.result.createObjectStore('snapshots');r.onerror=()=>reject(r.error);r.onsuccess=()=>{const db=r.result,t=db.transaction('snapshots','readwrite');t.objectStore('snapshots').put({id:'synthetic-unchanged',body:'synthetic-market-body'},'current');t.oncomplete=()=>{db.close();resolve();};t.onerror=()=>reject(t.error);};});
 });
 await page.reload();await page.waitForFunction(()=>!!navigator.serviceWorker.controller);
 await browser.close();browser=null;
 await sanitizeWarmProfile(profile);
 const manifest=await writeWarmProfileManifest({profileDir:profile,candidateSha:sha,runtimeProof:{databaseNames:['argus-verified-snapshots'],serviceWorkerReady:true,verifiedSnapshotRecordCount:1},source:{backendSha:sha,backendVersion:'13.7.51',frontendSha:sha,frontendVersion:'13.7.51',publicUrl:url,seededSnapshotId:'synthetic-unchanged'}});
 await seal(profile,encrypted,key,binding);await unseal(encrypted,restored,key,binding);
 assert.deepEqual(await validateWarmProfile({profileDir:restored,expectedCandidateSha:sha}),manifest);
 async function digests(dir,prefix=''){const result={};for(const item of await fs.readdir(path.join(dir,prefix),{withFileTypes:true})){const rel=prefix?`${prefix}/${item.name}`:item.name;if(item.isDirectory())Object.assign(result,await digests(dir,rel));else result[rel]=crypto.createHash('sha256').update(await fs.readFile(path.join(dir,rel))).digest('hex');}return result;}
 assert.deepEqual(await digests(profile),await digests(restored));
 browser=await launch(restored);await browser.setOffline(true);page=browser.pages()[0];await page.goto(url);
 const record=await page.evaluate(()=>new Promise((resolve,reject)=>{const r=indexedDB.open('argus-verified-snapshots');r.onerror=()=>reject(r.error);r.onsuccess=()=>{const db=r.result,q=db.transaction('snapshots').objectStore('snapshots').get('current');q.onsuccess=()=>{resolve(q.result);db.close();};q.onerror=()=>reject(q.error);};}));
 assert.deepEqual(record,{id:'synthetic-unchanged',body:'synthetic-market-body'});
 assert.equal(await page.title(),'Synthetic profile transport');
 console.log('owner-artifact-browser: PASS; full bytes, manifest, offline SW and IndexedDB restored');
} finally {if(browser)await browser.close();await new Promise(resolve=>server.close(resolve));await fs.rm(root,{recursive:true,force:true});}
