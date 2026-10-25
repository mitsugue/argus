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
const emptyLive = tl.tachibanaLiveView({ provider: 'TACHIBANA', status: 'LIVE', displayApproved: true, mode: 'DISPLAY', symbols: {} });
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

// Retired product controls must remain absent; numerical archive helpers below are retained.
const panel = fs.readFileSync(path.join(src, 'components', 'today', 'ArgusTodayPanel.tsx'), 'utf8');
assert.ok(!panel.includes('data-argus-contract="tachibana-live-v1"'));
assert.ok(!panel.includes('tachibanaLiveView('));
assert.ok(panel.includes('jp-market-engine-market-view-v1'), 'shared market view remains');

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
  provider: 'TACHIBANA', status: 'LIVE', displayApproved: true, mode: 'DISPLAY',
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
assert.ok(!intel.includes('overlayTachibanaLive'), 'retired live overlay must not replace delayed quotes');
assert.ok(intel.includes('useJapanWatchlist(jpSyms)'), 'shared delayed quote source remains');
const hook = fs.readFileSync(path.join(src, 'hooks', 'useDecisionEvidence.ts'), 'utf8');
assert.ok(hook.includes('const japaneseLive = data.japaneseLive ?? view?.japaneseLive ?? null'),
  'decision evidence must read the document-level japaneseLive the backend publishes');
assert.match(hook, /setTachibanaLiveDocument\(japaneseLive\s+\? \{ \.\.\.japaneseLive, readAt: data\.generatedAt \} : null\)/,
  'decision evidence must publish the same live document with its observation time');
assert.ok(hook.includes('{ ...marketView, japaneseLive }'), 'panel contract keeps marketView.japaneseLive');

console.log('tachibana-live.test: archived status and overlay helpers preserved; retired product controls absent');

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
assert.equal(jpLamp.detailJa, '立花 更新中');               // short word, no symbol list
assert.ok(!jpLamp.detailJa.includes('9984'));
assert.ok(!jpLamp.detailJa.includes('moomoo'));
assert.equal(liveHealth.overall, 'ok');                       // beacon recomputed from lamps
assert.equal(backendHealth.lamps[1].status, 'warning');       // input untouched
// auth failure is shown truthfully with the boundary code, never as LIVE
const authHealth = tl.applyTachibanaHealthOverlay(backendHealth,
  { provider: 'TACHIBANA', status: 'AUTH_FAILED', enabled: true, lastErrorClass: 'SECRET_MISSING',
    authBoundary: 'AUTH_SECRET_UNREADABLE', symbols: {} }, nowMs);
const authLamp = authHealth.lamps.find((l) => l.key === 'jp_realtime');
assert.equal(authLamp.status, 'warning');
assert.equal(authLamp.detailJa, '立花 認証失敗（AUTH_SECRET_UNREADABLE）');
assert.equal(authHealth.overall, 'warning');
// a LIVE claim without current rows never turns the lamp green
const emptyHealth = tl.applyTachibanaHealthOverlay(backendHealth,
  { provider: 'TACHIBANA', status: 'LIVE', displayApproved: true, mode: 'DISPLAY', enabled: true, symbols: {} }, nowMs);
assert.notEqual(emptyHealth.lamps.find((l) => l.key === 'jp_realtime').status, 'ok');
// DEGRADED: a thinly traded symbol may keep its previous-minute trade while connected.
// With at least one current row the lamp stays green; with none it waits (amber).
const degradedDoc = { ...liveDoc, status: 'DEGRADED', enabled: true };
const degradedLamp = tl.tachibanaJpRealtimeLamp(degradedDoc, nowMs);
assert.ok(tl.tachibanaCurrentRows(degradedDoc, nowMs).size > 0, 'fixture must carry a current row');
assert.deepEqual(degradedLamp, { status: 'ok', detailJa: '立花 更新中' });
const degradedEmptyLamp = tl.tachibanaJpRealtimeLamp({ ...degradedDoc, symbols: {} }, nowMs);
assert.deepEqual(degradedEmptyLamp, { status: 'warning', detailJa: '立花 更新待ち' });
assert.deepEqual(tl.tachibanaJpRealtimeLamp({ ...degradedDoc, symbols: staleDoc.symbols }, nowMs),
  { status: 'warning', detailJa: '立花 更新待ち' }, 'DEGRADED with only stale rows waits');
assert.deepEqual(tl.tachibanaJpRealtimeLamp({ ...liveDoc, status: 'STALE', enabled: true }, nowMs),
  { status: 'warning', detailJa: '立花 更新待ち' });
assert.deepEqual(tl.tachibanaJpRealtimeLamp({ ...liveDoc, status: 'MAINTENANCE', enabled: true, symbols: {} }, nowMs),
  { status: 'warning', detailJa: '立花 保守中' });
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
// 2026-10-25 (owner): the stock page has no separate data-status panel.
const details = fs.readFileSync(path.join(src, 'components', 'assetDesk', 'AssetDecisionCard.tsx'), 'utf8');
assert.ok(!details.includes('data-argus-contract="tachibana-board-v1"'), 'retired board must not render');
const strategy = require(path.join(src, 'lib', 'assetStrategy.ts'));
const asset = { symbol: '9984', market: 'JP', name: 'SBG' };
const withBoard = strategy.deriveStrategy(asset, undefined,
  { price: 9000, changePct: 1.12, volume: 1, date: '2026-09-03', status: 'live', tachibana: overlaidBoard.tachibana }, undefined, nowMs);
assert.ok(withBoard.dataLimitations[0].includes('立花ライブ証拠'), withBoard.dataLimitations[0]);
assert.ok(!withBoard.dataLimitations[0].startsWith('VWAP・資金フロー・板情報は未取得'));
const withoutBoard = strategy.deriveStrategy(asset, undefined,
  { price: 9000, changePct: 1.12, volume: 1, date: '2026-09-03', status: 'live' }, undefined, nowMs);
assert.ok(withoutBoard.dataLimitations[0].includes('未取得'));
console.log('tachibana-live.test: archived board calculation preserved; product board removed');

// ── v13.5.42: CLOSED session vocabulary, board baseline, chart current point ──
const closedDoc = {
  provider: 'TACHIBANA', status: 'CLOSED', displayApproved: true, mode: 'DISPLAY', enabled: true, lastAuthResult: 'PASS',
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
assert.equal(closedLamp.detailJa, '立花 閉場中');
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
assert.ok(!chartPanel.includes('data-argus-contract="chart-current-point-v1"'), 'retired live point must not render');
assert.ok(!chartPanel.includes('useTachibanaLiveDocument'), 'chart must not subscribe to retired live observations');
console.log('tachibana-live.test: archived CLOSED and current-point helpers preserved; live chart overlay removed');

assert.equal(tl.overlayTachibanaLive(jpSnapshot, { ...liveDoc, displayApproved: false }, nowMs), jpSnapshot);
assert.equal(tl.overlayTachibanaLive(jpSnapshot, { ...liveDoc, mode: 'SHADOW' }, nowMs), jpSnapshot);
assert.equal(tl.overlayTachibanaLive(jpSnapshot, liveDoc, nowMs + 16_000), jpSnapshot);

// Registered-stock PRICE display is separate from the unchanged 15s LIVE gate.
const quoteNow = Date.parse('2026-10-14T01:47:45Z');
const referenceDoc = {
  provider: 'TACHIBANA', enabled: true, displayApproved: true, mode: 'DISPLAY',
  shadowOnly: true, authoritative: false, status: 'STALE', providerHealth: 'AVAILABLE',
  cashSessionOpen: true, readAt: new Date(quoteNow).toISOString(),
  symbols: {'8058': {provider: 'TACHIBANA', price: 123.4, changePct: 2.3,
    sourceTimestamp: '2026-10-14T01:47:00Z', sourceTimestampPrecision: 'MINUTE',
    receivedAt: '2026-10-14T01:47:44Z', marketStatus: 'OPEN', freshness: 'DELAYED',
    realtimeClassification: 'CURRENT_MARKET_SNAPSHOT'}},
};
const copyReference = JSON.stringify(referenceDoc);
assert.equal(tl.tachibanaCurrentRows(referenceDoc,quoteNow).size,0);
assert.equal(tl.tachibanaPriceReferenceRows(referenceDoc,quoteNow).get('8058').price,123.4);
assert.equal(tl.tachibanaPriceReferenceRows(referenceDoc,quoteNow).get('8058').sourceTimestamp,'2026-10-14T01:47:00Z');
assert.equal(tl.tachibanaPriceTime(tl.tachibanaPriceReferenceRows(referenceDoc,quoteNow).get('8058')),'10:47');
assert.equal(JSON.stringify(referenceDoc),copyReference);
for (const changes of [{enabled:false},{displayApproved:false},{mode:'SHADOW'},{authoritative:true},
  {shadowOnly:false},{provider:'OTHER'}]) {
  assert.equal(tl.tachibanaPriceReferenceRows({...referenceDoc,...changes},quoteNow).size,0);
}
for (const changes of [{price:null},{price:NaN},{price:0},{marketStatus:'UNKNOWN'},
  {sourceTimestamp:null},{sourceTimestamp:'2026-10-14T01:48:00Z'},
  {sourceTimestamp:'2026-10-13T01:47:00Z'},{sourceTimestamp:'2026-10-14T01:47:00'},
  {sourceTimestamp:'2026-10-14T01:47:30Z'}, {receivedAt:null},
  {receivedAt:'2026-10-14T01:48:00Z'},{receivedAt:'2026-10-13T01:47:44Z'},
  {sourceTimestampPrecision:'UNKNOWN'},{realtimeClassification:'BEST_EFFORT_THINNED_REALTIME'}]) {
  const altered={...referenceDoc,symbols:{'8058':{...referenceDoc.symbols['8058'],...changes}}};
  assert.equal(tl.tachibanaPriceReferenceRows(altered,quoteNow).size,0,JSON.stringify(changes));
}
const closedReference={...referenceDoc,status:'CLOSED',cashSessionOpen:false,symbols:{'8058':{
  ...referenceDoc.symbols['8058'],marketStatus:'CLOSED',sourceTimestamp:null,sourceTimestampPrecision:'UNAVAILABLE',freshness:'UNAVAILABLE'}}};
assert.equal(tl.tachibanaCurrentRows(closedReference,quoteNow).size,0);
assert.equal(tl.tachibanaPriceReferenceRows(closedReference,quoteNow).get('8058').sourceTimestamp,null);
assert.equal(tl.tachibanaPriceTime(tl.tachibanaPriceReferenceRows(closedReference,quoteNow).get('8058')),'価格時刻不明');
assert.equal(tl.tachibanaQuoteReadInterval(referenceDoc,120_000),10_000);
for (const changes of [{enabled:false},{displayApproved:false},{cashSessionOpen:false},
  {mode:'SHADOW'},{status:'AUTH_FAILED'},{status:'MAINTENANCE'}]) {
  assert.equal(tl.tachibanaQuoteReadInterval({...referenceDoc,...changes},120_000),120_000);
}
const clockBeforeQuoteTest=Date.now;Date.now=()=>quoteNow;
try {
  tl.setTachibanaLiveDocument(null);tl.setTachibanaLiveDocument(referenceDoc);
  tl.setTachibanaLiveDocument({...referenceDoc,readAt:'2026-10-14T01:47:40Z',symbols:{}});
  assert.equal(tl.getTachibanaLiveDocument().symbols['8058'].price,123.4,'older analysis cannot replace current quote');
  tl.setTachibanaLiveDocument({...referenceDoc,quoteRequestedSymbols:['9984'],symbols:{'9984':{
    ...referenceDoc.symbols['8058'],price:234.5}}});
  assert.deepEqual(Object.keys(tl.getTachibanaLiveDocument().symbols).sort(),['8058','9984']);
  tl.setTachibanaLiveDocument({...referenceDoc,quoteRequestedSymbols:['8058'],symbols:{}});
  assert.deepEqual(Object.keys(tl.getTachibanaLiveDocument().symbols),['9984'],'missing requested row is not filled with another source');
  tl.setTachibanaLiveDocument({...referenceDoc,status:'AUTH_FAILED',providerHealth:'UNAVAILABLE',symbols:{}});
  const savedQuoteDoc=tl.getTachibanaLiveDocument();
  assert.equal(savedQuoteDoc.priceRecordsRetained,true);
  assert.equal(tl.tachibanaCurrentRows(savedQuoteDoc,quoteNow).size,0);
  assert.equal(tl.tachibanaPriceReferenceRows(savedQuoteDoc,quoteNow).get('9984').receivedAt,'2026-10-14T01:47:44Z');
  tl.setTachibanaLiveDocument(null);
  assert.equal(tl.getTachibanaLiveDocument(),null);

  // Render the actual card: minute quotes do not fall back to yesterday and
  // neither reference prices nor closed snapshots receive a false LIVE badge.
  const esbuild=require('esbuild');const Module=require('node:module');
  const entry=`import React from 'react';import {renderToStaticMarkup} from 'react-dom/server';
    import {AssetDecisionSummary} from ${JSON.stringify(path.join(src,'components/assetDesk/AssetDecisionSummary.tsx'))};
    import {setTachibanaLiveDocument} from ${JSON.stringify(path.join(src,'domain/tachibanaLive.ts'))};
    export function render(doc,d){setTachibanaLiveDocument(null);setTachibanaLiveDocument(doc);
      return renderToStaticMarkup(React.createElement(AssetDecisionSummary,{d,open:false,onToggle:()=>{}}));}`;
  const builtQuoteCard=esbuild.buildSync({stdin:{contents:entry,resolveDir:path.join(__dirname,'..'),loader:'tsx'},
    bundle:true,write:false,platform:'node',format:'cjs',external:['react','react-dom/server'],
    define:{'import.meta.env':'{}'},logLevel:'silent'}).outputFiles[0].text;
  const quoteCardModule=new Module(path.join(__dirname,'synthetic-quote-card.cjs'),module);
  quoteCardModule.filename=path.join(__dirname,'synthetic-quote-card.cjs');
  quoteCardModule.paths=module.paths;quoteCardModule._compile(builtQuoteCard,quoteCardModule.filename);
  const cardData={genre:'jp',asset:{market:'JP'},strat:{status:'delayed',price:100},decisionFirst:{
    held:false,symbol:'8058',name:'合成検査銘柄',priceText:'100円',changePct:-1,dataStatus:'前日'}};
  const renderedQuote=quoteCardModule.exports.render(referenceDoc,cardData);
  // 2026-10-25 (owner): two-line row. A real-time price shows its time beside
  // the change (data-quote="LIVE"); a received price that is not current says
  // 参考価格 / 引け後 / 受信停止 with its time. Never a false LIVE.
  assert.match(renderedQuote,/123\.4円/);assert.match(renderedQuote,/参考価格 10:47/);
  assert.doesNotMatch(renderedQuote,/分精度|立花証券|受信 10:47:44/);
  assert.doesNotMatch(renderedQuote,/data-quote="LIVE"|100円/);
  const freshPoint=Date.parse('2026-10-14T01:47:10Z');
  const freshReference={...referenceDoc,status:'LIVE',readAt:new Date(freshPoint).toISOString(),symbols:{'8058':{
    ...referenceDoc.symbols['8058'],freshness:'FRESH',receivedAt:'2026-10-14T01:47:09Z'}}};
  Date.now=()=>freshPoint;
  assert.match(quoteCardModule.exports.render(freshReference,cardData),/data-quote="LIVE"/);
  // 2026-10-22: a minute time stays current within its minute + 15 s while
  // the receipt is within 15 s; the shown time stays the stated minute.
  Date.now=()=>Date.parse('2026-10-14T01:47:24Z');
  assert.match(quoteCardModule.exports.render(freshReference,cardData),/data-quote="LIVE"/);
  Date.now=()=>Date.parse('2026-10-14T01:47:24.001Z');   // receipt 15.001 s old
  const afterExpiry=quoteCardModule.exports.render(freshReference,cardData);
  assert.match(afterExpiry,/123\.4円/);assert.doesNotMatch(afterExpiry,/data-quote="LIVE"|100円/);
  assert.match(afterExpiry,/10:47/);assert.doesNotMatch(afterExpiry,/分精度/);
  const lateReceipt={...freshReference,symbols:{'8058':{...freshReference.symbols['8058'],receivedAt:'2026-10-14T01:48:14Z'}}};
  Date.now=()=>Date.parse('2026-10-14T01:48:15Z');       // 75 s from the minute start
  assert.match(quoteCardModule.exports.render(lateReceipt,cardData),/data-quote="LIVE"/);
  Date.now=()=>Date.parse('2026-10-14T01:48:15.001Z');   // past the minute + 15 s
  assert.doesNotMatch(quoteCardModule.exports.render(lateReceipt,cardData),/data-quote="LIVE"/);
  Date.now=()=>quoteNow;
  const renderedClosed=quoteCardModule.exports.render(closedReference,cardData);
  assert.match(renderedClosed,/引け後|受信停止/);assert.match(renderedClosed,/価格時刻不明/);
  assert.doesNotMatch(renderedClosed,/data-quote="LIVE"/);
  assert.equal(cardData.strat.price,100,'reference display cannot alter analysis basis');
} finally { Date.now=clockBeforeQuoteTest;tl.setTachibanaLiveDocument(null); }
// Shared admission (same as the server's row_trade_current, 2026-10-22).
{
  const start='2026-10-22T06:00:00Z', t=(sec)=>Date.parse(start)+sec*1000, iso=(sec)=>new Date(t(sec)).toISOString();
  const cur=tl.tachibanaTradeTimeCurrent;
  assert.equal(cur(start,'MINUTE',iso(25),t(26)),true,'minute 26 s');
  assert.equal(cur(start,'MINUTE',iso(79),t(80)),false,'minute 80 s');
  assert.equal(cur(start,'MINUTE',iso(75),t(75)),true,'minute end + 15 s');
  assert.equal(cur(start,'SECOND',iso(15),t(16)),false,'second 16 s');
  assert.equal(cur(start,'SECOND',iso(15),t(15)),true,'second 15 s');
  assert.equal(cur(start,null,iso(15),t(16)),false,'unstated precision keeps 15 s');
  assert.equal(cur(start,'MINUTE',iso(10),t(30)),false,'receipt 20 s');
  assert.equal(cur(iso(60),'MINUTE',iso(25),t(26)),false,'future minute');
  assert.equal(cur(iso(10),'MINUTE',iso(25),t(26)),false,'unaligned minute');
  assert.equal(cur(null,'UNAVAILABLE',iso(25),t(26)),false,'no trade time');
  const doc={provider:'TACHIBANA',enabled:true,displayApproved:true,mode:'DISPLAY',shadowOnly:true,
    authoritative:false,status:'LIVE',providerHealth:'AVAILABLE',symbols:{'8058':{provider:'TACHIBANA',price:1,
    sourceTimestamp:start,sourceTimestampPrecision:'MINUTE',receivedAt:iso(25),freshness:'FRESH',marketStatus:'OPEN'}}};
  assert.equal(tl.tachibanaCurrentRows(doc,t(26)).size,1);
  assert.equal(tl.tachibanaCurrentRows({...doc,symbols:{'8058':{...doc.symbols['8058'],marketStatus:'CLOSED'}}},t(26)).size,0);
  assert.equal(tl.tachibanaCurrentRows({...doc,symbols:{'8058':{...doc.symbols['8058'],receivedAt:iso(79)}}},t(80)).size,0);
}
console.log('tachibana price reference: actual card, scope merge, chronology, closed/missing/future/precision and unchanged LIVE boundary pass');

// 2026-10-22: the Today Nikkei value uses the same minute-aware rule as the server.
{
  const esbuild=require('esbuild');const Module=require('node:module');
  const entry=`export {nikkeiLiveCurrent} from ${JSON.stringify(path.join(src,'hooks/useJapanMarketComparison.ts'))};`;
  const built=esbuild.buildSync({stdin:{contents:entry,resolveDir:path.join(__dirname,'..'),loader:'ts'},
    bundle:true,write:false,platform:'node',format:'cjs',external:['react','react-dom'],
    define:{'import.meta.env':'{}'},logLevel:'silent'}).outputFiles[0].text;
  const mod=new Module(path.join(__dirname,'synthetic-nikkei-live.cjs'),module);
  mod.filename=path.join(__dirname,'synthetic-nikkei-live.cjs');mod.paths=module.paths;mod._compile(built,mod.filename);
  const {nikkeiLiveCurrent}=mod.exports;
  const start=Date.parse('2026-10-22T06:00:00Z'), iso=(sec)=>new Date(start+sec*1000).toISOString();
  const q=(extra)=>({price:49000,previousClose:48900,changePct:.2,tradedAt:iso(0),tradedAtPrecision:'MINUTE',
    receivedAt:iso(25),delaySeconds:26,sessionOpen:true,realtime:true,...extra});
  assert.equal(nikkeiLiveCurrent(q(),start+26_000),true,'Nikkei minute 26 s');
  assert.equal(nikkeiLiveCurrent(q({receivedAt:iso(79)}),start+80_000),false,'Nikkei minute 80 s');
  assert.equal(nikkeiLiveCurrent(q({tradedAtPrecision:'SECOND',receivedAt:iso(15)}),start+16_000),false,'Nikkei second 16 s');
  assert.equal(nikkeiLiveCurrent(q({tradedAtPrecision:undefined,receivedAt:iso(15)}),start+16_000),false,'older payload keeps 15 s');
  assert.equal(nikkeiLiveCurrent(q({receivedAt:iso(10)}),start+30_000),false,'Nikkei receipt 20 s');
  assert.equal(nikkeiLiveCurrent(q({tradedAt:iso(60)}),start+26_000),false,'Nikkei future minute');
  assert.equal(nikkeiLiveCurrent(q({realtime:false,receivedAt:undefined}),start+600_000),true,'delayed source unchanged');
  console.log('tachibana Nikkei minute-precision admission PASS');
}
