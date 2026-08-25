#!/usr/bin/env node
'use strict';
// v13.5.36 — the exact NewsEvent → constraint → riskKernel → SDA trace the
// external review demanded (BLOCKER 5), plus the per-target relevance rules
// (BLOCKER 2): an energy-only bearish headline must not block buying an
// index ETF; PENDING or STALE headlines never gate the kernel at all.

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
const { webcrypto } = require('node:crypto');

require.extensions['.ts'] = (mod, filename) => {
  const output = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
    fileName: filename,
  }).outputText;
  mod._compile(output, filename);
};
if (!globalThis.crypto) globalThis.crypto = webcrypto;

const gate = require(path.join(__dirname, '..', 'src', 'domain', 'newsSignalGate.ts'));
const authority = require(path.join(__dirname, '..', 'src', 'domain', 'singleDecisionAuthority.ts'));

const newsEvent = (over = {}) => ({
  eventId: 'ev-rates-1', severity: 'HIGH', staleness: 'FRESH_UPDATE',
  confirmationState: 'MARKET_CONFIRMED',
  impactDirection: {
    schemaVersion: 'news-impact-direction-v1', polarity: 'up',
    directionByTarget: {
      broadMarket: 'BEARISH', japanEquities: 'BEARISH', growth: 'BEARISH',
      semiconductors: 'BEARISH', banks: 'BULLISH', exporters: 'MIXED',
      energy: 'UNCLEAR',
    },
    primaryDirection: 'BEARISH', timeHorizon: '1D-5D',
    transmissionChain: [], confidence: 'MEDIUM', directionAuthority: false,
  },
  ...over,
});

// ── BLOCKER 2: per-target relevance ──────────────────────────────────────
const subject = { symbol: '1321', market: 'JP', theme: 'index_core' };
assert.ok(gate.newsKernelGate([newsEvent()], subject),
  'broadMarket bearish must gate a JP index subject');
const energyOnly = newsEvent({
  impactDirection: { ...newsEvent().impactDirection,
    directionByTarget: { broadMarket: 'BULLISH', japanEquities: 'BULLISH',
      growth: 'BULLISH', semiconductors: 'UNCLEAR', banks: 'BULLISH',
      exporters: 'MIXED', energy: 'BEARISH' } },
});
assert.equal(gate.newsKernelGate([energyOnly], subject), null,
  'energy-only bearish must NOT gate an index subject (ceasefire example)');
assert.ok(gate.newsKernelGate([energyOnly],
  { symbol: '8031', market: 'JP', theme: 'trading_commodity' }),
  'energy bearish gates an energy/trading-theme subject');
const semiOnly = newsEvent({
  impactDirection: { ...newsEvent().impactDirection,
    directionByTarget: { broadMarket: 'MIXED', japanEquities: 'MIXED',
      growth: 'UNCLEAR', semiconductors: 'BEARISH', banks: 'UNCLEAR',
      exporters: 'UNCLEAR', energy: 'UNCLEAR' } },
});
assert.ok(gate.newsKernelGate([semiOnly],
  { symbol: '6146', market: 'JP', theme: 'semiconductor_photonics' }),
  'semiconductor bearish gates a semiconductor subject');
assert.equal(gate.newsKernelGate([semiOnly], subject), null,
  'semiconductor bearish must not gate an index subject');

// PENDING / STALE / INFO never gate.
assert.equal(gate.newsKernelGate(
  [newsEvent({ confirmationState: 'MARKET_CONFIRMATION_PENDING' })], subject), null,
  'PENDING must never gate the kernel');
assert.equal(gate.newsKernelGate(
  [newsEvent({ staleness: 'STALE' })], subject), null,
  'STALE must never gate the kernel');
assert.equal(gate.newsKernelGate(
  [newsEvent({ severity: 'WATCH' })], subject), null,
  'below-HIGH must never gate the kernel');
assert.equal(gate.newsKernelGate([newsEvent()],
  { symbol: 'BTC', market: 'CRYPTO', theme: 'crypto' }), null,
  'non-equity subjects are out of scope');

// ── BLOCKER 5: the full trace to a final SDA action ─────────────────────
// NewsEvent → gate → contribution literal → buildRiskKernel →
// evaluateSingleDecisionAuthority → BLOCK_BUY constraint on the action.
// The trace runs through VERIFIED canonical references (the resolver fixture
// from the canonical-decision-evidence contract) so the decision actually
// leaves DATA_GATED and the news constraint acts on a REAL evaluated action.
const resolver = require(path.join(
  __dirname, '..', 'src', 'domain', 'canonicalDecisionEvidence.ts'));
const NOW_MS = Date.parse('2026-08-22T05:00:10Z');
const CUTOFF = '2026-08-22T05:00:00Z';
const entry = {
  subject: { kind: 'ASSET', instrumentId: '1321', market: 'JP', horizon: 'FIVE_DAY' },
  informationCutoffAt: CUTOFF,
  marketTruth: {
    status: 'AVAILABLE', schemaVersion: 'argus-market-truth-decision-snapshot-v2',
    snapshotId: 'mts-' + 'a'.repeat(32), observationId: 'obs-' + 'b'.repeat(32),
    observedAt: '2026-08-22T04:59:30Z', knownAt: '2026-08-22T04:59:40Z',
    policyId: 'repo-market-provider-priority-v1',
    policySha256: 'c848e2537828a74ecb0914d374d5755ac5b79a3e99e4791b496e514ee8103bf3',
  },
  predictionLedger: {
    status: 'AVAILABLE', schemaVersion: 'argus-prediction-ledger-v2',
    contextId: 'pd-' + 'c'.repeat(32), mode: 'FORWARD_LIVE', asOf: CUTOFF,
    policyId: 'argus-calibration-three-class-v1',
    policySha256: '62ab147263dfb674301c0dc6585df4c1ffda02cb07380b3d9f94a870ec056379',
  },
  sho: {
    status: 'AVAILABLE', schemaVersion: 'argus-sho-reversal-v1',
    artifactId: 'sho-reversal-' + 'd'.repeat(32), asOf: CUTOFF,
    policyId: 'sho-jp-canonical-2026.08-round2-v1',
    policySha256: '0ddae6123f70dd858d5135528768fa9b6cea561f31f47201b8e882c978cbf532',
    state: 'MIXED', validationStatus: 'UNVALIDATED',
    primitiveFactorIds: [], targets: [], invalidation: null,
  },
  quality: { status: 'COMPLETE', freshness: 'FRESH',
    missingReasonCodes: [], conflictReasonCodes: [] },
};
const resolved = resolver.resolveCanonicalArtifactReferences(entry, NOW_MS);
assert.ok(resolved, 'fixture references must resolve');
const hit = gate.newsKernelGate([newsEvent()], subject);
const contribution = {
  evidenceRef: `news:impact-${hit.matchedTarget.toLowerCase()}-${hit.eventId}`,
  primitiveFactorId: 'news.market_impact_confirmed', sourceKind: 'EVENT',
  constraint: 'BLOCK_BUY', status: 'ACTIVE',
  severity: hit.severity === 'CRITICAL' ? 'HIGH' : 'MEDIUM',
  confidenceCapBps: 5500, observedAt: CUTOFF,
};
const buildInput = (withNews) => {
  const input = authority.buildDataGatedInputV2({
    subject: { kind: 'ASSET', instrumentId: '1321', market: 'JP', horizon: 'FIVE_DAY' },
    decisionAt: '2026-08-22T05:00:10Z',
    informationCutoffAt: resolved.informationCutoffAt,
    authorityPolicy: authority.SINGLE_DECISION_AUTHORITY_V2_POLICY,
    ownerContext: {
      schemaVersion: 'owner-decision-context-v1', privacyClass: 'DEVICE_LOCAL',
      asOf: resolved.informationCutoffAt, positionState: 'HELD',
      positionRiskBand: 'LOW', concentrationBand: 'LOW', addPermission: 'ALLOWED',
    },
  });
  input.marketTruth = resolved.marketTruth;
  input.predictionLedger = resolved.predictionLedger;
  input.sho = resolved.sho;
  input.quality = resolved.quality;
  input.riskKernel = authority.buildRiskKernel({
    schemaVersion: 'argus-risk-discipline-input-v1',
    subject: { kind: 'ASSET', instrumentId: '1321', market: 'JP' },
    asOf: resolved.informationCutoffAt,
    informationCutoffAt: resolved.informationCutoffAt,
    policy: { policyId: 'argus-risk-discipline-v1',
      policySha256: '6f6d1562d53e8f978ea8e558770cb6e71f3f84e6b28fe91b85797cfd3f2333b4' },
    contributions: withNews ? [contribution] : [{
      evidenceRef: 'portfolio:risk-1321',
      primitiveFactorId: 'portfolio.position_risk', sourceKind: 'PORTFOLIO',
      constraint: 'NONE', status: 'ACTIVE', severity: 'LOW',
      confidenceCapBps: 8000, observedAt: resolved.informationCutoffAt,
    }],
  });
  return authority.verifyDecisionEvidence(input);
};
const withNews = authority.evaluateSingleDecisionAuthority(buildInput(true));
const withoutNews = authority.evaluateSingleDecisionAuthority(buildInput(false));
assert.equal(withoutNews.status, 'EVALUATED');
assert.equal(withNews.status, 'EVALUATED',
  'a news constraint must not data-gate an otherwise verified decision');
assert.equal(withNews.guidance.riskConstraint, 'BLOCK_BUY',
  'the confirmed bearish news must surface as the BLOCK_BUY constraint');
assert.equal(withNews.primaryAction, 'HOLD',
  'held stays HOLD — news blocks new buying, never SELL/EXIT/WAIT');
assert.notEqual(withNews.primaryAction, 'BUY');
assert.ok(JSON.stringify(withNews).includes('news.market_impact_confirmed'),
  'the news primitive must survive into the evaluated result');

console.log('news-signal-gate.test: ok (per-target relevance + full NewsEvent→SDA trace)');
