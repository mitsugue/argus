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
  const noInput = authority.evaluateSingleDecisionAuthority();
  const validResult = authority.evaluateSingleDecisionAuthority(validInput);
  const hostileResult = authority.evaluateSingleDecisionAuthority(hostileInput);
  assert.strictEqual(noInput, validResult);
  assert.strictEqual(validResult, hostileResult);
  assert.strictEqual(authority.singleDecisionAuthority.evaluate(hostileInput), noInput);
  assert.equal(authority.singleDecisionAuthority.status, 'INACTIVE');
  assert.deepEqual(noInput, {
    schemaVersion: 'single-decision-authority-v1', status: 'INACTIVE', primaryAction: null,
    decisionId: null, evidenceBundleId: null, authorityPolicyId: null,
    supportingFactIds: [], blockingReasonCodes: ['authority_inactive'],
  });
  assert.equal(Object.isFrozen(noInput), true);
  assert.equal(Object.isFrozen(noInput.supportingFactIds), true);
  assert.equal(Object.isFrozen(noInput.blockingReasonCodes), true);

  const source = fs.readFileSync(sourcePath, 'utf8');
  assert.doesNotMatch(source, /from\s+['"]|require\s*\(/,
    'the inactive authority must have no runtime imports');
  assert.doesNotMatch(source, /localStorage|indexedDB|fetch\s*\(|XMLHttpRequest|WebSocket/);
  assert.doesNotMatch(source, /process\.env|import\.meta\.env|featureFlag|enabled\s*:/,
    'there is no activation control in Round 2A');

  console.log('single-decision-authority.test: ok (strict bundle, private join, inactive/null)');
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
