#!/usr/bin/env node
'use strict';
// v13.5.13 — canonical decision-evidence resolver contract.
//
// Proves the reviewed resolver boundary end-to-end on the device side:
//   1. backend-shaped reference payloads resolve, register, and let the SDA
//      reach EVALUATED (HOLD on a held subject with no constraints);
//   2. the same bytes WITHOUT the resolver still throw
//      canonical_artifact_resolver_unavailable (no plain-object bypass);
//   3. policy-pin drift, stale cutoffs, and incoherent quality fail closed.

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

const authority = require(path.join(
  __dirname, '..', 'src', 'domain', 'singleDecisionAuthority.ts'));
const resolver = require(path.join(
  __dirname, '..', 'src', 'domain', 'canonicalDecisionEvidence.ts'));

const NOW_MS = Date.parse('2026-08-22T05:00:10Z');
const CUTOFF = '2026-08-22T05:00:00Z';
const DECISION_AT = '2026-08-22T05:00:10Z';

function evidenceEntry() {
  return {
    subject: { kind: 'ASSET', instrumentId: '1321', market: 'JP', horizon: 'FIVE_DAY' },
    informationCutoffAt: CUTOFF,
    marketTruth: {
      status: 'AVAILABLE',
      schemaVersion: 'argus-market-truth-decision-snapshot-v2',
      snapshotId: 'mts-' + 'a'.repeat(32),
      observationId: 'obs-' + 'b'.repeat(32),
      observedAt: '2026-08-22T04:59:30Z',
      knownAt: '2026-08-22T04:59:40Z',
      policyId: 'repo-market-provider-priority-v1',
      policySha256: 'c848e2537828a74ecb0914d374d5755ac5b79a3e99e4791b496e514ee8103bf3',
    },
    predictionLedger: {
      status: 'AVAILABLE',
      schemaVersion: 'argus-prediction-ledger-v2',
      contextId: 'pd-' + 'c'.repeat(32),
      mode: 'FORWARD_LIVE',
      asOf: CUTOFF,
      policyId: 'argus-calibration-three-class-v1',
      policySha256: '62ab147263dfb674301c0dc6585df4c1ffda02cb07380b3d9f94a870ec056379',
    },
    sho: {
      status: 'AVAILABLE',
      schemaVersion: 'argus-sho-reversal-v1',
      artifactId: 'sho-reversal-' + 'd'.repeat(32),
      asOf: CUTOFF,
      policyId: 'sho-jp-canonical-2026.08-round2-v1',
      policySha256: '0ddae6123f70dd858d5135528768fa9b6cea561f31f47201b8e882c978cbf532',
      state: 'MIXED',
      validationStatus: 'UNVALIDATED',
      primitiveFactorIds: [],
      targets: [],
      invalidation: null,
    },
    quality: { status: 'COMPLETE', freshness: 'FRESH',
      missingReasonCodes: [], conflictReasonCodes: [] },
  };
}

function evaluatedInput(resolved) {
  const input = authority.buildDataGatedInputV2({
    subject: { kind: 'ASSET', instrumentId: '1321', market: 'JP', horizon: 'FIVE_DAY' },
    decisionAt: DECISION_AT,
    informationCutoffAt: resolved.informationCutoffAt,
    authorityPolicy: authority.SINGLE_DECISION_AUTHORITY_V2_POLICY,
    ownerContext: {
      schemaVersion: 'owner-decision-context-v1',
      privacyClass: 'DEVICE_LOCAL',
      asOf: resolved.informationCutoffAt,
      positionState: 'HELD',
      positionRiskBand: 'LOW',
      concentrationBand: 'LOW',
      addPermission: 'ALLOWED',
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
    contributions: [{
      evidenceRef: 'portfolio:risk-1321',
      primitiveFactorId: 'portfolio.position_risk',
      sourceKind: 'PORTFOLIO',
      constraint: 'NONE', status: 'ACTIVE', severity: 'LOW',
      confidenceCapBps: 8000, observedAt: resolved.informationCutoffAt,
    }],
  });
  return input;
}

// 1) resolver-registered references reach EVALUATED
const resolved = resolver.resolveCanonicalArtifactReferences(evidenceEntry(), NOW_MS);
assert.ok(resolved, 'coherent backend payload must resolve');
const result = authority.evaluateSingleDecisionAuthority(
  authority.verifyDecisionEvidence(evaluatedInput(resolved)));
assert.equal(result.status, 'EVALUATED',
  'verified artifacts + held owner context must leave DATA_GATED');
assert.equal(result.primaryAction, 'HOLD');
assert.equal(result.identities.marketTruth.status, 'AVAILABLE');
assert.equal(result.identities.predictionLedger.status, 'AVAILABLE');
assert.equal(result.identities.sho.status, 'AVAILABLE');
assert.equal(result.sevenSign.candidateLevel, 4, 'HOLD projects Seven Sign 4');
assert.ok(result.confidence.valueBps > 2500,
  'EVALUATED confidence must exceed the data-gated clamp');

// BUY stays structurally locked even with verified artifacts
assert.notEqual(result.primaryAction, 'BUY');

// 2) identical bytes WITHOUT the resolver still throw
const bypass = evaluatedInput(resolved);
bypass.marketTruth = JSON.parse(JSON.stringify(resolved.marketTruth));
assert.throws(
  () => authority.verifyDecisionEvidence(bypass),
  /canonical_artifact_resolver_unavailable/,
  'a plain object can never activate an AVAILABLE reference');

// 3) policy-pin drift fails closed
const drifted = evidenceEntry();
drifted.marketTruth.policySha256 = 'f'.repeat(64);
assert.equal(resolver.resolveCanonicalArtifactReferences(drifted, NOW_MS), null);

// 4) stale evidence (cutoff older than the age bound) fails closed
assert.equal(resolver.resolveCanonicalArtifactReferences(
  evidenceEntry(), NOW_MS + 11 * 60 * 1000), null);

// 5) all-AVAILABLE with degraded quality is incoherent → fail closed
const incoherent = evidenceEntry();
incoherent.quality = { status: 'PARTIAL', freshness: 'STALE',
  missingReasonCodes: ['market_truth_stale'], conflictReasonCodes: [] };
assert.equal(resolver.resolveCanonicalArtifactReferences(incoherent, NOW_MS), null);

// 6) a STALE reference resolves (identity kept) but keeps the SDA gated
const staleEntry = evidenceEntry();
staleEntry.marketTruth.status = 'STALE';
staleEntry.quality = { status: 'PARTIAL', freshness: 'STALE',
  missingReasonCodes: ['market_truth_stale'], conflictReasonCodes: [] };
const staleResolved = resolver.resolveCanonicalArtifactReferences(staleEntry, NOW_MS);
assert.ok(staleResolved, 'stale reference with identity must still resolve');
const staleResult = authority.evaluateSingleDecisionAuthority(
  authority.verifyDecisionEvidence(evaluatedInput(staleResolved)));
assert.equal(staleResult.status, 'DATA_GATED');
assert.equal(staleResult.primaryAction, 'WAIT');

console.log('canonical-decision-evidence.test: ok (resolver boundary, EVALUATED reachable, fail-closed)');
