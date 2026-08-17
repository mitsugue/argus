"""Round 2A Decision Evidence Bundle contract.

This module is deliberately a pure, public-safe producer/validator.  It has no
scanner, route, storage, registry, recovery, UI, or authority wiring.  It also
does not choose an action.  The only action vocabulary exported here is the
closed vocabulary reserved for a separately approved future authority.

Decimal fact values are canonical decimal strings rather than JSON floats.
That keeps the content address byte-identical in Python and JavaScript while
still rejecting non-finite values and pseudo-precision.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Iterable, List, Mapping, Sequence


SCHEMA_VERSION = "decision-evidence-bundle-v1"
PRIMARY_ACTIONS = ("BUY", "HOLD", "WAIT", "REDUCE", "EXIT")

MAX_FACTS = 32
MAX_MISSING_REASON_CODES = 12
MAX_CONFLICT_REASON_CODES = 12
MAX_SUPPORTING_FACT_REFS = 8
MAX_CANONICAL_BODY_BYTES = 64 * 1024
MAX_SAFE_INTEGER = 9_007_199_254_740_991
MAX_ABS_DECIMAL = Decimal("1000000000000")

SUBJECT_KINDS = ("ASSET",)
MARKETS = ("JP", "US", "CRYPTO", "FUND")
HORIZONS = ("INTRADAY", "ONE_DAY", "FIVE_DAY", "TWENTY_DAY", "LONG_TERM")
FACT_KINDS = (
    "PRICE_STATE",
    "MARKET_STATE",
    "FLOW_STATE",
    "TREND_STATE",
    "EVENT_STATE",
    "DISCLOSURE_STATE",
    "DATA_QUALITY",
    "VISIBILITY",
    "CALIBRATION",
    "RISK_FLAG",
    "POLICY_CONSTRAINT",
    "LEGACY_SIGNAL",
)
FACT_ROLES = ("OBSERVATION", "DERIVED_SIGNAL", "POLICY_CONSTRAINT", "MISSINGNESS")
VALUE_TYPES = ("BOOL", "INTEGER", "DECIMAL", "ENUM", "TIMESTAMP")
FACT_UNITS = (
    "NONE",
    "PERCENT",
    "BASIS_POINTS",
    "COUNT",
    "RATIO_BPS",
    "CURRENCY_MINOR",
    "PRICE",
    "SECONDS",
    "MILLISECONDS",
    "BYTES",
)
FRESHNESS_VALUES = ("FRESH", "DELAYED", "STALE", "UNKNOWN")
QUALITY_VALUES = ("VERIFIED", "SUPPORTED", "UNRESOLVED", "CONFLICT", "UNAVAILABLE")

_TOP_KEYS = {
    "schemaVersion",
    "bundleId",
    "privacyClass",
    "subject",
    "horizon",
    "asOf",
    "informationCutoffAt",
    "identities",
    "facts",
    "missingReasonCodes",
    "conflictReasonCodes",
}
_SUBJECT_KEYS = {"kind", "instrumentId", "market"}
_IDENTITY_KEYS = {
    "producerBuildSha",
    "evidencePolicyId",
    "evidencePolicySha256",
    "generationId",
}
_FACT_KEYS = {
    "factId",
    "kind",
    "role",
    "valueType",
    "value",
    "unit",
    "observedAt",
    "freshness",
    "quality",
    "sourceRef",
}

_BUNDLE_ID_RE = re.compile(r"deb-[0-9a-f]{64}\Z")
_SHA40_RE = re.compile(r"[0-9a-f]{40}\Z")
_SHA64_RE = re.compile(r"[0-9a-f]{64}\Z")
_INSTRUMENT_RE = re.compile(r"[A-Z0-9][A-Z0-9._:-]{0,31}\Z")
_IDENTIFIER_RE = re.compile(r"[a-z0-9][a-z0-9._:-]{0,63}\Z")
_FACT_ID_RE = re.compile(r"[a-z0-9][a-z0-9._:-]{0,63}\Z")
_SOURCE_REF_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@/-]{0,95}\Z")
_REASON_RE = re.compile(r"[a-z0-9][a-z0-9._:-]{0,63}\Z")
_ENUM_RE = re.compile(r"[A-Z][A-Z0-9_:-]{0,31}\Z")
_DECIMAL_RE = re.compile(r"-?(?:0|[1-9][0-9]{0,12})(?:\.[0-9]{1,8})?\Z")
_UTC_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z\Z")


class DecisionEvidenceValidationError(ValueError):
    """Raised when an evidence bundle violates the closed contract."""


def _fail(path: str, message: str) -> None:
    raise DecisionEvidenceValidationError(f"{path}: {message}")


def _exact_mapping(value: Any, keys: set[str], path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(path, "must be an object")
    actual = set(value.keys())
    if actual != keys:
        missing = sorted(keys - actual)
        extra = sorted(actual - keys)
        _fail(path, f"keys must be exact; missing={missing}, extra={extra}")
    return value


def _utc(value: Any, path: str) -> datetime:
    if not isinstance(value, str) or not _UTC_RE.fullmatch(value):
        _fail(path, "must be an exact UTC timestamp with whole-second precision")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise DecisionEvidenceValidationError(f"{path}: invalid UTC timestamp") from exc
    return parsed


def _reason_codes(value: Any, *, path: str, cap: int) -> List[str]:
    if not isinstance(value, list):
        _fail(path, "must be an array")
    if len(value) > cap:
        _fail(path, f"must contain at most {cap} codes")
    if any(not isinstance(code, str) or not _REASON_RE.fullmatch(code) for code in value):
        _fail(path, "contains a malformed reason code")
    if value != sorted(set(value)):
        _fail(path, "must be sorted and duplicate-free")
    return value


def _validate_decimal(value: Any, path: str) -> None:
    if not isinstance(value, str) or not _DECIMAL_RE.fullmatch(value):
        _fail(path, "must be a canonical finite decimal string")
    if value == "-0" or ("." in value and value.endswith("0")):
        _fail(path, "must not contain negative zero or trailing fractional zeroes")
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise DecisionEvidenceValidationError(f"{path}: invalid decimal") from exc
    if not number.is_finite() or abs(number) > MAX_ABS_DECIMAL:
        _fail(path, f"must be finite and within +/-{MAX_ABS_DECIMAL}")


def _validate_fact(fact: Any, *, index: int, cutoff: datetime) -> None:
    path = f"facts[{index}]"
    item = _exact_mapping(fact, _FACT_KEYS, path)
    if not isinstance(item["factId"], str) or not _FACT_ID_RE.fullmatch(item["factId"]):
        _fail(f"{path}.factId", "malformed fact identifier")
    if item["kind"] not in FACT_KINDS:
        _fail(f"{path}.kind", "unknown fact kind")
    if item["role"] not in FACT_ROLES:
        _fail(f"{path}.role", "unknown fact role")
    if item["valueType"] not in VALUE_TYPES:
        _fail(f"{path}.valueType", "unknown scalar value type")
    if item["unit"] not in FACT_UNITS:
        _fail(f"{path}.unit", "unknown unit")
    if item["freshness"] not in FRESHNESS_VALUES:
        _fail(f"{path}.freshness", "unknown freshness")
    if item["quality"] not in QUALITY_VALUES:
        _fail(f"{path}.quality", "unknown quality")
    if (not isinstance(item["sourceRef"], str)
            or not _SOURCE_REF_RE.fullmatch(item["sourceRef"])
            or "://" in item["sourceRef"]):
        _fail(f"{path}.sourceRef", "must be a bounded identifier, never a URL or payload")
    observed = _utc(item["observedAt"], f"{path}.observedAt")
    if observed > cutoff:
        _fail(f"{path}.observedAt", "cannot be later than informationCutoffAt")

    value_type = item["valueType"]
    value = item["value"]
    if value_type == "BOOL":
        if not isinstance(value, bool):
            _fail(f"{path}.value", "BOOL requires a boolean")
    elif value_type == "INTEGER":
        if isinstance(value, bool) or not isinstance(value, int) or abs(value) > MAX_SAFE_INTEGER:
            _fail(f"{path}.value", "INTEGER requires a JavaScript-safe integer")
    elif value_type == "DECIMAL":
        _validate_decimal(value, f"{path}.value")
    elif value_type == "ENUM":
        if not isinstance(value, str) or not _ENUM_RE.fullmatch(value):
            _fail(f"{path}.value", "ENUM requires a bounded uppercase token")
    elif value_type == "TIMESTAMP":
        if _utc(value, f"{path}.value") > cutoff:
            _fail(f"{path}.value", "timestamp fact cannot be later than informationCutoffAt")


def _body_from_bundle(bundle: Mapping[str, Any]) -> Dict[str, Any]:
    return {key: copy.deepcopy(value) for key, value in bundle.items() if key != "bundleId"}


def _canonical_json_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise DecisionEvidenceValidationError("bundle is not canonical JSON") from exc


def compute_bundle_id(bundle_or_body: Mapping[str, Any]) -> str:
    """Return the content address over the canonical body (bundleId excluded)."""
    body = _body_from_bundle(bundle_or_body)
    return "deb-" + hashlib.sha256(_canonical_json_bytes(body)).hexdigest()


def validate_decision_evidence_bundle(bundle: Any) -> None:
    """Strictly validate shape, bounds, temporal order, and content address."""
    top = _exact_mapping(bundle, _TOP_KEYS, "bundle")
    if top["schemaVersion"] != SCHEMA_VERSION:
        _fail("schemaVersion", f"must equal {SCHEMA_VERSION}")
    if top["privacyClass"] != "PUBLIC_EVIDENCE":
        _fail("privacyClass", "must equal PUBLIC_EVIDENCE")
    if not isinstance(top["bundleId"], str) or not _BUNDLE_ID_RE.fullmatch(top["bundleId"]):
        _fail("bundleId", "must be deb- followed by a lowercase SHA-256")

    subject = _exact_mapping(top["subject"], _SUBJECT_KEYS, "subject")
    if subject["kind"] not in SUBJECT_KINDS:
        _fail("subject.kind", "only the asset subject is defined in v1")
    if not isinstance(subject["instrumentId"], str) or not _INSTRUMENT_RE.fullmatch(subject["instrumentId"]):
        _fail("subject.instrumentId", "must be a normalized bounded public identifier")
    if subject["market"] not in MARKETS:
        _fail("subject.market", "unknown market")
    if top["horizon"] not in HORIZONS:
        _fail("horizon", "unknown horizon")

    as_of = _utc(top["asOf"], "asOf")
    cutoff = _utc(top["informationCutoffAt"], "informationCutoffAt")
    if cutoff > as_of:
        _fail("informationCutoffAt", "cannot be later than asOf")

    identities = _exact_mapping(top["identities"], _IDENTITY_KEYS, "identities")
    if not isinstance(identities["producerBuildSha"], str) or not _SHA40_RE.fullmatch(identities["producerBuildSha"]):
        _fail("identities.producerBuildSha", "must be an exact lowercase 40-hex build SHA")
    if not isinstance(identities["evidencePolicyId"], str) or not _IDENTIFIER_RE.fullmatch(identities["evidencePolicyId"]):
        _fail("identities.evidencePolicyId", "malformed policy identifier")
    if not isinstance(identities["evidencePolicySha256"], str) or not _SHA64_RE.fullmatch(identities["evidencePolicySha256"]):
        _fail("identities.evidencePolicySha256", "must be an exact lowercase SHA-256")
    if not isinstance(identities["generationId"], str) or not _IDENTIFIER_RE.fullmatch(identities["generationId"]):
        _fail("identities.generationId", "malformed generation identifier")

    facts = top["facts"]
    if not isinstance(facts, list):
        _fail("facts", "must be an array")
    if len(facts) > MAX_FACTS:
        _fail("facts", f"must contain at most {MAX_FACTS} facts")
    for index, fact in enumerate(facts):
        _validate_fact(fact, index=index, cutoff=cutoff)
    fact_ids = [fact["factId"] for fact in facts]
    if fact_ids != sorted(set(fact_ids)):
        _fail("facts", "must be sorted by factId and duplicate-free")

    missing = _reason_codes(
        top["missingReasonCodes"], path="missingReasonCodes", cap=MAX_MISSING_REASON_CODES)
    conflicts = _reason_codes(
        top["conflictReasonCodes"], path="conflictReasonCodes", cap=MAX_CONFLICT_REASON_CODES)
    if not facts and not missing and not conflicts:
        _fail("bundle", "must contain a fact or an explicit missing/conflict reason")

    if len(_canonical_json_bytes(_body_from_bundle(top))) > MAX_CANONICAL_BODY_BYTES:
        _fail("bundle", f"canonical body exceeds {MAX_CANONICAL_BODY_BYTES} bytes")

    expected = compute_bundle_id(top)
    if top["bundleId"] != expected:
        _fail("bundleId", "does not match the canonical bundle body")


def canonical_bundle_body_bytes(bundle: Mapping[str, Any]) -> bytes:
    """Return validated canonical body bytes used by both language mirrors."""
    validate_decision_evidence_bundle(bundle)
    return _canonical_json_bytes(_body_from_bundle(bundle))


def build_decision_evidence_bundle(
    *,
    instrument_id: str,
    market: str,
    horizon: str,
    as_of: str,
    information_cutoff_at: str,
    producer_build_sha: str,
    evidence_policy_id: str,
    evidence_policy_sha256: str,
    generation_id: str,
    facts: Sequence[Mapping[str, Any]],
    missing_reason_codes: Iterable[str] = (),
    conflict_reason_codes: Iterable[str] = (),
) -> Dict[str, Any]:
    """Build one immutable-by-convention, public-safe content-addressed bundle.

    Input collections are copied.  Facts are sorted by factId and reason codes
    are sorted/deduplicated before strict validation.  Unknown fact fields are
    rejected rather than projected away.
    """
    copied_facts = [copy.deepcopy(dict(fact)) for fact in facts]
    copied_facts.sort(key=lambda fact: str(fact.get("factId", "")))
    body: Dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "privacyClass": "PUBLIC_EVIDENCE",
        "subject": {
            "kind": "ASSET",
            "instrumentId": instrument_id,
            "market": market,
        },
        "horizon": horizon,
        "asOf": as_of,
        "informationCutoffAt": information_cutoff_at,
        "identities": {
            "producerBuildSha": producer_build_sha,
            "evidencePolicyId": evidence_policy_id,
            "evidencePolicySha256": evidence_policy_sha256,
            "generationId": generation_id,
        },
        "facts": copied_facts,
        "missingReasonCodes": sorted(set(missing_reason_codes)),
        "conflictReasonCodes": sorted(set(conflict_reason_codes)),
    }
    bundle = {**body, "bundleId": compute_bundle_id(body)}
    validate_decision_evidence_bundle(bundle)
    return bundle


__all__ = [
    "DecisionEvidenceValidationError",
    "SCHEMA_VERSION",
    "PRIMARY_ACTIONS",
    "MAX_FACTS",
    "MAX_MISSING_REASON_CODES",
    "MAX_CONFLICT_REASON_CODES",
    "MAX_SUPPORTING_FACT_REFS",
    "MAX_CANONICAL_BODY_BYTES",
    "build_decision_evidence_bundle",
    "canonical_bundle_body_bytes",
    "compute_bundle_id",
    "validate_decision_evidence_bundle",
]
