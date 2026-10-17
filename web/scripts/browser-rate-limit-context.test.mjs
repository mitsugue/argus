import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { chromium } from 'playwright';
import { installBrowserRateLimitProof } from './browser-rate-limit-proof.mjs';

// Dedicated synthetic pages; no owner session, provider or saved market body.
const server = createServer((req, res) => {
  res.setHeader('Content-Type', 'text/html');
  res.end('<!doctype html><title>synthetic context</title>');
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const origin = `http://127.0.0.1:${server.address().port}`;
const browser = await chromium.launch({ headless: true });
try {
  for (const kind of ['MAIN', 'WARM', 'CONTROLLED_429', 'HEADLINE']) {
    const context = await browser.newContext({ serviceWorkers: 'block' });
    await context.addInitScript(installBrowserRateLimitProof);
    let calls = 0;
    await context.route('**/api/argus/chart-intelligence?*', route => {
      calls++;
      return route.fulfill({ status: 429, contentType: 'application/json',
        body: '{"error":"rate_limited","message":"synthetic context response"}' });
    });
    const page = await context.newPage();
    await page.goto(origin);
    for (let navigation = 0; navigation < 2; navigation++) {
      if (navigation) await page.reload();
      const result = await page.evaluate(async () => {
        const url = location.origin + '/api/argus/chart-intelligence?symbol=1321';
        const response = await fetch(url, { cache: 'no-store', redirect: 'error' });
        return { actualStatus: response.status, originalBody: await response.json(),
          proof: await window.__argusAcceptanceRateLimitReads.get(url) };
      });
      assert.equal(result.actualStatus, 429, kind);
      assert.equal(result.originalBody.error, 'rate_limited', kind);
      assert.deepEqual(result.proof, { status: 429, bodyRead: 'JSON',
        errorField: 'RATE_LIMITED', messageIsString: true }, kind);
    }
    assert.equal(calls, 2, kind);
    await context.close();
  }
  console.log('429本文の固定分類：4検査画面・再読込・元の応答保持・追加通信なし 合格');
} finally {
  await browser.close();
  await new Promise(resolve => server.close(resolve));
}
