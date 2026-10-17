import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {chromium} from 'playwright';
const require=createRequire(import.meta.url);
const {build}=createRequire(require.resolve('vite/package.json'))('esbuild');
const web=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const fixture=await build({stdin:{contents:`import React from 'react';import {createRoot} from 'react-dom/client';
import {NikkeiResearchChartView} from './src/components/chart/NikkeiResearchChart';
import {LevelMapView} from './src/components/today/LevelMapCard';
import {useNewsIntelligence} from './src/hooks/useNewsIntelligence';
function Health(){const s=useNewsIntelligence();return <output id="health" data-status={s.status} data-health={s.intakeHealth?.status??'pending'}>{s.view?.eventCount??'loading'}</output>}
window.renderFixture=(chart,future,map)=>createRoot(document.getElementById('root')).render(<div className="argus-today"><LevelMapView state={map}/><section className="jp-comparison"><h2>日経平均の水準と見通し</h2><NikkeiResearchChartView chart={chart} future={future}/></section><Health/></div>);`,loader:'tsx',resolveDir:web},
bundle:true,write:false,format:'iife',platform:'browser',loader:{'.css':'empty'},
define:{'import.meta.env.VITE_ARGUS_BACKEND_URL':JSON.stringify('https://chart.test'),'process.env.NODE_ENV':JSON.stringify('development')},logLevel:'silent'});
const prices=[64200,65600,63100,64600,63900,65700,66800,65900,67000,68957,68309];
const chart={schemaVersion:'jp-market-chart-layers-v1',today:'2026-10-05',start:'2026-04-04',end:'2027-01-05',
points:prices.map((close,i)=>({date:new Date(Date.UTC(2026,8,2+i*3)).toISOString().slice(0,10),close,eps:3987.78,epsDate:'2026-08-31'})),
current:{morningOf:'2026-10-05',eps:3987.78,epsDate:'2026-10-02',previousClose:68309,previousSession:'2026-10-02',atr14:1235},
pivots:[{date:'2026-09-08',kind:'BOTTOM',price:63100,confirmedOn:'2026-09-14'}],pending:null,candidates:[],
nearest:[{side:'UP',multiple:18,price:71780,reachedWithin10SessionsPct:38,sessionsMedian:10},{side:'DOWN',multiple:17,price:67792,reachedWithin10SessionsPct:89,sessionsMedian:0}],actionAuthority:false,automaticAiCalls:0};
const future={rows:[['one','2026-10-01','2026-10-10',69700,72000,'天井圏'],['two','2026-10-16','2026-10-22',65500,65500,'戻り'],['three','2026-10-27','2026-11-04',63300,63300,'底'],['four','2026-11-06','2026-11-13',64800,64800,'戻り'],['five','2026-11-19','2026-11-26',63600,63600,'底']].map(([id,start,end,low,high,tag])=>({id,start,end,level:{low,high},tag}))};
const latest={morningOf:chart.today,createdAt:'2026-10-04T09:35:00Z',previousClose:68309,previousSession:'2026-10-02',eps:3987.78,epsDate:'2026-10-02',per:17.13,atr14:1235,epsJumped:false,epsLabelJa:'ARGUS推計（公式値ではありません）',
rows:chart.nearest.map(n=>({...n,kinds:['PER_LINE'],distancePct:n.side==='UP'?5.1:-.8,distanceAtr:n.side==='UP'?2.8:-.4,bandJa:'2割前後',tier:'MAP',sessions25:0,sessions75:12})),atrGuides:{UP:[],DOWN:[]},fixedNotesJa:[],actionAuthority:false};
const browser=await chromium.launch({headless:true});
try{
 for(const width of [320,390,1280]){
  const page=await browser.newPage({viewport:{width,height:844}}),errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.route('https://chart.test/',r=>r.fulfill({contentType:'text/html',body:'<div id="root"></div>'}));
  await page.route('**/api/argus/news-intelligence',r=>r.fulfill({json:{schemaVersion:'argus-news-intelligence-v1',generatedAt:'2026-10-05T01:00:00Z',intakeStatus:'HEALTHY',eventCount:7,events:[]}}));
  let healthRelease;const healthDelay=new Promise(resolve=>{healthRelease=resolve});
  await page.route('**/api/argus/news-intake/health',async r=>{await healthDelay;await r.fulfill({json:{schemaVersion:'argus-news-intake-health-v1',status:'HEALTHY',configured:true,threadAlive:true,pending:0,lastSyncAt:'2026-10-05T01:00:00Z',recentMessages:[{messageId:'private-id-must-not-render'}]}})});
  await page.goto('https://chart.test/');
  await page.addStyleTag({content:['src/styles/theme.css','src/components/today/LevelMapCard.css','src/components/chart/NikkeiResearchChart.css','src/components/today/ReadingHierarchy.css'].map(p=>fs.readFileSync(path.join(web,p),'utf8')).join('\n')+'html,body,#root{height:auto;overflow:visible}body{margin:0;padding:16px;background:var(--bg);color:var(--text-main);font-family:system-ui}#root{max-width:700px;margin:auto}h2{font-size:18px;margin-top:0}.card{background:var(--surface);border:1px solid var(--line);border-radius:14px}'});
  await page.addScriptTag({content:fixture.outputFiles[0].text});
  await page.evaluate(([c,f,m])=>window.renderFixture(c,f,m),[chart,future,{latest,missedMornings:[]}]);
  await page.locator('#health[data-status="data"]').waitFor();
  assert.equal(await page.locator('#health').innerText(),'7','slow health must not block the acquired news');
  assert.equal(await page.locator('#health').getAttribute('data-health'),'pending');
  healthRelease();await page.locator('#health[data-health="HEALTHY"]').waitFor();
  assert.equal(await page.getByText('private-id-must-not-render').count(),0);
  assert.equal(await page.locator('.nr-selection > b').innerText(),'1 天井圏 · 10/1〜10/10');
  const svg=page.locator('.nr-plot-wrap svg');
  const axes=()=>page.locator('.nr-axis').allTextContents();const initial=await axes();
  await page.getByRole('button',{name:'拡大',exact:true}).click();assert.notDeepEqual(await axes(),initial);
  await page.getByRole('button',{name:'今日へ戻る',exact:true}).click();assert.deepEqual(await axes(),initial);
  await svg.scrollIntoViewIfNeeded();const box=await svg.boundingBox();
  await page.mouse.move(box.x+box.width*.45,box.y+100);await page.mouse.down();
  await page.mouse.move(box.x+box.width*.7,box.y+100,{steps:8});await page.mouse.up();
  assert.notDeepEqual(await axes(),initial,'horizontal dragging changes the displayed dates');
  await page.getByRole('button',{name:'今日へ戻る',exact:true}).click();
  await svg.evaluate(el=>{const b=el.getBoundingClientRect(),x=b.x+b.width*.45,y=b.y+130;
   const emit=(type,id,dx)=>el.dispatchEvent(new PointerEvent(type,{bubbles:true,pointerType:'touch',pointerId:id,clientX:x+dx,clientY:y}));
   // Synthetic multi-touch validates state arithmetic; capture is unavailable for synthetic contacts.
   const capture=el.setPointerCapture;el.setPointerCapture=()=>{};
   emit('pointerdown',101,-20);emit('pointerdown',102,20);emit('pointermove',102,90);emit('pointerup',101,-20);emit('pointerup',102,90);el.setPointerCapture=capture;
  });
  await page.waitForFunction(previous=>JSON.stringify([...document.querySelectorAll('.nr-axis')].map(el=>el.textContent))!==JSON.stringify(previous),initial);
  assert.notDeepEqual(await axes(),initial,'two-finger separation zooms the dates');
  await page.getByRole('button',{name:'今日へ戻る',exact:true}).click();
  await page.locator('svg g[role="button"]').nth(1).click();
  assert.equal(await page.locator('.nr-selection > b').innerText(),'2 戻り · 10/16〜10/22','tap opens that point, not a nearby point');
  await page.locator('svg g[role="button"]').nth(2).focus();await page.keyboard.press('Enter');
  assert.equal(await page.locator('.nr-selection > b').innerText(),'3 底 · 10/27〜11/4');
  await page.getByRole('button',{name:'今日へ戻る',exact:true}).click();
  assert.equal(await page.locator('.nr-point-label').evaluateAll(labels=>{
    const boxes=labels.map(el=>el.getBoundingClientRect());
    return boxes.every((a,i)=>boxes.slice(i+1).every(b=>a.right<=b.left||b.right<=a.left||a.bottom<=b.top||b.bottom<=a.top));
  }),true,'the five price labels do not overlap');
  assert.equal(await page.locator('.lm-reach article strong').first().evaluate(el=>parseFloat(getComputedStyle(el).fontSize)),30);
  assert.equal(await page.locator('.nr-nearest').count(),0,'the reach statistic has one reading location');
  assert.ok((await page.locator('.lm-reach').innerText()).includes('今後の確率や、反発した割合ではありません'));
  assert.equal(await page.locator('.lm-heading > b').evaluate(el=>el.getBoundingClientRect().height<=parseFloat(getComputedStyle(el).lineHeight)*1.1),true,'title stays on one line');
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false,'no horizontal page overflow');
  assert.deepEqual(errors,[]);
  if(process.env.CHART_UI_EVIDENCE_DIR){fs.mkdirSync(process.env.CHART_UI_EVIDENCE_DIR,{recursive:true});await page.screenshot({path:path.join(process.env.CHART_UI_EVIDENCE_DIR,`chart-reading-${width}.png`),fullPage:true});}
  await page.close();
 }
 console.log('PASS chart reading: 320/390/1280px, point taps, keyboard, drag, pinch arithmetic, return to today, prominent frequencies, nonblocking news health');
}finally{await browser.close()}
