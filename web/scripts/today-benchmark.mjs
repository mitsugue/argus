// Repeatable Today product benchmark. Measures what a real user experiences:
// time to Primary Action, key numbers, first/all headline charts, payload
// totals, request scheduling, and warm-start behavior. Target-agnostic: run
// against live production for the baseline or a local candidate for the
// after-comparison, with identical methodology.
//
//   node scripts/today-benchmark.mjs --url https://mitsugue.github.io/argus/ \
//     --out ../artifacts/today-benchmark-live.json
import { chromium } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';

const args = Object.fromEntries(process.argv.slice(2).reduce((rows, value, index, all) => {
  if (value.startsWith('--')) rows.push([value.slice(2), all[index + 1]]);
  return rows;
}, []));
const target = (args.url ?? 'https://mitsugue.github.io/argus/').replace(/\/?$/, '/');
const outputPath = path.resolve(args.out ?? '../artifacts/today-benchmark.json');
const label = args.label ?? 'unlabeled';

const MILESTONES = [
  ['shell', () => !!document.querySelector('.nav')],
  ['primary-action', () => {
    const node = document.querySelector('.at-call strong');
    return !!node && /BUY|HOLD|WAIT|REDUCE|EXIT|様子見|買い|保有|縮小|撤退/.test(node.textContent ?? '');
  }],
  ['key-numbers', () => [...document.querySelectorAll('.at-index-strip b')]
    .some((node) => /[0-9][\d,.]*/.test(node.textContent ?? ''))],
  ['first-chart', () => [...document.querySelectorAll(
    '[data-argus-contract="today-projection-state-v1"][data-projection-state="available"], .at-headline-chart[data-headline-state="data"]',
  )].length >= 1],
  ['four-charts', () => document.querySelectorAll('.at-headline-chart[data-headline-state="data"]').length >= 4
    || (document.querySelectorAll('.at-index svg path, .at-index polyline').length >= 4
      && !!document.querySelector('[data-projection-state="available"]'))],
  ['probability', () => /UP\s*\d+%|RANGE\s*\d+%|DOWN\s*\d+%/.test(document.body.textContent ?? '')],
];

async function measurePhase(page, phase, budgetMs) {
  const t0 = await page.evaluate(() => performance.now());
  const results = {};
  // The current production surface hides market data behind a collapsed
  // disclosure; a real user must open it, so the benchmark opens it as soon
  // as it exists and counts that as part of the product experience.
  const opener = (async () => {
    try {
      const summary = page.locator('summary', { hasText: '根拠・市場データ' });
      await summary.waitFor({ state: 'attached', timeout: budgetMs });
      const open = await summary.evaluate((node) => node.closest('details')?.open ?? false);
      if (!open) await summary.click();
    } catch { /* absent means the restored layout shows data directly */ }
  })();
  // All milestones are armed concurrently from t0 so a missing milestone can
  // never inflate the timestamps of the ones that follow it.
  await Promise.all(MILESTONES.map(async ([name, predicate]) => {
    try {
      await page.waitForFunction(predicate, null, { timeout: budgetMs });
      results[name] = Math.round(await page.evaluate(() => performance.now()) - t0);
    } catch {
      results[name] = null;
    }
  }));
  await opener.catch(() => {});
  const network = await page.evaluate(() => {
    const rows = performance.getEntriesByType('resource');
    const api = rows.filter((row) => row.name.includes('/api/argus/'));
    const chart = api.filter((row) => row.name.includes('chart-intelligence'));
    return {
      requestCount: rows.length,
      apiCount: api.length,
      totalDecodedBytes: rows.reduce((sum, row) => sum + (row.decodedBodySize || 0), 0),
      chartRequests: chart.map((row) => ({
        symbol: new URL(row.name).searchParams.get('symbol'),
        kind: new URL(row.name).searchParams.get('snapshot')
          ?? new URL(row.name).searchParams.get('view'),
        start: Math.round(row.startTime), duration: Math.round(row.duration),
        decodedBytes: row.decodedBodySize,
      })),
      longTasks: (globalThis.__ARGUS_LONG_TASKS ?? []).slice(0, 40),
      longTaskTotalMs: (globalThis.__ARGUS_LONG_TASKS ?? [])
        .reduce((sum, task) => sum + task.d, 0),
    };
  });
  return { phase, milestonesMs: results, network };
}

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ viewport: { width: 1280, height: 800 } });
await context.addInitScript(() => {
  globalThis.__ARGUS_LONG_TASKS = [];
  try {
    new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        globalThis.__ARGUS_LONG_TASKS.push({
          t: Math.round(entry.startTime), d: Math.round(entry.duration),
        });
      }
    }).observe({ entryTypes: ['longtask'] });
  } catch { /* longtask unsupported */ }
});
const page = await context.newPage();

await page.goto(`${target}#today`, { waitUntil: 'domcontentloaded', timeout: 60_000 });
const cold = await measurePhase(page, 'cold', 45_000);

// Let pending writes/settling finish before the warm phase.
await page.waitForTimeout(3_000);
await page.reload({ waitUntil: 'domcontentloaded', timeout: 60_000 });
const warm = await measurePhase(page, 'warm', 45_000);

// Route transition responsiveness (no remote data should be required again).
const routes = [];
for (const [name, hash] of [['holdings', '#holdings'], ['notifications', '#notifications'],
  ['settings', '#settings'], ['today', '#today']]) {
  const t0 = await page.evaluate(() => performance.now());
  await page.evaluate((h) => { location.hash = h; }, hash);
  await page.waitForFunction((h) => location.hash === h, hash, { timeout: 10_000 });
  await page.waitForFunction(() => {
    const main = document.querySelector('.shell__main');
    return !!main && main.textContent.trim().length > 50;
  }, null, { timeout: 10_000 }).catch(() => {});
  routes.push({ name, ms: Math.round(await page.evaluate(() => performance.now()) - t0) });
}

const report = {
  schemaVersion: 'argus-today-benchmark-v1', label, target,
  measuredAt: new Date().toISOString(),
  cold, warm, routes,
};
fs.mkdirSync(path.dirname(outputPath), { recursive: true });
fs.writeFileSync(outputPath, `${JSON.stringify(report, null, 2)}\n`);
console.log(JSON.stringify({ label, cold: cold.milestonesMs, warm: warm.milestonesMs,
  coldBytes: cold.network.totalDecodedBytes, warmBytes: warm.network.totalDecodedBytes,
  routes }, null, 1));
await browser.close();
