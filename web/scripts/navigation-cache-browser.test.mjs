import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { build } from 'esbuild';
import { chromium } from 'playwright';
const original=fs.readFileSync('scripts/market-brief-recovery.test.cjs','utf8');
const saved=vm.runInNewContext(original.slice(original.indexOf("const factId"),original.indexOf('const response'))+'; saved;');
const bundle=await build({stdin:{contents:`import React,{useEffect,useState} from 'react';
import {createRoot} from 'react-dom/client';
import {AppShell} from './src/components/AppShell';
import {useMarketBrief} from './src/hooks/useMarketBrief';
function Screen(){const {brief,loading}=useMarketBrief();useEffect(()=>{window.mounts=(window.mounts||0)+1},[]);return <section><input aria-label="画面の状態"/><p data-testid="brief">{brief?.unifiedSummary?.sections.view.textJa||'未取得'}</p><p data-testid="loading">{String(loading)}</p></section>}
function Fixture(){const [page,setPage]=useState('today');return <><button onClick={()=>setPage('asset')}>銘柄を開く</button><button onClick={()=>setPage('today')}>トップへ戻る</button><AppShell sidebar={null} lastUpdated={new Date()} pageKey={page}><Screen/></AppShell></>}
createRoot(document.getElementById('root')).render(<Fixture/>);`,resolveDir:process.cwd(),loader:'tsx'},bundle:true,write:false,loader:{'.css':'empty'},define:{'import.meta.env.VITE_ARGUS_BACKEND_URL':'"https://nav-api.test"','__PRODUCT_VERSION__':'"13.8.79"','__BUILD_ID__':'"test"','__BUILD_TIME__':'"test"','__GIT_SHA__':'"test"','process.env.NODE_ENV':'"production"'}});
if(process.argv.includes('--compile-only')){console.log('画面移動のブラウザ検査をコンパイル済み（実行はCIのブラウザ準備後）');process.exit(0)}
const browser=await chromium.launch({headless:true});
try{const page=await browser.newPage({viewport:{width:390,height:844}});let requests=0;const errors=[];
page.on('pageerror',err=>errors.push(err.message));
await page.route('https://nav-api.test/**',route=>{requests++;return route.fulfill({status:200,contentType:'application/json',headers:{'Access-Control-Allow-Origin':'*'},body:JSON.stringify(route.request().url().endsWith('/market-brief')?saved:{})})});
await page.route('https://nav-ui.test/**',route=>route.fulfill({status:200,contentType:'text/html',body:'<!doctype html><div id="root"></div><script>'+bundle.outputFiles[0].text+'</script>'}));
await page.goto('https://nav-ui.test/');await page.locator('[data-testid="loading"]').filter({hasText:'false'}).waitFor();
await page.getByLabel('画面の状態').fill('保存した画面');const before=requests;
for(let n=0;n<5;n++){await page.getByRole('button',{name:'銘柄を開く'}).click();await page.getByRole('button',{name:'トップへ戻る'}).click()}
assert.equal(await page.evaluate(()=>window.mounts),1,'ページ移動で保存済み画面を破棄しない');
assert.equal(await page.getByLabel('画面の状態').inputValue(),'保存した画面');
assert.equal(requests,before,'移動だけで市場説明を再取得しない');assert.deepEqual(errors,[]);
await page.reload();await page.locator('[data-testid="loading"]').filter({hasText:'false'}).waitFor();assert.ok(requests>before,'手動の全再読込では最新値を取得する');
console.log('390px画面: 10回のページ移動で再マウント/追加API読取0、手動全再読込で再取得 PASS');
}finally{await browser.close()}
