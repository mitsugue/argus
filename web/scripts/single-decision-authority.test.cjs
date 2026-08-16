#!/usr/bin/env node
'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { createHash, webcrypto } = require('node:crypto');
const ts = require('typescript');

require.extensions['.ts'] = (mod, filename) => {
  const output = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
    fileName: filename,
  }).outputText;
  mod._compile(output, filename);
};

if (!globalThis.crypto) globalThis.crypto = webcrypto;

const sourcePath = path.join(__dirname, '..', 'src', 'domain', 'singleDecisionAuthority.ts');
const authority = require(sourcePath);

const EXPECTED_BUNDLE_ID = 'deb-15a6b23889b84f7598ee1e5cc16216531949882a6d88a656d925d2309561ee24';

function fixture() {
  return {
    schemaVersion: 'decision-evidence-bundle-v1',
    bundleId: EXPECTED_BUNDLE_ID,
    privacyClass: 'PUBLIC_EVIDENCE',
    subject: { kind: 'ASSET', instrumentId: '7203', market: 'JP' },
    horizon: 'FIVE_DAY',
    asOf: '2026-08-15T10:00:00Z',
    informationCutoffAt: '2026-08-15T09:59:00Z',
    identities: {
      producerBuildSha: 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
      evidencePolicyId: 'round2a-evidence-v1',
      evidencePolicySha256: 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
      generationId: 'generation-20260815',
    },
    facts: [
      {
        factId: 'data.quality', kind: 'DATA_QUALITY', role: 'POLICY_CONSTRAINT',
        valueType: 'ENUM', value: 'LIVE', unit: 'NONE', observedAt: '2026-08-15T09:59:00Z',
        freshness: 'FRESH', quality: 'VERIFIED', sourceRef: 'argus:data-quality:7203',
      },
      {
        factId: 'price.change_pct', kind: 'PRICE_STATE', role: 'OBSERVATION',
        valueType: 'DECIMAL', value: '-2.35', unit: 'PERCENT', observedAt: '2026-08-15T09:58:00Z',
        freshness: 'FRESH', quality: 'VERIFIED', sourceRef: 'ep-7203-20260815',
      },
      {
        factId: 'visibility.entry_blocked', kind: 'VISIBILITY', role: 'POLICY_CONSTRAINT',
        valueType: 'BOOL', value: true, unit: 'NONE', observedAt: '2026-08-15T09:57:00Z',
        freshness: 'FRESH', quality: 'SUPPORTED', sourceRef: 'visibility-guard:7203',
      },
    ],
    missingReasonCodes: ['market_depth_unavailable'],
    conflictReasonCodes: [],
  };
}

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

const V2_SUBJECT = {
  kind: 'ASSET', instrumentId: '7203', market: 'JP', horizon: 'FIVE_DAY',
};
const V2_POLICY = {
  policyId: 'single-decision-authority-v2', policySha256: 'a'.repeat(64),
};

function owner(positionState = 'NOT_HELD', addPermission = 'ALLOWED') {
  return {
    schemaVersion: 'owner-decision-context-v1', privacyClass: 'DEVICE_LOCAL',
    asOf: '2026-08-16T09:00:00Z', positionState, positionRiskBand: 'LOW',
    concentrationBand: 'LOW', addPermission,
  };
}

function riskKernel(constraint = 'NONE') {
  return authority.buildRiskKernel({
    schemaVersion: 'argus-risk-discipline-input-v1',
    subject: { kind: 'ASSET', instrumentId: '7203', market: 'JP' },
    asOf: '2026-08-16T09:00:00Z',
    informationCutoffAt: '2026-08-16T08:59:00Z',
    policy: { policyId: 'risk-discipline-v1', policySha256: 'b'.repeat(64) },
    contributions: [{
      evidenceRef: 'risk:trend.market', primitiveFactorId: 'trend.market', sourceKind: 'MARKET',
      constraint, status: 'ACTIVE', severity: constraint === 'NONE' ? 'LOW' : 'HIGH',
      confidenceCapBps: 8500, observedAt: '2026-08-16T08:58:00Z',
    }],
  });
}

function v2Fixture({
  positionState = 'NOT_HELD', shoState = 'REVERSAL_EARLY', buyEligible = true,
  constraint = 'NONE',
} = {}) {
  return {
    schemaVersion: 'single-decision-authority-input-v2',
    subject: clone(V2_SUBJECT),
    decisionAt: '2026-08-16T09:00:00Z',
    informationCutoffAt: '2026-08-16T08:59:00Z',
    authorityPolicy: clone(V2_POLICY),
    marketTruth: {
      status: 'AVAILABLE', schemaVersion: 'argus-market-truth-v1',
      snapshotId: 'market:snapshot-7203', observationId: 'market:observation-7203',
      observedAt: '2026-08-16T08:57:00Z', knownAt: '2026-08-16T08:58:00Z',
      policyId: 'market-truth-v1', policySha256: 'c'.repeat(64),
    },
    predictionLedger: {
      status: 'AVAILABLE', schemaVersion: 'argus-prediction-ledger-v2',
      contextId: 'prediction:context-7203', mode: 'FORWARD_LIVE',
      asOf: '2026-08-16T08:58:00Z', policyId: 'prediction-ledger-v2',
      policySha256: 'd'.repeat(64),
    },
    sho: {
      status: 'AVAILABLE', schemaVersion: 'argus-sho-v1', artifactId: 'sho:artifact-7203',
      asOf: '2026-08-16T08:58:00Z', policyId: 'sho-policy-v1', policySha256: 'e'.repeat(64),
      state: shoState, validationStatus: 'VALIDATED', buyEligible,
      primitiveFactorIds: ['momentum.reversal', 'trend.market'],
      targets: [{
        targetId: 'target.primary', value: '3125.5', unit: 'PRICE',
        sourceRef: 'sho:target-primary',
      }],
      invalidation: {
        invalidationId: 'invalidation.primary', value: '2840', unit: 'PRICE',
        sourceRef: 'sho:invalidation-primary',
      },
    },
    riskKernel: riskKernel(constraint),
    contextEvidence: [{
      evidenceRef: 'event:calendar-clear', primitiveFactorId: 'event.calendar_clear',
      sourceKind: 'EVENT', constraint: 'NONE', status: 'ACTIVE',
      observedAt: '2026-08-16T08:58:00Z',
    }],
    quality: {
      status: 'COMPLETE', freshness: 'FRESH', missingReasonCodes: [], conflictReasonCodes: [],
    },
    ownerContext: owner(positionState),
    challengeEvidence: [],
    sevenSignCalibration: {
      status: 'MISSING', artifactId: null, policyId: null, policySha256: null,
      expectancyBpsByLevel: null, sampleSizeByLevel: null,
      outOfSample: false, holdoutImmutable: false,
    },
  };
}

async function main() {
  assert.deepEqual([...authority.PRIMARY_ACTIONS], ['BUY', 'HOLD', 'WAIT', 'REDUCE', 'EXIT']);
  assert.equal(new Set(authority.PRIMARY_ACTIONS).size, 5);
  assert.equal(authority.MAX_FACTS, 32);
  assert.equal(authority.MAX_SUPPORTING_FACT_REFS, 8);
  assert.equal(authority.MAX_CANONICAL_BODY_BYTES, 64 * 1024);

  const bundle = fixture();
  assert.deepEqual(authority.validateDecisionEvidenceBundle(bundle), { ok: true, errors: [] });
  const canonical = authority.canonicalDecisionEvidenceBodyJson(bundle);
  const nodeId = `deb-${createHash('sha256').update(canonical, 'utf8').digest('hex')}`;
  assert.equal(nodeId, EXPECTED_BUNDLE_ID, 'Python/TypeScript canonical hash vector drifted');
  assert.equal(await authority.computeDecisionEvidenceBundleId(bundle), EXPECTED_BUNDLE_ID);
  assert.equal(await authority.verifyDecisionEvidenceBundleId(bundle), true);

  const wrongHash = clone(bundle);
  wrongHash.bundleId = `deb-${'0'.repeat(64)}`;
  assert.equal(authority.validateDecisionEvidenceBundle(wrongHash).ok, true,
    'structural validation stays synchronous and separate from content verification');
  assert.equal(await authority.verifyDecisionEvidenceBundleId(wrongHash), false);

  const reorderedObject = {
    facts: bundle.facts,
    conflictReasonCodes: bundle.conflictReasonCodes,
    informationCutoffAt: bundle.informationCutoffAt,
    identities: bundle.identities,
    horizon: bundle.horizon,
    subject: bundle.subject,
    privacyClass: bundle.privacyClass,
    schemaVersion: bundle.schemaVersion,
    missingReasonCodes: bundle.missingReasonCodes,
    bundleId: bundle.bundleId,
    asOf: bundle.asOf,
  };
  assert.equal(authority.canonicalDecisionEvidenceBodyJson(reorderedObject), canonical,
    'object key order must not affect canonical bytes');

  const unsorted = clone(bundle);
  unsorted.facts.reverse();
  assert.equal(authority.validateDecisionEvidenceBundle(unsorted).ok, false);
  const duplicate = clone(bundle);
  duplicate.facts[1].factId = duplicate.facts[0].factId;
  assert.equal(authority.validateDecisionEvidenceBundle(duplicate).ok, false);
  const unknownTop = { ...clone(bundle), callerAction: 'EXIT' };
  assert.equal(authority.validateDecisionEvidenceBundle(unknownTop).ok, false);
  const unknownFact = clone(bundle);
  unknownFact.facts[0].rawPayload = { action: 'EXIT' };
  assert.equal(authority.validateDecisionEvidenceBundle(unknownFact).ok, false);
  const privateBundle = clone(bundle);
  privateBundle.privacyClass = 'DEVICE_LOCAL';
  assert.equal(authority.validateDecisionEvidenceBundle(privateBundle).ok, false);

  const tooMany = clone(bundle);
  tooMany.facts = Array.from({ length: authority.MAX_FACTS + 1 }, (_, index) => ({
    ...clone(bundle.facts[0]), factId: `fact.${String(index).padStart(2, '0')}`,
  }));
  assert.equal(authority.validateDecisionEvidenceBundle(tooMany).ok, false);
  const badDecimalFloat = clone(bundle);
  badDecimalFloat.facts[1].value = -2.35;
  assert.equal(authority.validateDecisionEvidenceBundle(badDecimalFloat).ok, false);
  const pseudoPrecision = clone(bundle);
  pseudoPrecision.facts[1].value = '-2.3500';
  assert.equal(authority.validateDecisionEvidenceBundle(pseudoPrecision).ok, false);
  const badObservedAt = clone(bundle);
  badObservedAt.facts[0].observedAt = '2026-08-15T10:00:01Z';
  assert.equal(authority.validateDecisionEvidenceBundle(badObservedAt).ok, false);
  const rawUrl = clone(bundle);
  rawUrl.facts[0].sourceRef = 'https://provider.test/raw';
  assert.equal(authority.validateDecisionEvidenceBundle(rawUrl).ok, false);

  const ownerContext = {
    schemaVersion: 'owner-decision-context-v1', privacyClass: 'DEVICE_LOCAL',
    asOf: '2026-08-15T10:00:00Z', positionState: 'HELD', positionRiskBand: 'HIGH',
    concentrationBand: 'MEDIUM', addPermission: 'BLOCKED',
  };
  assert.deepEqual(authority.validateOwnerDecisionContext(ownerContext), { ok: true, errors: [] });
  for (const privateField of ['quantity', 'costBasis', 'pricePaid', 'pnl', 'returnPct']) {
    assert.equal(authority.validateOwnerDecisionContext({
      ...ownerContext, [privateField]: 100,
    }).ok, false, `${privateField} must not enter the bounded authority context`);
  }

  const validInput = { evidenceBundle: bundle, ownerContext };
  const hostileInput = {
    ...validInput, enabled: true, activate: true, callerAction: 'EXIT', proof: true,
    actionVotes: ['EXIT', 'EXIT', 'EXIT'], trusted: true,
  };
  const noInput = authority.evaluateInactiveSingleDecisionAuthorityV1();
  const validResult = authority.evaluateInactiveSingleDecisionAuthorityV1(validInput);
  const hostileResult = authority.evaluateInactiveSingleDecisionAuthorityV1(hostileInput);
  assert.strictEqual(noInput, validResult);
  assert.strictEqual(validResult, hostileResult);
  assert.strictEqual(authority.inactiveSingleDecisionAuthorityV1.evaluate(hostileInput), noInput);
  assert.equal(authority.inactiveSingleDecisionAuthorityV1.status, 'INACTIVE');
  assert.deepEqual(noInput, {
    schemaVersion: 'single-decision-authority-v1', status: 'INACTIVE', primaryAction: null,
    decisionId: null, evidenceBundleId: null, authorityPolicyId: null,
    supportingFactIds: [], blockingReasonCodes: ['authority_inactive'],
  });
  assert.equal(Object.isFrozen(noInput), true);
  assert.equal(Object.isFrozen(noInput.supportingFactIds), true);
  assert.equal(Object.isFrozen(noInput.blockingReasonCodes), true);

  assert.deepEqual(authority.SINGLE_DECISION_AUTHORITY_V2_POLICY, {
    policyId: 'argus-single-decision-authority-v2',
    policySha256: 'bbd5da4bb68fed291908ff574f36a3c1c4b20bb48cf86d6a837eecf98353ea31',
  });
  assert.equal(Object.isFrozen(authority.SINGLE_DECISION_AUTHORITY_V2_POLICY), true);

  const risk = riskKernel();
  assert.deepEqual(authority.validateRiskKernel(risk), { ok: true, errors: [] });
  assert.equal(risk.riskKernelId,
    'rk-e656a5d83168ea50818e62e935a960d87d7103c7a9487b913b771ca46d39cb19',
    'Python/TypeScript Risk Kernel hash drifted');
  assert.equal(risk.finalActionAuthority, false);
  assert.equal(risk.primitiveFactors.length, 1);

  const duplicateRisk = authority.buildRiskKernel({
    schemaVersion: 'argus-risk-discipline-input-v1',
    subject: { kind: 'ASSET', instrumentId: '7203', market: 'JP' },
    asOf: '2026-08-16T09:00:00Z', informationCutoffAt: '2026-08-16T08:59:00Z',
    policy: { policyId: 'risk-discipline-v1', policySha256: 'b'.repeat(64) },
    contributions: [
      {
        evidenceRef: 'market:volatility', primitiveFactorId: 'volatility.regime',
        sourceKind: 'MARKET', constraint: 'BLOCK_BUY', status: 'ACTIVE', severity: 'LOW',
        confidenceCapBps: 7600, observedAt: '2026-08-16T08:58:00Z',
      },
      {
        evidenceRef: 'sho:volatility', primitiveFactorId: 'volatility.regime',
        sourceKind: 'SHO', constraint: 'BLOCK_BUY', status: 'ACTIVE', severity: 'MEDIUM',
        confidenceCapBps: 7200, observedAt: '2026-08-16T08:58:00Z',
      },
    ],
  });
  assert.equal(duplicateRisk.primitiveFactors.length, 1, 'shared primitive factors never vote twice');
  assert.equal(duplicateRisk.confidenceCapBps, 7200);

  const actionCases = [
    [v2Fixture(), 'BUY'],
    [v2Fixture({ positionState: 'HELD', shoState: 'MIXED', buyEligible: false }), 'HOLD'],
    [v2Fixture({ shoState: 'MIXED', buyEligible: false }), 'WAIT'],
    [v2Fixture({ positionState: 'HELD', constraint: 'REDUCE_RISK' }), 'REDUCE'],
    [v2Fixture({ positionState: 'HELD', constraint: 'EXIT_RISK' }), 'EXIT'],
  ];
  for (const [input, action] of actionCases) {
    const result = authority.evaluateSingleDecisionAuthority(input);
    assert.equal(result.status, 'EVALUATED');
    assert.equal(result.primaryAction, action);
    assert.equal(authority.validateSingleDecisionAuthorityResultV2(result).ok, true);
  }
  assert.equal(authority.singleDecisionAuthority.status, 'ACTIVE_V2');
  assert.equal(authority.evaluateSingleDecisionAuthority(v2Fixture({ constraint: 'EXIT_RISK' })).primaryAction,
    'WAIT', 'EXIT is held-only');
  assert.equal(authority.evaluateSingleDecisionAuthority(v2Fixture({ constraint: 'REDUCE_RISK' })).primaryAction,
    'WAIT', 'REDUCE is held-only');

  const completeV2 = v2Fixture();
  assert.deepEqual(authority.validateSingleDecisionAuthorityInputV2(completeV2), { ok: true, errors: [] });
  const canonicalDecision = authority.evaluateSingleDecisionAuthority(completeV2);
  assert.equal(canonicalDecision.decisionId,
    'sda-d76713b5560b65fc92c179ea7cda91477a75858d1408fbd959265610477b33cb',
    'Python/TypeScript SDA hash drifted');
  assert.equal(canonicalDecision.primaryAction, 'BUY');
  assert.equal(canonicalDecision.sevenSign.candidateLevel, 5);
  assert.equal(canonicalDecision.sevenSign.productionLevel, null);

  const challenged = clone(completeV2);
  challenged.challengeEvidence = [{
    challengeId: 'ai.challenge-1', sourceKind: 'AI', status: 'AVAILABLE',
    asOf: '2026-08-16T09:00:00Z', proposedAction: 'EXIT',
    dissentReasonCodes: ['ai_downside_dissent'], evidenceRefs: ['ai:challenge-1'],
  }];
  const challengedResult = authority.evaluateSingleDecisionAuthority(challenged);
  assert.equal(challengedResult.primaryAction, canonicalDecision.primaryAction,
    'AI challenge cannot alter the final action');
  assert.deepEqual(challengedResult.confidence, canonicalDecision.confidence);

  const privateOwner = clone(completeV2);
  privateOwner.ownerContext.quantity = 100;
  const privateResult = authority.evaluateSingleDecisionAuthority(privateOwner);
  assert.equal(privateResult.status, 'DATA_GATED');
  assert.equal(privateResult.primaryAction, 'WAIT');
  assert.equal(privateResult.subject, null);

  const dataGatedInput = authority.buildDataGatedInputV2({
    subject: V2_SUBJECT, decisionAt: '2026-08-16T09:00:00Z',
    informationCutoffAt: '2026-08-16T08:59:00Z', authorityPolicy: V2_POLICY,
  });
  const dataGatedResult = authority.evaluateSingleDecisionAuthority(dataGatedInput);
  assert.equal(dataGatedResult.status, 'DATA_GATED');
  assert.equal(dataGatedResult.primaryAction, 'WAIT');
  assert.equal(dataGatedResult.decisionId,
    'sda-bc4d8fc1e85c6c2655475342b0193b96592ec68f8a4575afe2f49b5612431a6f',
    'Python/TypeScript missing-artifact hash drifted');
  assert.equal(dataGatedResult.identities.marketTruth.status, 'MISSING');
  assert.equal(dataGatedResult.identities.risk.status, 'DATA_GATED');
  assert.equal(dataGatedResult.sevenSign.candidateLevel, null);

  const calibrated = clone(completeV2);
  calibrated.sevenSignCalibration = {
    status: 'VALIDATED', artifactId: 'seven:calibration-1',
    policyId: 'seven-sign-calibration-v1', policySha256: 'f'.repeat(64),
    expectancyBpsByLevel: [-500, -300, -100, 0, 150, 300, 500],
    sampleSizeByLevel: [30, 30, 30, 30, 30, 30, 30],
    outOfSample: true, holdoutImmutable: true,
  };
  const unverifiedCalibration = authority.evaluateSingleDecisionAuthority(calibrated).sevenSign;
  assert.equal(unverifiedCalibration.productionLevel, null,
    'caller-asserted calibration cannot enter production');
  assert.ok(unverifiedCalibration.reasonCodes.includes('calibration_artifact_not_verified'));
  calibrated.sevenSignCalibration.expectancyBpsByLevel = [0, 100, 50, 200, 300, 400, 500];
  assert.equal(authority.evaluateSingleDecisionAuthority(calibrated).sevenSign.productionLevel, null,
    'non-monotonic Seven Sign calibration cannot enter production');

  const beforeAdapter = clone(canonicalDecision);
  const adapter = authority.buildPredictionLedgerV2Adapter(canonicalDecision);
  assert.deepEqual(canonicalDecision, beforeAdapter, 'adapter must not mutate the result');
  assert.equal(adapter.appendMode, 'APPEND_ONLY');
  assert.equal(adapter.mutatesExistingRows, false);
  assert.equal(adapter.adapterId,
    'pla-b4485012e3d25f7abdeeca1ea5f03afef8faa5743a5e1f5f9e19789d1b4d3492',
    'Python/TypeScript ledger adapter hash drifted');
  assert.equal(adapter.marketTruthRef.snapshotId, canonicalDecision.identities.marketTruth.snapshotId);
  assert.equal(adapter.singleDecisionRef.decisionId, canonicalDecision.decisionId);

  const source = fs.readFileSync(sourcePath, 'utf8');
  assert.doesNotMatch(source, /from\s+['"]|require\s*\(/,
    'the pure authority must have no runtime imports');
  assert.doesNotMatch(source, /localStorage|indexedDB|fetch\s*\(|XMLHttpRequest|WebSocket/);
  assert.doesNotMatch(source, /process\.env|import\.meta\.env|featureFlag/);

  console.log('single-decision-authority.test: ok (v1 compatibility + active deterministic v2)');
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
