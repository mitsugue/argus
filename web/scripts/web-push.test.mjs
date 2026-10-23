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

// 2026-10-23: a registered symbol's move opens that symbol's screen.
const worker = windows => {
  const h = {}; const shown = []; const log = [];
  const sw = {registration:{scope:'https://example.org/argus/',showNotification:async(title,options)=>shown.push({title,options})},
    addEventListener:(name,fn)=>h[name]=fn,
    clients:{matchAll:async()=>windows(log),openWindow:async url=>{log.push(['open',url]);return {};}}};
  vm.runInNewContext(fs.readFileSync('public/push-worker.js','utf8'),{self:sw,URL,Date,Number,Promise,indexedDB:{open(){throw Error('storage full');}}});
  const click = async hash => { let t; h.notificationclick({notification:{data:{deliveryId:id,hash},close(){}},waitUntil:p=>t=p}); await t; };
  const show = async hash => { let t; h.push({data:{json:()=>({...payload,hash})},waitUntil:p=>t=p}); await t; };
  return {click, show, shown, log};
};
{
  const w = worker(() => []);
  for (const hash of ['#asset/SOXL','#asset/7203','#asset/285A','#asset/BRK.B','#asset/BRK-B']) await w.show(hash);
  for (const hash of ['#asset/soxl','#asset/','#asset/SOXL/why-downside','#asset/../settings','#asset/%2E%2E',
    '#asset/SOXL?x=1','#asset/SOXL#x','#asset/ABCDEFGHIJK','#asset/SO XL','#holdings','#asset/SOXL.','#assets/SOXL'])
    await w.show(hash);
  assert.deepEqual(w.shown.map(n => n.options.data.hash),
    ['#asset/SOXL','#asset/7203','#asset/285A','#asset/BRK.B','#asset/BRK-B']);
  await w.click('#asset/SOXL');
  assert.deepEqual(w.log, [['open','https://example.org/argus/#asset/SOXL']]);
  const before = w.log.length; await w.click('#asset/../settings'); assert.equal(w.log.length, before);
}
const appWindow = (log, navigate) => [{url:'https://example.org/argus/#today',
  focus:async function(){log.push(['focus']);return this;}, ...(navigate ? {navigate} : {})}];
{ // navigate works: focus first, then move the open window; no second window.
  const w = worker(log => appWindow(log, async url => { log.push(['navigate',url]); return {}; }));
  await w.click('#asset/SOXL');
  assert.deepEqual(w.log, [['focus'],['navigate','https://example.org/argus/#asset/SOXL']]);
}
{ // navigate throws (iOS home-screen app): open the target instead.
  const w = worker(log => appWindow(log, async () => { log.push(['navigate']); throw new TypeError('not allowed'); }));
  await w.click('#asset/SOXL');
  assert.deepEqual(w.log, [['focus'],['navigate'],['open','https://example.org/argus/#asset/SOXL']]);
}
{ // navigate missing, or resolving to nothing, also opens the target.
  const w = worker(log => appWindow(log, null));
  await w.click('#asset/7203');
  assert.deepEqual(w.log, [['focus'],['open','https://example.org/argus/#asset/7203']]);
  const n = worker(log => appWindow(log, async () => { log.push(['navigate']); return null; }));
  await n.click('#asset/7203');
  assert.deepEqual(n.log, [['focus'],['navigate'],['open','https://example.org/argus/#asset/7203']]);
}
{ // focus throws: navigation is still tried; matchAll throwing still opens.
  const w = worker(log => [{url:'https://example.org/argus/', focus:async()=>{throw Error('no focus');},
    navigate:async url=>{log.push(['navigate',url]);return {};}}]);
  await w.click('#asset/SOXL');
  assert.deepEqual(w.log, [['navigate','https://example.org/argus/#asset/SOXL']]);
  const m = worker(() => { throw Error('clients unavailable'); });
  await m.click('#asset/SOXL');
  assert.deepEqual(m.log, [['open','https://example.org/argus/#asset/SOXL']]);
}
{ // a window outside the app scope is never navigated.
  const w = worker(log => [{url:'https://example.org/other/', focus:async()=>log.push(['focus']),
    navigate:async()=>log.push(['navigate'])}]);
  await w.click('#asset/SOXL');
  assert.deepEqual(w.log, [['open','https://example.org/argus/#asset/SOXL']]);
}
console.log('Web Push: symbol screen links and navigate fallback to openWindow PASS');
