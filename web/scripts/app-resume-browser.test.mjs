import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {chromium,webkit} from 'playwright';
import https from 'node:https';
import fs from 'node:fs';
import os from 'node:os';
import {execFileSync} from 'node:child_process';
const require=createRequire(import.meta.url);
const {build}=createRequire(require.resolve('vite/package.json'))('esbuild');
const web=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
// Exercise Set-Cookie in a real HTTPS response. CDP Fetch.fulfillRequest can
// retain the cookie while dropping its partition identity; a routed response
// is therefore insufficient to certify the browser's storage policy.
const tlsDirectory=fs.mkdtempSync(path.join(os.tmpdir(),'argus-resume-test-tls-'));
execFileSync('openssl',['req','-x509','-newkey','rsa:2048','-nodes','-days','1',
 '-subj','/CN=127.0.0.1','-addext','subjectAltName=IP:127.0.0.1',
 '-keyout',path.join(tlsDirectory,'key.pem'),'-out',path.join(tlsDirectory,'cert.pem')],{stdio:'ignore'});
fs.chmodSync(path.join(tlsDirectory,'key.pem'),0o600);
let handleApi;
const server=https.createServer({key:fs.readFileSync(path.join(tlsDirectory,'key.pem')),
 cert:fs.readFileSync(path.join(tlsDirectory,'cert.pem'))},(req,res)=>{
 void handleApi({request:()=>({url:()=>backendOrigin+req.url,method:()=>req.method,headers:()=>req.headers}),
  fulfill:({status=200,headers={},body='',contentType})=>{if(contentType)headers['Content-Type']=contentType;
   res.writeHead(status,headers);res.end(body);}});
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
const backendOrigin='https://127.0.0.1:'+server.address().port;
const fixture=await build({stdin:{contents:`
 import React, {useState,useEffect} from 'react';
 import App from './src/App';
 import {AssetsProvider} from './src/hooks/useAssets';
 import {WatchlistSyncLifecycle} from './src/hooks/useWatchlistSync';
 import {createRoot} from 'react-dom/client';
 import {OwnerAccess} from './src/components/OwnerAccess';
 import {installOwnerTransport} from './src/lib/ownerSession';
 import {sessionViewCheckpoint} from './src/lib/sessionViewCheckpoint';
 window.flushViewCheckpoint=()=>sessionViewCheckpoint.flush();
 window.fixtureCheckpointPresence=()=>['polling:useMarketRegime','polling:useVisibilityGuard','macro-event-analysis','sector-heatmap','market-news','news-intelligence','nikkei-live'].map(key=>({key,present:sessionViewCheckpoint.hasRestored(key)}));
 import {useEventsActive} from './src/hooks/useEventsActive';
 import {useMarketBrief} from './src/hooks/useMarketBrief';
 import {useFutureMap} from './src/hooks/useFutureMap';
 import {useIndexChart} from './src/hooks/useChartIntelligence';
 import {useJapanMarketComparison,useNikkeiLive} from './src/hooks/useJapanMarketComparison';
 window.mounts=0;window.passkeyPrompts=0;Object.defineProperty(navigator,'credentials',{value:{get:()=>{window.passkeyPrompts++;throw Error('unexpected passkey');}}});
 function Screen(){const [text,setText]=useState('');
  useEventsActive();const brief=useMarketBrief();useFutureMap();const chart=useIndexChart('SPX','daily'),live=useNikkeiLive(),comparison=useJapanMarketComparison(5);
  useEffect(()=>{window.mounts++;},[]);
  return <main><input aria-label="保持する入力" value={text} onChange={e=>setText(e.target.value)}/>
   <output id="comparison-ready">{comparison.loading?'loading':'ready'}</output><output id="saved-brief-ready">{brief.loading?'loading':'ready'}</output><output id="chart">{chart.data?.symbol??'loading'}</output><output id="live">{live.quote?.price??'aged'}</output>
   <button id="fixture-reload" onClick={()=>location.reload()}>再読み込み</button></main>;}
 window.fixtureNativeFetch=window.fetch.bind(window);
 installOwnerTransport();
 createRoot(document.getElementById('root')).render(<React.StrictMode><OwnerAccess>{__FULL_APP_FIXTURE__?<AssetsProvider><WatchlistSyncLifecycle/><App/><Screen/></AssetsProvider>:<Screen/>}</OwnerAccess></React.StrictMode>);
`,loader:'tsx',resolveDir:web},bundle:true,write:false,format:'iife',platform:'browser',
 loader:{'.css':'empty'},define:{'import.meta.env':JSON.stringify({VITE_ARGUS_OWNER_AUTH_REQUIRED:'1',VITE_ARGUS_BACKEND_URL:backendOrigin}),
 '__PRODUCT_VERSION__':JSON.stringify('13.8.175'),'__FRONTEND_BUILD_SHA__':JSON.stringify('fixture-build'),'__APP_VERSION__':JSON.stringify('fixture-version'),
 '__FULL_APP_FIXTURE__':JSON.stringify(process.env.ARGUS_FULL_APP_FIXTURE==='1'),
 'process.env.NODE_ENV':JSON.stringify('development')},logLevel:'silent'});
if(process.env.ARGUS_FULL_APP_FIXTURE==='1')fs.writeFileSync('/private/tmp/argus-owner-resume-repair-20261013/full-fixture-compiled.js',fixture.outputFiles[0].text);
// Playwright's default disables browser storage partitioning. Test the real
// partitioned-cookie policy by removing just that default feature override.
const {chromiumSwitches}=require(path.join(path.dirname(require.resolve('playwright-core/package.json')),
 'lib/server/chromium/chromiumSwitches.js'));
const disabled=chromiumSwitches(false,undefined).find(arg=>arg.startsWith('--disable-features='));
assert(disabled?.split(',').includes('ThirdPartyStoragePartitioning'));
const engine=process.env.ARGUS_BROWSER_ENGINE??'chromium';assert(['chromium','webkit'].includes(engine));
const browser=engine==='webkit'?await webkit.launch({headless:true}):await chromium.launch({headless:true,ignoreDefaultArgs:[disabled],
 args:[disabled.split(',').filter(part=>part!=='ThirdPartyStoragePartitioning').join(',')]});
try{
 const context=await browser.newContext({ignoreHTTPSErrors:true});
 await context.addInitScript(()=>{
  Object.defineProperty(navigator,'standalone',{value:true});
  window.testVisibility='visible';
  Object.defineProperty(document,'visibilityState',{get:()=>window.testVisibility});
  Object.defineProperty(document,'hidden',{get:()=>window.testVisibility==='hidden'});
  window.switchApp=state=>{window.testVisibility=state;document.dispatchEvent(new Event('visibilitychange'));};
 });
 await context.route('**/*',route=>{const url=route.request().url();return url.startsWith(backendOrigin+'/')||url.startsWith('https://resume-ui.test/')||url.startsWith('https://other-ui.test/')?route.continue():route.abort();});
 const page=await context.newPage();const counts=new Map(),indexQueryCounts=new Map();const errors=[];let sessionUnavailable=false;let fixtureExpiry=0;
 page.on('pageerror',e=>{errors.push(e.message);console.log(JSON.stringify({fixturePageError:e.message,fixtureStack:e.stack}));});
 console.log(JSON.stringify({engine,version:browser.version()}));
 await page.route('https://resume-ui.test/',route=>route.fulfill({status:200,contentType:'text/html; charset=utf-8',
  body:'<!doctype html><meta charset="utf-8"><div id="root"></div><script>'+fixture.outputFiles[0].text+'</script>'}));
 handleApi=route=>{
  const request=route.request(),url=new URL(request.url());
  if(url.pathname.endsWith('/cookie-probe'))return route.fulfill({status:200,contentType:'application/json',
   headers:{'access-control-allow-origin':request.headers().origin,'access-control-allow-credentials':'true'},
   body:JSON.stringify({cookieSeen:!!request.headers().cookie?.includes('__Secure-argus-owner-resume=')})});
  if(request.method()==='OPTIONS')return route.fulfill({status:204,headers:{'access-control-allow-origin':'https://resume-ui.test',
   'access-control-allow-headers':'Content-Type,X-ARGUS-OWNER-SESSION,X-ARGUS-OWNER-NONCE,X-ARGUS-OWNER-RESUME','access-control-allow-methods':'GET,POST,OPTIONS','access-control-allow-credentials':'true'}});
  const key=url.pathname;if(key.endsWith('/index-chart')){const q=url.pathname+url.search;indexQueryCounts.set(q,(indexQueryCounts.get(q)??0)+1);}
  counts.set(key,(counts.get(key)??0)+1);
  const nonce=request.headers()['x-argus-owner-nonce']??'';
  const headers={'access-control-allow-origin':'https://resume-ui.test','access-control-allow-credentials':'true','access-control-expose-headers':'X-ARGUS-OWNER-NONCE','X-ARGUS-OWNER-NONCE':nonce};
  let body={};
  if(key.endsWith('/password')){fixtureExpiry=Date.now()+86400000;body={token:'s'.repeat(43),expiresAt:fixtureExpiry};}
  else if(key.endsWith('/session')){
   if(sessionUnavailable)return route.fulfill({status:503,headers,body:'{}'});
   if(request.method()==='POST'){
    if(!request.headers().cookie?.includes('__Secure-argus-owner-resume='))return route.fulfill({status:401,headers,body:'{}'});
    body={token:'s'.repeat(43),expiresAt:fixtureExpiry};
   }else{
    body={authenticated:true};
    if(request.headers()['x-argus-owner-resume']==='1')headers['set-cookie']='__Secure-argus-owner-resume='+('s'.repeat(43))+'; Path=/api/argus/owner-auth/; Secure; HttpOnly; SameSite=None; Partitioned';
   }
  }
  else if(key.endsWith('/macro-event-analysis'))body={items:[]};
  else if(key.endsWith('/market-regime'))body={status:'mock',asOf:'',regime:{label:'CAUTIOUS',confidence:0.2,summaryJa:'合成検査'},ratesBackdrop:{posture:'neutral',rationaleJa:'合成検査'},rotationGroups:[],topRotations:[],supportingEvidence:[]};
  else if(key.endsWith('/visibility-guard'))body={asOf:'',engineVersion:'fixture',visibilityLevel:'minimal',blockedActions:['ENTER','ADD'],warnings:[],limitations:[],confidenceCap:0.25,reasonCodes:[],coverageLineJa:'合成検査'};
  else if(key.endsWith('/action-labels'))body={status:'mock',asOf:'',labels:[],marketPosture:{label:'CAUTIOUS',rationaleJa:'合成検査'}};
  else if(key.endsWith('/japan-watchlist')||key.endsWith('/us-watchlist'))body={status:'unavailable',asOf:null,stocks:[]};
  else if(key.endsWith('/sector-heatmap'))body={schemaVersion:'jp-sector-heatmap-v1',targetDate:'2026-10-13',isToday:false,session:{session:'CLOSED'},rows:[],collectionErrors:{}};
  else if(key.endsWith('/market-shock'))body={schemaVersion:'argus-market-shock-v1',status:'unavailable',eventCount:0,events:[]};
  else if(key.endsWith('/news-intelligence'))body={schemaVersion:'argus-news-intelligence-v1',eventCount:0,events:[],generatedAt:new Date().toISOString(),intakeStatus:'UNAVAILABLE'};
  else if(key.endsWith('/market-ledger'))body={table:[],derivedMetrics:[],phase3:{calendar:[]}};
  else if(key.endsWith('/market-news'))body={status:'unavailable',items:[],asOf:null};
  else if(key==='/api/argus/events')body={status:'mock',asOf:null,timezone:'Asia/Tokyo',sources:[],events:[]};
  else if(key.endsWith('/events-active'))body={events:[]};
  else if(key.endsWith('/future-map'))body={schemaVersion:'argus-future-map-public-v1',availability:'AVAILABLE',updatedAt:'2026-10-06',
   lastChangedAt:'2026-10-06',today:'2026-10-06',rows:[{id:'fixture',view:'v',tag:'底'}],status:{position:'観測中',nextAlert:{date:'2026-10-16',label:'参考'},nextBottom:{date:'2026-10-16',label:'未検証'}},record:{scored:0,reached:0},argusValidated:false,actionAuthority:false};
  else if(key.endsWith('/index-chart'))body=url.searchParams.get('live')==='1'
   ? {actionAuthority:false,quote:{price:100,previousClose:99,changePct:1,tradedAt:new Date(Date.now()).toISOString(),receivedAt:new Date(Date.now()).toISOString(),delaySeconds:0,sessionOpen:true,realtime:true,source:'立花証券'}}
   : {index:url.searchParams.get('index'),symbol:url.searchParams.get('index'),timeframe:url.searchParams.get('timeframe'),status:'unavailable',periodEnd:null,quoteState:'STALE',indicators:{bars:[],status:'unavailable',missingReasons:['fixture']},zones:[],turningPoints:[],eventMarkers:[],valuationLevels:[],reactionAnomalies:[],relationshipBreaks:[],critique:[],scenarios:[],automaticAiCalls:0};
  return route.fulfill({status:200,contentType:'application/json',headers,body:JSON.stringify(body)});
 };
 await page.goto('https://resume-ui.test/');
 await page.getByLabel('復旧用パスワード').fill('fixture-password');
 await page.getByRole('button',{name:'パスワードで開く'}).click();
 await page.locator('#chart').filter({hasText:'SPX'}).waitFor();
 await page.locator('#live').filter({hasText:'100'}).waitFor();
 await page.getByLabel('保持する入力').fill('開いていた画面');
 // Before installing the synthetic clock (which removes NavigationTiming),
 // exercise real HTTPS/IndexedDB document recovery and native navigation type.
 await page.locator('#saved-brief-ready').filter({hasText:'ready'}).waitFor();
 await page.locator('#comparison-ready').filter({hasText:'ready'}).waitFor();
 await page.evaluate(()=>window.flushViewCheckpoint());
 const passwordReads=counts.get('/api/argus/owner-auth/password');
 // An absent saved entry must not erase a session still active in memory.
 await page.evaluate(()=>sessionStorage.removeItem('argus.owner.session.v1'));
 const beforeMissingReturn=Object.fromEntries(counts),beforeIndexQueries=Object.fromEntries(indexQueryCounts);
 for(let i=0;i<10;i++)await page.evaluate(()=>{window.switchApp('hidden');window.switchApp('visible');});
 await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(resolve)));
 assert.deepEqual(Object.fromEntries(counts),beforeMissingReturn,'missing sessionStorage causes no ordinary-return reads');
 assert.equal(await page.evaluate(()=>window.passkeyPrompts),0);
 // A new document can recover the same session without another ceremony.
 const sessionBeforeCookie=counts.get('/api/argus/owner-auth/session');
 await page.locator('#saved-brief-ready').filter({hasText:'ready'}).waitFor();
 await page.locator('#comparison-ready').filter({hasText:'ready'}).waitFor();
 await page.evaluate(()=>window.flushViewCheckpoint());
 console.log(JSON.stringify({beforeDocumentCookieRecovery:{engine,cookieStored:(await context.cookies(backendOrigin+'/api/argus/owner-auth/session')).some(c=>c.name==='__Secure-argus-owner-resume')}}));
 await page.evaluate(()=>window.switchApp('hidden'));
 await page.goto('https://resume-ui.test/');
 try { await page.locator('#chart').filter({hasText:'SPX'}).waitFor(); }
 catch(error){console.log(JSON.stringify({documentRecoveryFailed:{engine,lock:await page.evaluate(()=>document.documentElement.dataset.argusOwnerLock??null),view:await page.evaluate(()=>document.documentElement.dataset.argusResumeView??null),passkeyButton:await page.getByRole('button',{name:'パスキーで開く',exact:true}).count(),cookieStored:(await context.cookies(backendOrigin+'/api/argus/owner-auth/session')).some(c=>c.name==='__Secure-argus-owner-resume')}}));throw error;}
 const nativeNavigationType=await page.evaluate(()=>performance.getEntriesByType('navigation')[0].type);
 // Allow local test-driver round trips before pausing; a sampled current
 // millisecond can already be in the past when Playwright receives pauseAt.
 await page.clock.install();await page.clock.pauseAt(await page.evaluate(()=>Date.now()+1000));
 assert.equal(counts.get('/api/argus/owner-auth/session'),sessionBeforeCookie+2,'one cookie resume and one fresh header verification');
 assert.equal(counts.get('/api/argus/owner-auth/password'),passwordReads);
 assert.equal(await page.evaluate(()=>window.passkeyPrompts),0);
 const cookies=await context.cookies(backendOrigin+'/api/argus/owner-auth/session');
 const recovery=cookies.find(c=>c.name==='__Secure-argus-owner-resume');
 assert(recovery?.httpOnly&&recovery.secure&&recovery.sameSite==='None'&&recovery.expires===-1);
 console.log(JSON.stringify({cookiePolicy:cookies.map(c=>({name:c.name,httpOnly:c.httpOnly,secure:c.secure,sameSite:c.sameSite,session:c.expires===-1,partitionKey:c.partitionKey??null})),browser:browser.version()}));
 if(engine==='chromium')assert(recovery.partitionKey,'the session-only recovery cookie must be partitioned');
 const ownCookieSeen=await page.evaluate(async base=>(await window.fixtureNativeFetch(base+'/api/argus/owner-auth/cookie-probe',{credentials:'include'})).json(),backendOrigin);
 assert.equal(ownCookieSeen.cookieSeen,true);
 const other=await context.newPage();await other.route('https://other-ui.test/',r=>r.fulfill({status:200,contentType:'text/html; charset=utf-8',body:'<!doctype html><meta charset="utf-8"><p>isolated privacy probe</p>'}));
 await other.goto('https://other-ui.test/');
 const otherCookieSeen=await other.evaluate(async base=>(await fetch(base+'/api/argus/owner-auth/cookie-probe',{credentials:'include'})).json(),backendOrigin);
 assert.equal(otherCookieSeen.cookieSeen,false,'the same resume credential must never reach a different top-site partition');await other.close();await page.bringToFront();
 const dataBeforeRecovery=Object.fromEntries(Object.entries(beforeMissingReturn).filter(([key])=>!key.startsWith('/api/argus/owner-auth/')));
 const dataAfterRecovery=Object.fromEntries([...counts].filter(([key])=>!key.startsWith('/api/argus/owner-auth/')));
 console.log(JSON.stringify({fixtureCheckpointPresence:await page.evaluate(()=>window.fixtureCheckpointPresence())}));
 console.log(JSON.stringify({resumeView:await page.evaluate(()=>document.documentElement.dataset.argusResumeView),navigation:nativeNavigationType}));
 console.log(JSON.stringify({indexQueryCountsBefore:beforeIndexQueries,indexQueryCountsAfter:Object.fromEntries(indexQueryCounts)}));
 console.log(JSON.stringify({documentRecoveryReadersBefore:dataBeforeRecovery,documentRecoveryReadersAfter:dataAfterRecovery}));
 assert.deepEqual(dataAfterRecovery,dataBeforeRecovery,'storage-lost document recovery must not restart all market readers');
 if(process.env.ARGUS_FULL_APP_FIXTURE==='1'){
  await page.getByText('前回分',{exact:true}).waitFor();
  assert.equal(await page.getByText(/突発の市場ショック: なし/).count(),0,
   'restoring an empty previous news/shock view cannot certify that no shock currently exists');
  console.log('fixture stage: prior news/shock observation displayed without current-absence claim');
 }
 console.log('fixture stage: cookie probes completed');
 await page.clock.resume();
 console.log('fixture stage: clock resumed');
 const afterDocumentRecovery=Object.fromEntries(counts);
 for(let i=0;i<10;i++)await page.evaluate(()=>{window.switchApp('hidden');window.switchApp('visible');});
 await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(resolve)));
 assert.deepEqual(Object.fromEntries(counts),afterDocumentRecovery,'returns after recovery retain readers');
 console.log('fixture stage: recovered returns checked');
 await page.getByLabel('保持する入力').fill('開いていた画面');
 // The resumed document's timers were paused after native navigation was observed.
 const before=Object.fromEntries(counts),mounts=await page.evaluate(()=>window.mounts);
 for(let i=0;i<10;i++)await page.evaluate(()=>{window.switchApp('hidden');window.switchApp('visible');});
 await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
 assert.deepEqual(Object.fromEntries(counts),before,'ten app switches must not authenticate or reacquire readers');
 assert.equal(await page.evaluate(()=>window.mounts),mounts,'protected screen stays mounted');
 assert.equal(await page.getByLabel('保持する入力').inputValue(),'開いていた画面');
 assert.equal(await page.locator('.owner-access-screen').count(),0);
 console.log('fixture stage: input and mount retained');
 // Suspended timers must not allow an old realtime quote to remain authoritative.
 await page.evaluate(()=>window.switchApp('hidden'));
 await page.clock.setSystemTime(Date.now()+20_000);
 await page.evaluate(()=>window.switchApp('visible'));
 await page.locator('#live').filter({hasText:'aged'}).waitFor();
 assert.deepEqual(Object.fromEntries(counts),before,'aging a quote locally needs no HTTP');
 console.log('fixture stage: old quote aged locally');
 // Existing realtime cadence still refreshes without rebooting the screen.
 await page.clock.runFor(10_001);
 await page.locator('#live').filter({hasText:'100'}).waitFor();
 assert.equal(await page.evaluate(()=>window.mounts),mounts);
 console.log('fixture stage: periodic quote refreshed');
 // A manual reload rebuilds the readers, but restores the same-build PWA login without Face ID/password.
 const sessionBeforeManual=counts.get('/api/argus/owner-auth/session');
 const indexReads=counts.get('/api/argus/index-chart');
 await page.clock.resume();
 await page.locator('#fixture-reload').click();
 console.log('fixture stage: manual reload clicked');
 await page.locator('#chart').filter({hasText:'SPX'}).waitFor();
 assert.equal(counts.get('/api/argus/owner-auth/password'),passwordReads,'manual reload restores rather than logging in');
 assert.equal(counts.get('/api/argus/owner-auth/session'),sessionBeforeManual+1,'one shared verification for the manual reload');
 assert.ok(counts.get('/api/argus/index-chart')>indexReads,'manual reload starts a new chart read');
 for(const key of ['/api/argus/events-active','/api/argus/market-brief','/api/argus/future-map'])
  assert.ok(counts.get(key)>before[key],`manual reload starts ${key}`);
 // A retained login and a transient verification failure need connection recovery,
 // not another biometric ceremony. Exercise the actual access gate and transport.
 sessionUnavailable=true;
 await page.reload();await page.clock.install();
 await page.clock.runFor(3_001);
 assert.equal(await page.getByRole('button',{name:'パスキーで開く',exact:true}).count(),0,
  'a slow saved-session verification must not offer another Face ID ceremony');
 await page.clock.runFor(60_001);
 assert.equal(await page.getByRole('button',{name:'パスキーで開く',exact:true}).count(),0,
  'a transient restore failure retains the login and offers connection recovery');
 await page.getByRole('button',{name:'接続を再確認',exact:true}).waitFor();
 sessionUnavailable=false;
 await page.getByRole('button',{name:'接続を再確認',exact:true}).click();
 await page.locator('#chart').filter({hasText:'SPX'}).waitFor();
 assert.equal(counts.get('/api/argus/owner-auth/password'),passwordReads,'retry verifies the saved login, never creates another one');
 // Restoration does not extend the original login's 24-hour expiry.
 await page.evaluate(()=>window.switchApp('hidden'));
 await page.clock.runFor(86_400_001);
 await page.evaluate(()=>window.switchApp('visible'));
 await page.getByRole('button',{name:'パスキーで開く',exact:true}).waitFor();
 assert.equal(await page.getByRole('button',{name:'接続を再確認',exact:true}).count(),0,
  'expiry must offer a new login rather than recovery of an expired one');
 assert.deepEqual(errors,[]);
 console.log('PASS PWA owner screen: ten app switches, input/mount/session retained, zero resume requests, local quote expiry, periodic quotes, manual full reload, shared restore');
}finally{await browser.close();await new Promise(resolve=>server.close(resolve));fs.rmSync(tlsDirectory,{recursive:true,force:true});}
