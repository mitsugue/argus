#!/usr/bin/env node
'use strict';
// v13.5.29 — important-event constraint tiering (external review item C) and
// the degraded-feed kernel split (item F).
//
// Proves:
//   1. critical/high → WAIT_REQUIRED; medium/low/unknown → BLOCK_BUY only
//      (a medium statistics release must not carry FOMC's hard constraint,
//      and an UNCLASSIFIED event must not silently escalate);
//   2. the gate consumes the UNCAPPED imminent feed — event #9+ (beyond the
//      8-item display cap) still produces a constraint;
//   3. the strongest impact wins per symbol; non-imminent rows are ignored;
//   4. useAssetIntel wires the tier module and splits the discipline factor:
//      per-symbol authorities still data-gate, degraded auxiliary feeds only
//      BLOCK_BUY (the old one-stale-feed→every-symbol-WAIT lever is gone).

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

const tier = require(path.join(__dirname, '..', 'src', 'domain', 'importantEventsTier.ts'));

// 1. Tier mapping.
assert.equal(tier.eventKernelConstraint('critical'), 'WAIT_REQUIRED');
assert.equal(tier.eventKernelConstraint('high'), 'WAIT_REQUIRED');
assert.equal(tier.eventKernelConstraint('medium'), 'BLOCK_BUY');
assert.equal(tier.eventKernelConstraint('low'), 'BLOCK_BUY');
assert.equal(tier.eventKernelConstraint(null), 'BLOCK_BUY');
assert.equal(tier.eventKernelConstraint(undefined), 'BLOCK_BUY');
assert.equal(tier.eventKernelSeverity('critical'), 'HIGH');
assert.equal(tier.eventKernelSeverity('high'), 'MEDIUM');
assert.equal(tier.eventKernelSeverity('medium'), 'MEDIUM');

// 2. Uncapped imminent feed: 12 D-1 events (display would cap at 8) — the
// 12th still gates its linked symbol.
const imminent = Array.from({ length: 12 }, (_, index) => ({
  eventCode: `MACRO${index}`, countdown: 'D-1', displayImpact: 'high',
  linkedAssets: [`SYM${index}`], title: `event ${index}`,
}));
const gate = tier.imminentEventGate({ events: [], imminent });
assert.equal(gate.size, 12);
assert.equal(gate.get('SYM11').eventCode, 'MACRO11');

// 3. Strongest impact wins; non-imminent countdowns ignored; fallback to the
// capped display list when the backend has no imminent field yet.
const mixed = tier.imminentEventGate({
  events: [],
  imminent: [
    { eventCode: 'CPI', countdown: 'D-1', displayImpact: 'medium', linkedAssets: ['QQQ'], title: null },
    { eventCode: 'FOMC', countdown: 'D', displayImpact: 'critical', linkedAssets: ['QQQ'], title: null },
    { eventCode: 'PMI', countdown: 'D-3', displayImpact: 'critical', linkedAssets: ['SPY'], title: null },
  ],
});
assert.equal(mixed.get('QQQ').eventCode, 'FOMC');
assert.equal(mixed.get('QQQ').displayImpact, 'critical');
assert.equal(mixed.has('SPY'), false, 'D-3 must not gate');
const fallback = tier.imminentEventGate({
  events: [{ eventCode: 'NFP', countdown: 'D-1', displayImpact: 'high', linkedAssets: ['SPY'], title: 'NFP' }],
});
assert.equal(fallback.get('SPY').eventCode, 'NFP');
assert.equal(tier.imminentEventGate(null).size, 0);

// 4. Wiring + kernel split (structural, same style as the device-ledger
// contract test): the hook must consume the tier module, and the old
// composite lever (isPartial data-gating every symbol) must be gone.
const hook = fs.readFileSync(
  path.join(__dirname, '..', 'src', 'hooks', 'useAssetIntel.ts'), 'utf8');
assert.ok(hook.includes("from '../domain/importantEventsTier'"),
  'useAssetIntel must import the tier module');
assert.ok(hook.includes('imminentEventGate(impEvents)'),
  'the kernel event gate must come from the uncapped feed');
assert.ok(hook.includes('eventKernelConstraint(gateEntry.displayImpact)'),
  'the event constraint must be tiered by impact');
assert.ok(!hook.includes('missingQuote || sessionAuthorityMissing || isPartial || visLimited'),
  'the composite one-feed-stale→all-symbols-gated lever must be removed');
assert.ok(hook.includes("primitiveFactorId: 'discipline.degraded_auxiliary_feeds'"),
  'degraded auxiliary feeds must be a distinct primitive');
assert.ok(/degraded_auxiliary_feeds[^}]+BLOCK_BUY/s.test(hook),
  'degraded feeds must BLOCK_BUY (not data-gate)');

// MARKET VIEW strip (item A): display-only, explicitly no action authority.
const panel = fs.readFileSync(path.join(
  __dirname, '..', 'src', 'components', 'today', 'ArgusTodayPanel.tsx'), 'utf8');
assert.ok(panel.includes('sho-market-view-v1'), 'panel must render the market view');
assert.ok(panel.includes('actionAuthority !== false) return null'),
  'the strip must refuse a projection that claims authority');
const store = fs.readFileSync(path.join(
  __dirname, '..', 'src', 'hooks', 'useDecisionEvidence.ts'), 'utf8');
assert.ok(store.includes("view.actionAuthority === false ? view : null"),
  'the store must drop a market view that claims authority');

console.log('important-events-tier.test: ok (tiering, uncapped gate, kernel split, market view)');

// ── v13.5.29 NEWS/EVENT DIRECTIONAL IMPACT (structural contract) ──────────
// News may only BLOCK new buying, only after MARKET confirmation; the Today
// surface renders chart view / news view / action as three separate
// judgments with no summation anywhere.
assert.ok(hook.includes("primitiveFactorId: 'news.market_impact_confirmed'"),
  'news constraint must be its own primitive');
// v13.5.29: the gate itself lives in domain/newsSignalGate (per-subject
// relevance) and is proven EXECUTABLY by news-signal-gate.test.cjs — here we
// only pin the wiring and the BLOCK_BUY-only vocabulary.
assert.ok(hook.includes("newsKernelGate(newsEvents"),
  'the kernel must consume the per-subject news gate');
const newsBlock = hook.slice(hook.indexOf('const newsHit'),
  hook.indexOf("primitiveFactorId: 'news.market_impact_confirmed'") + 400);
assert.ok(newsBlock.includes("constraint: 'BLOCK_BUY'"),
  'news constrains new buying only');
assert.ok(!/newsHit[^]*?constraint:\s*'(EXIT_RISK|REDUCE_RISK|WAIT_REQUIRED)'/.test(newsBlock),
  'news can never SELL/EXIT/WAIT the decision');
const panel2 = fs.readFileSync(path.join(
  __dirname, '..', 'src', 'components', 'today', 'ArgusTodayPanel.tsx'), 'utf8');
assert.ok(panel2.includes('news-event-signal-v1'),
  'Today must render the independent news signal');
assert.ok(panel2.includes('チャート観とは独立'),
  'the strip must declare independence from the chart view');
assert.ok(panel2.includes('ニュースは売買権限を持たない'),
  'the strip must disclaim action authority');

console.log('important-events-tier.test: news directional impact contract ok');

// ── v13.5.29 — calendar OUTAGE must not data-gate every symbol ────────────
const unknownBlock = hook.slice(hook.indexOf('if (importantEventsUnknown) {'),
  hook.indexOf('} else if (gateEntry) {'));
assert.ok(unknownBlock.includes("constraint: 'BLOCK_BUY'")
  && unknownBlock.includes("status: 'ACTIVE'"),
  'calendar outage must BLOCK_BUY (availability failure), not data-gate');
// Owner directive: internal engine names never render on screen.
for (const file of ['../src/components/today/ArgusTodayPanel.tsx',
  '../src/lib/notifications.ts',
  '../src/components/dashboard/DownsideIncidentCard.tsx']) {
  const text = fs.readFileSync(path.join(__dirname, file), 'utf8');
  const visible = text.match(/['"`>][^'"`<\n]*(（SDA）|（SHO）|はSDA|SDAの|SDA正本|SHO証拠)[^'"`<\n]*['"`<]/);
  assert.ok(!visible, `internal jargon leaked to UI in ${file}: ${visible && visible[0]}`);
}
console.log('important-events-tier.test: v13.5.29 outage softening + jargon-free UI ok');
