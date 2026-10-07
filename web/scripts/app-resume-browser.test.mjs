import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {chromium} from 'playwright';
const require=createRequire(import.meta.url);
const {build}=createRequire(require.resolve('vite/package.json'))('esbuild');
const web=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const fixture=await build({stdin:{contents:`
 import React, {useState,useEffect} from 'react';
 import {createRoot} from 'react-dom/client';
 import {OwnerAccess} from './src/components/OwnerAccess';
 import {installOwnerTransport} from './src/lib/ownerSession';
 import {useEventsActive} from './src/hooks/useEventsActive';
 import {useMarketBrief} from './src/hooks/useMarketBrief';
 import {useFutureMap} from './src/hooks/useFutureMap';
 import {useIndexChart} from './src/hooks/useChartIntelligence';
 import {useNikkeiLive} from './src/hooks/useJapanMarketComparison';
 window.mounts=0;
 function Screen(){const [text,setText]=useState('');
  useEventsActive();useMarketBrief();useFutureMap();const chart=useIndexChart('SPX','daily'),live=useNikkeiLive();
  useEffect(()=>{window.mounts++;},[]);
  return <main><input aria-label="保持する入力" value={text} onChange={e=>setText(e.target.value)}/>
   <output id="chart">{chart.data?.symbol??'loading'}</output><output id="live">{live.quote?.price??'aged'}</output>
   <button onClick={()=>location.reload()}>再読み込み</button></main>;}
 installOwnerTransport();
 createRoot(document.getElementById('root')).render(<React.StrictMode><OwnerAccess><Screen/></OwnerAccess></React.StrictMode>);
`,loader:'tsx',resolveDir:web},bundle:true,write:false,format:'iife',platform:'browser',
 loader:{'.css':'empty'},define:{'import.meta.env':JSON.stringify({VITE_ARGUS_OWNER_AUTH_REQUIRED:'1',VITE_ARGUS_BACKEND_URL:'https://resume-api.test'}),
 '__FRONTEND_BUILD_SHA__':JSON.stringify('fixture-build'),'__APP_VERSION__':JSON.stringify('fixture-version'),
 'process.env.NODE_ENV':JSON.stringify('development')},logLevel:'silent'});
const browser=await chromium.launch({headless:true});
try{
 const context=await browser.newContext();
 await context.addInitScript(()=>{
  Object.defineProperty(navigator,'standalone',{value:true});
  window.testVisibility='visible';
  Object.defineProperty(document,'visibilityState',{get:()=>window.testVisibility});
  Object.defineProperty(document,'hidden',{get:()=>window.testVisibility==='hidden'});
  window.switchApp=state=>{window.testVisibility=state;document.dispatchEvent(new Event('visibilitychange'));};
 });
 const page=await context.newPage();const counts=new Map();const errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 await page.route('https://resume-ui.test/',route=>route.fulfill({status:200,contentType:'text/html',
  body:'<div id="root"></div><script>'+fixture.outputFiles[0].text+'</script>'}));
 await page.route('https://resume-api.test/**',route=>{
  const request=route.request(),url=new URL(request.url());
  if(request.method()==='OPTIONS')return route.fulfill({status:204,headers:{'access-control-allow-origin':'https://resume-ui.test',
   'access-control-allow-headers':'*','access-control-allow-methods':'GET,POST,OPTIONS'}});
  const key=url.pathname;counts.set(key,(counts.get(key)??0)+1);
  const nonce=request.headers()['x-argus-owner-nonce']??'';
  const headers={'access-control-allow-origin':'https://resume-ui.test','access-control-expose-headers':'X-ARGUS-OWNER-NONCE','X-ARGUS-OWNER-NONCE':nonce};
  let body={};
  if(key.endsWith('/password'))body={token:'s'.repeat(43),expiresAt:Date.now()+86400000};
  else if(key.endsWith('/session'))body={authenticated:true};
  else if(key.endsWith('/events-active'))body={events:[]};
  else if(key.endsWith('/future-map'))body={schemaVersion:'argus-future-map-public-v1',availability:'AVAILABLE',updatedAt:'2026-10-06',
   lastChangedAt:'2026-10-06',today:'2026-10-06',rows:[{id:'fixture',view:'v',tag:'底'}],status:{position:'観測中'},record:{scored:0,reached:0},argusValidated:false,actionAuthority:false};
  else if(key.endsWith('/index-chart'))body=url.searchParams.get('live')==='1'
   ? {actionAuthority:false,quote:{price:100,previousClose:99,changePct:1,tradedAt:new Date(Date.now()).toISOString(),receivedAt:new Date(Date.now()).toISOString(),delaySeconds:0,sessionOpen:true,realtime:true,source:'立花証券'}}
   : {index:'SPX',symbol:'SPX',timeframe:'daily'};
  return route.fulfill({status:200,contentType:'application/json',headers,body:JSON.stringify(body)});
 });
 await page.goto('https://resume-ui.test/');
 await page.getByLabel('復旧用パスワード').fill('fixture-password');
 await page.getByRole('button',{name:'パスワードで開く'}).click();
 await page.locator('#chart').filter({hasText:'SPX'}).waitFor();
 await page.locator('#live').filter({hasText:'100'}).waitFor();
 await page.getByLabel('保持する入力').fill('開いていた画面');
 await page.clock.install(); // deterministic checks: periodic timers remain scheduled
 const before=Object.fromEntries(counts),mounts=await page.evaluate(()=>window.mounts);
 for(let i=0;i<10;i++)await page.evaluate(()=>{window.switchApp('hidden');window.switchApp('visible');});
 await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
 assert.deepEqual(Object.fromEntries(counts),before,'ten app switches must not authenticate or reacquire readers');
 assert.equal(await page.evaluate(()=>window.mounts),mounts,'protected screen stays mounted');
 assert.equal(await page.getByLabel('保持する入力').inputValue(),'開いていた画面');
 assert.equal(await page.locator('.owner-access-screen').count(),0);
 // Suspended timers must not allow an old realtime quote to remain authoritative.
 await page.evaluate(()=>window.switchApp('hidden'));
 await page.clock.setSystemTime(Date.now()+20_000);
 await page.evaluate(()=>window.switchApp('visible'));
 await page.locator('#live').filter({hasText:'aged'}).waitFor();
 assert.deepEqual(Object.fromEntries(counts),before,'aging a quote locally needs no HTTP');
 // Existing realtime cadence still refreshes without rebooting the screen.
 await page.clock.runFor(10_001);
 await page.locator('#live').filter({hasText:'100'}).waitFor();
 assert.equal(await page.evaluate(()=>window.mounts),mounts);
 // A manual reload rebuilds the readers, but restores the same-build PWA login without Face ID/password.
 const passwordReads=counts.get('/api/argus/owner-auth/password');
 const indexReads=counts.get('/api/argus/index-chart');
 await page.getByRole('button',{name:'再読み込み',exact:true}).click();
 await page.locator('#chart').filter({hasText:'SPX'}).waitFor();
 assert.equal(counts.get('/api/argus/owner-auth/password'),passwordReads,'manual reload restores rather than logging in');
 assert.equal(counts.get('/api/argus/owner-auth/session'),2,'one login verification plus one shared automatic restore');
 assert.ok(counts.get('/api/argus/index-chart')>indexReads,'manual reload starts a new chart read');
 for(const key of ['/api/argus/events-active','/api/argus/market-brief','/api/argus/future-map'])
  assert.ok(counts.get(key)>before[key],`manual reload starts ${key}`);
 assert.deepEqual(errors,[]);
 console.log('PASS PWA owner screen: ten app switches, input/mount/session retained, zero resume requests, local quote expiry, periodic quotes, manual full reload, shared restore');
}finally{await browser.close();}
