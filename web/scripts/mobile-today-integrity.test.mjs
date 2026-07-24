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
const replay = read('src/components/marketReplay/MarketContextReplay.tsx');
const loaderCss = read('src/components/common/TriangleStepLoader.css');
const vite = read('vite.config.ts');

assert.deepEqual(
  navigation.PRIMARY_NAVIGATION.map((item) => item.mobileLabel),
  ['Today', 'Assets', 'Review', 'Market'],
);
assert.deepEqual(
  navigation.PRIMARY_NAVIGATION.map((item) => item.route),
  ['command', 'watchlist', 'core', 'regime'],
);
assert.equal(navigation.HASH_ROUTES['#today'], 'command');
assert.equal(navigation.HASH_ROUTES['#assets'], 'watchlist');
assert.equal(navigation.HASH_ROUTES['#positions'], 'core');
assert.equal(navigation.HASH_ROUTES['#market'], 'regime');
assert.deepEqual(navigation.SYSTEM_NAVIGATION.map((item) => item.route),
  ['quality', 'backup', 'guide']);
assert.equal(navigation.pageDirection('command', 'watchlist'), 1);
assert.equal(navigation.pageDirection('regime', 'core'), -1);
assert.equal(navigation.primaryRouteIndex('quality'), -1);

assert.match(nav, /PRIMARY_NAVIGATION\.map/);
assert.match(nav, /SYSTEM_NAVIGATION\.map/);
assert.doesNotMatch(nav, /onClick=\{onReviewLink\}[^]*Review<\/button>/);
assert.match(app, /window\.addEventListener\('popstate', onLocation\)/);
assert.match(app, /history\.pushState/);
assert.match(app, /PRIMARY_NAVIGATION/);
assert.match(app, /pageDirection=\{pageEnterDirection\}/);
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
assert.match(today, /move \?/);
assert.match(todayCss, /grid-template-columns:repeat\(4,minmax\(0,1fr\)\)/);

assert.match(hook, /isVerifiedMarketInstrument/);
assert.match(hook, /instrument:\s*symbol!\.toUpperCase\(\)/);
assert.match(hook, /scope:\s*'market'.*snapshot:\s*'verified'/s);
assert.match(hook, /requestSequence !== sequence\.current/);
assert.match(hook, /inflight\.get\(url\)/);
assert.match(replay, /MARKET_INSTRUMENTS\.map/);
assert.doesNotMatch(replay, /const INSTRUMENTS:/);

assert.match(today, /chartLoad\.loaderVisible/);
assert.match(today, /TriangleStepLoader compact/);
assert.match(today, /slowInitial[\s\S]*初回データを準備中/);
assert.match(today, /chartLoad\.retry/);
assert.match(hook, /225/);
assert.match(hook, /5_000/);
assert.doesNotMatch(loaderCss, /rotate\(/);
assert.match(loaderCss, /prefers-reduced-motion:reduce/);

assert.match(vite, /cleanupOutdatedCaches:\s*true/);
assert.match(vite, /clientsClaim:\s*true/);
assert.match(vite, /skipWaiting:\s*true/);
assert.match(vite, /snapshot:\s*'verified'|chart-intelligence/);
assert.doesNotMatch(command + today + hook, /method:\s*['"]POST['"]/);

console.log('mobile-today-integrity.test: ok (navigation, geometry, instruments, loader, PWA)');
