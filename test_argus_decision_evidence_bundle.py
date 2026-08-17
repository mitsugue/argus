"""Round 2A Decision Evidence Bundle contract tests.

The contract is content-addressed, scalar-only, public-safe and detached from all
runtime authority/storage paths.  The same fixed hash is asserted by the browser
contract test to catch Python/TypeScript canonicalization drift.
"""
from __future__ import annotations

import ast
import copy
import json
from pathlib import Path

import pytest

import argus_decision_evidence_bundle as DEB


EXPECTED_BUNDLE_ID = "deb-15a6b23889b84f7598ee1e5cc16216531949882a6d88a656d925d2309561ee24"


def facts():
    return [
        {
            "factId": "data.quality",
            "kind": "DATA_QUALITY",
            "role": "POLICY_CONSTRAINT",
            "valueType": "ENUM",
            "value": "LIVE",
            "unit": "NONE",
            "observedAt": "2026-08-15T09:59:00Z",
            "freshness": "FRESH",
            "quality": "VERIFIED",
            "sourceRef": "argus:data-quality:7203",
        },
        {
            "factId": "price.change_pct",
            "kind": "PRICE_STATE",
            "role": "OBSERVATION",
            "valueType": "DECIMAL",
            "value": "-2.35",
            "unit": "PERCENT",
            "observedAt": "2026-08-15T09:58:00Z",
            "freshness": "FRESH",
            "quality": "VERIFIED",
            "sourceRef": "ep-7203-20260815",
        },
        {
            "factId": "visibility.entry_blocked",
            "kind": "VISIBILITY",
            "role": "POLICY_CONSTRAINT",
            "valueType": "BOOL",
            "value": True,
            "unit": "NONE",
            "observedAt": "2026-08-15T09:57:00Z",
            "freshness": "FRESH",
            "quality": "SUPPORTED",
            "sourceRef": "visibility-guard:7203",
        },
    ]


def build(**overrides):
    args = {
        "instrument_id": "7203",
        "market": "JP",
        "horizon": "FIVE_DAY",
        "as_of": "2026-08-15T10:00:00Z",
        "information_cutoff_at": "2026-08-15T09:59:00Z",
        "producer_build_sha": "a" * 40,
        "evidence_policy_id": "round2a-evidence-v1",
        "evidence_policy_sha256": "b" * 64,
        "generation_id": "generation-20260815",
        "facts": facts(),
        "missing_reason_codes": ["market_depth_unavailable"],
        "conflict_reason_codes": [],
    }
    args.update(overrides)
    return DEB.build_decision_evidence_bundle(**args)


def test_exact_closed_action_vocabulary_is_contract_only():
    assert DEB.PRIMARY_ACTIONS == ("BUY", "HOLD", "WAIT", "REDUCE", "EXIT")
    assert len(set(DEB.PRIMARY_ACTIONS)) == 5
    assert not hasattr(DEB, "evaluate")
    assert not hasattr(DEB, "activate")


def test_fixed_cross_language_content_address_and_canonical_body():
    bundle = build()
    assert bundle["bundleId"] == EXPECTED_BUNDLE_ID
    DEB.validate_decision_evidence_bundle(bundle)
    body = DEB.canonical_bundle_body_bytes(bundle)
    assert body == json.dumps(
        {key: value for key, value in bundle.items() if key != "bundleId"},
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    assert DEB.compute_bundle_id(bundle) == EXPECTED_BUNDLE_ID


def test_builder_is_order_invariant_and_copies_inputs():
    original_facts = list(reversed(facts()))
    missing = ["source_unavailable", "market_depth_unavailable", "source_unavailable"]
    bundle = build(facts=original_facts, missing_reason_codes=missing)
    again = build(facts=facts(), missing_reason_codes=["market_depth_unavailable", "source_unavailable"])
    assert bundle == again
    assert [fact["factId"] for fact in bundle["facts"]] == sorted(
        fact["factId"] for fact in original_facts)
    assert bundle["missingReasonCodes"] == ["market_depth_unavailable", "source_unavailable"]
    original_facts[0]["value"] = False
    missing.append("late_mutation")
    assert bundle == again


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("producer_build_sha", "c" * 40),
        ("evidence_policy_id", "round2a-evidence-v2"),
        ("evidence_policy_sha256", "d" * 64),
        ("generation_id", "generation-20260816"),
        ("horizon", "TWENTY_DAY"),
    ],
)
def test_identity_or_horizon_drift_changes_bundle_id(field, replacement):
    assert build(**{field: replacement})["bundleId"] != EXPECTED_BUNDLE_ID


def test_mutation_after_content_address_is_rejected():
    bundle = build()
    bundle["facts"][1]["value"] = "-2.34"
    with pytest.raises(DEB.DecisionEvidenceValidationError, match="bundleId"):
        DEB.validate_decision_evidence_bundle(bundle)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda b: b.__setitem__("callerAction", "EXIT"),
        lambda b: b["subject"].__setitem__("symbolName", "private note"),
        lambda b: b["identities"].__setitem__("enabled", True),
        lambda b: b["facts"][0].__setitem__("rawPayload", {"action": "EXIT"}),
    ],
)
def test_unknown_fields_are_rejected_at_every_boundary(mutate):
    bundle = build()
    mutate(bundle)
    with pytest.raises(DEB.DecisionEvidenceValidationError, match="keys must be exact"):
        DEB.validate_decision_evidence_bundle(bundle)


@pytest.mark.parametrize("private_field", [
    "quantity", "costBasis", "pricePaid", "pnl", "returnPct", "holdings", "ownerId",
])
def test_private_owner_fields_cannot_enter_public_fact(private_field):
    hostile = facts()
    hostile[0][private_field] = 100
    with pytest.raises(DEB.DecisionEvidenceValidationError, match="keys must be exact"):
        build(facts=hostile)


def test_bundle_privacy_class_is_explicitly_public_only():
    bundle = build()
    bundle["privacyClass"] = "DEVICE_LOCAL"
    bundle["bundleId"] = DEB.compute_bundle_id(bundle)
    with pytest.raises(DEB.DecisionEvidenceValidationError, match="PUBLIC_EVIDENCE"):
        DEB.validate_decision_evidence_bundle(bundle)


def test_fact_and_reason_caps_are_exact():
    template = facts()[0]
    capped = [{**template, "factId": f"fact.{index:02d}"} for index in range(DEB.MAX_FACTS)]
    DEB.validate_decision_evidence_bundle(build(facts=capped))
    with pytest.raises(DEB.DecisionEvidenceValidationError, match="at most 32"):
        build(facts=capped + [{**template, "factId": "fact.32"}])
    with pytest.raises(DEB.DecisionEvidenceValidationError, match="at most 12"):
        build(missing_reason_codes=[f"missing.{index:02d}" for index in range(13)])
    with pytest.raises(DEB.DecisionEvidenceValidationError, match="at most 12"):
        build(conflict_reason_codes=[f"conflict.{index:02d}" for index in range(13)])
    assert DEB.MAX_SUPPORTING_FACT_REFS == 8
    assert DEB.MAX_CANONICAL_BODY_BYTES == 64 * 1024


def fact_with(value_type, value, *, unit="NONE"):
    row = copy.deepcopy(facts()[0])
    row.update({"valueType": value_type, "value": value, "unit": unit})
    return row


@pytest.mark.parametrize(
    ("value_type", "value"),
    [
        ("BOOL", True),
        ("INTEGER", 42),
        ("DECIMAL", "0.125"),
        ("ENUM", "PARTIAL"),
        ("TIMESTAMP", "2026-08-15T09:58:00Z"),
    ],
)
def test_each_scalar_type_is_supported_without_nested_payload(value_type, value):
    DEB.validate_decision_evidence_bundle(build(facts=[fact_with(value_type, value)]))


@pytest.mark.parametrize(
    ("value_type", "value"),
    [
        ("BOOL", 1),
        ("INTEGER", True),
        ("INTEGER", 9_007_199_254_740_992),
        ("DECIMAL", -2.35),
        ("DECIMAL", "NaN"),
        ("DECIMAL", "Infinity"),
        ("DECIMAL", "1.2300"),
        ("DECIMAL", "-0"),
        ("DECIMAL", "1000000000000.1"),
        ("ENUM", "free form prose"),
        ("TIMESTAMP", "2026-08-15T09:58:00+00:00"),
        ("TIMESTAMP", {"nested": "payload"}),
    ],
)
def test_malformed_noncanonical_or_nested_scalars_fail(value_type, value):
    with pytest.raises(DEB.DecisionEvidenceValidationError):
        build(facts=[fact_with(value_type, value)])


def test_temporal_boundaries_are_fail_closed():
    with pytest.raises(DEB.DecisionEvidenceValidationError, match="later than asOf"):
        build(information_cutoff_at="2026-08-15T10:00:01Z")
    late_fact = facts()
    late_fact[0]["observedAt"] = "2026-08-15T10:00:00Z"
    with pytest.raises(DEB.DecisionEvidenceValidationError, match="informationCutoffAt"):
        build(facts=late_fact)
    with pytest.raises(DEB.DecisionEvidenceValidationError, match="whole-second precision"):
        build(as_of="2026-08-15T10:00:00.123Z")


def test_source_refs_are_identifiers_not_urls_or_payloads():
    hostile = facts()
    hostile[0]["sourceRef"] = "https://provider.test/raw"
    with pytest.raises(DEB.DecisionEvidenceValidationError, match="sourceRef"):
        build(facts=hostile)
    hostile[0]["sourceRef"] = "headline with arbitrary prose"
    with pytest.raises(DEB.DecisionEvidenceValidationError, match="sourceRef"):
        build(facts=hostile)


def test_silent_empty_bundle_is_rejected_but_explicit_missing_is_valid():
    with pytest.raises(DEB.DecisionEvidenceValidationError, match="explicit missing"):
        build(facts=[], missing_reason_codes=[])
    bundle = build(facts=[], missing_reason_codes=["all_sources_unavailable"])
    DEB.validate_decision_evidence_bundle(bundle)


def test_unsorted_or_duplicate_semantic_arrays_are_rejected():
    bundle = build()
    bundle["facts"].reverse()
    bundle["bundleId"] = DEB.compute_bundle_id(bundle)
    with pytest.raises(DEB.DecisionEvidenceValidationError, match="sorted"):
        DEB.validate_decision_evidence_bundle(bundle)
    bundle = build()
    bundle["missingReasonCodes"] = ["source_unavailable", "market_depth_unavailable"]
    bundle["bundleId"] = DEB.compute_bundle_id(bundle)
    with pytest.raises(DEB.DecisionEvidenceValidationError, match="sorted"):
        DEB.validate_decision_evidence_bundle(bundle)


def test_module_is_pure_and_has_no_runtime_integration_imports():
    source_path = Path(DEB.__file__)
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_roots = {
        node.names[0].name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
    } | {
        (node.module or "").split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    assert imported_roots <= {
        "__future__", "copy", "hashlib", "json", "re", "datetime", "decimal", "typing",
    }
    called_names = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert called_names.isdisjoint({
        "open", "urlopen", "request", "connect", "send", "write", "replace",
    })
