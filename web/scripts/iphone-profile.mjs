// iPhone 14 Pro Max equivalent interaction profile. Chromium mobile emulation
// (430x932 @3x, touch) with CPU throttling approximates the real device's
// constrained main thread; WebKit provides Safari-truth layout. Measures what
// the owner actually feels: tap latency, route navigation, scroll->paint of
// already-loaded content, long tasks, and bottom dead space.
//
//   node scripts/iphone-profile.mjs --url https://mitsugue.github.io/argus/ \
//     --label live --throttle 4 --out ../artifacts/iphone-profile-live.json
import { chromium, webkit } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';

const args = Object.fromEntries(process.argv.slice(2).reduce((rows, value, index, all) => {
  if (value.startsWith('--')) rows.push([value.slice(2), all[index + 1]]);
  return rows;
}, []));
const target = (args.url ?? 'https://mitsugue.github.io/argus/').replace(/\/?$/, '/');
const label = args.label ?? 'unlabeled';
const throttle = Number(args.throttle ?? 4);
const outputPath = path.resolve(args.out ?? `../artifacts/iphone-profile-${label}.json`);
const shotDir = path.resolve(path.dirname(outputPath), `iphone-shots-${label}`);
fs.mkdirSync(shotDir, { recursive: true });

const DEVICE = {
  viewport: { width: 430, height: 932 }, deviceScaleFactor: 3,
  isMobile: true, hasTouch: true,
  userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) '
    + 'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1',
};

async function armObservers(page) {
  await page.addInitScript(() => {
    globalThis.__LT = [];
    try {
      new PerformanceObserver((list) => {
        for (const entry of list.getEntries()) {
          globalThis.__LT.push({ t: Math.round(entry.startTime), d: Math.round(entry.duration) });
        }
      }).observe({ entryTypes: ['longtask'] });
    } catch { /* unsupported */ }
  });
}

async function paintLatency(page) {
  // Time from now until the browser can complete two animation frames —
  // a direct proxy for "the main thread can respond to my input".
  return page.evaluate(() => new Promise((resolve) => {
    const start = performance.now();
    requestAnimationFrame(() => requestAnimationFrame(() =>
      resolve(Math.round(performance.now() - start))));
  }));
}

async function tapRoute(page, name) {
  const button = page.locator('.nav__mobile').getByRole('button', { name, exact: true });
  const t0 = Date.now();
  try {
    await button.tap({ timeout: 8_000 });
  } catch (error) {
    const visible = await button.isVisible().catch(() => false);
    return { route: name, error: `tap_failed visible=${visible} ${String(error).slice(0, 80)}` };
  }
  // route content swap = main content contains new route's text
  await page.waitForFunction(() => {
    const main = document.querySelector('.shell__main');
    return !!main && main.textContent.trim().length > 40;
  }, null, { timeout: 20_000 }).catch(() => {});
  const contentMs = Date.now() - t0;
  const frame = await paintLatency(page);
  return { route: name, contentMs, postTapFrameMs: frame };
}

async function scrollProbe(page) {
  // Scroll through the page in viewport steps. After each step measure how
  // long until the frame settles (already-loaded content must paint at once).
  const steps = [];
  const total = await page.evaluate(() => document.body.scrollHeight);
  for (let y = 0; y < Math.min(total, 6000); y += 800) {
    const t0 = Date.now();
    await page.evaluate((top) => window.scrollTo({ top, behavior: 'instant' }), y);
    const frameMs = await paintLatency(page);
    steps.push({ y, frameMs, settleMs: Date.now() - t0 });
  }
  await page.evaluate(() => window.scrollTo({ top: 0, behavior: 'instant' }));
  return steps;
}

const report = { schemaVersion: 'argus-iphone-profile-v1', label, target, throttle,
  measuredAt: new Date().toISOString() };

// ---------- Chromium with CPU throttle: interaction truth ----------
{
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext(DEVICE);
  await armObservers(context);
  const page = await context.newPage();
  const cdp = await context.newCDPSession(page);
  await cdp.send('Emulation.setCPUThrottlingRate', { rate: throttle });

  const t0 = Date.now();
  await page.goto(`${target}#today`, { waitUntil: 'domcontentloaded', timeout: 60_000 });
  await page.waitForSelector('.nav', { timeout: 30_000 });
  const shellMs = Date.now() - t0;
  await page.waitForFunction(() => {
    const node = document.querySelector('.at-call strong');
    return !!node && (node.textContent ?? '').trim().length > 0;
  }, null, { timeout: 30_000 }).catch(() => {});
  const primaryMs = Date.now() - t0;
  const chartMs = await page.waitForFunction(() =>
    !!document.querySelector('[data-projection-state="available"]'),
  null, { timeout: 45_000 }).then(
    async () => Date.now() - t0, () => null);

  // settle, then interaction probes on the warm page
  await page.waitForTimeout(2_000);
  const coldLongTasks = await page.evaluate(() => ({
    totalMs: globalThis.__LT.reduce((sum, t) => sum + t.d, 0),
    worst: [...globalThis.__LT].sort((a, b) => b.d - a.d).slice(0, 8),
    count: globalThis.__LT.length,
  }));

  const idleFrame = await paintLatency(page);
  const scrollSteps = await scrollProbe(page);
  const navigation = [];
  for (const name of ['Holdings', 'Alerts', 'Settings', 'Today']) {
    navigation.push(await tapRoute(page, name));
    await page.waitForTimeout(400);
  }
  // second lap = fully warm routes (no first-mount cost)
  const navigationWarm = [];
  for (const name of ['Holdings', 'Alerts', 'Settings', 'Today']) {
    navigationWarm.push(await tapRoute(page, name));
    await page.waitForTimeout(400);
  }
  const selectorSwitch = [];
  for (const symbol of ['1306', 'SPY', 'QQQ', '1321']) {
    const control = page.locator(`[data-argus-control="market-instrument"][data-instrument="${symbol}"]`);
    if (await control.count()) {
      await control.first().scrollIntoViewIfNeeded().catch(() => {});
      const t1 = Date.now();
      try {
        await control.first().tap({ timeout: 3_000 });
      } catch {
        // Actionability flake in the inner scroll container: dispatch the
        // click directly — we are measuring the app's response latency here.
        await control.first().evaluate((node) => node.click());
      }
      await page.waitForFunction((sym) => document.querySelector(
        '[data-argus-contract="canonical-market-snapshot-v1"]',
      )?.getAttribute('data-canonical-instrument') === sym, symbol,
      { timeout: 20_000 }).catch(() => {});
      const projectionMs = await page.waitForFunction(() =>
        !!document.querySelector('[data-projection-state="available"]'),
      null, { timeout: 20_000 }).then(() => Date.now() - t1, () => null);
      selectorSwitch.push({ symbol, contractMs: Date.now() - t1, projectionMs });
    }
  }
  const interactionLongTasks = await page.evaluate(() => ({
    totalMs: globalThis.__LT.reduce((sum, t) => sum + t.d, 0),
    worst: [...globalThis.__LT].sort((a, b) => b.d - a.d).slice(0, 8),
  }));

  report.chromiumThrottled = {
    coldMs: { shell: shellMs, primaryAction: primaryMs, chart: chartMs },
    coldLongTasks, idleFrameMs: idleFrame, scrollSteps, navigation,
    navigationWarm, selectorSwitch, interactionLongTasks,
  };
  await browser.close();
}

// ---------- WebKit: Safari layout truth + bottom dead space ----------
{
  const browser = await webkit.launch({ headless: true });
  const context = await browser.newContext(DEVICE);
  const page = await context.newPage();
  await page.goto(`${target}#today`, { waitUntil: 'domcontentloaded', timeout: 60_000 });
  await page.waitForSelector('.nav', { timeout: 30_000 });
  await page.waitForTimeout(6_000);
  const layout = await page.evaluate(() => {
    const nav = document.querySelector('.nav');
    const main = document.querySelector('.shell__main');
    const navRect = nav?.getBoundingClientRect() ?? null;
    const sections = [...(main?.children ?? [])];
    const lastContent = sections.at(-1)?.getBoundingClientRect() ?? null;
    return {
      innerHeight, docScrollHeight: document.body.scrollHeight,
      navTop: navRect?.top ?? null, navBottom: navRect?.bottom ?? null,
      lastContentBottom: lastContent?.bottom ?? null,
      mainBottomPadding: main ? getComputedStyle(main).paddingBottom : null,
      shellMinHeight: document.querySelector('.shell')
        ? getComputedStyle(document.querySelector('.shell')).minHeight : null,
      bodyMinHeight: getComputedStyle(document.body).minHeight,
      gapBelowContentToNav: navRect && lastContent
        ? Math.round(navRect.top - lastContent.bottom) : null,
    };
  });
  await page.screenshot({ path: path.join(shotDir, 'webkit-today-top.png') });
  await page.evaluate(() => window.scrollTo({ top: document.body.scrollHeight, behavior: 'instant' }));
  await page.waitForTimeout(800);
  await page.screenshot({ path: path.join(shotDir, 'webkit-today-bottom.png') });
  report.webkitLayout = layout;
  await browser.close();
}

fs.writeFileSync(outputPath, `${JSON.stringify(report, null, 2)}\n`);
console.log(JSON.stringify({ label,
  cold: report.chromiumThrottled.coldMs,
  idleFrameMs: report.chromiumThrottled.idleFrameMs,
  nav: report.chromiumThrottled.navigation,
  navWarm: report.chromiumThrottled.navigationWarm,
  scrollWorst: [...report.chromiumThrottled.scrollSteps].sort((a, b) => b.frameMs - a.frameMs)[0],
  selectorSwitch: report.chromiumThrottled.selectorSwitch,
  longTasks: report.chromiumThrottled.interactionLongTasks.totalMs,
  webkitGap: report.webkitLayout.gapBelowContentToNav,
}, null, 1));
