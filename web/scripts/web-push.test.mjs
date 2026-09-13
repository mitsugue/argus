import fs from 'node:fs';import vm from 'node:vm';import assert from 'node:assert/strict';
const handlers={};const notices=[];const opened=[];
const self={registration:{scope:'https://example.org/argus/',showNotification:async(title,options)=>notices.push({title,options})},
  addEventListener:(name,fn)=>handlers[name]=fn,clients:{matchAll:async()=>[],openWindow:async url=>opened.push(url)}};
vm.runInNewContext(fs.readFileSync('public/push-worker.js','utf8'),{self,URL,Date,Number,Promise,indexedDB:{open(){throw Error('storage full');}}});
const id='12345678-1234-1234-1234-123456789abc';
const payload={schemaVersion:'argus-web-push-v1',deliveryId:id,title:'通知',body:'日程',hash:'#notifications/sq/jp-monthly-sq-2026-10',expiresAt:new Date(Date.now()+60000).toISOString()};
async function push(data){let task;handlers.push({data:{json:()=>data},waitUntil:p=>task=p});await task;}
await push(payload);assert.equal(notices.length,1);assert.equal(notices[0].options.renotify,false);
await push({...payload,hash:'https://evil.test/'});await push({...payload,expiresAt:'2000-01-01'});assert.equal(notices.length,1);
let task;let closed=false;handlers.notificationclick({notification:{data:{deliveryId:id,hash:payload.hash},close:()=>closed=true},waitUntil:p=>task=p});await task;
assert(closed);assert.deepEqual(opened,['https://example.org/argus/#notifications/sq/jp-monthly-sq-2026-10']);
console.log('Web Push: scoped navigation, expiry, browser display and receipt-storage failure PASS');
