import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { buildSync } from 'esbuild';
import { chromium } from 'playwright';

// Real component, isolated synthetic API. No owner login, market or AI request.
const script = buildSync({ stdin: { contents: `import React from 'react';import {createRoot} from 'react-dom/client';
import {WeightedPerInput} from './src/components/today/WeightedPerInput';
createRoot(document.getElementById('root')).render(<WeightedPerInput/>);`, loader: 'tsx', resolveDir: process.cwd() },
  bundle: true, write: false, format: 'iife', define: { 'import.meta.env': JSON.stringify({ VITE_ARGUS_BACKEND_URL: '' }) } }).outputFiles[0].text;
const css = fs.readFileSync('src/components/today/LevelMapCard.css', 'utf8');
const html = `<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>
:root{--line:#29323c;--text-main:#e2e8f0;--text-faint:#9aa8b8;--bg-card:#131d27}body{margin:12px;background:#0b121a;color:var(--text-main);font:15px/1.6 system-ui}a{color:#8ebeff}button{background:#152f4b;color:#e2e8f0;border:1px solid #436080;border-radius:6px} ${css}</style><main id="root"></main><script>${script}</script>`;
const server = createServer((req, res) => { res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' }); res.end(html); });
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const browser = await chromium.launch({ headless: true });
const output = process.env.ARGUS_MANUAL_PER_BROWSER_OUTPUT;
if (output) fs.mkdirSync(output, { recursive: true });
const evidence = [];
try {
  for (const width of [320, 390, 430]) {
    const page = await browser.newPage({ viewport: { width, height: 844 } });
    const errors = []; page.on('pageerror', error => errors.push(error.message));
    let state = { revision: 0, enabled: false, referenceDate: null, stale: false, inputDue: true, defaultDate: '2026-10-14', dueDate: '2026-10-09' };
    const posts = [];
    await page.route('**/api/argus/owner-auth/weighted-per', async route => {
      const req = route.request();
      if (req.method() === 'POST') {
        const body = req.postDataJSON(); posts.push(body);
        if (body.operation === 'save' && body.per === 30 && !body.confirmed) {
          await route.fulfill({ status: 409, json: { error: 'confirmation_required' } }); return;
        }
        assert.equal(body.revision, state.revision);
        state = { ...state, revision: state.revision + 1, enabled: body.operation === 'save', referenceDate: body.operation === 'save' ? body.date : null, inputDue: false };
      }
      await route.fulfill({ status: 200, json: state });
    });
    page.on('dialog', async dialog => dialog.accept());
    await page.goto(`http://127.0.0.1:${server.address().port}`);
    await page.getByRole('heading', { name: '今週の加重平均を書き写す' }).waitFor();
    assert.equal(await page.getByRole('link', { name: /日経平均プロフィル/ }).getAttribute('href'), 'https://indexes.nikkei.co.jp/nkave/archives/data?list=per');
    assert.equal(await page.getByLabel('対象日', { exact: true }).inputValue(), '2026-10-14');
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    assert.ok(await page.getByRole('button', { name: '保存', exact: true }).evaluate(el => el.getBoundingClientRect().height >= 44));
    if (output) await page.screenshot({ path: path.join(output, `manual-per-${width}.png`), fullPage: true });
    await page.getByLabel('対象日', { exact: true }).fill('2026-10-13');
    await page.getByLabel('予想PER（加重平均・倍）').fill('30');
    await page.getByRole('button', { name: '保存', exact: true }).click();
    await page.getByRole('button', { name: '確認して保存', exact: true }).waitFor();
    assert.equal(posts.length, 1, 'confirmation dialog never submits automatically');
    await page.getByRole('button', { name: '確認して保存', exact: true }).click();
    await page.getByText('保存しました。', { exact: false }).waitFor();
    assert.equal(await page.getByRole('heading', { name: '今週の加重平均を書き写す' }).count(), 0);
    assert.deepEqual(posts[1], { revision: 0, operation: 'save', date: '2026-10-13', per: 30, confirmed: true });
    await page.getByRole('button', { name: '入力値を消して補正をやめる' }).click();
    await page.getByText('補正なしに戻しました。').waitFor();
    assert.equal(state.enabled, false);
    assert.equal(await page.evaluate(() => localStorage.length + sessionStorage.length), 0, 'manual value never enters browser storage');
    assert.deepEqual(errors, []);
    evidence.push({ width, save: true, explicitConfirmation: true, clear: true, noHorizontalOverflow: true, touch44: true, browserStorageEntries: 0 });
    await page.close();
  }
  if (output) fs.writeFileSync(path.join(output, 'result.json'), JSON.stringify({ status: 'PASS', synthetic: true, cases: evidence }, null, 2));
  console.log(JSON.stringify({ status: 'PASS', synthetic: true, cases: evidence }));
} finally { await browser.close(); await new Promise(resolve => server.close(resolve)); }
