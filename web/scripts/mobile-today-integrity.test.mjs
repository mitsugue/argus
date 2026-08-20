import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import ts from 'typescript';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const read = (file) => fs.readFileSync(path.join(root, file), 'utf8');

async function importTypeScriptModule(relativePath) {
  const output = ts.transpileModule(read(relativePath), {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
    fileName: relativePath,
  }).outputText;
  return import(`data:text/javascript;base64,${Buffer.from(output).toString('base64')}`);
}

const navigation = await importTypeScriptModule('src/navigation.ts');
const instruments = await importTypeScriptModule('src/domain/marketInstruments.ts');
const app = read('src/App.tsx');
const shell = read('src/components/AppShell.tsx');
const nav = read('src/components/NavRail.tsx');
const navCss = read('src/components/NavRail.css');
const shellCss = read('src/components/AppShell.css');
const stickyCss = read('src/components/dashboard/MobileStickyCommand.css');
const command = read('src/routes/CommandCenter.tsx');
const today = read('src/components/today/ArgusTodayPanel.tsx');
const todayCss = read('src/components/today/ArgusToday.css');
const hook = read('src/hooks/useChartIntelligence.ts');
const loaderCss = read('src/components/common/TriangleStepLoader.css');
const acceptance = read('scripts/mobile-today-acceptance.mjs');
const vite = read('vite.config.ts');
const indexHtml = read('index.html');

assert.deepEqual(
  navigation.PRIMARY_NAVIGATION.map((item) => item.mobileLabel),
  ['Today', 'Holdings', 'Alerts', 'Settings'],
);
assert.deepEqual(
  navigation.PRIMARY_NAVIGATION.map((item) => item.route),
  ['command', 'watchlist', 'notifications', 'settings'],
);
assert.equal(navigation.HASH_ROUTES['#today'], 'command');
assert.equal(navigation.HASH_ROUTES['#notifications'], 'notifications');
assert.equal(navigation.HASH_ROUTES['#settings'], 'settings');
for (const retired of ['#assets', '#positions', '#quality', '#backup', '#guide',
  '#review', '#market']) assert.equal(navigation.parseLocationHash(retired), undefined);
assert.equal(navigation.pageDirection('command', 'watchlist'), 1);
assert.equal(navigation.pageDirection('settings', 'notifications'), -1);
assert.equal(navigation.primaryRouteIndex('settings'), 3);

assert.match(nav, /PRIMARY_NAVIGATION\.map/);
assert.doesNotMatch(nav, /SYSTEM_NAVIGATION/);
assert.doesNotMatch(nav, /onClick=\{onReviewLink\}[^]*Review<\/button>/);
assert.match(app, /window\.addEventListener\('popstate', onLocation\)/);
assert.match(app, /history\.pushState/);
assert.match(app, /PRIMARY_NAVIGATION/);
assert.match(app, /pageDirection=\{pageEnterDirection\}/);
assert.match(app, /MAX_MOBILE_SAFE_BOTTOM_PX\s*=\s*34/);
assert.match(app, /padding-bottom:env\(safe-area-inset-bottom,0px\)/);
assert.match(app,
  /Math\.min\(MAX_MOBILE_SAFE_BOTTOM_PX, Math\.max\(0, measured\)\)/);
assert.match(app,
  /style\.setProperty\('--argus-safe-bottom', `\$\{bounded\}px`\)/);
assert.match(app, /window\.addEventListener\('pageshow', refresh\)/);
assert.match(app, /window\.visualViewport\?\.addEventListener\('resize', refresh\)/);
assert.match(shell, /setAnimDir\(pageDirection\)/);

assert.match(navCss, /--argus-safe-bottom:\s*clamp\(0px,\s*env\(safe-area-inset-bottom,\s*0px\),\s*34px\)/);
assert.match(navCss, /--argus-mobile-nav-height/);
assert.match(navCss, /height:\s*var\(--argus-mobile-nav-height\)/);
assert.match(navCss, /padding:\s*0 4px var\(--argus-safe-bottom\)/);
assert.match(stickyCss, /bottom:\s*var\(--argus-mobile-nav-height\)/);
assert.match(shellCss, /padding-bottom:\s*var\(--argus-mobile-nav-height\)/);
assert.match(stickyCss, /height:\s*var\(--argus-mobile-sticky-height\)/);
for (const width of [390, 430]) {
  const viewportBottom = width === 390 ? 844 : 932;
  const safeBottom = 34;
  const navHeight = 58 + safeBottom;
  const navRect = { top: viewportBottom - navHeight, bottom: viewportBottom };
  const stickyRect = { bottom: navRect.top, top: navRect.top - 34 };
  assert.equal(navRect.bottom, viewportBottom);
  assert.equal(stickyRect.bottom, navRect.top);
  assert.ok(navHeight - safeBottom >= 44);
}

assert.deepEqual(instruments.MARKET_INSTRUMENTS.map((item) => item.symbol),
  ['1321', '1306', 'SPY', 'QQQ']);
for (const symbol of ['1321', '1306', 'SPY', 'QQQ']) {
  assert.equal(instruments.isVerifiedMarketInstrument(symbol, 'daily'), true);
}
assert.equal(instruments.isVerifiedMarketInstrument('1321', 'weekly'), false);
assert.equal(instruments.normalizeMarketInstrument('JP', 'bad'), '1321');
assert.equal(instruments.normalizeMarketInstrument('US', 'bad'), 'SPY');
assert.match(command, /MARKET_INSTRUMENTS\.map/);
assert.match(command, /horizon:\s*chartHorizon/);
assert.match(today, /instruments\.map/);
// v13.5.1: the four instruments are lightweight NAME selectors; the one
// selected projection chart below carries all data and probabilities.
assert.match(today, /at-index-strip--selectors/);
assert.doesNotMatch(today, /HeadlineMiniChart|at-headline-probs/);
assert.match(today, /data-projection-source/);
assert.match(todayCss, /grid-template-columns:repeat\(4,minmax\(0,1fr\)\)/);

assert.match(hook, /isVerifiedMarketInstrument/);
assert.match(hook, /instrument:\s*symbol!\.toUpperCase\(\)/);
assert.match(hook, /scope:\s*'market'.*snapshot:\s*'verified'/s);
assert.match(hook, /requestSequence !== sequence\.current/);
assert.match(hook, /inflight\.get\(url\)/);
assert.doesNotMatch(app + command + today, /MarketRegime|MarketContextReplay|#market/);

assert.match(today, /chartLoad\.loaderVisible/);
assert.match(today, /TriangleStepLoader compact/);
assert.match(today, /slowInitial[\s\S]*初回データを準備中/);
assert.match(today, /chartLoad\.retry/);
assert.match(hook, /225/);
assert.match(hook, /5_000/);
assert.doesNotMatch(loaderCss, /rotate\(/);
assert.match(loaderCss, /prefers-reduced-motion:reduce/);
assert.match(acceptance, /controlled warm revalidation did not start/);
assert.match(acceptance, /selectCanonicalControls\(warmPage\)/);
assert.match(acceptance, /selectCanonicalControls\(rateLimitPage\)/);
assert.match(acceptance, /ERR_INTERNET_DISCONNECTED/,
  'the deliberate offline reload must be classified separately from unexpected console failures');
// v13.5.0: only the selected instrument revalidates its heavy snapshot on
// reload; the four headline charts come from the compact bootstrap, so the
// controlled-429 reload budget is exactly one bounded request.
assert.match(acceptance, /expectedCalls: 1/);
assert.match(acceptance, /headline-first-decision-visibility/,
  'the headline-first regression gate must exist in the acceptance engine');
assert.match(acceptance, /hostileSafeAreaBottom/,
  'mobile geometry must reject an oversized runtime safe-area value');
assert.match(acceptance, /fulfillCapturedSnapshot\(route, evidence, 4_000\)/,
  'cold loader acceptance must keep the delayed request active after shell readiness');
assert.ok(acceptance.indexOf('const coldLoaderAppeared')
  < acceptance.indexOf('await coldPage.goto(TODAY_URL'),
  'cold loader observer must be armed before navigation triggers the delayed request');
assert.match(acceptance,
  /waitForShell\(coldPage\);[\s\S]*openCanonicalEvidence\(coldPage\);[\s\S]*coldLoaderAppeared/,
  'mobile cold-state assertions must make the collapsed evidence region visible');
assert.match(acceptance,
  /state: 'attached'[\s\S]*selectCanonical1321FiveDay\(page\)/,
  'mobile acceptance must open the disclosure through selection before requiring visible controls');
assert.match(acceptance, /warmRequestStart/);
assert.match(acceptance, /const warm = await browser\.newContext\(\{[\s\S]*serviceWorkers: 'block'/);
assert.match(acceptance, /warmSeedSnapshotId/);
assert.match(acceptance, /await warm\.unroute/);
assert.match(acceptance, /data-projection-revalidation-state'\) === 'background'/);
assert.match(acceptance, /validateCanonicalWarmRevalidationTransition/);
assert.match(acceptance, /warmResponseRelease/);
const warmBlock = acceptance.slice(
  acceptance.indexOf('// Warm cache is the immediate visible authority'),
  acceptance.indexOf('const before304'),
);
assert.doesNotMatch(warmBlock, /waitForTimeout|warmLoader|warmSkeleton/,
  'warm acceptance must use semantic state without sleeps or visual-loader authority');
assert.match(acceptance, /\['Today', '#today'\], \['Holdings', '#holdings'\]/);
assert.match(acceptance, /\['Alerts', '#notifications'\], \['Settings', '#settings'\]/);
assert.doesNotMatch(acceptance, /nav__mobile-system|\['Assets', '#assets'\]|\['Review', '#positions'\]/);

assert.match(vite, /cleanupOutdatedCaches:\s*true/);
assert.match(vite, /clientsClaim:\s*true/);
assert.match(vite, /skipWaiting:\s*true/);
assert.match(vite, /snapshot:\s*'verified'|chart-intelligence/);
assert.doesNotMatch(command + today + hook, /method:\s*['"]POST['"]/);
assert.doesNotMatch(indexHtml, /fonts\.(?:googleapis|gstatic)\.com/,
  'the production shell must not depend on an external font request');

console.log('mobile-today-integrity.test: ok (navigation, geometry, instruments, loader, PWA)');
