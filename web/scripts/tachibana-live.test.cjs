// v13.5.38 — TACHIBANA LIVE owner-facing indicator + Japanese live evidence.
//
// Proves: truthful status vocabulary, LIVE never shown without current
// accepted evidence, provenance required per row, no fabricated values,
// absent document renders UNAVAILABLE with a reason, glossary coverage, and
// the panel renders the surface from the evidence document only.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

require.extensions['.ts'] = (mod, filename) => {
  const output = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
    fileName: filename,
  }).outputText;
  mod._compile(output, filename);
};

const src = path.join(__dirname, '..', 'src');
const tl = require(path.join(src, 'domain', 'tachibanaLive.ts'));
const glossary = require(path.join(src, 'domain', 'glossary.ts'));

// 1) absent document: UNAVAILABLE with a reason; never LIVE.
const absent = tl.tachibanaLiveView(null);
assert.equal(absent.status, 'UNAVAILABLE');
assert.equal(absent.present, false);
assert.ok(absent.reasonJa.includes('未接続'));
assert.equal(absent.rows.length, 0);

// 2) LIVE requires current FRESH priced evidence — a connected-but-empty LIVE claim is demoted.
const emptyLive = tl.tachibanaLiveView({ provider: 'TACHIBANA', status: 'LIVE', symbols: {} });
assert.equal(emptyLive.status, 'UNAVAILABLE');

const doc = {
  provider: 'TACHIBANA', authority: 'SHADOW_NON_AUTHORITATIVE', status: 'LIVE',
  updatedAt: '2026-09-03T03:31:00+00:00', marketPhase: 'AFTERNOON_OPEN',
  symbols: {
    '9984': { provider: 'TACHIBANA', price: 9000, previousClose: 8900, changePct: 1.12,
      vwap: 8975.5, bestBid: 8999, bestAsk: 9001, bidQty: 300, askQty: 200,
      freshness: 'FRESH', sourceTimestamp: '2026-09-03T03:30:58+00:00', marketStatus: 'OPEN' },
    '8058': { provider: 'TACHIBANA', price: 3500, freshness: 'FRESH', changePct: null },
    '5803': { price: 1234, freshness: 'FRESH' },          // no provenance -> dropped
  },
};
const live = tl.tachibanaLiveView(doc);
assert.equal(live.status, 'LIVE');
assert.equal(live.statusJa, 'ライブ');
assert.deepEqual(live.rows.map((r) => r.symbol), ['8058', '9984']);
const row = live.rows.find((r) => r.symbol === '9984');
assert.equal(row.price, 9000);
assert.equal(row.vwap, 8975.5);
assert.equal(row.bestBid, 9001 - 2);
// 3) missing values stay null (rendered as '—'), never fabricated.
const partial = live.rows.find((r) => r.symbol === '8058');
assert.equal(partial.changePct, null);
assert.equal(tl.formatJpy(null), '—');
assert.equal(tl.formatPct(null), '—');
assert.equal(tl.formatPct(1.125), '+1.13%');

// 4) every status has a label and a glossary entry.
for (const status of ['LIVE', 'DEGRADED', 'STALE', 'UNAVAILABLE', 'AUTH_FAILED', 'MAINTENANCE', 'DISABLED']) {
  assert.ok(tl.TACHIBANA_STATUS_JA[status], `label for ${status}`);
  const key = glossary.TACHIBANA_STATUS_GLOSSARY[status];
  assert.ok(key && glossary.glossaryEntry(key), `glossary entry for ${status}`);
  const view = tl.tachibanaLiveView({ provider: 'TACHIBANA', status, symbols: {} });
  assert.equal(view.status, status === 'LIVE' ? 'UNAVAILABLE' : status);
}
// unknown status token never renders as LIVE
assert.equal(tl.tachibanaLiveView({ provider: 'TACHIBANA', status: 'WHATEVER' }).status, 'UNAVAILABLE');

// 5) the panel renders from the evidence document only and shows provenance.
const panel = fs.readFileSync(path.join(src, 'components', 'today', 'ArgusTodayPanel.tsx'), 'utf8');
assert.ok(panel.includes('data-argus-contract="tachibana-live-v1"'));
assert.ok(panel.includes('evidence.marketView?.japaneseLive'), 'panel must read the backend evidence document');
assert.ok(panel.includes('提供元 TACHIBANA'), 'rows must show provenance');
assert.ok(panel.includes('data-tachibana-status={tachibana.status}'));
assert.ok(!panel.includes("'LIVE'") || !/data-tachibana-status=['"]LIVE['"]/.test(panel), 'status never hard-coded');

// 6) v13.5.39 realtime overlay: a current FRESH Tachibana row replaces the JP
//    watchlist row as provider tachibana / LIVE; everything else is untouched.
const nowMs = Date.parse('2026-09-03T04:31:02+00:00');
const jpSnapshot = {
  status: 'delayed',
  stocks: [
    { symbol: '9984', name: 'ソフトバンクG', price: 8800, changeAbs: -100, changePct: -1.1,
      status: 'delayed', provider: 'jquants', source: 'jquants', sourceTimestamp: '2026-09-02',
      delayClass: 'T-1' },
    { symbol: '7203', name: 'トヨタ', price: 2900, status: 'delayed', provider: 'jquants',
      source: 'jquants', sourceTimestamp: '2026-09-02', delayClass: 'T-1' },
  ],
};
const liveDoc = {
  provider: 'TACHIBANA', status: 'LIVE',
  symbols: {
    '9984': { provider: 'TACHIBANA', price: 9000, changeAbs: 100, changePct: 1.12, volume: 1200000,
      vwap: 8975.5, bestBid: 8999, bestAsk: 9001, freshness: 'FRESH', marketStatus: 'OPEN',
      sourceTimestamp: '2026-09-03T04:30:58+00:00', receivedAt: '2026-09-03T04:31:00+00:00' },
  },
};
const overlaid = tl.overlayTachibanaLive(jpSnapshot, liveDoc, nowMs);
const sb = overlaid.stocks.find((r) => r.symbol === '9984');
assert.equal(sb.price, 9000);
assert.equal(sb.provider, 'tachibana');
assert.equal(sb.source, 'tachibana');
assert.equal(sb.status, 'live');
assert.equal(sb.quoteTruth.delayClass, 'LIVE');
assert.equal(sb.quoteTruth.provider, 'tachibana');
assert.equal(sb.tachibanaLive, true);
assert.equal(overlaid.tachibanaLiveCount, 1);
assert.equal(overlaid.status, 'mixed');
const toyota = overlaid.stocks.find((r) => r.symbol === '7203');
assert.equal(toyota.provider, 'jquants');            // untouched fallback, truthfully delayed
assert.equal(toyota.price, 2900);
// stale evidence never overlays (60 s proof window) and a non-LIVE doc never overlays
const staleDoc = { ...liveDoc, symbols: { '9984': { ...liveDoc.symbols['9984'], freshness: 'STALE' } } };
assert.equal(tl.overlayTachibanaLive(jpSnapshot, staleDoc, nowMs), jpSnapshot);
assert.equal(tl.overlayTachibanaLive(jpSnapshot, liveDoc, nowMs + 120_000), jpSnapshot);
assert.equal(tl.overlayTachibanaLive(jpSnapshot, { ...liveDoc, status: 'AUTH_FAILED' }, nowMs), jpSnapshot);
assert.equal(tl.overlayTachibanaLive(jpSnapshot, null, nowMs), jpSnapshot);
// the module store publishes/clears the document
tl.setTachibanaLiveDocument(liveDoc);
assert.equal(tl.getTachibanaLiveDocument().status, 'LIVE');
tl.setTachibanaLiveDocument({ provider: 'moomoo', status: 'LIVE' });
assert.equal(tl.getTachibanaLiveDocument(), null);
// the asset pipeline applies the overlay before prices/rows are derived
const intel = fs.readFileSync(path.join(src, 'hooks', 'useAssetIntel.ts'), 'utf8');
assert.ok(intel.includes('overlayTachibanaLive(peJpRaw.data'), 'useAssetIntel must overlay Tachibana LIVE onto JP quotes');
const hook = fs.readFileSync(path.join(src, 'hooks', 'useDecisionEvidence.ts'), 'utf8');
assert.ok(hook.includes('const japaneseLive = data.japaneseLive ?? view?.japaneseLive ?? null'),
  'decision evidence must read the document-level japaneseLive the backend publishes');
assert.ok(hook.includes('setTachibanaLiveDocument(japaneseLive)'), 'decision evidence must publish the live document');
assert.ok(hook.includes('{ ...marketView, japaneseLive }'), 'panel contract keeps marketView.japaneseLive');

console.log('tachibana-live.test: truthful status, provenance, no fabrication, realtime overlay, glossary ok');

// ── v13.5.40: owner-visible cutover ────────────────────────────────────────
// (a) the owner never sees the word "mock": an absent quote is 未取得.
const deskFormat = require(path.join(src, 'components', 'assetDesk', 'deskFormat.ts'));
const mockLabel = deskFormat.freshnessOf({ status: 'mock', date: null }, undefined);
assert.equal(mockLabel.text, '未取得');
assert.ok(!/mock/i.test(mockLabel.text));
const deskSource = fs.readFileSync(path.join(src, 'components', 'assetDesk', 'deskFormat.ts'), 'utf8');
assert.ok(!deskSource.includes("text: 'mock'"), 'deskFormat must not render the label "mock"');

// (b) JP realtime lamp + overall beacon follow Tachibana evidence.
const backendHealth = {
  asOf: '2026-09-03T05:00:00+09:00', overall: 'warning',
  lamps: [
    { key: 'bridge', labelJa: 'ブリッジ', status: 'ok', detailJa: '稼働中' },
    { key: 'jp_realtime', labelJa: 'JP realtime', status: 'warning', detailJa: 'moomoo日本株クオート権限なし' },
  ],
};
const liveHealth = tl.applyTachibanaHealthOverlay(backendHealth, liveDoc, nowMs);
const jpLamp = liveHealth.lamps.find((l) => l.key === 'jp_realtime');
assert.equal(jpLamp.status, 'ok');
assert.ok(jpLamp.detailJa.startsWith('LIVE — Tachibanaから更新中'), jpLamp.detailJa);
assert.ok(jpLamp.detailJa.includes('9984'));
assert.ok(!jpLamp.detailJa.includes('moomoo'));
assert.equal(liveHealth.overall, 'ok');                       // beacon recomputed from lamps
assert.equal(backendHealth.lamps[1].status, 'warning');       // input untouched
// auth failure is shown truthfully with the boundary code, never as LIVE
const authHealth = tl.applyTachibanaHealthOverlay(backendHealth,
  { provider: 'TACHIBANA', status: 'AUTH_FAILED', enabled: true, lastErrorClass: 'SECRET_MISSING',
    authBoundary: 'AUTH_SECRET_UNREADABLE', symbols: {} }, nowMs);
const authLamp = authHealth.lamps.find((l) => l.key === 'jp_realtime');
assert.equal(authLamp.status, 'warning');
assert.ok(authLamp.detailJa.includes('認証失敗') && authLamp.detailJa.includes('AUTH_SECRET_UNREADABLE'));
assert.equal(authHealth.overall, 'warning');
// a LIVE claim without current rows never turns the lamp green
const emptyHealth = tl.applyTachibanaHealthOverlay(backendHealth,
  { provider: 'TACHIBANA', status: 'LIVE', enabled: true, symbols: {} }, nowMs);
assert.notEqual(emptyHealth.lamps.find((l) => l.key === 'jp_realtime').status, 'ok');
// disabled / absent document: backend lamp is left exactly as published
assert.equal(tl.applyTachibanaHealthOverlay(backendHealth, null, nowMs), backendHealth);
assert.equal(tl.applyTachibanaHealthOverlay(backendHealth,
  { provider: 'TACHIBANA', status: 'DISABLED', enabled: false, symbols: {} }, nowMs), backendHealth);
// a stopped lamp elsewhere still dominates the beacon
const stoppedHealth = tl.applyTachibanaHealthOverlay(
  { ...backendHealth, lamps: [{ key: 'budget', labelJa: '予算', status: 'stopped', detailJa: '停止' }, backendHealth.lamps[1]] },
  liveDoc, nowMs);
assert.equal(stoppedHealth.overall, 'stopped');
// the store notifies subscribers so the beacon re-renders on new evidence
let notified = 0;
const unsubscribe = tl.subscribeTachibanaLive(() => { notified += 1; });
tl.setTachibanaLiveDocument(liveDoc);
unsubscribe();
tl.setTachibanaLiveDocument(null);
assert.equal(notified, 1);
const healthHook = fs.readFileSync(path.join(src, 'hooks', 'useSystemHealth.ts'), 'utf8');
assert.ok(healthHook.includes('applyTachibanaHealthOverlay(backendHealth, getTachibanaLiveDocument())'),
  'useSystemHealth must apply the Tachibana overlay for the logo beacon and popover');
console.log('tachibana-live.test: v13.5.40 owner-visible cutover (未取得 label, JP realtime lamp) ok');

// (c) Asset Detail board: the overlaid row carries VWAP/bid/ask and the desk forwards it.
const overlaidBoard = tl.overlayTachibanaLive(jpSnapshot, liveDoc, nowMs).stocks.find((r) => r.symbol === '9984');
assert.equal(overlaidBoard.tachibana.vwap, 8975.5);
assert.equal(overlaidBoard.tachibana.bestBid, 8999);
assert.equal(overlaidBoard.tachibana.askQty, null);   // absent in evidence → null, never fabricated
assert.equal(jpSnapshot.stocks.find((r) => r.symbol === '7203').tachibana, undefined);
const deskList = fs.readFileSync(path.join(src, 'components', 'assetDesk', 'AssetDeskList.tsx'), 'utf8');
assert.ok(deskList.includes('.tachibana ?? null'), 'desk list must forward the Tachibana board');
const details = fs.readFileSync(path.join(src, 'components', 'assetDesk', 'AssetDecisionDetails.tsx'), 'utf8');
assert.ok(details.includes('data-argus-contract="tachibana-board-v1"'), 'Asset Detail renders the board');
assert.ok(details.includes('売買権限なし'), 'board is reference only');
const strategy = require(path.join(src, 'lib', 'assetStrategy.ts'));
const asset = { symbol: '9984', market: 'JP', name: 'SBG' };
const withBoard = strategy.deriveStrategy(asset, undefined,
  { price: 9000, changePct: 1.12, volume: 1, date: '2026-09-03', status: 'live', tachibana: overlaidBoard.tachibana }, undefined, nowMs);
assert.ok(withBoard.dataLimitations[0].includes('立花ライブ証拠'), withBoard.dataLimitations[0]);
assert.ok(!withBoard.dataLimitations[0].startsWith('VWAP・資金フロー・板情報は未取得'));
const withoutBoard = strategy.deriveStrategy(asset, undefined,
  { price: 9000, changePct: 1.12, volume: 1, date: '2026-09-03', status: 'live' }, undefined, nowMs);
assert.ok(withoutBoard.dataLimitations[0].includes('未取得'));
console.log('tachibana-live.test: Asset Detail board (VWAP/板) from Tachibana evidence ok');

// ── v13.5.42: CLOSED session vocabulary, board baseline, chart current point ──
const closedDoc = {
  provider: 'TACHIBANA', status: 'CLOSED', enabled: true, lastAuthResult: 'PASS',
  updatedAt: '2026-09-03T07:35:00+00:00', marketPhase: 'CLOSED',
  symbols: {
    '5803': { provider: 'TACHIBANA', price: 12000, previousClose: 11900, changePct: 0.84, volume: 5000000,
      vwap: 11950.5, bestBid: 11990, bestAsk: 12010, bidQty: 100, askQty: 200,
      freshness: 'DELAYED', marketStatus: 'CLOSED', sourceTimestamp: '2026-09-03T06:30:00+00:00' },
  },
};
const closedView = tl.tachibanaLiveView(closedDoc);
assert.equal(closedView.status, 'CLOSED');
assert.equal(closedView.statusJa, '市場クローズ');
assert.ok(closedView.reasonJa.includes('接続確認済'));
assert.ok(glossary.GLOSSARY[closedView.glossaryKey], 'CLOSED needs a glossary entry');
// lamp: provider healthy + market closed → green, never UNAVAILABLE, never moomoo text
const closedHealth = tl.applyTachibanaHealthOverlay(backendHealth, closedDoc, nowMs);
const closedLamp = closedHealth.lamps.find((l) => l.key === 'jp_realtime');
assert.equal(closedLamp.status, 'ok');
assert.ok(closedLamp.detailJa.includes('市場クローズ') && closedLamp.detailJa.includes('5803'));
assert.ok(!closedLamp.detailJa.includes('moomoo'));
// CLOSED baseline never overlays price/provider (no false LIVE) but attaches the board
const jpClosedSnapshot = { status: 'delayed', stocks: [
  { symbol: '5803', price: 11800, status: 'delayed', provider: 'jquants', quoteTruth: { delayClass: 'DELAYED' } },
  { symbol: '7203', price: 2900, status: 'delayed', provider: 'jquants' } ] };
const closedOverlay = tl.overlayTachibanaLive(jpClosedSnapshot, closedDoc, nowMs);
const fujikura = closedOverlay.stocks.find((r) => r.symbol === '5803');
assert.equal(fujikura.price, 11800);                 // row price untouched
assert.equal(fujikura.provider, 'jquants');
assert.equal(fujikura.tachibana.vwap, 11950.5);
assert.equal(fujikura.tachibanaMarketStatus, 'CLOSED');
assert.equal(closedOverlay.tachibanaBoardCount, 1);
assert.equal(closedOverlay.tachibanaLiveCount, undefined);
assert.equal(closedOverlay.status, 'delayed');
assert.equal(closedOverlay.stocks.find((r) => r.symbol === '7203').tachibana, undefined);
// chart current point: LIVE when current, CLOSED for the baseline, null otherwise
const livePoint = tl.tachibanaCurrentPoint('9984', liveDoc, nowMs);
assert.equal(livePoint.state, 'LIVE'); assert.equal(livePoint.price, 9000); assert.equal(livePoint.source, 'TACHIBANA');
const closedPoint = tl.tachibanaCurrentPoint('5803', closedDoc, nowMs);
assert.equal(closedPoint.state, 'CLOSED'); assert.equal(closedPoint.price, 12000);
assert.equal(tl.tachibanaCurrentPoint('7203', closedDoc, nowMs), null);
assert.equal(tl.tachibanaCurrentPoint('5803', { ...closedDoc, status: 'AUTH_FAILED' }, nowMs), null);
const chartPanel = fs.readFileSync(path.join(src, "components", "chart", "ChartIntelligencePanel.tsx"), "utf8");
assert.ok(chartPanel.includes('data-argus-contract="chart-current-point-v1"'), 'chart renders the current point');
assert.ok(chartPanel.includes('現在値ソース: TACHIBANA'), 'chart names the current price source');
console.log('tachibana-live.test: v13.5.42 CLOSED vocabulary, board baseline, chart current point ok');
