import fs from 'node:fs';import vm from 'node:vm';import assert from 'node:assert/strict';import ts from 'typescript';
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

// 2026-11-13: each delivery record in Settings says which notice it was and when it was sent.
{
  const label={exports:{}};
  vm.runInNewContext(ts.transpileModule(fs.readFileSync('src/lib/pushRecordLabel.ts','utf8'),
    {compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText,{exports:label.exports,Date,Number});
  const kind=label.exports.pushRecordKindJa;
  assert.equal(kind('jp-monthly-sq-2026-11:DAY'),'11月のSQ・当日');
  assert.equal(kind('jp-monthly-sq-2026-11:PREVIOUS_SESSION'),'11月のSQ・最終取引日');
  assert.equal(kind('jp-monthly-sq-2026-12:WEEK'),'12月のSQ・週の案内');
  assert.equal(kind('news:fiscal:abc'),'財政・金利の警戒変化');
  assert.equal(kind('news:nie-1:HIGH'),'重大ニュース');
  assert.equal(kind('owner-change:pair:NIKKEI_2X:up:2026-11-13:4'),'監視銘柄の急騰・急落');
  assert.equal(kind('test:1234'),'確認通知');
  for (const unknown of [undefined,null,'',{},'jp-monthly-sq-2026-11:LATER']) assert.equal(kind(unknown),'通知');
  assert.equal(label.exports.pushRecordSentJa(null),'未送信');
  assert.match(label.exports.pushRecordSentJa(Date.parse('2026-11-12T23:00:30Z')/1000),/2026\/11\/13 8:00:30/);
  // The server keys these exact shapes (argus_web_push / jp_market_events / argus_jp_fiscal_runtime).
  const py=['../argus_web_push.py','../jp_market_events.py','../argus_jp_fiscal_runtime.py'].map(f=>fs.readFileSync(f,'utf8')).join('\n');
  for (const shape of ['"jp-monthly-sq-" + contract.strftime("%Y-%m")','"DAY" if today == sq_day else "PREVIOUS_SESSION"',"'news:'+event_id","'owner-change:'+event_id","'test:'+str(uuid.uuid4())","'news:fiscal:'+packet['id']"])
    assert.ok(py.includes(shape),shape);
  const panel=fs.readFileSync('src/components/settings/WebPushPanel.tsx','utf8');
  assert.ok(panel.includes('pushRecordKindJa(d.event_key)')&&panel.includes('pushRecordSentJa(d.attempted)'));
  console.log('通知の送った記録: 知らせの種類と送信の時刻 PASS');
}
