"""Recovery Phase A PR D proof-core contract and hostile tests."""

from __future__ import annotations

from dataclasses import fields, replace
import hashlib
import inspect
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

import argus_recovery_proof as proof
import argus_recovery_registry as registry


NOW = "2026-08-15T01:00:00Z"
INITIAL_TIME = "2026-08-15T00:55:00Z"
VERIFY_TIME = "2026-08-15T00:56:00Z"
FINAL_TIME = "2026-08-15T00:57:00Z"
RECEIPT_TIME = "2026-08-15T00:58:00Z"

GENERATION_ID = "gen_" + "1" * 32
OTHER_GENERATION_ID = "gen_" + "2" * 32
MANIFEST_ID = "manifest_" + "3" * 32
POINTER_ID = "pointer_" + "4" * 32
FULL_ID = "full_" + "5" * 32
RECEIPT_ID = "receipt_" + "6" * 32
BUILD_SHA = "7" * 40
VERIFIER_SHA = "8" * 40


def digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


REDUCER_DIGEST = digest("reducer-v1")
STATE_SCHEMA_DIGEST = digest("state-schema-v1")
KEY_ID_DIGEST = digest("key-id-v1")
FULL_DIGEST = digest("full-object-v1")
ROOT_T = digest("root-at-t")
EXTERNAL_ID = "external_public.ledger"


def make_policy(**changes):
    values = {
        "supportedReducerDigests": (REDUCER_DIGEST,),
        "supportedStateSchemaDigests": (STATE_SCHEMA_DIGEST,),
        "supportedBuildShas": (BUILD_SHA,),
        "supportedVerifierBuildShas": (VERIFIER_SHA,),
    }
    values.update(changes)
    return proof.make_proof_policy(**values)


def _trusted_replace(evidence, *, reseal=True, **changes):
    values = {
        field.name: object.__getattribute__(evidence, field.name)
        for field in fields(proof.VerifiedRecoveryEvidence)
    }
    values.update(changes)
    result = proof._trusted_evidence_from_verifier(**values)
    if reseal and proof._valid_evidence_structure(result):
        receipt = replace(
            result.verifierReceipt,
            transcriptDigest=proof._evidence_transcript_digest(result),
        )
        values["verifierReceipt"] = receipt
        result = proof._trusted_evidence_from_verifier(**values)
    return result


def make_evidence(segment_ranges=(), *, lag_seconds=60):
    t_sequence = 10
    h_sequence = segment_ranges[-1][1] if segment_ranges else t_sequence
    segment_ids = tuple(
        "wal_" + format(index + 9, "032x")
        for index in range(len(segment_ranges))
    )
    prior_kind = proof.PredecessorKind.FULL_GENERATION
    prior_id = FULL_ID
    prior_digest = FULL_DIGEST
    prior_root = ROOT_T
    segments = []
    for index, (start, end) in enumerate(segment_ranges):
        end_root = digest(f"root-at-{end}")
        segment_digest = digest(f"segment-{index}-{start}-{end}")
        segments.append(proof.WalSegmentEvidence(
            segmentId=segment_ids[index],
            generationId=GENERATION_ID,
            expectedDigest=segment_digest,
            observedDigest=segment_digest,
            startSequence=start,
            endSequence=end,
            predecessorKind=prior_kind,
            predecessorIdentity=prior_id,
            predecessorDigest=prior_digest,
            startStateRoot=prior_root,
            endStateRoot=end_root,
            reducerDigest=REDUCER_DIGEST,
            stateSchemaDigest=STATE_SCHEMA_DIGEST,
            buildSha=BUILD_SHA,
            keyIdDigest=KEY_ID_DIGEST,
            verifiedAt=VERIFY_TIME,
            authenticityReceiptDigest=digest(f"segment-receipt-{index}"),
        ))
        prior_kind = proof.PredecessorKind.WAL_SEGMENT
        prior_id = segment_ids[index]
        prior_digest = segment_digest
        prior_root = end_root
    root_h = prior_root

    declaration = proof.ExternalReferenceDeclaration(
        referenceId=EXTERNAL_ID,
        expectedDigest=digest("external-object"),
        immutableLocatorDigest=digest("external-locator"),
    )
    manifest = proof.AuthorityManifestEvidence(
        manifestId=MANIFEST_ID,
        authorityEpoch=3,
        generationId=GENERATION_ID,
        manifestDigest=digest("manifest-placeholder"),
        observedDigest=digest("manifest-placeholder"),
        pointerIdentity=POINTER_ID,
        fullGenerationId=FULL_ID,
        fullGenerationDigest=FULL_DIGEST,
        baselineWalSequence=t_sequence,
        remoteCoveredHighWater=h_sequence,
        stateRootAtT=ROOT_T,
        stateRootAtH=root_h,
        walTail=(
            proof.WalTailDeclaration.SEGMENTS if segments
            else proof.WalTailDeclaration.EXPLICIT_EMPTY
        ),
        walSegmentIds=segment_ids,
        externalReferences=(declaration,),
        registryPolicyDigest=registry.registry_policy_sha256(),
        reducerDigest=REDUCER_DIGEST,
        stateSchemaDigest=STATE_SCHEMA_DIGEST,
        buildSha=BUILD_SHA,
        keyIdDigest=KEY_ID_DIGEST,
        verifiedAt=VERIFY_TIME,
        authenticityReceiptDigest=digest("manifest-receipt"),
    )
    manifest_digest = proof._manifest_contract_digest(manifest)
    manifest = replace(
        manifest,
        manifestDigest=manifest_digest,
        observedDigest=manifest_digest,
    )
    initial = proof.ManifestReadbackEvidence(
        manifestId=MANIFEST_ID,
        manifestDigest=manifest_digest,
        pointerIdentity=POINTER_ID,
        authorityEpoch=3,
        generationId=GENERATION_ID,
        observedAt=INITIAL_TIME,
        readbackReceiptDigest=digest("initial-readback"),
    )
    final = replace(
        initial,
        observedAt=FINAL_TIME,
        readbackReceiptDigest=digest("final-readback"),
    )
    full = proof.FullGenerationEvidence(
        fullGenerationId=FULL_ID,
        generationId=GENERATION_ID,
        expectedDigest=FULL_DIGEST,
        observedDigest=FULL_DIGEST,
        coversThroughSequence=t_sequence,
        stateRoot=ROOT_T,
        reducerDigest=REDUCER_DIGEST,
        stateSchemaDigest=STATE_SCHEMA_DIGEST,
        buildSha=BUILD_SHA,
        keyIdDigest=KEY_ID_DIGEST,
        verifiedAt=VERIFY_TIME,
        authenticityReceiptDigest=digest("full-receipt"),
    )
    state_coverage = tuple(
        proof.StateCoverageEvidence(
            stateId=row.stateId,
            generationId=GENERATION_ID,
            coveredThroughSequence=h_sequence,
            completeness=proof.CoverageCompleteness.EXACT_COMPLETE,
            coverageDigest=digest(f"state-coverage-{row.stateId}"),
            verificationReceiptDigest=digest(
                f"state-coverage-receipt-{row.stateId}"),
        )
        for row in registry.states() if row.mustPreserveNow
    )
    mutation_coverage = tuple(
        proof.MutationCoverageEvidence(
            mutationId=row.mutationId,
            generationId=GENERATION_ID,
            coveredThroughSequence=h_sequence,
            completeness=proof.CoverageCompleteness.EXACT_COMPLETE,
            coverageDigest=digest(f"mutation-coverage-{row.mutationId}"),
            verificationReceiptDigest=digest(
                f"mutation-coverage-receipt-{row.mutationId}"),
        )
        for row in registry.mutations()
    )
    external = proof.ExternalReferenceEvidence(
        referenceId=EXTERNAL_ID,
        generationId=GENERATION_ID,
        expectedDigest=declaration.expectedDigest,
        observedDigest=declaration.expectedDigest,
        immutableLocatorDigest=declaration.immutableLocatorDigest,
        verifiedAt=VERIFY_TIME,
        verificationReceiptDigest=digest("external-receipt"),
    )
    restore = proof.IsolatedRestoreEvidence(
        generationId=GENERATION_ID,
        restoredThroughSequence=h_sequence,
        stateRoot=root_h,
        verifierBuildSha=VERIFIER_SHA,
        completedAt=VERIFY_TIME,
        verificationReceiptDigest=digest("restore-receipt"),
    )
    hard_rpo = proof.HardRpoEvidence(
        mutationCoverage=proof.CoverageCompleteness.EXACT_COMPLETE,
        instrumentationCoverage=
        proof.InstrumentationCoverage.COMPLETE_NO_GAPS,
        remoteDurableLagSeconds=lag_seconds,
        clockTrust=proof.ClockTrust.TRUSTED,
        clockObservedAt=RECEIPT_TIME,
        clockReceiptDigest=digest("clock-receipt"),
    )
    receipt = proof.VerifierReceiptEvidence(
        receiptId=RECEIPT_ID,
        transcriptDigest=digest("receipt-placeholder"),
        manifestId=MANIFEST_ID,
        generationId=GENERATION_ID,
        verifiedThroughSequence=h_sequence,
        verifierBuildSha=VERIFIER_SHA,
        issuedAt=RECEIPT_TIME,
    )
    evidence = proof._trusted_evidence_from_verifier(
        schemaVersion=proof.EVIDENCE_SCHEMA_VERSION,
        verificationBoundary=proof.VerificationBoundary.TRUSTED_VERIFIER_OUTPUT,
        mode=proof.RecoveryMode.FULL_PLUS_WAL,
        manifest=manifest,
        initialManifestReadback=initial,
        finalManifestReadback=final,
        fullGeneration=full,
        walSegments=tuple(segments),
        stateCoverage=state_coverage,
        mutationCoverage=mutation_coverage,
        externalReferences=(external,),
        isolatedRestore=restore,
        hardRpoEvidence=hard_rpo,
        verificationTime=RECEIPT_TIME,
        verifierBuildSha=VERIFIER_SHA,
        verifierReceipt=receipt,
    )
    return _trusted_replace(evidence)


@pytest.mark.parametrize("segment_ranges", [
    (),
    ((11, 12),),
    ((11, 12), (13, 15), (16, 19)),
])
def test_positive_golden_full_empty_one_and_multiple_wal(segment_ranges):
    result = proof.evaluate_recovery_proof(
        make_evidence(segment_ranges), make_policy(), NOW)
    assert proof.proof_result_document(result) == {
        "status": "PROVEN",
        "hardRpoClaimPermitted": True,
    }
    assert result.reasonCodes == ()
    assert result.hardRpoReasonCodes == ()
    assert result.transcript.checkedPredicateIds == proof.PREDICATE_IDS


def test_positive_golden_proven_but_lag_exceeds_rpo_policy():
    result = proof.evaluate_recovery_proof(
        make_evidence(((11, 12),), lag_seconds=1801), make_policy(), NOW)
    assert result.status is proof.ProofStatus.PROVEN
    assert result.hardRpoClaimPermitted is False
    assert result.reasonCodes == ()
    assert result.hardRpoReasonCodes == (
        proof.HardRpoReasonCode.REMOTE_DURABLE_LAG_EXCEEDED,
    )


def test_default_and_canonical_result_are_fail_closed():
    policy = make_policy()
    for hostile in (
            None, True, False, "true", "false", 1, 1.0, float("nan"),
            {"tagVerified": True}, [make_evidence()]):
        result = proof.evaluate_recovery_proof(hostile, policy, NOW)
        assert proof.proof_result_document(result) == {
            "status": "NOT_PROVEN",
            "hardRpoClaimPermitted": False,
        }
    assert proof.proof_result_document({"status": "PROVEN"}) == {
        "status": "NOT_PROVEN",
        "hardRpoClaimPermitted": False,
    }


def test_public_evidence_constructor_cannot_accept_caller_boolean():
    with pytest.raises(TypeError):
        proof.VerifiedRecoveryEvidence(tagVerified=True)


_DEFAULT_POLICY = object()


def assert_not_proven(evidence, policy=_DEFAULT_POLICY, now=NOW):
    result = proof.evaluate_recovery_proof(
        evidence, make_policy() if policy is _DEFAULT_POLICY else policy, now)
    assert result.status is proof.ProofStatus.NOT_PROVEN
    assert result.hardRpoClaimPermitted is False
    assert result.reasonCodes
    assert proof.proof_result_document(result) == {
        "status": "NOT_PROVEN",
        "hardRpoClaimPermitted": False,
    }
    return result


def _alter_manifest(evidence, *, recompute_contract=False, **changes):
    manifest = replace(evidence.manifest, **changes)
    if recompute_contract:
        manifest_digest = proof._manifest_contract_digest(manifest)
        manifest = replace(
            manifest,
            manifestDigest=manifest_digest,
            observedDigest=manifest_digest,
        )
    return _trusted_replace(evidence, manifest=manifest)


@pytest.mark.parametrize("name,mutator", [
    ("schema-bool", lambda e: _trusted_replace(e, reseal=False,
                                                schemaVersion=True)),
    ("raw-boundary", lambda e: _trusted_replace(
        e, reseal=False, verificationBoundary="TRUSTED_VERIFIER_OUTPUT")),
    ("raw-mode", lambda e: _trusted_replace(
        e, reseal=False, mode="FULL_PLUS_WAL")),
    ("wal-list", lambda e: _trusted_replace(
        e, reseal=False, walSegments=list(e.walSegments))),
    ("state-list", lambda e: _trusted_replace(
        e, reseal=False, stateCoverage=list(e.stateCoverage))),
    ("numeric-string", lambda e: _trusted_replace(
        e, reseal=False, manifest=replace(
            e.manifest, baselineWalSequence="10"))),
    ("bool-as-int", lambda e: _trusted_replace(
        e, reseal=False, manifest=replace(
            e.manifest, baselineWalSequence=True))),
    ("nan", lambda e: _trusted_replace(
        e, reseal=False, manifest=replace(
            e.manifest, baselineWalSequence=float("nan")))),
    ("infinity", lambda e: _trusted_replace(
        e, reseal=False, hardRpoEvidence=replace(
            e.hardRpoEvidence, remoteDurableLagSeconds=float("inf")))),
    ("negative", lambda e: _trusted_replace(
        e, reseal=False, manifest=replace(
            e.manifest, baselineWalSequence=-1))),
    ("malformed-digest", lambda e: _trusted_replace(
        e, reseal=False, fullGeneration=replace(
            e.fullGeneration, observedDigest="not-a-digest"))),
    ("malformed-sha", lambda e: _trusted_replace(
        e, reseal=False, verifierBuildSha="not-a-sha")),
    ("malformed-generation", lambda e: _trusted_replace(
        e, reseal=False, fullGeneration=replace(
            e.fullGeneration, generationId="generation-latest"))),
    ("malformed-timestamp", lambda e: _trusted_replace(
        e, reseal=False, verificationTime="2026-08-15 00:58:00")),
    ("raw-wal-enum", lambda e: _trusted_replace(
        e, reseal=False, manifest=replace(
            e.manifest, walTail="EXPLICIT_EMPTY"))),
    ("unknown-enum", lambda e: _trusted_replace(
        e, reseal=False, hardRpoEvidence=replace(
            e.hardRpoEvidence, clockTrust="VERY_TRUSTED"))),
])
def test_fail_closed_exact_type_matrix(name, mutator):
    del name
    assert_not_proven(mutator(make_evidence()))


def test_malformed_ancestry_identity_is_rejected():
    evidence = make_evidence(((11, 12),))
    segment = replace(evidence.walSegments[0], predecessorIdentity="latest")
    assert_not_proven(_trusted_replace(
        evidence, reseal=False, walSegments=(segment,)))


def test_missing_and_extra_fields_and_hostile_truthiness_are_total():
    missing = make_evidence()
    object.__delattr__(missing, "manifest")
    assert_not_proven(missing)

    extra = make_evidence()
    object.__setattr__(extra, "tagVerified", True)
    assert_not_proven(extra)

    class TruthTrap:
        def __bool__(self):
            raise AssertionError("truthiness must not run")

        def __str__(self):
            raise AssertionError("formatting must not run")

    trapped = _trusted_replace(
        make_evidence(), reseal=False, mode=TruthTrap())
    assert_not_proven(trapped)


def test_exact_dataclass_subclasses_are_rejected():
    class FullSubclass(proof.FullGenerationEvidence):
        pass

    evidence = make_evidence()
    raw = evidence.fullGeneration
    subclass = FullSubclass(**{
        field.name: getattr(raw, field.name)
        for field in fields(proof.FullGenerationEvidence)
    })
    assert_not_proven(_trusted_replace(
        evidence, reseal=False, fullGeneration=subclass))


def _tamper_cases():
    def wrong_manifest_digest(e):
        return _alter_manifest(e, observedDigest=digest("wrong-manifest"))

    def changed_pointer(e):
        return _trusted_replace(e, finalManifestReadback=replace(
            e.finalManifestReadback,
            pointerIdentity="pointer_" + "9" * 32))

    def initial_readback_mismatch(e):
        return _trusted_replace(e, initialManifestReadback=replace(
            e.initialManifestReadback,
            manifestDigest=digest("wrong-initial-readback")))

    def missing_full(e):
        return _trusted_replace(e, reseal=False, fullGeneration=None)

    def wrong_full_digest(e):
        return _trusted_replace(e, fullGeneration=replace(
            e.fullGeneration, observedDigest=digest("wrong-full")))

    def wrong_full_generation(e):
        return _trusted_replace(e, fullGeneration=replace(
            e.fullGeneration, generationId=OTHER_GENERATION_ID))

    def wrong_full_key(e):
        return _trusted_replace(e, fullGeneration=replace(
            e.fullGeneration, keyIdDigest=digest("wrong-key")))

    def missing_segment(e):
        return _trusted_replace(e, walSegments=e.walSegments[:-1])

    def duplicate_segment(e):
        return _trusted_replace(
            e, walSegments=(e.walSegments[0], e.walSegments[0],
                            e.walSegments[2]))

    def overlapping_segment(e):
        middle = replace(e.walSegments[1], startSequence=12)
        return _trusted_replace(
            e, walSegments=(e.walSegments[0], middle, e.walSegments[2]))

    def forked_segment(e):
        middle = replace(
            e.walSegments[1],
            predecessorKind=proof.PredecessorKind.FULL_GENERATION,
            predecessorIdentity=FULL_ID,
            predecessorDigest=FULL_DIGEST,
        )
        return _trusted_replace(
            e, walSegments=(e.walSegments[0], middle, e.walSegments[2]))

    def reordered_segments(e):
        return _trusted_replace(
            e, walSegments=(e.walSegments[1], e.walSegments[0],
                            e.walSegments[2]))

    def predecessor_mismatch(e):
        first = replace(
            e.walSegments[0], predecessorIdentity="full_" + "a" * 32)
        return _trusted_replace(
            e, walSegments=(first,) + e.walSegments[1:])

    def segment_root_mismatch(e):
        final = replace(e.walSegments[-1], endStateRoot=digest("wrong-root"))
        return _trusted_replace(e, walSegments=e.walSegments[:-1] + (final,))

    def cross_generation(e):
        middle = replace(
            e.walSegments[1], generationId=OTHER_GENERATION_ID)
        return _trusted_replace(
            e, walSegments=(e.walSegments[0], middle, e.walSegments[2]))

    def unsupported_reducer(e):
        segment = replace(
            e.walSegments[0], reducerDigest=digest("unsupported-reducer"))
        return _trusted_replace(e, walSegments=(segment,) + e.walSegments[1:])

    def unsupported_schema(e):
        segment = replace(
            e.walSegments[0],
            stateSchemaDigest=digest("unsupported-schema"))
        return _trusted_replace(e, walSegments=(segment,) + e.walSegments[1:])

    def unsupported_build(e):
        segment = replace(e.walSegments[0], buildSha="b" * 40)
        return _trusted_replace(e, walSegments=(segment,) + e.walSegments[1:])

    def incompatible_full_schema(e):
        return _trusted_replace(e, fullGeneration=replace(
            e.fullGeneration,
            stateSchemaDigest=digest("unsupported-full-schema")))

    def incompatible_full_build(e):
        return _trusted_replace(e, fullGeneration=replace(
            e.fullGeneration, buildSha="c" * 40))

    def missing_external(e):
        return _trusted_replace(e, externalReferences=())

    def wrong_external_digest(e):
        external = replace(
            e.externalReferences[0], observedDigest=digest("wrong-external"))
        return _trusted_replace(e, externalReferences=(external,))

    def restore_root_mismatch(e):
        return _trusted_replace(e, isolatedRestore=replace(
            e.isolatedRestore, stateRoot=digest("wrong-restore-root")))

    def stale_receipt(e):
        return _trusted_replace(
            e, verificationTime="2026-08-15T00:40:00Z",
            verifierReceipt=replace(
                e.verifierReceipt, issuedAt="2026-08-15T00:40:00Z"))

    def future_receipt(e):
        return _trusted_replace(
            e, verificationTime="2026-08-15T01:01:00Z",
            verifierReceipt=replace(
                e.verifierReceipt, issuedAt="2026-08-15T01:01:00Z"))

    def invalid_clock(e):
        return _trusted_replace(e, hardRpoEvidence=replace(
            e.hardRpoEvidence, clockTrust=proof.ClockTrust.UNTRUSTED))

    def final_reread_before_verification(e):
        return _trusted_replace(e, finalManifestReadback=replace(
            e.finalManifestReadback,
            observedAt="2026-08-15T00:55:30Z"))

    def wrong_baseline(e):
        return _trusted_replace(e, fullGeneration=replace(
            e.fullGeneration, coversThroughSequence=9))

    return (
        ("wrong-manifest-digest", wrong_manifest_digest),
        ("changed-pointer", changed_pointer),
        ("initial-readback", initial_readback_mismatch),
        ("missing-full", missing_full),
        ("wrong-full-digest", wrong_full_digest),
        ("wrong-full-generation", wrong_full_generation),
        ("wrong-full-key", wrong_full_key),
        ("missing-segment", missing_segment),
        ("duplicate-segment", duplicate_segment),
        ("overlap", overlapping_segment),
        ("fork", forked_segment),
        ("reorder", reordered_segments),
        ("predecessor", predecessor_mismatch),
        ("segment-root", segment_root_mismatch),
        ("cross-generation", cross_generation),
        ("unsupported-reducer", unsupported_reducer),
        ("unsupported-schema", unsupported_schema),
        ("unsupported-build", unsupported_build),
        ("incompatible-full-schema", incompatible_full_schema),
        ("incompatible-full-build", incompatible_full_build),
        ("missing-external", missing_external),
        ("wrong-external", wrong_external_digest),
        ("restore-root", restore_root_mismatch),
        ("stale-receipt", stale_receipt),
        ("future-receipt", future_receipt),
        ("invalid-clock", invalid_clock),
        ("final-reread-before-verification", final_reread_before_verification),
        ("wrong-baseline", wrong_baseline),
    )


@pytest.mark.parametrize("name,mutator", _tamper_cases())
def test_tamper_chain_coverage_and_time_matrix(name, mutator):
    del name
    evidence = make_evidence(((11, 12), (13, 15), (16, 19)))
    assert_not_proven(mutator(evidence))


def test_gap_is_denied_even_with_valid_segment_receipts():
    evidence = make_evidence(((11, 12), (13, 15), (16, 19)))
    middle = replace(evidence.walSegments[1], startSequence=14)
    altered = _trusted_replace(
        evidence,
        walSegments=(evidence.walSegments[0], middle,
                     evidence.walSegments[2]),
    )
    result = assert_not_proven(altered)
    assert proof.ReasonCode.WAL_GAP in result.reasonCodes


def test_empty_wal_must_be_explicit_and_only_when_t_equals_h():
    evidence = make_evidence()
    implicit = _alter_manifest(
        evidence, recompute_contract=True,
        walTail=proof.WalTailDeclaration.SEGMENTS)
    assert proof.ReasonCode.WAL_TAIL_RANGE_INVALID in \
        assert_not_proven(implicit).reasonCodes

    advanced = _alter_manifest(
        evidence, recompute_contract=True, remoteCoveredHighWater=11)
    assert_not_proven(advanced)


def test_coverage_and_policy_drift_matrix(monkeypatch):
    evidence = make_evidence(((11, 12),))
    missing_state = _trusted_replace(
        evidence, stateCoverage=evidence.stateCoverage[:-1])
    assert proof.ReasonCode.STATE_COVERAGE_INCOMPLETE in \
        assert_not_proven(missing_state).reasonCodes

    missing_mutation = _trusted_replace(
        evidence, mutationCoverage=evidence.mutationCoverage[:-1])
    assert proof.ReasonCode.MUTATION_COVERAGE_INCOMPLETE in \
        assert_not_proven(missing_mutation).reasonCodes

    gap = _trusted_replace(
        evidence, hardRpoEvidence=replace(
            evidence.hardRpoEvidence,
            instrumentationCoverage=proof.InstrumentationCoverage.GAP_PRESENT,
        ))
    assert proof.ReasonCode.MUTATION_COVERAGE_INCOMPLETE in \
        assert_not_proven(gap).reasonCodes

    policy = make_policy()
    monkeypatch.setattr(
        proof.registry, "registry_policy_sha256",
        lambda: digest("drifted-registry-policy"),
    )
    result = assert_not_proven(evidence, policy=policy)
    assert proof.ReasonCode.REGISTRY_POLICY_MISMATCH in result.reasonCodes


@pytest.mark.parametrize("policy", [
    None,
    {},
    True,
    "policy",
    replace(make_policy(), maxReceiptAgeSeconds=True),
    replace(make_policy(), maxSegments=proof.ABSOLUTE_MAX_SEGMENTS + 1),
    replace(make_policy(), supportedBuildShas=(BUILD_SHA, BUILD_SHA)),
    replace(make_policy(), supportedReducerDigests=[REDUCER_DIGEST]),
])
def test_policy_is_exact_typed_bounded_and_unique(policy):
    result = assert_not_proven(make_evidence(), policy=policy)
    assert result.reasonCodes == (proof.ReasonCode.INVALID_POLICY,)


def test_cardinality_bounds_fail_closed_before_proof():
    evidence = make_evidence(((11, 12), (13, 15), (16, 19)))
    bounded = make_policy(maxSegments=2)
    result = assert_not_proven(evidence, policy=bounded)
    assert proof.ReasonCode.CARDINALITY_EXCEEDED in result.reasonCodes

    oversized_state = _trusted_replace(
        evidence, reseal=False,
        stateCoverage=(evidence.stateCoverage[0],) *
        (proof.ABSOLUTE_MAX_STATE_COVERAGE + 1),
    )
    assert assert_not_proven(oversized_state).reasonCodes == (
        proof.ReasonCode.INVALID_EVIDENCE_STRUCTURE,
    )


def test_maximum_segment_cardinality_is_metadata_only_and_bounded():
    ranges = tuple((11 + index, 11 + index)
                   for index in range(proof.ABSOLUTE_MAX_SEGMENTS))
    started = time.perf_counter()
    result = proof.evaluate_recovery_proof(
        make_evidence(ranges), make_policy(), NOW)
    elapsed = time.perf_counter() - started
    assert result.status is proof.ProofStatus.PROVEN
    assert result.hardRpoClaimPermitted is True
    assert elapsed < 10.0


def test_explicit_now_is_required_canonical_and_no_hidden_clock():
    evidence = make_evidence()
    for invalid in (
            None, True, 0, "now", "2026-08-15T01:00:00+00:00",
            "2026-08-15T01:00:00.000Z"):
        result = assert_not_proven(evidence, now=invalid)
        assert result.reasonCodes == (proof.ReasonCode.INVALID_NOW,)
    assert proof.evaluate_recovery_proof(
        evidence, make_policy(), NOW).status is proof.ProofStatus.PROVEN


def test_evaluation_and_transcript_are_byte_deterministic():
    evidence = make_evidence(((11, 12), (13, 15)))
    policy = make_policy()
    first = proof.evaluate_recovery_proof(evidence, policy, NOW)
    second = proof.evaluate_recovery_proof(evidence, policy, NOW)
    assert first == second
    assert proof.proof_transcript_canonical_bytes(first) == \
        proof.proof_transcript_canonical_bytes(second)
    document = proof.proof_transcript_document(first)
    assert set(document) == {
        "schemaVersion", "checkedPredicateIds", "outcomeCodes",
        "hardRpoOutcomeCodes", "policySchemaVersion",
        "freshnessPolicyVersion", "evidenceDigest", "manifestIdentity",
        "generationId",
    }
    assert len(proof.proof_transcript_canonical_bytes(first)) < 4096


def test_determinism_across_python_hash_seeds():
    script = """
import json
import argus_recovery_proof as p
import test_argus_recovery_proof as t
e = t.make_evidence(((11, 12), (13, 15)))
r = p.evaluate_recovery_proof(e, t.make_policy(), t.NOW)
print(json.dumps({"result": p.proof_result_document(r),
                  "transcript": p.proof_transcript_document(r)},
                 sort_keys=True, separators=(",", ":")))
"""
    outputs = []
    for seed in ("0", "1", "42", "random"):
        environment = dict(os.environ)
        environment["PYTHONHASHSEED"] = seed
        environment["PYTHONPYCACHEPREFIX"] = \
            "/private/tmp/argus-prd-subprocess-pycache"
        completed = subprocess.run(
            [sys.executable, "-c", script], check=True,
            cwd=Path(__file__).parent, env=environment,
            capture_output=True, text=True,
        )
        outputs.append(completed.stdout.strip())
    assert len(set(outputs)) == 1


def test_library_has_no_io_authority_selection_or_hidden_runtime_inputs():
    source = inspect.getsource(proof)
    forbidden = (
        "import scanner", "import requests", "import socket", "import random",
        "os.getenv", "os.environ", "datetime.now", "time.time", "open(",
        "latest authority", "fallback_to_previous",
    )
    assert not [token for token in forbidden if token in source]
    assert "argus_recovery_measurement" not in source
    assert "registry.registry_policy_sha256()" in source


def test_reason_and_transcript_outputs_never_contain_raw_exception_or_state():
    sentinel = "OWNER-SECRET-STATE-7b8d"
    result = proof.evaluate_recovery_proof(
        {"tagVerified": True, "ownerState": sentinel}, make_policy(), NOW)
    encoded = json.dumps({
        "result": proof.proof_result_document(result),
        "transcript": proof.proof_transcript_document(result),
    }, sort_keys=True)
    assert sentinel not in encoded
    assert "tagVerified" not in encoded
    assert "exception" not in encoded.lower()
