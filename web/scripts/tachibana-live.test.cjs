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

console.log('tachibana-live.test: truthful status, provenance, no fabrication, glossary ok');
