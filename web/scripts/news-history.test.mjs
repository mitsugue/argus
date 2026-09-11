import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';
const require = createRequire(import.meta.url);
const { build } = createRequire(require.resolve('vite/package.json'))('esbuild');
const web = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const fixture = await build({
  stdin: { contents: `import React from 'react'; import {createRoot} from 'react-dom/client';
    import {NewsHistory} from './src/components/notifications/NewsAlertsPanel';
    createRoot(document.getElementById('root')).render(<NewsHistory/>);`, loader:'tsx', resolveDir:web },
  bundle:true, write:false, format:'iife', platform:'browser', loader:{'.css':'empty'},
  define:{'import.meta.env.VITE_ARGUS_BACKEND_URL':JSON.stringify('https://news-history.test'),
    'process.env.NODE_ENV':JSON.stringify('development')}, logLevel:'silent',
});
const browser = await chromium.launch({headless:true});
try {
 const page = await browser.newPage(); let calls = 0;
 const event = {eventId:'history-1',headlineJa:'ECB、0.25%利上げ決定',
   whyJa:'当時の金利変更の説明',japanImpactJa:'為替反応は未確認',source:'Nikkei',
   sourceReceivedAt:'2026-09-10T12:37:11Z',staleness:'STALE',analysisState:'AI_ANALYZED',
   alertEligible:false,sdaAuthority:false};
 await page.route('https://news-history.test/**',async route=>{
   assert.equal(route.request().method(),'GET');
   assert.equal(new URL(route.request().url()).searchParams.get('view'),'history'); calls++;
   await route.fulfill({status:calls===1?200:503,contentType:'application/json',
     headers:{'access-control-allow-origin':'*'},body:JSON.stringify({
       schemaVersion:'argus-news-intelligence-v1',generatedAt:'2026-09-11T14:00:00Z',events:[event]})});
 });
 await page.setContent('<div id="root"></div>');
 await page.addScriptTag({content:fixture.outputFiles[0].text});
 await page.getByRole('button',{name:'過去の重要ニュースを見る'}).waitFor();
 assert.equal(calls,0,'history must not trigger work before it is opened');
 await page.getByRole('button',{name:'過去の重要ニュースを見る'}).click();
 await page.locator('[data-news-history-event="history-1"]').waitFor();
 assert.match(await page.locator('body').innerText(),/過去の情報/);
 assert.match(await page.locator('body').innerText(),/09\/10.*21:37/);
 assert.match(await page.locator('body').innerText(),/当時の解釈/);
 await page.getByRole('button',{name:'履歴を再取得'}).click();
 await page.getByRole('status').filter({hasText:'履歴を更新できません'}).waitFor();
 assert.equal(await page.locator('[data-news-history-event="history-1"]').count(),1);
 assert.equal(calls,2);
 console.log('PASS historical news: on-demand GET, original receipt, past interpretation, retained data on failure');
} finally { await browser.close(); }
