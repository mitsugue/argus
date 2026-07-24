"""Verified, immutable public view snapshots.

This module is intentionally provider-free.  Producers build a complete view,
verify a JSON read-back, and only then replace the current pointer.  Public GET
handlers consume the pointer and never invoke the producer.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import threading
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional, Tuple


SCHEMA_VERSION = "argus-verified-view-snapshot-v1"
STORE_SCHEMA_VERSION = "argus-verified-view-store-v1"
METHOD_VERSION = "verified-chart-view-v1"
QUALITY_RANK = {"stale": 0, "partial": 1, "live": 2}
MAX_CURRENT = 24
MAX_HISTORY = 48


def _stable_json_value(value: Any) -> Any:
    # JSON.parse/stringify in browsers represents 100.0 as 100.  Normalize
    # integral finite floats so Python and TypeScript compute the same ID.
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        return int(value)
    if isinstance(value, list):
        return [_stable_json_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _stable_json_value(item) for key, item in value.items()}
    return value


def _canonical(value: Any) -> str:
    return json.dumps(
        _stable_json_value(value), ensure_ascii=False, sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _parse_time(value: Any) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        if len(text) == 10:
            return datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def snapshot_key(kind: str, instrument: str, horizon: str) -> str:
    return ":".join((
        str(kind or "").strip().lower(),
        str(instrument or "").strip().upper(),
        str(horizon or "").strip().upper(),
    ))


def empty_store() -> Dict[str, Any]:
    return {
        "schemaVersion": STORE_SCHEMA_VERSION,
        "current": {},
        "history": [],
        "lastPublishedAt": None,
    }


def _identity_material(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    # Keep the identifier portable across Python/JSON and browser JSON.  The
    # dataset hash binds the OHLCV input, while the state/method/time fields
    # identify the complete view publication. Payload validity is checked
    # separately before either server or browser accepts the envelope.
    fields = (
        "schemaVersion", "kind", "instrument", "horizon", "datasetHash",
        "payloadHash", "methodVersion", "asOf", "generatedAt", "verifiedAt", "quality",
        "sourceStatus", "verificationStatus",
    )
    return {key: snapshot.get(key) for key in fields}


def snapshot_id(snapshot: Dict[str, Any]) -> str:
    return f"vs-{_sha(_identity_material(snapshot))[:32]}"


def _portable_number(value: Any) -> Optional[str]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    text = f"{number:.8f}".rstrip("0").rstrip(".")
    return "0" if text in {"", "-0"} else text


def payload_hash(payload: Dict[str, Any]) -> str:
    indicators = payload.get("indicators") if isinstance(payload, dict) else None
    bars = indicators.get("bars") if isinstance(indicators, dict) else []
    material = [{
        "date": str(row.get("date") or ""),
        "open": _portable_number(row.get("open")),
        "high": _portable_number(row.get("high")),
        "low": _portable_number(row.get("low")),
        "close": _portable_number(row.get("close")),
        "volume": (_portable_number(row.get("volume"))
                   if row.get("volume") is not None else None),
        "availableFrom": str(row.get("availableFrom") or ""),
    } for row in bars if isinstance(row, dict)]
    return _sha(material)


def _valid_bars(payload: Dict[str, Any]) -> Tuple[bool, str]:
    indicators = payload.get("indicators")
    bars = indicators.get("bars") if isinstance(indicators, dict) else None
    if not isinstance(bars, list) or not bars:
        return False, "empty_required_series"
    dates = []
    for row in bars:
        if not isinstance(row, dict):
            return False, "malformed_series"
        date = str(row.get("date") or "")[:10]
        if not date:
            return False, "missing_series_date"
        try:
            opening = float(row.get("open"))
            high = float(row.get("high"))
            low = float(row.get("low"))
            close = float(row.get("close"))
        except (TypeError, ValueError):
            return False, "non_numeric_series"
        if min(opening, high, low, close) <= 0 or high < low:
            return False, "invalid_ohlc"
        if high < max(opening, close) or low > min(opening, close):
            return False, "inconsistent_ohlc"
        dates.append(date)
    if dates != sorted(dates) or len(dates) != len(set(dates)):
        return False, "mixed_or_unsorted_series"
    return True, "ok"


def verify_snapshot(
        snapshot: Any, *, expected_kind: Optional[str] = None,
        expected_instrument: Optional[str] = None,
        expected_horizon: Optional[str] = None,
        expected_method_version: Optional[str] = None,
        now_iso: Optional[str] = None) -> Tuple[bool, str]:
    if not isinstance(snapshot, dict):
        return False, "malformed_snapshot"
    required = (
        "schemaVersion", "snapshotId", "kind", "instrument", "horizon",
        "datasetHash", "payloadHash", "methodVersion", "asOf", "generatedAt", "verifiedAt",
        "quality", "sourceStatus", "payload",
    )
    if any(key not in snapshot for key in required):
        return False, "schema_missing_field"
    if snapshot.get("schemaVersion") != SCHEMA_VERSION:
        return False, "schema_incompatible"
    if snapshot.get("verificationStatus") != "verified":
        return False, "readback_unverified"
    if not str(snapshot.get("datasetHash") or "").strip():
        return False, "dataset_hash_missing"
    if snapshot.get("payloadHash") != payload_hash(snapshot.get("payload") or {}):
        return False, "payload_hash_mismatch"
    if not str(snapshot.get("methodVersion") or "").strip():
        return False, "method_version_missing"
    if expected_kind and str(snapshot.get("kind")).lower() != expected_kind.lower():
        return False, "kind_mismatch"
    if expected_instrument and str(snapshot.get("instrument")).upper() != \
            expected_instrument.upper():
        return False, "instrument_mismatch"
    if expected_horizon and str(snapshot.get("horizon")).upper() != \
            expected_horizon.upper():
        return False, "horizon_mismatch"
    if expected_method_version and snapshot.get("methodVersion") != \
            expected_method_version:
        return False, "method_version_incompatible"
    if snapshot.get("quality") not in QUALITY_RANK:
        return False, "quality_invalid"
    if not isinstance(snapshot.get("sourceStatus"), dict):
        return False, "source_status_invalid"
    if any("mock" in str(value).lower()
           for value in snapshot["sourceStatus"].values()):
        return False, "mock_source"
    payload = snapshot.get("payload")
    if not isinstance(payload, dict) or not payload:
        return False, "empty_payload"
    if "mock" in str(payload.get("status") or "").lower() or \
            "mock" in str(payload.get("source") or "").lower():
        return False, "mock_payload"
    if payload.get("automaticAiCalls") not in (None, 0):
        return False, "automatic_ai_payload"
    metadata = payload.get("instrumentMetadata")
    actual_symbol = (metadata.get("symbol") if isinstance(metadata, dict)
                     else payload.get("symbol"))
    if actual_symbol and str(actual_symbol).upper() != \
            str(snapshot.get("instrument")).upper():
        return False, "payload_instrument_mismatch"
    ok, reason = _valid_bars(payload)
    if not ok:
        return ok, reason
    replay = payload.get("marketReplay")
    horizon_key = str(snapshot.get("horizon") or "").upper().removesuffix("D")
    if isinstance(replay, dict):
        context = (replay.get("contexts") or {}).get(horizon_key)
        if not isinstance(context, dict):
            return False, "horizon_payload_missing"
        if context.get("datasetHash") != snapshot.get("datasetHash"):
            return False, "dataset_hash_mismatch"
    times = [_parse_time(snapshot.get(name))
             for name in ("asOf", "generatedAt", "verifiedAt")]
    if any(value is None for value in times):
        return False, "timestamp_invalid"
    now = _parse_time(now_iso) if now_iso else datetime.now(timezone.utc)
    if now and any(value > now.replace(microsecond=0)
                   and (value - now).total_seconds() > 300 for value in times):
        return False, "future_timestamp"
    if snapshot_id(snapshot) != snapshot.get("snapshotId"):
        return False, "snapshot_id_mismatch"
    return True, "verified"


def build_snapshot(
        *, payload: Dict[str, Any], kind: str, instrument: str, horizon: str,
        dataset_hash: str, method_version: str, as_of: str, generated_at: str,
        quality: str, source_status: Dict[str, str]) -> Dict[str, Any]:
    candidate = {
        "schemaVersion": SCHEMA_VERSION,
        "snapshotId": "",
        "kind": kind,
        "instrument": instrument.upper(),
        "horizon": horizon.upper(),
        "datasetHash": dataset_hash,
        "payloadHash": payload_hash(payload),
        "methodVersion": method_version,
        "asOf": as_of,
        "generatedAt": generated_at,
        "verifiedAt": generated_at,
        "quality": quality,
        "sourceStatus": dict(source_status),
        "verificationStatus": "verified",
        "payload": copy.deepcopy(payload),
    }
    candidate["snapshotId"] = snapshot_id(candidate)
    return candidate


def _is_older(candidate: Dict[str, Any], current: Dict[str, Any]) -> bool:
    new_time = _parse_time(candidate.get("generatedAt"))
    old_time = _parse_time(current.get("generatedAt"))
    return bool(new_time and old_time and new_time < old_time)


def needs_generation(
        store: Dict[str, Any], *, kind: str, instrument: str, horizon: str,
        dataset_hash: str, method_version: str) -> bool:
    current = (store.get("current") or {}).get(
        snapshot_key(kind, instrument, horizon))
    ok, _ = verify_snapshot(
        current, expected_kind=kind, expected_instrument=instrument,
        expected_horizon=horizon, expected_method_version=method_version)
    return not (ok and current.get("datasetHash") == dataset_hash)


def publish_atomic(
        store: Dict[str, Any], candidate: Dict[str, Any],
        *, now_iso: Optional[str] = None) -> Tuple[Dict[str, Any], str]:
    """Verify a serialized read-back, then replace exactly one current pointer."""
    ok, reason = verify_snapshot(candidate, now_iso=now_iso)
    if not ok:
        return copy.deepcopy(store), reason
    try:
        read_back = json.loads(_canonical(candidate))
    except (TypeError, ValueError):
        return copy.deepcopy(store), "temporary_write_failed"
    ok, reason = verify_snapshot(read_back, now_iso=now_iso)
    if not ok:
        return copy.deepcopy(store), reason
    key = snapshot_key(
        read_back["kind"], read_back["instrument"], read_back["horizon"])
    result = normalize_store(store)
    current = result["current"].get(key)
    if isinstance(current, dict):
        if current.get("snapshotId") == read_back.get("snapshotId"):
            return result, "unchanged"
        if _is_older(read_back, current):
            return result, "older_rejected"
        if QUALITY_RANK[read_back["quality"]] < QUALITY_RANK[current["quality"]]:
            return result, "quality_downgrade_rejected"
        result["history"].append({
            "key": key, "snapshotId": current.get("snapshotId"),
            "replacedAt": read_back.get("verifiedAt"),
        })
    result["current"][key] = read_back
    if len(result["current"]) > MAX_CURRENT:
        ordered = sorted(
            result["current"].items(),
            key=lambda item: str(item[1].get("verifiedAt") or ""),
            reverse=True)
        result["current"] = dict(ordered[:MAX_CURRENT])
    result["history"] = result["history"][-MAX_HISTORY:]
    result["lastPublishedAt"] = read_back.get("verifiedAt")
    return result, "published"


def normalize_store(value: Any) -> Dict[str, Any]:
    result = empty_store()
    if not isinstance(value, dict):
        return result
    for key, snapshot in (value.get("current") or {}).items():
        ok, _ = verify_snapshot(snapshot)
        expected = snapshot_key(
            snapshot.get("kind"), snapshot.get("instrument"),
            snapshot.get("horizon")) if isinstance(snapshot, dict) else ""
        if ok and key == expected:
            result["current"][key] = copy.deepcopy(snapshot)
    history = value.get("history")
    if isinstance(history, list):
        result["history"] = [
            copy.deepcopy(item) for item in history[-MAX_HISTORY:]
            if isinstance(item, dict)]
    result["lastPublishedAt"] = value.get("lastPublishedAt")
    return result


def state_hash(store: Dict[str, Any]) -> str:
    return _sha(normalize_store(store))


def read_back_verified(local: Dict[str, Any], remote: Dict[str, Any]) -> bool:
    return state_hash(local) == state_hash(remote)


class SingleFlight:
    """Coalesce concurrent producers for the same logical snapshot key."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._flights: Dict[str, Dict[str, Any]] = {}

    def run(self, key: str, producer: Callable[[], Any]) -> Any:
        with self._lock:
            flight = self._flights.get(key)
            if flight is None:
                flight = {"event": threading.Event(), "owner": True}
                self._flights[key] = flight
                owner = True
            else:
                owner = False
        if not owner:
            flight["event"].wait()
            if flight.get("error") is not None:
                raise flight["error"]
            return copy.deepcopy(flight.get("result"))
        try:
            result = producer()
            flight["result"] = copy.deepcopy(result)
            return result
        except BaseException as exc:
            flight["error"] = exc
            raise
        finally:
            flight["event"].set()
            with self._lock:
                self._flights.pop(key, None)
