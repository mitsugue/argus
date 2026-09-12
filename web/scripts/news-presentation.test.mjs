import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {chromium} from 'playwright';
const require = createRequire(import.meta.url);
const {build} = createRequire(require.resolve('vite/package.json'))('esbuild');
const web = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const fixture = await build({
  stdin: {contents: `import React from 'react'; import {createRoot} from 'react-dom/client';
    import {TodayNewsCards} from './src/components/today/ArgusTodayPanel';
    import {orderMaterialNews} from './src/domain/newsPresentation';
    window.orderNews = orderMaterialNews;
    window.renderNews = rows => createRoot(document.getElementById('root')).render(
      <div className="argus-today"><section className="at-event card">
      <TodayNewsCards rows={orderMaterialNews(rows)} onOpen={id => {window.openedNews = id;}} />
      </section></div>);`, loader:'tsx', resolveDir:web},
  bundle:true, write:false, format:'iife', platform:'browser', loader:{'.css':'empty'},
  define:{'import.meta.env.VITE_ARGUS_BACKEND_URL':JSON.stringify('https://news.test'),
    'process.env.NODE_ENV':JSON.stringify('development')}, logLevel:'silent',
});
const row = (id, severity, at, extra={}) => ({id,eventId:id,severity,sourceReceivedAt:at,
  headlineJa:id==='story'?'供給制約についての重要な記事':'市場の観測値についての記事',
  kind:'ニュース',whyJa:'観測した事実と、今後確認する市場反応を区別します。',
  metaJa:'受信した時点 · AI解析済み',eventMemory:null,...extra});
const story = row('story','HIGH','2026-09-12T02:00:00Z',{
  newsEvent:{eventId:'story',impactDirection:{primaryDirection:'BEARISH',
    directionByTarget:{japanEquities:'BEARISH',energy:'BULLISH'},transmissionChain:[]}},
  eventMemory:{status:'WATCHING',flagRecovery:false,openedDaysAgo:0,calibrationMode:'SHADOW',
    analogEvidence:{independentEpisodeCount:2,insufficientEvidence:true}},
});
const input=[story,{...story},row('older','HIGH','2026-09-11T02:00:00Z',{newsEvent:{eventId:'older'}}),
  row('critical','CRITICAL','2026-09-10T02:00:00Z'),
  row('stale','CRITICAL','2026-09-09T02:00:00Z',{staleness:'STALE'})];
const before = JSON.stringify(input);
const browser=await chromium.launch({headless:true});
try {
 for(const width of [390,1280]) {
  const page=await browser.newPage({viewport:{width,height:844}}); const errors=[];
  page.on('pageerror',e=>{errors.push(e.message); console.error(e.message);});
  await page.route('https://news-ui.test/', route=>route.fulfill({status:200,contentType:'text/html',body:'<div id="root"></div>'}));
  await page.goto('https://news-ui.test/');
  await page.addStyleTag({content:fs.readFileSync(path.join(web,'src/styles/theme.css'),'utf8')
    + fs.readFileSync(path.join(web,'src/components/today/ArgusToday.css'),'utf8')
    + 'body{margin:0;padding:12px;background:#0b1218;color:#dce5eb;font-family:system-ui}.card{background:#111b24}button{font-family:inherit}'});
  await page.addScriptTag({content:fixture.outputFiles[0].text});
  const ordered=await page.evaluate(rows=>window.orderNews(rows),input);
  assert.deepEqual(ordered.map(x=>x.eventId),['critical','story','older']);
  assert.equal(JSON.stringify(input),before,'presentation must not mutate stored input');
  const followups=await page.evaluate(rows=>window.orderNews(rows),[story,{...story,id:'followup',eventId:'followup'}]);
  assert.equal(followups.length,2,'same-title follow-ups with distinct IDs remain available');
  const revised=await page.evaluate(rows=>window.orderNews(rows),[
    {...story,revision:1},{...story,revision:2,severity:'INFO'}]);
  assert.equal(revised.length,0,'latest revision can remove a stale importance classification');
  await page.evaluate(rows=>window.renderNews(rows),input);
  await page.locator('.at-news-row').first().waitFor();
  assert.equal(await page.locator('.at-news-row').count(),3);
  assert.equal(await page.getByText(story.headlineJa,{exact:true}).count(),1,'one article has one headline');
  assert.equal(await page.locator('.at-news-row').first().getAttribute('data-news-event-id'),'critical');
  assert.equal(await page.locator('.at-news-row mark').first().innerText(),'重大');
  assert.equal(await page.getByText('影響の見立て: 弱気').isVisible(),true);
  assert.equal(await page.getByText('この記事だけでは上下を決めません',{exact:false}).isVisible(),true);
  assert.equal(await page.locator('.at-event-memory').isVisible(),false,'internal evidence is initially folded');
  await page.getByText('過去の事例との照合 · 検証中',{exact:true}).click();
  assert.equal(await page.locator('.at-event-memory').isVisible(),true);
  await page.locator('article[data-news-event-id="story"] > button').click();
  assert.equal(await page.evaluate(()=>window.openedNews),'story','tap must open the same article');
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);
  assert.deepEqual(errors,[]);
  if(process.env.NEWS_UI_EVIDENCE_DIR) {
    fs.mkdirSync(process.env.NEWS_UI_EVIDENCE_DIR,{recursive:true});
    await page.getByText('過去の事例との照合 · 検証中',{exact:true}).click();
    await page.screenshot({path:path.join(process.env.NEWS_UI_EVIDENCE_DIR,`news-cards-${width}.png`),fullPage:true});
  }
  await page.close();
 }
 console.log('PASS news presentation: single article, importance/recency order, revisions, distinct follow-ups, folded evidence, matching detail tap, 390/1280px');
} finally {await browser.close();}
