import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';

const require = createRequire(import.meta.url);
const { build } = createRequire(require.resolve('vite/package.json'))('esbuild');
const web = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const fixture = await build({
  stdin: { contents: `
    import React, {useState, useLayoutEffect} from 'react';
    import {createRoot} from 'react-dom/client';
    import {useIndexChart} from './src/hooks/useChartIntelligence';
    window.indexChartFrames = [];
    function Harness() {
      const [selected, setSelected] = useState({index:'SPX', timeframe:'daily'});
      const state = useIndexChart(selected.index, selected.timeframe);
      window.setIndexChartSelection = (index, timeframe='daily') => setSelected({index,timeframe});
      useLayoutEffect(() => {
        window.indexChartFrames.push({selected, data:state.data});
      });
      return <pre id="state">{JSON.stringify({selected,...state})}</pre>;
    }
    createRoot(document.getElementById('root')).render(<Harness/>);
  `, loader: 'tsx', resolveDir: web },
  bundle: true, write: false, format: 'iife', platform: 'browser',
  define: { 'import.meta.env.VITE_ARGUS_BACKEND_URL': JSON.stringify('https://index-chart.test'),
    'process.env.NODE_ENV': JSON.stringify('development') },
  logLevel: 'silent',
});

const browser = await chromium.launch({headless:true});
try {
  const page = await browser.newPage();
  const pending = new Map();
  const counts = new Map();
  await page.route('https://index-chart.test/**', async route => {
    const url = new URL(route.request().url());
    const key = `${url.searchParams.get('index')}:${url.searchParams.get('timeframe')}`;
    counts.set(key, (counts.get(key) ?? 0) + 1);
    pending.set(key, route);
  });
  const request = async key => {
    const deadline = Date.now() + 5000;
    while (!pending.has(key) && Date.now() < deadline) await new Promise(r => setTimeout(r, 5));
    assert.ok(pending.has(key), `request missing: ${key}`);
    const route = pending.get(key); pending.delete(key); return route;
  };
  const reply = (route, index, timeframe='daily', value=100) => route.fulfill({
    status:200, contentType:'application/json', headers:{'access-control-allow-origin':'*'},
    body:JSON.stringify({index,symbol:index,timeframe,value}),
  });
  const state = () => page.locator('#state').textContent().then(JSON.parse);
  const selected = (index, timeframe='daily') => page.evaluate(
    ({index,timeframe}) => window.setIndexChartSelection(index,timeframe), {index,timeframe});
  const waitData = (index, timeframe='daily') => page.waitForFunction(
    ({index,timeframe}) => {
      const s=JSON.parse(document.querySelector('#state').textContent);
      return s.data?.index===index && s.data?.timeframe===timeframe;
    }, {index,timeframe});
  await page.setContent('<div id="root"></div>');
  await page.addScriptTag({content:fixture.outputFiles[0].text});
  await reply(await request('SPX:daily'),'SPX');
  await waitData('SPX');

  await selected('NDX');
  const late = await request('NDX:daily');
  assert.equal((await state()).data,null,'another index must disappear while the selected index is loading');
  await selected('TOPIX');
  await reply(await request('TOPIX:daily'),'TOPIX');
  await waitData('TOPIX');
  const lateResponse = page.waitForResponse(r => r.url().includes('index=NDX'));
  await reply(late,'NDX');
  await (await lateResponse).finished();
  await page.evaluate(() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r))));
  assert.equal((await state()).data.index,'TOPIX','a late response must not replace the current index');

  await selected('NDX');
  await waitData('NDX');
  assert.equal(counts.get('NDX:daily'),1,'a verified matching cache is reused');
  await selected('NDX','weekly');
  const weekly = await request('NDX:weekly');
  assert.equal((await state()).data,null,'daily values must not be shown as weekly');
  await reply(weekly,'SPX','weekly');
  await page.waitForFunction(() => JSON.parse(document.querySelector('#state').textContent).error);
  assert.equal((await state()).data,null,'a mismatched response must be rejected');

  await selected('N225');
  await (await request('N225:daily')).fulfill({status:200,contentType:'application/json',
    headers:{'access-control-allow-origin':'*'},body:JSON.stringify({status:'expected_skip',index:'N225'})});
  await page.waitForFunction(() => JSON.parse(document.querySelector('#state').textContent).expectedSkip);
  await selected(null);
  await page.waitForFunction(() => JSON.parse(document.querySelector('#state').textContent).selected.index===null);
  assert.deepEqual(await state(),{selected:{index:null,timeframe:'daily'},data:null,expectedSkip:false,loading:false,error:null});

  await selected('SPX');
  await waitData('SPX');
  await page.evaluate(() => document.dispatchEvent(new Event('visibilitychange')));
  const refresh = await request('SPX:daily');
  assert.equal((await state()).data.value,100,'same-index cached values remain available during refresh');
  await reply(refresh,'SPX','daily',101);
  await page.waitForFunction(() => JSON.parse(document.querySelector('#state').textContent).data?.value===101);
  const wrongFrames = await page.evaluate(() => window.indexChartFrames.filter(({selected,data}) =>
    data && (data.index!==selected.index || data.timeframe!==selected.timeframe)));
  assert.deepEqual(wrongFrames,[],'no committed React render may mix selected and displayed identities');
  console.log('PASS index chart identity: delayed switch, stale response, matching cache, timeframe, response identity, missing data, disabled selection, same-index refresh');
} finally {
  await browser.close();
}
