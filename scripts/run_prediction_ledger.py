#!/usr/bin/env python3
"""Offline, fail-closed Prediction Ledger v2 segment runner.

The runner has no network or provider credentials.  It accepts the additive
``canonicalPredictionLedger`` projection emitted by the existing prediction
snapshot route, verifies every sealed input, resolves only exact target-session
truth, and writes one immutable hash-chained segment plus bounded derived state.

Historical segments are the authority.  The pending index, aggregate, and
manifest are rebuildable bounded projections and are never scanned as history.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

import argus_calibration  # noqa: E402
import argus_decision_ledger as decision_ledger  # noqa: E402
import argus_market_data_truth as market_truth  # noqa: E402


SEGMENT_SCHEMA = "argus-prediction-ledger-segment-v1"
INDEX_SCHEMA = "argus-prediction-ledger-index-v1"
AGGREGATE_SCHEMA = "argus-prediction-ledger-aggregate-v1"
MANIFEST_SCHEMA = "argus-prediction-ledger-manifest-v1"

SUPPORTED_MODE = "forward_live"
SUPPORTED_CLASS_ORDER_VERSION = (
    f"{argus_calibration.SCHEMA_VERSION}:{argus_calibration.BAND_VERSION}")
SCENARIO_DOWNSIDE_TARGET_ID = "scenario.downside_boundary"
SCENARIO_REBOUND_TARGET_ID = "scenario.rebound_boundary"
RESOLUTION_METHOD_VERSION = "exact-target-session-ohlc-v1"
EVALUATION_METHOD_VERSION = "prediction-ledger-calibration-v1"

MAX_INPUT_BYTES = 16 * 1024 * 1024
MAX_SEGMENT_BYTES = 16 * 1024 * 1024
MAX_INDEX_BYTES = 16 * 1024 * 1024
MAX_AGGREGATE_BYTES = 1024 * 1024
MAX_MANIFEST_BYTES = 128 * 1024
MAX_OUTCOME_OBSERVATIONS = 1024
MAX_ISSUED_DECISIONS = 192
MAX_PENDING_RECORDS = 4096
MAX_IDENTITY_RECORDS = 8192
MAX_AGGREGATE_METRICS = 256
MAX_RESOLUTION_ATTEMPTS = 8
MAX_PENDING_SOURCE_SEGMENTS = 512
MAX_PENDING_AUTHORITY_BYTES = 64 * 1024 * 1024

_SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


class LedgerRunError(ValueError):
    """A fail-closed input, integrity, bound, or persistence error."""


def _canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise LedgerRunError("non_canonical_json") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _sealed_document(body: Mapping[str, Any]) -> Dict[str, Any]:
    output = copy.deepcopy(dict(body))
    output["digest"] = _digest(output)
    return output


def _verify_document(value: Any, *, schema: str,
                     record_type: str) -> Dict[str, Any]:
    if not isinstance(value, dict) or value.get("schemaVersion") != schema or \
            value.get("recordType") != record_type:
        raise LedgerRunError(f"invalid_{record_type}_shape")
    material = copy.deepcopy(value)
    supplied = material.pop("digest", None)
    if not isinstance(supplied, str) or supplied != _digest(material):
        raise LedgerRunError(f"invalid_{record_type}_digest")
    return copy.deepcopy(value)


def _verify_segment(value: Any) -> Dict[str, Any]:
    document = _verify_document(
        value, schema=SEGMENT_SCHEMA,
        record_type="immutable_prediction_segment")
    material = copy.deepcopy(document)
    material.pop("digest", None)
    supplied_id = material.pop("segmentId", None)
    if supplied_id != "pls-" + _digest(material)[:32]:
        raise LedgerRunError("invalid_segment_id")
    if document.get("mode") != SUPPORTED_MODE or \
            not _RUN_ID_RE.fullmatch(str(document.get("runId") or "")) or \
            not _SHA40_RE.fullmatch(str(document.get("runnerBuildSha") or "")) or \
            not _SHA40_RE.fullmatch(str(document.get("producerBuildSha") or "")) or \
            not re.fullmatch(r"[0-9a-f]{64}", str(
                document.get("inputDigest") or "")):
        raise LedgerRunError("invalid_segment_identity")
    _parse_time(document.get("runAt"), "segment_run_at")
    previous = document.get("previousSegment")
    if previous is not None and (not isinstance(previous, dict) or set(
            previous) != {"path", "segmentId", "digest", "runId"}):
        raise LedgerRunError("invalid_segment_predecessor_reference")
    decisions = document.get("issuedDecisions")
    outcomes = document.get("outcomeResolutions")
    evaluations = document.get("evaluationEvents")
    if not all(isinstance(rows, list) for rows in
               (decisions, outcomes, evaluations)):
        raise LedgerRunError("invalid_segment_records")
    if any(not decision_ledger.verify_prediction_record_v2(record) or
           record.get("mode") != SUPPORTED_MODE for record in decisions):
        raise LedgerRunError("invalid_segment_prediction")
    if any(not decision_ledger.verify_outcome_resolution_event(record) or
           record.get("mode") != SUPPORTED_MODE for record in outcomes):
        raise LedgerRunError("invalid_segment_outcome")
    if any(not decision_ledger.verify_evaluation_event(record) or
           record.get("mode") != SUPPORTED_MODE for record in evaluations):
        raise LedgerRunError("invalid_segment_evaluation")
    counts = document.get("counts") or {}
    if counts.get("issued") != len(decisions) or \
            counts.get("outcomes") != len(outcomes) or \
            counts.get("evaluations") != len(evaluations) or \
            not isinstance(counts.get("pendingAfter"), int) or \
            isinstance(counts.get("pendingAfter"), bool) or \
            not 0 <= counts.get("pendingAfter") <= MAX_PENDING_RECORDS:
        raise LedgerRunError("segment_count_mismatch")
    truth_evidence = document.get("truthEvidence") or {}
    decision_snapshot = truth_evidence.get("decisionSnapshot")
    valid_snapshot, _ = market_truth.verify_decision_snapshot(
        decision_snapshot)
    outcome_observations = truth_evidence.get("outcomeObservations")
    if not valid_snapshot or not isinstance(outcome_observations, list) or \
            len(outcome_observations) > MAX_OUTCOME_OBSERVATIONS or \
            any(not market_truth.validate_observation(row)[0]
                for row in outcome_observations) or \
            truth_evidence.get("outcomeBundleDigest") != \
            _digest(outcome_observations):
        raise LedgerRunError("invalid_segment_truth_evidence")
    return document


def _parse_time(value: Any, field: str) -> datetime:
    text = str(value or "").strip()
    if not text or len(text) == 10:
        raise LedgerRunError(f"invalid_{field}")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise LedgerRunError(f"invalid_{field}") from exc
    if parsed.tzinfo is None:
        raise LedgerRunError(f"timezone_required_{field}")
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _same_instant(left: Any, right: Any) -> bool:
    try:
        return _parse_time(left, "left_time") == _parse_time(
            right, "right_time")
    except LedgerRunError:
        return False


def _finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) \
        and math.isfinite(float(value))


def _read_json(path: Path, *, maximum: int = MAX_INPUT_BYTES) -> Any:
    try:
        if path.stat().st_size > maximum:
            raise LedgerRunError(f"json_too_large:{path.name}")
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except LedgerRunError:
        raise
    except (OSError, json.JSONDecodeError) as exc:
        raise LedgerRunError(f"invalid_json:{path.name}") from exc


def _bounded_payload(value: Any, *, maximum: int, error: str) -> bytes:
    payload = _canonical_bytes(value) + b"\n"
    if len(payload) > maximum:
        raise LedgerRunError(error)
    return payload


def _atomic_write(path: Path, value: Any, *, maximum: int,
                  overflow_error: str) -> None:
    _ensure_directory(path.parent)
    payload = _bounded_payload(
        value, maximum=maximum, error=overflow_error)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
                mode="wb", dir=str(path.parent),
                prefix=f".{path.name}.", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(str(temporary), str(path))
        _fsync_directory(path.parent)
    except OSError as exc:
        raise LedgerRunError(f"state_write_failed:{path.name}") from exc
    finally:
        if temporary is not None and temporary.exists():
            try:
                temporary.unlink()
            except OSError:
                pass


def _write_immutable(path: Path, value: Any, *, maximum: int,
                     overflow_error: str) -> None:
    _ensure_directory(path.parent)
    payload = _bounded_payload(
        value, maximum=maximum, error=overflow_error)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
                mode="wb", dir=str(path.parent),
                prefix=f".{path.name}.install.", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        # A hard link publishes the already-fsynced inode atomically while
        # retaining O_EXCL semantics for immutable names.
        os.link(str(temporary), str(path))
        _fsync_directory(path.parent)
    except FileExistsError as exc:
        raise LedgerRunError("immutable_document_collision") from exc
    except OSError as exc:
        raise LedgerRunError("immutable_document_create_failed") from exc
    finally:
        if temporary is not None and temporary.exists():
            try:
                temporary.unlink()
            except OSError:
                pass


def _install_immutable_or_verify(
        path: Path, value: Any, *, maximum: int,
        overflow_error: str) -> None:
    """Install an immutable document, or accept an exact crash-recovery copy."""
    payload = _bounded_payload(
        value, maximum=maximum, error=overflow_error)
    if path.exists():
        existing = _read_json(path, maximum=maximum)
        if existing != value or _canonical_bytes(existing) + b"\n" != payload:
            raise LedgerRunError("immutable_document_collision")
        return
    try:
        _write_immutable(
            path, value, maximum=maximum, overflow_error=overflow_error)
    except LedgerRunError as exc:
        # A concurrent identical installer may win between exists() and link().
        if str(exc) != "immutable_document_collision" or not path.exists():
            raise
        existing = _read_json(path, maximum=maximum)
        if existing != value or _canonical_bytes(existing) + b"\n" != payload:
            raise


def _fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(str(path), os.O_RDONLY)
    except OSError as exc:
        raise LedgerRunError(f"directory_open_failed:{path.name}") from exc
    try:
        os.fsync(descriptor)
    except OSError as exc:
        raise LedgerRunError(f"directory_fsync_failed:{path.name}") from exc
    finally:
        os.close(descriptor)


def _ensure_directory(path: Path) -> None:
    missing: List[Path] = []
    cursor = path
    while not cursor.exists():
        missing.append(cursor)
        if cursor.parent == cursor:
            break
        cursor = cursor.parent
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise LedgerRunError(f"directory_create_failed:{path.name}") from exc
    if not path.is_dir():
        raise LedgerRunError(f"invalid_state_directory:{path.name}")
    # Persist both every new directory and its containing directory entry.
    for directory in reversed(missing):
        _fsync_directory(directory)
        _fsync_directory(directory.parent)


def _confined_path(root: Path, relative: Any, *, top: str) -> Path:
    """Resolve a manifest/index reference without permitting path escape."""
    text = str(relative or "")
    candidate_relative = Path(text)
    parts = candidate_relative.parts
    if not text or candidate_relative.is_absolute() or len(parts) < 2 or \
            parts[0] != top or any(part in ("", ".", "..") for part in parts):
        raise LedgerRunError(f"invalid_{top}_path")
    candidate = root.joinpath(*parts)
    try:
        candidate.resolve(strict=False).relative_to(root.resolve(strict=False))
    except ValueError as exc:
        raise LedgerRunError(f"invalid_{top}_path") from exc
    return candidate


def _empty_index() -> Dict[str, Any]:
    return {
        "identities": {},
        "pending": {},
        "evictedIdentityCount": 0,
    }


def _decode_index(value: Any) -> Dict[str, Any]:
    document = _verify_document(
        value, schema=INDEX_SCHEMA, record_type="bounded_record_index")
    if document.get("mode") != SUPPORTED_MODE:
        raise LedgerRunError("index_mode_mismatch")
    identities_raw = document.get("identities")
    pending_raw = document.get("pending")
    if not isinstance(identities_raw, list) or \
            not isinstance(pending_raw, list) or \
            len(identities_raw) > MAX_IDENTITY_RECORDS or \
            len(pending_raw) > MAX_PENDING_RECORDS:
        raise LedgerRunError("index_bound_exceeded")
    identities: Dict[str, Dict[str, Any]] = {}
    for row in identities_raw:
        if not isinstance(row, dict):
            raise LedgerRunError("invalid_identity_row")
        record_id = str(row.get("id") or "")
        integrity = str(row.get("integrityHash") or "")
        if not record_id or not integrity or record_id in identities:
            raise LedgerRunError("invalid_identity_row")
        _parse_time(row.get("registeredAt"), "identity_registered_at")
        identities[record_id] = copy.deepcopy(row)
    pending: Dict[str, Dict[str, Any]] = {}
    for row in pending_raw:
        if not isinstance(row, dict):
            raise LedgerRunError("invalid_pending_row")
        prediction = row.get("prediction")
        prediction_id = str(row.get("predictionId") or "")
        if prediction_id in pending or not prediction_id or \
                not decision_ledger.verify_prediction_record_v2(prediction) or \
                prediction.get("id") != prediction_id or \
                prediction.get("mode") != SUPPORTED_MODE or \
                not _finite_number(row.get("decisionPrice")) or \
                float(row["decisionPrice"]) <= 0:
            raise LedgerRunError("invalid_pending_row")
        attempts = row.get("attempts")
        sequence = row.get("sequence")
        if not isinstance(attempts, int) or isinstance(attempts, bool) or \
                attempts < 0 or not isinstance(sequence, int) or \
                isinstance(sequence, bool) or sequence < 0 or \
                attempts != sequence or attempts >= MAX_RESOLUTION_ATTEMPTS:
            raise LedgerRunError("invalid_pending_sequence")
        state = row.get("state")
        latest_outcome_id = row.get("latestOutcomeEventId")
        latest_outcome_hash = row.get("latestOutcomeIntegrityHash")
        if attempts == 0:
            if state != "pending_maturity" or latest_outcome_id is not None or \
                    latest_outcome_hash is not None:
                raise LedgerRunError("invalid_pending_state")
        else:
            latest_identity = identities.get(str(latest_outcome_id or "")) or {}
            if state != "retry_wait" or not latest_outcome_id or \
                    not latest_outcome_hash or \
                    latest_identity.get("recordType") != \
                    "outcome_resolution" or \
                    latest_identity.get("integrityHash") != \
                    latest_outcome_hash:
                raise LedgerRunError("invalid_pending_retry_identity")
        maturity = prediction.get("maturity") or {}
        if row.get("predictionIntegrityHash") != \
                prediction.get("integrityHash") or \
                row.get("targetSessionId") != maturity.get("targetSessionId") or \
                row.get("targetAt") != maturity.get("targetAt") or \
                row.get("maturityAt") != maturity.get("maturityAt"):
            raise LedgerRunError("pending_prediction_binding_mismatch")
        identity = identities.get(prediction_id) or {}
        if identity.get("recordType") != "issued_decision" or \
                identity.get("integrityHash") != \
                prediction.get("integrityHash"):
            raise LedgerRunError("pending_identity_binding_mismatch")
        pending[prediction_id] = copy.deepcopy(row)
    counts = document.get("counts") or {}
    if counts.get("identityCount") != len(identities) or \
            counts.get("pendingCount") != len(pending):
        raise LedgerRunError("index_count_mismatch")
    retention = document.get("retention") or {}
    evicted = retention.get("evictedIdentityCount")
    if not isinstance(evicted, int) or isinstance(evicted, bool) or evicted < 0:
        raise LedgerRunError("invalid_identity_retention")
    return {"identities": identities, "pending": pending,
            "evictedIdentityCount": evicted}


def _encode_index(state: Dict[str, Any], *, updated_at: str) -> Dict[str, Any]:
    identities = sorted(
        (copy.deepcopy(row) for row in state["identities"].values()),
        key=lambda row: row["id"])
    pending = sorted(
        (copy.deepcopy(row) for row in state["pending"].values()),
        key=lambda row: row["predictionId"])
    if len(identities) > MAX_IDENTITY_RECORDS:
        raise LedgerRunError("identity_index_overflow")
    if len(pending) > MAX_PENDING_RECORDS:
        raise LedgerRunError("pending_index_overflow")
    document = _sealed_document({
        "schemaVersion": INDEX_SCHEMA,
        "recordType": "bounded_record_index",
        "mode": SUPPORTED_MODE,
        "updatedAt": updated_at,
        "identities": identities,
        "pending": pending,
        "counts": {
            "identityCount": len(identities),
            "pendingCount": len(pending),
        },
        "retention": {
            "strategy": "recent_plus_pending_monotonic_replay_guard",
            "evictedIdentityCount": int(state.get(
                "evictedIdentityCount") or 0),
        },
        "bounds": {
            "maxIdentities": MAX_IDENTITY_RECORDS,
            "maxPending": MAX_PENDING_RECORDS,
            "overflowPolicy": (
                "prune_resolved_recent_with_monotonic_replay_guard"),
        },
    })
    _bounded_payload(
        document, maximum=MAX_INDEX_BYTES, error="index_too_large")
    return document


def _empty_aggregate() -> Dict[str, Any]:
    document = _sealed_document({
        "schemaVersion": AGGREGATE_SCHEMA,
        "recordType": "forward_live_calibration_aggregate",
        "mode": SUPPORTED_MODE,
        "purpose": "calibration",
        "updatedAt": None,
        "evaluationCount": 0,
        "unscorableCount": 0,
        "metrics": [],
        "bounds": {"maxMetrics": MAX_AGGREGATE_METRICS},
    })
    _bounded_payload(
        document, maximum=MAX_AGGREGATE_BYTES,
        error="aggregate_too_large")
    return document


def _segment_from_reference(root: Path, reference: Any, *, label: str) \
        -> Tuple[Path, Dict[str, Any]]:
    if not isinstance(reference, dict) or set(reference) != {
            "path", "segmentId", "digest", "runId"}:
        raise LedgerRunError(f"invalid_{label}_reference")
    path = _confined_path(root, reference.get("path"), top="segments")
    if not path.is_file():
        raise LedgerRunError(f"{label}_file_missing")
    document = _verify_segment(_read_json(path, maximum=MAX_SEGMENT_BYTES))
    if document.get("digest") != reference.get("digest") or \
            document.get("segmentId") != reference.get("segmentId") or \
            document.get("runId") != reference.get("runId"):
        raise LedgerRunError(f"{label}_mismatch")
    return path, document


def _validate_aggregate(value: Any) -> Dict[str, Any]:
    document = _verify_document(
        value, schema=AGGREGATE_SCHEMA,
        record_type="forward_live_calibration_aggregate")
    if document.get("mode") != SUPPORTED_MODE or \
            document.get("purpose") != "calibration":
        raise LedgerRunError("aggregate_mode_mismatch")
    evaluation_count = document.get("evaluationCount")
    unscorable_count = document.get("unscorableCount")
    if not isinstance(evaluation_count, int) or \
            isinstance(evaluation_count, bool) or evaluation_count < 0 or \
            not isinstance(unscorable_count, int) or \
            isinstance(unscorable_count, bool) or unscorable_count < 0 or \
            unscorable_count > evaluation_count:
        raise LedgerRunError("invalid_aggregate_counts")
    metrics = document.get("metrics")
    if not isinstance(metrics, list) or len(metrics) > MAX_AGGREGATE_METRICS:
        raise LedgerRunError("aggregate_bound_exceeded")
    keys = set()
    for row in metrics:
        if not isinstance(row, dict) or not row.get("key") or row["key"] in keys:
            raise LedgerRunError("invalid_aggregate_metric")
        keys.add(row["key"])
        for field in ("count", "numericCount", "missingCount",
                      "trueCount", "falseCount"):
            if not isinstance(row.get(field), int) or \
                    isinstance(row.get(field), bool) or row[field] < 0:
                raise LedgerRunError("invalid_aggregate_metric")
        expected_key = "|".join((
            str(row.get("metricType")), str(row.get("metricVersion")),
            str(row.get("unit")), str(row.get("methodVersion")),
        ))
        numeric_count = row["numericCount"]
        numeric_sum = row.get("numericSum")
        components = (numeric_count + row["missingCount"] +
                      row["trueCount"] + row["falseCount"])
        if row["key"] != expected_key or components != row["count"] or \
                row["count"] > evaluation_count - unscorable_count or \
                not _finite_number(numeric_sum):
            raise LedgerRunError("invalid_aggregate_metric")
        minimum, maximum, mean = (row.get("minimum"), row.get("maximum"),
                                  row.get("mean"))
        if numeric_count == 0:
            if float(numeric_sum) != 0.0 or any(
                    item is not None for item in (minimum, maximum, mean)):
                raise LedgerRunError("invalid_aggregate_metric")
        elif not all(_finite_number(item)
                     for item in (minimum, maximum, mean)) or \
                float(minimum) > float(maximum) or \
                not float(minimum) * numeric_count - 1e-9 <= \
                float(numeric_sum) <= \
                float(maximum) * numeric_count + 1e-9 or \
                float(mean) != round(
                    float(numeric_sum) / numeric_count, 8):
            raise LedgerRunError("invalid_aggregate_metric")
    return document


def _merge_aggregate(previous: Dict[str, Any],
                     evaluations: Sequence[Dict[str, Any]], *,
                     updated_at: str) -> Dict[str, Any]:
    previous = _validate_aggregate(previous)
    # The core performs the canonical strict-mode and event verification gate.
    try:
        decision_ledger.aggregate_evaluation_events(
            list(evaluations), mode=SUPPORTED_MODE, purpose="calibration")
    except ValueError as exc:
        raise LedgerRunError("invalid_calibration_events") from exc
    rows = {row["key"]: copy.deepcopy(row)
            for row in previous.get("metrics") or []}
    evaluation_count = int(previous.get("evaluationCount") or 0)
    unscorable_count = int(previous.get("unscorableCount") or 0)
    for event in evaluations:
        if not decision_ledger.verify_evaluation_event(event) or \
                event.get("mode") != SUPPORTED_MODE:
            raise LedgerRunError("non_forward_live_evaluation")
        evaluation_count += 1
        if event.get("evaluationStatus") != "SCORED":
            unscorable_count += 1
        for metric in event.get("metrics") or []:
            if metric.get("family") != "score":
                continue
            key = "|".join((
                str(metric.get("metricType")),
                str(metric.get("metricVersion")),
                str(metric.get("unit")),
                str(metric.get("methodVersion")),
            ))
            row = rows.setdefault(key, {
                "key": key,
                "metricType": metric.get("metricType"),
                "metricVersion": metric.get("metricVersion"),
                "unit": metric.get("unit"),
                "methodVersion": metric.get("methodVersion"),
                "count": 0,
                "numericCount": 0,
                "numericSum": 0.0,
                "minimum": None,
                "maximum": None,
                "missingCount": 0,
                "trueCount": 0,
                "falseCount": 0,
            })
            row["count"] += 1
            value = metric.get("value")
            if value is None:
                row["missingCount"] += 1
            elif isinstance(value, bool):
                row["trueCount" if value else "falseCount"] += 1
            elif _finite_number(value):
                number = float(value)
                row["numericCount"] += 1
                row["numericSum"] = math.fsum(
                    (float(row["numericSum"]), number))
                row["minimum"] = number if row["minimum"] is None else min(
                    float(row["minimum"]), number)
                row["maximum"] = number if row["maximum"] is None else max(
                    float(row["maximum"]), number)
    if len(rows) > MAX_AGGREGATE_METRICS:
        raise LedgerRunError("aggregate_metric_overflow")
    output = []
    for key in sorted(rows):
        row = rows[key]
        numeric_count = row["numericCount"]
        row["mean"] = (round(float(row["numericSum"]) / numeric_count, 8)
                       if numeric_count else None)
        output.append(row)
    document = _sealed_document({
        "schemaVersion": AGGREGATE_SCHEMA,
        "recordType": "forward_live_calibration_aggregate",
        "mode": SUPPORTED_MODE,
        "purpose": "calibration",
        "updatedAt": updated_at,
        "evaluationCount": evaluation_count,
        "unscorableCount": unscorable_count,
        "metrics": output,
        "bounds": {"maxMetrics": MAX_AGGREGATE_METRICS},
    })
    _bounded_payload(
        document, maximum=MAX_AGGREGATE_BYTES,
        error="aggregate_too_large")
    return document


def _load_state(root: Path) -> Tuple[Dict[str, Any], Dict[str, Any], Optional[Dict[str, Any]]]:
    manifest_path = root / "manifest.json"
    # Unreferenced version files can remain after a crash.  The manifest alone
    # is the commit pointer, and a retry verifies/reuses exact immutable files.
    if not manifest_path.exists():
        return _empty_index(), _empty_aggregate(), None
    manifest = _verify_document(
        _read_json(manifest_path, maximum=MAX_MANIFEST_BYTES),
        schema=MANIFEST_SCHEMA,
        record_type="prediction_ledger_manifest")
    if manifest.get("mode") != SUPPORTED_MODE:
        raise LedgerRunError("manifest_mode_mismatch")
    index_ref = manifest.get("index") or {}
    aggregate_ref = manifest.get("aggregate") or {}
    index_path = _confined_path(root, index_ref.get("path"), top="indexes")
    aggregate_path = _confined_path(
        root, aggregate_ref.get("path"), top="aggregates")
    if Path(str(index_ref.get("path"))).parts[:2] != ("indexes", "versions") or \
            Path(str(aggregate_ref.get("path"))).parts[:2] != \
            ("aggregates", "versions"):
        raise LedgerRunError("manifest_projection_path_mismatch")
    if not index_path.is_file() or not aggregate_path.is_file():
        raise LedgerRunError("manifest_projection_file_missing")
    index_document = _read_json(index_path, maximum=MAX_INDEX_BYTES)
    aggregate_document = _read_json(
        aggregate_path, maximum=MAX_AGGREGATE_BYTES)
    index = _decode_index(index_document)
    aggregate = _validate_aggregate(aggregate_document)
    if index_ref.get("digest") != index_document.get("digest") or \
            index_ref.get("identityCount") != \
            index_document["counts"]["identityCount"] or \
            index_ref.get("pendingCount") != \
            index_document["counts"]["pendingCount"] or \
            aggregate_ref.get("digest") != aggregate_document.get("digest") or \
            aggregate_ref.get("evaluationCount") != \
            aggregate_document.get("evaluationCount") or \
            aggregate_ref.get("unscorableCount") != \
            aggregate_document.get("unscorableCount"):
        raise LedgerRunError("manifest_projection_mismatch")
    head = manifest.get("head")
    head_path, head_document = _segment_from_reference(
        root, head, label="manifest_head")
    previous = head_document.get("previousSegment")
    if previous is not None:
        previous_path, previous_document = _segment_from_reference(
            root, previous, label="manifest_predecessor")
        if previous_path == head_path or _parse_time(
                previous_document.get("runAt"), "predecessor_run_at") > \
                _parse_time(head_document.get("runAt"), "head_run_at"):
            raise LedgerRunError("invalid_manifest_predecessor_order")
    updated_at = manifest.get("updatedAt")
    watermarks = manifest.get("watermarks") or {}
    last_run_at = watermarks.get("runAt")
    max_issued_at = watermarks.get("maxIssuedAt")
    if not _same_instant(updated_at, last_run_at) or \
            not _same_instant(last_run_at, head_document.get("runAt")) or \
            index_document.get("updatedAt") != updated_at or \
            aggregate_document.get("updatedAt") != updated_at:
        raise LedgerRunError("manifest_watermark_mismatch")
    if max_issued_at is not None and _parse_time(
            max_issued_at, "max_issued_at") > _parse_time(
                last_run_at, "last_run_at"):
        raise LedgerRunError("invalid_manifest_issuance_watermark")
    return index, aggregate, manifest


def _validate_pending_authority(
        root: Path, pending: Mapping[str, Mapping[str, Any]],
        identities: Mapping[str, Mapping[str, Any]]) -> None:
    """Cross-check each derived pending row against its direct source segment.

    This performs bounded direct lookups named by the index; it never discovers
    history with a directory walk or glob.
    """
    segments: Dict[str, Dict[str, Any]] = {}
    verified_bytes = 0

    def load_segment(source: str) -> Dict[str, Any]:
        nonlocal verified_bytes
        segment = segments.get(source)
        if segment is None:
            if len(segments) >= MAX_PENDING_SOURCE_SEGMENTS:
                raise LedgerRunError("pending_source_segment_bound_exceeded")
            source_path = _confined_path(root, source, top="segments")
            if not source_path.is_file():
                raise LedgerRunError("pending_source_segment_missing")
            try:
                source_bytes = source_path.stat().st_size
            except OSError as exc:
                raise LedgerRunError(
                    "pending_source_segment_unreadable") from exc
            if source_bytes > MAX_SEGMENT_BYTES or \
                    verified_bytes + source_bytes > \
                    MAX_PENDING_AUTHORITY_BYTES:
                raise LedgerRunError("pending_authority_byte_bound_exceeded")
            segment = _verify_segment(_read_json(
                source_path, maximum=MAX_SEGMENT_BYTES))
            segments[source] = segment
            verified_bytes += source_bytes
        return segment

    for prediction_id in sorted(pending):
        row = pending[prediction_id]
        source = str(row.get("sourceSegment") or "")
        segment = load_segment(source)
        prediction = next((record for record in
                           segment.get("issuedDecisions") or []
                           if record.get("id") == prediction_id), None)
        if prediction is None or not \
                decision_ledger.verify_prediction_record_v2(prediction) or \
                prediction != row.get("prediction"):
            raise LedgerRunError("pending_source_prediction_mismatch")
        snapshot = (segment.get("truthEvidence") or {}).get(
            "decisionSnapshot")
        if not isinstance(snapshot, dict):
            raise LedgerRunError("pending_source_truth_missing")
        selections = _snapshot_selected_entries(snapshot)
        selected = selections.get(row.get("decisionObservationId")) or {}
        observation = selected.get("observation")
        values = (observation or {}).get("values") or {}
        instrument = (observation or {}).get("instrument") or {}
        if observation is None or not _finite_number(values.get("price")) or \
                float(values["price"]) != float(row["decisionPrice"]) or \
                instrument.get("instrumentId") != row.get("instrumentId") or \
                instrument.get("currency") != row.get("currency"):
            raise LedgerRunError("pending_projection_authority_mismatch")
        if int(row.get("attempts") or 0) > 0:
            latest_id = str(row.get("latestOutcomeEventId") or "")
            latest_identity = identities.get(latest_id) or {}
            outcome_segment = load_segment(str(
                latest_identity.get("sourceSegment") or ""))
            outcome = next((record for record in
                            outcome_segment.get("outcomeResolutions") or []
                            if record.get("id") == latest_id), None)
            if outcome is None or not \
                    decision_ledger.verify_outcome_resolution_event(
                        outcome, prediction) or \
                    outcome.get("integrityHash") != \
                    row.get("latestOutcomeIntegrityHash") or \
                    outcome.get("sequence") != row.get("sequence") or \
                    outcome.get("status") not in ("UNSCORABLE", "AMBIGUOUS"):
                raise LedgerRunError("pending_source_outcome_mismatch")


def _snapshot_selected_entries(
        snapshot: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Return only canonical selected facts; alternates never gain authority."""
    observations: Dict[str, Dict[str, Any]] = {}
    for selection in snapshot.get("selections") or []:
        if not isinstance(selection, dict):
            raise LedgerRunError("invalid_decision_selection")
        selected = selection.get("selected")
        selected_id = selection.get("selectedObservationId")
        if selected is None and selected_id is None:
            continue
        observation = (selected or {}).get("observation") \
            if isinstance(selected, dict) else None
        valid, _ = market_truth.validate_observation(observation)
        if not valid or selected_id != observation.get("observationId") or \
                selected.get("selectionEligible") is not True or \
                selected.get("rejectionReason") is not None:
            raise LedgerRunError("invalid_selected_decision_observation")
        if not any(entry == selected for entry in
                   (selection.get("candidates") or [])):
            raise LedgerRunError("selected_observation_not_in_candidates")
        prior = observations.get(selected_id)
        normalized = {
            "observation": copy.deepcopy(observation),
            "selection": copy.deepcopy(selection),
            "qualityAtAsOf": copy.deepcopy(
                selected.get("qualityAtAsOf") or {}),
        }
        if prior is not None and prior != normalized:
            raise LedgerRunError("decision_observation_collision")
        observations[selected_id] = normalized
    return observations


def _validate_input(snapshot: Any, *, expected_mode: str,
                    runner_build_sha: str) -> Dict[str, Any]:
    if expected_mode != SUPPORTED_MODE:
        raise LedgerRunError("calibration_runner_requires_forward_live")
    if not _SHA40_RE.fullmatch(str(runner_build_sha or "")):
        raise LedgerRunError("runner_build_sha_must_be_exact")
    if not isinstance(snapshot, dict):
        raise LedgerRunError("invalid_snapshot")
    decision_at = _iso(_parse_time(snapshot.get("asOf"), "snapshot_as_of"))
    run_at = _iso(_parse_time(
        snapshot.get("generatedAt"), "snapshot_generated_at"))
    if _parse_time(decision_at, "snapshot_as_of") > _parse_time(
            run_at, "snapshot_generated_at"):
        raise LedgerRunError("snapshot_time_inversion")
    projection = snapshot.get("canonicalPredictionLedger")
    if not isinstance(projection, dict) or \
            projection.get("schemaVersion") != \
            decision_ledger.PREDICTION_LEDGER_V2_SCHEMA or \
            projection.get("mode") != expected_mode:
        raise LedgerRunError("canonical_projection_mode_or_schema_mismatch")
    if projection.get("authority") != "PREDICTION_EVIDENCE_ONLY" or \
            projection.get("finalDecisionAuthorityActive") is not False:
        raise LedgerRunError("canonical_projection_authority_escalation")
    decisions_raw = projection.get("issuedDecisions") or []
    outcome_raw = projection.get("outcomeTruthObservations") or []
    if not isinstance(decisions_raw, list) or not isinstance(outcome_raw, list):
        raise LedgerRunError("invalid_canonical_projection_arrays")
    if len(decisions_raw) > MAX_ISSUED_DECISIONS:
        raise LedgerRunError("issued_decision_input_overflow")
    if len(outcome_raw) > MAX_OUTCOME_OBSERVATIONS:
        raise LedgerRunError("outcome_truth_input_overflow")
    candidate_count = projection.get("candidateCount")
    issued_count = projection.get("issuedCount")
    omitted_count = projection.get("omittedCandidateCount")
    # Projection status/quality flags are diagnostics, never evidence
    # authority.  A partial mixed-market projection may still resolve existing
    # pending decisions and may contain individually complete issued records.
    if projection.get("status") not in ("COMPLETE", "INCOMPLETE") or \
            not isinstance(candidate_count, int) or \
            isinstance(candidate_count, bool) or \
            not isinstance(issued_count, int) or isinstance(issued_count, bool) or \
            not isinstance(omitted_count, int) or \
            isinstance(omitted_count, bool) or candidate_count < 0 or \
            issued_count < 0 or omitted_count < 0 or \
            candidate_count < issued_count or omitted_count > candidate_count or \
            issued_count != len(decisions_raw):
        raise LedgerRunError("canonical_projection_incomplete")

    market_snapshot = projection.get("marketTruthSnapshot")
    if market_snapshot is None:
        raise LedgerRunError("market_truth_snapshot_required")
    valid, reason = market_truth.verify_decision_snapshot(market_snapshot)
    if not valid:
        raise LedgerRunError(f"invalid_market_truth_snapshot:{reason}")
    producer_sha = str(market_snapshot.get("buildIdentity") or "")
    if not _SHA40_RE.fullmatch(producer_sha) or \
            projection.get("producerBuildSha") != producer_sha:
        raise LedgerRunError("producer_build_sha_must_be_exact")
    projection_decision_at = projection.get("decisionAt")
    projection_generated_at = projection.get("generatedAt")
    if not _same_instant(market_snapshot.get("decisionAt"), decision_at) or \
            not _same_instant(projection_decision_at, decision_at):
        raise LedgerRunError("market_truth_decision_cutoff_mismatch")
    truth_generated = _parse_time(
        market_snapshot.get("generatedAt"), "truth_generated_at")
    projection_generated = _parse_time(
        projection_generated_at, "projection_generated_at")
    if truth_generated != projection_generated or \
            projection_generated > _parse_time(run_at, "run_at"):
        raise LedgerRunError("truth_generated_after_run")
    decision_observations = _snapshot_selected_entries(market_snapshot)

    decisions: List[Dict[str, Any]] = []
    seen_decisions: Dict[str, str] = {}
    decision_evidence: Dict[str, Dict[str, Any]] = {}
    for prediction in decisions_raw:
        if not decision_ledger.verify_prediction_record_v2(prediction) or \
                prediction.get("mode") != expected_mode:
            raise LedgerRunError("invalid_or_cross_mode_prediction")
        prediction_id = prediction["id"]
        integrity = prediction["integrityHash"]
        prior = seen_decisions.get(prediction_id)
        if prior is not None:
            if prior != integrity:
                raise LedgerRunError("input_prediction_id_collision")
            continue
        if _parse_time(prediction.get("issuedAt"),
                       "prediction_issued_at") > _parse_time(run_at, "run_at"):
            raise LedgerRunError("prediction_issued_after_run")
        if (prediction.get("engine") or {}).get("buildSha") != producer_sha:
            raise LedgerRunError("prediction_producer_identity_mismatch")
        truth_ref = prediction.get("truthRef") or {}
        if truth_ref.get("snapshotId") != market_snapshot.get("snapshotId"):
            raise LedgerRunError("prediction_truth_snapshot_mismatch")
        selected_entry = decision_observations.get(truth_ref.get("sourceId")) or {}
        observation = selected_entry.get("observation")
        values = (observation or {}).get("values") or {}
        selection = selected_entry.get("selection") or {}
        quality = selected_entry.get("qualityAtAsOf") or {}
        if observation is None or observation.get("factType") != "QUOTE" or \
                not _finite_number(values.get("price")) or \
                float(values["price"]) <= 0:
            raise LedgerRunError("prediction_decision_price_unbound")
        source = observation.get("source") or {}
        expected_truth_ref = decision_ledger.point_in_time_truth_ref(
            snapshot_id=market_snapshot["snapshotId"],
            source_id=observation["observationId"],
            as_of=observation.get("observedAt"),
            known_at=observation.get("knownAt"),
            content_hash=observation["observationId"],
            observation_kind="decision_quote",
            observed_fields=sorted(values),
            provider=source.get("providerKey") or "",
            revision=str(observation.get("revision") or ""))
        instrument = observation.get("instrument") or {}
        if truth_ref != expected_truth_ref or \
                instrument.get("symbol") != prediction.get("symbol") or \
                instrument.get("market") != prediction.get("market"):
            raise LedgerRunError("prediction_truth_fields_mismatch")
        if quality.get("freshness") not in {
                market_truth.FRESH, market_truth.DELAYED} or \
                quality.get("completeness") != market_truth.COMPLETE or \
                selection.get("freshness") != quality.get("freshness") or \
                selection.get("completeness") != market_truth.COMPLETE or \
                prediction.get("missingEvidence"):
            raise LedgerRunError("prediction_selected_truth_incomplete")
        if not _same_instant(prediction.get("issuedAt"),
                             projection_generated_at):
            raise LedgerRunError("prediction_issuance_time_mismatch")
        _, _, scoring_reason = _scenario_contract(prediction)
        if scoring_reason:
            raise LedgerRunError(
                f"unsupported_prediction_scoring_contract:{scoring_reason}")
        seen_decisions[prediction_id] = integrity
        decisions.append(copy.deepcopy(prediction))
        decision_evidence[prediction_id] = copy.deepcopy(observation)

    outcome_observations: List[Dict[str, Any]] = []
    seen_outcomes: Dict[str, Dict[str, Any]] = {}
    for observation in outcome_raw:
        valid, reason = market_truth.validate_observation(observation)
        if not valid:
            raise LedgerRunError(f"invalid_outcome_observation:{reason}")
        if _parse_time(observation.get("knownAt"),
                       "outcome_known_at") > _parse_time(run_at, "run_at"):
            raise LedgerRunError("future_outcome_truth")
        observation_id = observation["observationId"]
        prior = seen_outcomes.get(observation_id)
        if prior is not None:
            if prior != observation:
                raise LedgerRunError("outcome_observation_collision")
            continue
        seen_outcomes[observation_id] = copy.deepcopy(observation)
        outcome_observations.append(copy.deepcopy(observation))
    outcome_observations.sort(key=lambda row: row["observationId"])
    return {
        "snapshot": copy.deepcopy(snapshot),
        "projection": copy.deepcopy(projection),
        "inputDigest": _digest({
            "asOf": decision_at,
            "generatedAt": run_at,
            "canonicalPredictionLedger": projection,
        }),
        "decisionAt": decision_at,
        "runAt": run_at,
        "producerBuildSha": producer_sha,
        "marketSnapshot": copy.deepcopy(market_snapshot),
        "decisions": decisions,
        "decisionEvidence": decision_evidence,
        "outcomeObservations": outcome_observations,
        "outcomeBundleDigest": _digest(outcome_observations),
    }


def _record_type(record: Mapping[str, Any]) -> str:
    return str(record.get("recordType") or "")


def _register_identity(identities: Dict[str, Dict[str, Any]],
                       record: Mapping[str, Any], *,
                       source_segment: str,
                       registered_at: str) -> bool:
    record_id = str(record.get("id") or "")
    integrity = str(record.get("integrityHash") or "")
    record_type = _record_type(record)
    if not record_id or not integrity or not record_type:
        raise LedgerRunError("record_identity_missing")
    prior = identities.get(record_id)
    if prior is not None:
        if prior.get("integrityHash") != integrity or \
                prior.get("recordType") != record_type:
            raise LedgerRunError("record_id_collision")
        return False
    identities[record_id] = {
        "id": record_id,
        "integrityHash": integrity,
        "recordType": record_type,
        "sourceSegment": source_segment,
        "registeredAt": registered_at,
    }
    return True


def _prune_identities(state: Dict[str, Any]) -> None:
    """Bound the replay index without making evicted records replayable.

    Pending predictions are always retained.  Other oldest identities may be
    dropped only because the manifest's monotonic run/issuance watermarks make
    a later reintroduction of an unknown old prediction fail closed.
    """
    identities = state["identities"]
    protected_ids = set(state["pending"])
    protected_ids.update(
        str(row.get("latestOutcomeEventId"))
        for row in state["pending"].values()
        if row.get("latestOutcomeEventId"))
    if len(protected_ids) > MAX_IDENTITY_RECORDS:
        raise LedgerRunError("pending_identities_exceed_identity_bound")
    overflow = len(identities) - MAX_IDENTITY_RECORDS
    if overflow <= 0:
        return
    removable = sorted(
        (row for record_id, row in identities.items()
         if record_id not in protected_ids),
        key=lambda row: (str(row.get("registeredAt") or ""), row["id"]))
    if len(removable) < overflow:
        raise LedgerRunError("identity_index_overflow")
    for row in removable[:overflow]:
        identities.pop(row["id"], None)
    state["evictedIdentityCount"] = int(
        state.get("evictedIdentityCount") or 0) + overflow


def _pending_entry(prediction: Dict[str, Any], observation: Dict[str, Any],
                   *, source_segment: str) -> Dict[str, Any]:
    instrument = observation.get("instrument") or {}
    maturity = prediction.get("maturity") or {}
    return {
        "predictionId": prediction["id"],
        "predictionIntegrityHash": prediction["integrityHash"],
        "prediction": copy.deepcopy(prediction),
        "decisionObservationId": observation["observationId"],
        "decisionPrice": float((observation.get("values") or {})["price"]),
        "instrumentId": instrument.get("instrumentId"),
        "currency": instrument.get("currency"),
        "targetSessionId": maturity.get("targetSessionId"),
        "targetAt": maturity.get("targetAt"),
        "maturityAt": maturity.get("maturityAt"),
        "sourceSegment": source_segment,
        "state": "pending_maturity",
        "attempts": 0,
        "sequence": 0,
        "latestOutcomeEventId": None,
        "latestOutcomeIntegrityHash": None,
    }


def _expected_path_bars(horizon: str) -> Optional[int]:
    return {
        "next_session": 1,
        "1d": 1,
        "3d": 3,
        "5d": 5,
        "20d": 20,
    }.get(str(horizon))


def _selected_outcome_path(
        pending: Mapping[str, Any], observations: Sequence[Mapping[str, Any]],
        *, run_at: str) -> Tuple[Optional[List[Dict[str, Any]]],
                                Optional[Dict[str, Any]], str]:
    prediction = pending["prediction"]
    expected = _expected_path_bars(prediction.get("forecastHorizon"))
    if expected is None:
        return None, None, "unsupported_forecast_horizon"
    try:
        history = market_truth.select_history_as_of(
            observations,
            instrument_id=pending.get("instrumentId"),
            market=prediction.get("market"), fact_type="OHLCV_BAR",
            as_of=run_at, expected_currency=pending.get("currency"))
    except (TypeError, ValueError) as exc:
        raise LedgerRunError("outcome_truth_selection_failed") from exc
    target_at = (prediction.get("maturity") or {}).get("targetAt")
    target_selection = next((row for row in history
                             if _same_instant(
                                 ((row.get("selected") or {}).get(
                                     "observation") or {}).get("periodEnd"),
                                 target_at)), None)
    if target_selection is None or target_selection.get("selected") is None:
        return None, None, "exact_target_session_truth_missing"
    target = target_selection["selected"]["observation"]
    fields = target.get("values") or {}
    if target.get("completeness") != market_truth.COMPLETE or \
            any(not _finite_number(fields.get(field)) for field in
                ("open", "high", "low", "close")):
        return None, target, "exact_target_session_ohlc_incomplete"
    issued_at = prediction.get("issuedAt")
    selected = []
    for selection in history:
        entry = selection.get("selected") or {}
        observation = entry.get("observation") or {}
        period_end = observation.get("periodEnd")
        values = observation.get("values") or {}
        if not period_end or not _same_instant(
                observation.get("observedAt"), period_end):
            continue
        if _parse_time(period_end, "period_end") <= _parse_time(
                issued_at, "issued_at") or \
                _parse_time(period_end, "period_end") > _parse_time(
                    target_at, "target_at"):
            continue
        if observation.get("completeness") != market_truth.COMPLETE or \
                any(not _finite_number(values.get(field)) for field in
                    ("open", "high", "low", "close")):
            continue
        selected.append(copy.deepcopy(observation))
    selected.sort(key=lambda row: _parse_time(row["periodEnd"], "period_end"))
    if not selected or selected[-1]["observationId"] != target["observationId"]:
        return None, target, "target_session_not_path_end"
    if len(selected) < expected:
        return None, target, "target_path_ohlc_incomplete"
    selected = selected[-expected:]
    return selected, target, ""


def _scenario_contract(prediction: Mapping[str, Any]) \
        -> Tuple[Optional[Dict[str, float]], Optional[float], str]:
    distribution = prediction.get("forecastDistribution")
    if not isinstance(distribution, dict):
        return None, None, "forecast_distribution_missing"
    if distribution.get("classOrderVersion") != \
            SUPPORTED_CLASS_ORDER_VERSION or tuple(
                distribution.get("classLabels") or ()) != \
            tuple(argus_calibration.CLASSES):
        return None, None, "unsupported_forecast_class_order"
    probabilities = distribution.get("probabilities") or []
    if len(probabilities) != len(argus_calibration.CLASSES):
        return None, None, "invalid_forecast_distribution"
    probs = dict(zip(argus_calibration.CLASSES,
                     (float(value) for value in probabilities)))
    ladder = prediction.get("targetLadder") or []
    if len(ladder) != 2 or {row.get("targetId") for row in ladder} != {
            SCENARIO_DOWNSIDE_TARGET_ID, SCENARIO_REBOUND_TARGET_ID}:
        return None, None, "noncanonical_scenario_targets"
    downside = next((row for row in ladder
                     if row.get("targetId") == SCENARIO_DOWNSIDE_TARGET_ID), None)
    rebound = next((row for row in ladder
                    if row.get("targetId") == SCENARIO_REBOUND_TARGET_ID), None)
    target_at = (prediction.get("maturity") or {}).get("targetAt")
    if not downside or not rebound or downside.get("unit") != "%" or \
            rebound.get("unit") != "%" or \
            downside.get("comparator") != "<" or \
            rebound.get("comparator") != ">" or \
            downside.get("targetAt") != target_at or \
            rebound.get("targetAt") != target_at or \
            not _finite_number(downside.get("value")) or \
            not _finite_number(rebound.get("value")):
        return None, None, "scenario_boundaries_missing"
    lower = float(downside["value"])
    upper = float(rebound["value"])
    if lower >= 0 or upper <= 0 or not math.isclose(
            abs(lower), abs(upper), rel_tol=0.0, abs_tol=1e-9):
        return None, None, "scenario_boundaries_not_symmetric"
    _, expected_policy = scenario_evaluation_policy(
        band_pct=abs(upper), horizon=str(prediction.get("forecastHorizon")))
    if prediction.get("evaluationPolicy") != expected_policy:
        return None, None, "evaluation_policy_mismatch"
    return probs, abs(upper), ""


def scenario_evaluation_policy(*, band_pct: float,
                               horizon: str) \
        -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """The exact producer/runner calibration-policy binding contract."""
    if not _finite_number(band_pct) or float(band_pct) <= 0:
        raise LedgerRunError("invalid_scenario_band")
    material = {
        "bandPct": float(band_pct),
        "bandVersion": argus_calibration.BAND_VERSION,
        "classOrder": list(argus_calibration.CLASSES),
        "classOrderVersion": SUPPORTED_CLASS_ORDER_VERSION,
        "downsideComparator": "<",
        "horizon": str(horizon),
        "reboundComparator": ">",
        "scorerVersion": argus_calibration.SCORER_VERSION,
    }
    return material, {
        "policyId": "argus-calibration-three-class-v1",
        "policyVersion": argus_calibration.SCORER_VERSION,
        "parametersHash": _digest(material),
    }


def _metric(**kwargs: Any) -> Dict[str, Any]:
    metric = decision_ledger.evaluation_metric(**kwargs)
    if metric is None:
        raise LedgerRunError("metric_construction_failed")
    return metric


def _missing_metric(metric_type: str, reason: str) -> Dict[str, Any]:
    return _metric(
        metric_type=metric_type, family="missing", value=None,
        unit="status", metric_version="1",
        method_version=RESOLUTION_METHOD_VERSION,
        polarity="contextual", missing_reason=reason[:200])


def _threshold_value(rule: Mapping[str, Any], base: float) -> Optional[float]:
    value = rule.get("value")
    if not _finite_number(value):
        return None
    unit = str(rule.get("unit") or "").lower()
    if unit in ("%", "pct", "percent"):
        return base * (1.0 + float(value) / 100.0)
    if unit in ("price", "jpy", "usd"):
        return float(value)
    return None


def _first_touch(path: Sequence[Mapping[str, Any]], rule: Mapping[str, Any],
                 base: float) -> Optional[Dict[str, Any]]:
    threshold = _threshold_value(rule, base)
    if threshold is None:
        raise LedgerRunError("unsupported_target_unit")
    comparator = str(rule.get("comparator") or "touch")
    for observation in path:
        values = observation.get("values") or {}
        high, low = float(values["high"]), float(values["low"])
        touched = (
            high > threshold if comparator == ">" else
            high >= threshold if comparator == ">=" else
            low < threshold if comparator == "<" else
            low <= threshold if comparator == "<=" else
            low <= threshold <= high if comparator in ("touch", "==", "")
            else False
        )
        if comparator not in (">", ">=", "<", "<=", "touch", "==", ""):
            raise LedgerRunError("unsupported_target_comparator")
        if touched:
            return copy.deepcopy(observation)
    return None


def _observed_metrics(prediction: Mapping[str, Any],
                      path: Sequence[Mapping[str, Any]],
                      target: Mapping[str, Any], base: float) \
        -> Tuple[List[Dict[str, Any]], float]:
    evidence = [row["observationId"] for row in path]
    target_at = (prediction.get("maturity") or {})["targetAt"]
    high_row = max(path, key=lambda row: float(row["values"]["high"]))
    low_row = min(path, key=lambda row: float(row["values"]["low"]))
    mfe = (float(high_row["values"]["high"]) / base - 1.0) * 100.0
    mae = (float(low_row["values"]["low"]) / base - 1.0) * 100.0
    end = (float(target["values"]["close"]) / base - 1.0) * 100.0
    common = {
        "unit": "%", "metric_version": "1",
        "method_version": RESOLUTION_METHOD_VERSION,
        "polarity": "contextual", "window": prediction.get("forecastHorizon"),
        "observed_at": target_at, "evidence_refs": evidence,
    }
    metrics = [
        _metric(metric_type="path.mfe_pct", family="mfe",
                value=round(mfe, 8), observation_ref=high_row["observationId"],
                first_observed_at=high_row["observedAt"], **common),
        _metric(metric_type="path.mae_pct", family="mae",
                value=round(mae, 8), observation_ref=low_row["observationId"],
                first_observed_at=low_row["observedAt"], **common),
        _metric(metric_type="horizon.end_return_pct", family="end",
                value=round(end, 8), observation_ref=target["observationId"],
                **common),
    ]
    for row in prediction.get("targetLadder") or []:
        touched = _first_touch(path, row, base)
        metrics.append(_metric(
            metric_type="target.touch", family="target",
            value=touched is not None, unit="boolean", metric_version="1",
            method_version=RESOLUTION_METHOD_VERSION, polarity="contextual",
            window=prediction.get("forecastHorizon"), observed_at=target_at,
            first_observed_at=(touched or {}).get("observedAt") or "",
            observation_ref=(touched or {}).get("observationId") or "",
            target_ref=row.get("targetId"), evidence_refs=evidence))
    invalidation = prediction.get("invalidation")
    if invalidation is not None:
        touched = _first_touch(path, invalidation, base)
        metrics.append(_metric(
            metric_type="invalidation.touch", family="invalidation",
            value=touched is not None, unit="boolean", metric_version="1",
            method_version=RESOLUTION_METHOD_VERSION, polarity="contextual",
            window=prediction.get("forecastHorizon"), observed_at=target_at,
            first_observed_at=(touched or {}).get("observedAt") or "",
            observation_ref=(touched or {}).get("observationId") or "",
            target_ref=invalidation.get("ruleId"), evidence_refs=evidence))
    if str(prediction.get("candidateAction") or "").upper() == "WAIT":
        metrics.extend([
            _metric(metric_type="opportunity.avoided_mae_pct",
                    family="opportunity", value=round(max(0.0, -mae), 8),
                    observation_ref=low_row["observationId"], **common),
            _metric(metric_type="opportunity.missed_mfe_pct",
                    family="opportunity", value=round(max(0.0, mfe), 8),
                    observation_ref=high_row["observationId"], **common),
        ])
    return metrics, end


def _target_truth_ref(target: Mapping[str, Any], prediction: Mapping[str, Any],
                      *, bundle_digest: str,
                      observation_kind: str = "target_session_ohlc") \
        -> Dict[str, Any]:
    source = target.get("source") or {}
    maturity = prediction.get("maturity") or {}
    truth_ref = decision_ledger.point_in_time_truth_ref(
        snapshot_id=f"otb-{bundle_digest[:32]}",
        source_id=target.get("observationId"),
        as_of=maturity.get("targetAt"), known_at=target.get("knownAt"),
        content_hash=target.get("observationId"),
        observation_kind=observation_kind,
        observed_fields=sorted((target.get("values") or {}).keys()),
        target_session_id=maturity.get("targetSessionId"),
        provider=source.get("providerKey") or "",
        revision=str(target.get("revision") or ""))
    if truth_ref is None:
        raise LedgerRunError("target_truth_ref_construction_failed")
    return truth_ref


def _missing_truth_ref(prediction: Mapping[str, Any], *, run_at: str,
                       bundle_digest: str, reason: str) -> Dict[str, Any]:
    maturity = prediction.get("maturity") or {}
    missing_id = "missing-" + _digest({
        "predictionId": prediction.get("id"),
        "targetSessionId": maturity.get("targetSessionId"),
        "bundleDigest": bundle_digest, "reason": reason,
    })[:32]
    truth_ref = decision_ledger.point_in_time_truth_ref(
        snapshot_id=f"otb-{bundle_digest[:32]}", source_id=missing_id,
        as_of=maturity.get("targetAt"), known_at=run_at,
        content_hash=bundle_digest,
        observation_kind="target_session_missing",
        observed_fields=["fetch_status"],
        target_session_id=maturity.get("targetSessionId"), revision="")
    if truth_ref is None:
        raise LedgerRunError("missing_truth_ref_construction_failed")
    return truth_ref


def _unscorable_outcome(
        prediction: Dict[str, Any], pending: Mapping[str, Any], *,
        run_at: str, bundle_digest: str, reason: str,
        target: Optional[Mapping[str, Any]] = None) \
        -> Tuple[Dict[str, Any], Dict[str, Any]]:
    truth_ref = (_target_truth_ref(
        target, prediction, bundle_digest=bundle_digest,
        observation_kind="target_session_unscorable") if target is not None
        else _missing_truth_ref(
            prediction, run_at=run_at, bundle_digest=bundle_digest,
            reason=reason))
    metrics = [_missing_metric("truth.target_session_unscorable", reason)]
    if str(prediction.get("candidateAction") or "").upper() == "WAIT":
        metrics.extend([
            _missing_metric("opportunity.avoided_mae_pct", reason),
            _missing_metric("opportunity.missed_mfe_pct", reason),
        ])
    sequence = int(pending.get("sequence") or 0) + 1
    outcome = decision_ledger.outcome_resolution_event(
        prediction=prediction, recorded_at=run_at, truth_ref=truth_ref,
        status="UNSCORABLE", metrics=metrics,
        method_version=RESOLUTION_METHOD_VERSION, sequence=sequence,
        previous_event_id=pending.get("latestOutcomeEventId") or "",
        missing_reasons=[reason])
    if outcome is None:
        raise LedgerRunError("unscorable_outcome_construction_failed")
    evaluation = decision_ledger.evaluation_event_record(
        prediction=prediction, outcome=outcome, evaluated_at=run_at,
        metrics=[_missing_metric("score.unscorable", reason)],
        scoring_policy=prediction.get("evaluationPolicy"),
        evaluator_id="argus-calibration",
        evaluator_version=EVALUATION_METHOD_VERSION,
        build_sha=_CURRENT_RUNNER_SHA)
    if evaluation is None:
        raise LedgerRunError("unscorable_evaluation_construction_failed")
    return outcome, evaluation


_CURRENT_RUNNER_SHA = ""


def _resolve_pending(
        pending: Mapping[str, Any], observations: Sequence[Mapping[str, Any]],
        *, run_at: str, bundle_digest: str) \
        -> Tuple[Dict[str, Any], Dict[str, Any], str]:
    prediction = copy.deepcopy(pending["prediction"])
    path, target, truth_reason = _selected_outcome_path(
        pending, observations, run_at=run_at)
    probabilities, band_pct, scoring_reason = _scenario_contract(prediction)
    reason = truth_reason or scoring_reason
    if reason:
        outcome, evaluation = _unscorable_outcome(
            prediction, pending, run_at=run_at,
            bundle_digest=bundle_digest, reason=reason,
            target=target if not truth_reason else None)
        return outcome, evaluation, "retry_wait"

    assert path is not None and target is not None
    assert probabilities is not None and band_pct is not None
    metrics, end_return = _observed_metrics(
        prediction, path, target, float(pending["decisionPrice"]))
    target_truth = _target_truth_ref(
        target, prediction, bundle_digest=bundle_digest)
    target_true_refs = {
        metric.get("observationRef") for metric in metrics
        if metric.get("family") == "target" and metric.get("value") is True}
    invalidation_true_refs = {
        metric.get("observationRef") for metric in metrics
        if metric.get("family") == "invalidation" and metric.get("value") is True}
    ambiguous = bool(target_true_refs & invalidation_true_refs)
    status = "AMBIGUOUS" if ambiguous else "OBSERVED"
    sequence = int(pending.get("sequence") or 0) + 1
    outcome = decision_ledger.outcome_resolution_event(
        prediction=prediction, recorded_at=run_at, truth_ref=target_truth,
        status=status, metrics=metrics,
        method_version=RESOLUTION_METHOD_VERSION, sequence=sequence,
        previous_event_id=pending.get("latestOutcomeEventId") or "")
    if outcome is None:
        raise LedgerRunError("observed_outcome_construction_failed")
    if ambiguous:
        evaluation_metrics = [_missing_metric(
            "score.ambiguous_same_bar", "same_bar_target_and_invalidation")]
    else:
        realized = argus_calibration.classify_realized(end_return, band_pct)
        brier = argus_calibration.brier_multiclass(probabilities, realized)
        rps = argus_calibration.rps(probabilities, realized)
        hit = argus_calibration.argmax_hit(probabilities, realized)
        common = {
            "family": "score", "metric_version": "1",
            "method_version": argus_calibration.SCORER_VERSION,
            "polarity": "lower_better", "window": prediction.get(
                "forecastHorizon"), "observed_at": (
                    prediction.get("maturity") or {})["targetAt"],
            "observation_ref": target["observationId"],
            "target_ref": realized, "evidence_refs": [outcome["id"]],
        }
        evaluation_metrics = [
            _metric(metric_type="score.brier_raw_sum",
                    value=brier["brierRawSum"], unit="score", **common),
            _metric(metric_type="score.brier_normalized_mean",
                    value=brier["brierNormalizedMean"], unit="score", **common),
            _metric(metric_type="score.rps_raw", value=rps["rpsRaw"],
                    unit="score", **common),
            _metric(metric_type="score.rps_normalized",
                    value=rps["rpsNormalized"], unit="score", **common),
            _metric(
                metric_type="score.argmax_hit", family="score",
                value=1.0 if hit else 0.0, unit="ratio",
                metric_version="1",
                method_version=argus_calibration.SCORER_VERSION,
                polarity="higher_better",
                window=prediction.get("forecastHorizon"),
                observed_at=(prediction.get("maturity") or {})["targetAt"],
                observation_ref=target["observationId"],
                target_ref=realized, evidence_refs=[outcome["id"]]),
        ]
    evaluation = decision_ledger.evaluation_event_record(
        prediction=prediction, outcome=outcome, evaluated_at=run_at,
        metrics=evaluation_metrics,
        scoring_policy=prediction.get("evaluationPolicy"),
        evaluator_id="argus-calibration",
        evaluator_version=EVALUATION_METHOD_VERSION,
        build_sha=_CURRENT_RUNNER_SHA)
    if evaluation is None:
        raise LedgerRunError("evaluation_construction_failed")
    return outcome, evaluation, "retry_wait" if ambiguous else "resolved"


def _manifest_document(*, segment: Dict[str, Any], segment_path: str,
                       index: Dict[str, Any], aggregate: Dict[str, Any],
                       index_path: str, aggregate_path: str,
                       updated_at: str,
                       max_issued_at: Optional[str]) -> Dict[str, Any]:
    document = _sealed_document({
        "schemaVersion": MANIFEST_SCHEMA,
        "recordType": "prediction_ledger_manifest",
        "mode": SUPPORTED_MODE,
        "updatedAt": updated_at,
        "head": {
            "path": segment_path,
            "segmentId": segment["segmentId"],
            "digest": segment["digest"],
            "runId": segment["runId"],
        },
        "index": {
            "path": index_path,
            "digest": index["digest"],
            **index["counts"],
        },
        "aggregate": {
            "path": aggregate_path,
            "digest": aggregate["digest"],
            "evaluationCount": aggregate["evaluationCount"],
            "unscorableCount": aggregate["unscorableCount"],
        },
        "bounds": {
            "maxPending": MAX_PENDING_RECORDS,
            "maxIssuedPerRun": MAX_ISSUED_DECISIONS,
            "maxIdentities": MAX_IDENTITY_RECORDS,
            "maxAggregateMetrics": MAX_AGGREGATE_METRICS,
            "historyAuthority": "immutable_segment_chain",
        },
        "watermarks": {
            "runAt": updated_at,
            "maxIssuedAt": max_issued_at,
            "replayPolicy": "unknown_issued_at_must_exceed_max_issued_at",
        },
    })
    _bounded_payload(
        document, maximum=MAX_MANIFEST_BYTES,
        error="manifest_too_large")
    return document


def run_prediction_ledger(snapshot: Dict[str, Any], *, ledger_root: Path,
                          expected_mode: str, run_id: str,
                          runner_build_sha: str) -> Dict[str, Any]:
    """Validate one input and atomically advance the bounded v2 projections."""
    global _CURRENT_RUNNER_SHA
    if not _RUN_ID_RE.fullmatch(str(run_id or "")):
        raise LedgerRunError("invalid_run_id")
    context = _validate_input(
        snapshot, expected_mode=expected_mode,
        runner_build_sha=runner_build_sha)
    _CURRENT_RUNNER_SHA = runner_build_sha
    root = Path(ledger_root)
    index_state, previous_aggregate, previous_manifest = _load_state(root)
    identities = index_state["identities"]
    pending = index_state["pending"]
    _validate_pending_authority(root, pending, identities)
    run_at = context["runAt"]
    previous_watermarks = (previous_manifest or {}).get("watermarks") or {}
    previous_run_at = previous_watermarks.get("runAt")
    previous_max_issued_at = previous_watermarks.get("maxIssuedAt")
    if previous_run_at is not None and _parse_time(
            run_at, "run_at") < _parse_time(
                previous_run_at, "previous_run_at"):
        raise LedgerRunError("ledger_run_time_regression")
    run_date = run_at[:10]
    segment_relative = f"segments/{run_date}/{run_id}.json"
    segment_path = root / segment_relative

    if segment_path.exists():
        existing = _verify_segment(_read_json(segment_path))
        head = (previous_manifest or {}).get("head") or {}
        if existing.get("runId") == run_id and \
                existing.get("inputDigest") == context["inputDigest"] and \
                existing.get("runnerBuildSha") == runner_build_sha and \
                existing.get("runAt") == run_at and \
                head.get("path") == segment_relative and \
                head.get("digest") == existing.get("digest"):
            return {
                "ok": True, "idempotent": True,
                "segmentPath": segment_relative,
                "segmentId": existing["segmentId"],
                "issued": existing["counts"]["issued"],
                "outcomes": existing["counts"]["outcomes"],
                "evaluations": existing["counts"]["evaluations"],
                "pending": len(pending),
            }
        # A previous attempt may have installed this exact segment and crashed
        # before committing the manifest.  Equality is checked after the full
        # deterministic document is rebuilt below.

    new_decisions: List[Dict[str, Any]] = []
    new_outcomes: List[Dict[str, Any]] = []
    new_evaluations: List[Dict[str, Any]] = []
    for prediction in context["decisions"]:
        prior_identity = identities.get(prediction["id"])
        if prior_identity is None and previous_max_issued_at is not None and \
                _parse_time(prediction.get("issuedAt"), "prediction_issued_at") <= \
                _parse_time(previous_max_issued_at,
                            "previous_max_issued_at"):
            raise LedgerRunError("stale_prediction_replay")
        is_new = _register_identity(
            identities, prediction, source_segment=segment_relative,
            registered_at=run_at)
        if is_new:
            new_decisions.append(copy.deepcopy(prediction))
            evidence = context["decisionEvidence"][prediction["id"]]
            pending[prediction["id"]] = _pending_entry(
                prediction, evidence, source_segment=segment_relative)

    run_dt = _parse_time(run_at, "run_at")
    for prediction_id in sorted(list(pending)):
        row = pending[prediction_id]
        maturity_at = _parse_time(row.get("maturityAt"), "maturity_at")
        if run_dt < maturity_at:
            continue
        outcome, evaluation, state = _resolve_pending(
            row, context["outcomeObservations"], run_at=run_at,
            bundle_digest=context["outcomeBundleDigest"])
        outcome_new = _register_identity(
            identities, outcome, source_segment=segment_relative,
            registered_at=run_at)
        evaluation_new = _register_identity(
            identities, evaluation, source_segment=segment_relative,
            registered_at=run_at)
        if outcome_new != evaluation_new:
            raise LedgerRunError("outcome_evaluation_idempotency_mismatch")
        if outcome_new:
            new_outcomes.append(outcome)
            new_evaluations.append(evaluation)
        row["attempts"] = int(row.get("attempts") or 0) + 1
        row["sequence"] = outcome["sequence"]
        row["latestOutcomeEventId"] = outcome["id"]
        row["latestOutcomeIntegrityHash"] = outcome["integrityHash"]
        row["state"] = state
        if state == "resolved" or row["attempts"] >= MAX_RESOLUTION_ATTEMPTS:
            pending.pop(prediction_id, None)

    if len(pending) > MAX_PENDING_RECORDS:
        raise LedgerRunError("pending_index_overflow")
    _prune_identities(index_state)

    aggregate = _merge_aggregate(
        previous_aggregate, new_evaluations, updated_at=run_at)
    index_document = _encode_index(
        index_state, updated_at=run_at)
    previous_head = (previous_manifest or {}).get("head")
    segment_body = {
        "schemaVersion": SEGMENT_SCHEMA,
        "recordType": "immutable_prediction_segment",
        "runId": run_id,
        "mode": SUPPORTED_MODE,
        "runAt": run_at,
        "runnerBuildSha": runner_build_sha,
        "producerBuildSha": context["producerBuildSha"],
        "inputDigest": context["inputDigest"],
        "projectionStatus": context["projection"].get("status"),
        "previousSegment": (copy.deepcopy(previous_head)
                            if previous_head is not None else None),
        "truthEvidence": {
            "decisionSnapshot": context["marketSnapshot"],
            "outcomeBundleDigest": context["outcomeBundleDigest"],
            "outcomeObservations": context["outcomeObservations"],
        },
        "issuedDecisions": new_decisions,
        "outcomeResolutions": new_outcomes,
        "evaluationEvents": new_evaluations,
        "counts": {
            "issued": len(new_decisions),
            "outcomes": len(new_outcomes),
            "evaluations": len(new_evaluations),
            "pendingAfter": len(pending),
        },
    }
    segment_body["segmentId"] = "pls-" + _digest(segment_body)[:32]
    segment = _sealed_document(segment_body)
    _bounded_payload(
        segment, maximum=MAX_SEGMENT_BYTES, error="segment_too_large")
    index_relative = f"indexes/versions/{segment['segmentId']}.json"
    aggregate_relative = f"aggregates/versions/{segment['segmentId']}.json"
    issued_times = [prediction.get("issuedAt")
                    for prediction in context["decisions"]]
    max_issued_at = previous_max_issued_at
    for issued_at in issued_times:
        if max_issued_at is None or _parse_time(
                issued_at, "issued_at") > _parse_time(
                    max_issued_at, "max_issued_at"):
            max_issued_at = issued_at
    manifest = _manifest_document(
        segment=segment, segment_path=segment_relative,
        index=index_document, aggregate=aggregate,
        index_path=index_relative, aggregate_path=aggregate_relative,
        updated_at=run_at, max_issued_at=max_issued_at)

    # Every prospective object has passed its serialized byte bound before the
    # first install.  Versioned projections cannot invalidate the old manifest;
    # the atomic manifest replace is the sole commit point.
    _install_immutable_or_verify(
        segment_path, segment, maximum=MAX_SEGMENT_BYTES,
        overflow_error="segment_too_large")
    _install_immutable_or_verify(
        root / index_relative, index_document, maximum=MAX_INDEX_BYTES,
        overflow_error="index_too_large")
    _install_immutable_or_verify(
        root / aggregate_relative, aggregate,
        maximum=MAX_AGGREGATE_BYTES,
        overflow_error="aggregate_too_large")
    _atomic_write(
        root / "manifest.json", manifest, maximum=MAX_MANIFEST_BYTES,
        overflow_error="manifest_too_large")
    return {
        "ok": True, "idempotent": False,
        "segmentPath": segment_relative,
        "segmentId": segment["segmentId"],
        "issued": len(new_decisions),
        "outcomes": len(new_outcomes),
        "evaluations": len(new_evaluations),
        "pending": len(pending),
        "identityCount": len(identities),
        "aggregateEvaluationCount": aggregate["evaluationCount"],
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--ledger-root", required=True)
    parser.add_argument("--expected-mode", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--runner-build-sha", required=True)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)
    try:
        snapshot = _read_json(Path(args.snapshot))
        result = run_prediction_ledger(
            snapshot, ledger_root=Path(args.ledger_root),
            expected_mode=args.expected_mode, run_id=args.run_id,
            runner_build_sha=args.runner_build_sha)
    except LedgerRunError as exc:
        print(json.dumps({"ok": False, "error": str(exc)},
                         sort_keys=True), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
