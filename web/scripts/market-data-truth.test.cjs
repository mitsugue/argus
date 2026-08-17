const assert = require('node:assert/strict');
const fs = require('node:fs');

const read = (path) => fs.readFileSync(new URL(path, `file://${__filename}`), 'utf8');
const instruments = read('../src/domain/marketInstruments.ts');
const truth = read('../src/domain/liveQuote.ts');
const watchTruth = read('../src/domain/watchQuoteTruth.ts');
const jpHook = read('../src/hooks/useJapanWatchlist.ts');
const usHook = read('../src/hooks/useUSWatchlist.ts');
const today = read('../src/components/today/ArgusTodayPanel.tsx');
const desk = read('../src/components/assetDesk/AssetDecisionSummary.tsx');
const deskList = read('../src/components/assetDesk/AssetDeskList.tsx');

for (const label of [
  '1321 日経225 ETF',
  '1306 TOPIX ETF',
  'SPY S&P 500 ETF',
  'QQQ Nasdaq 100 ETF',
]) assert.match(instruments, new RegExp(label));

assert.match(instruments, /underlying: 'Nasdaq-100'/);
assert.doesNotMatch(instruments, /Nasdaq Composite/);
assert.match(truth, /'LIVE' \| '15m' \| '20m' \| 'EOD' \| 'T-1' \| 'UNKNOWN'/);
assert.match(truth, /transport heartbeat is not a market timestamp/);
assert.match(truth, /raw\.realtimeEvidence === true/);
assert.match(truth, /A LIVE label is a claim, not evidence/);
assert.match(truth, /ms > nowMs/);
assert.match(watchTruth, /snapshotDelay === 'LIVE'/);
assert.match(jpHook, /normalizeJapanWatchSnapshot\([\s\S]*s\.data/);
assert.match(usHook, /normalizeUSWatchSnapshot\([\s\S]*s\.data/);
assert.match(today, /LIVE QUOTE/);
assert.match(today, /ANALYSIS/);
assert.match(today, /quoteAsOf\(quote\)/);
assert.match(today, /quoteAge\(quote\)/);
assert.match(desk, /instrumentType/);
assert.match(desk, /delayClass/);
assert.match(desk, /quoteAsOf/);
assert.match(deskList, /provider: '投信総合ライブラリー'/);
assert.match(deskList, /delayClass: 'EOD'/);
assert.doesNotMatch(deskList, /date: f\.date, status: 'live'/);

console.log('market-data-truth.test: ok');
