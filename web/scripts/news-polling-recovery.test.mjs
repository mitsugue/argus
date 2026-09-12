import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {chromium} from 'playwright';
const require=createRequire(import.meta.url);
const {build}=createRequire(require.resolve('vite/package.json'))('esbuild');
const web=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const fixture=await build({stdin:{contents:`import React from 'react';
 import {createRoot} from 'react-dom/client';
 import {useNewsIntelligence} from './src/hooks/useNewsIntelligence';
 import {useMarketShock} from './src/hooks/useMarketShock';
 function Probe(){const news=useNewsIntelligence(),risk=useMarketShock();
 return <><output id="news">{JSON.stringify(news)}</output><output id="risk">{JSON.stringify(risk)}</output></>}
 createRoot(document.getElementById('root')).render(<Probe/>);`,loader:'tsx',resolveDir:web},
 bundle:true,write:false,format:'iife',platform:'browser',define:{'import.meta.env.VITE_ARGUS_BACKEND_URL':JSON.stringify('https://news.test'),'process.env.NODE_ENV':JSON.stringify('development')},logLevel:'silent'});
const browser=await chromium.launch({headless:true});
try{
 const page=await browser.newPage();let phase='initial', stalled;const counts={news:0,risk:0};
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.clock.install();
 await page.route('https://news-ui.test/',route=>route.fulfill({status:200,contentType:'text/html',body:'<div id="root"></div>'}));
 await page.route('https://news.test/api/argus/**',async route=>{
  const news=route.request().url().endsWith('/news-intelligence'),key=news?'news':'risk';counts[key]++;
  if(phase===key){stalled?.();return;} // No headers: simulate a stalled independent source.
  await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({
   schemaVersion:news?'argus-news-intelligence-v1':'argus-market-shock-v1',
   generatedAt:'2026-09-12T05:00:00Z',eventCount:1,
   events:[{eventId:`${key}-${phase}`,headlineJa:news?'取得済みの記事':'取得済みの市場リスク'}]})});
 });
 await page.goto('https://news-ui.test/');await page.addScriptTag({content:fixture.outputFiles[0].text});
 const value=async id=>JSON.parse(await page.locator('#'+id).innerText());
 await page.waitForFunction(()=>['news','risk'].every(id=>JSON.parse(document.getElementById(id).textContent).status==='data'));
 for(const key of ['news','risk']){
  const before=await value(key);phase=key;const countBefore=counts[key];
  const observedStall=new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(new Error('stalled source not requested')),5000);stalled=()=>{clearTimeout(timer);resolve();};});
  const requested=page.waitForRequest(r=>r.url().endsWith(key==='news'?'/news-intelligence':'/market-shock'));
  await page.evaluate(()=>window.dispatchEvent(new Event('online')));
  await requested;await observedStall;
  assert.ok(counts[key]>countBefore);
  const other=key==='news'?'risk':'news';
  await page.waitForFunction(({id,phase})=>{const s=JSON.parse(document.getElementById(id).textContent);return s.status==='data'&&s.view.events[0].eventId===id+'-'+phase;},{id:other,phase});
  await page.clock.fastForward(20_001);
  await page.waitForFunction(id=>JSON.parse(document.getElementById(id).textContent).status==='error',key);
  assert.deepEqual((await value(key)).view,before.view,'timeout must retain acquired evidence');
  assert.equal((await value(other)).status,'data');
  phase='recovered-'+key;await page.evaluate(()=>window.dispatchEvent(new Event('online')));
  await page.waitForFunction(phase=>['news','risk'].every(id=>{const s=JSON.parse(document.getElementById(id).textContent);return s.status==='data'&&s.view.events[0].eventId===id+'-'+phase;}),phase);
  assert.equal((await value(key)).view.events[0].eventId,`${key}-${phase}`,'expired flight must allow the next response');
 }
 assert.deepEqual(errors,[]);console.log('PASS stalled news/risk requests release their flight, retain prior evidence and recover independently');
}finally{await browser.close()}
