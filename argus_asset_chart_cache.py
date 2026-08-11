"""Bounded durable cache for provider-free Asset Desk chart GETs."""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any, Callable, Dict, Optional, Tuple


SCHEMA_VERSION = "argus-asset-chart-report-cache-v1"
MAX_RECORDS = 24
MAX_PAYLOAD_BYTES = 2 * 1024 * 1024
MAX_STORE_BYTES = 32 * 1024 * 1024


_NORMALIZED_STORE_MARKER = object()


class _NormalizedStore(dict):
    """A short-lived result produced by this module's normalizer."""

    __slots__ = ("_normalized_store_marker",)

    def __init__(self, value: Dict[str, Any]) -> None:
        super().__init__(value)
        self._normalized_store_marker = _NORMALIZED_STORE_MARKER

    def _invalidate(self) -> None:
        self._normalized_store_marker = None

    def __setitem__(self, key: Any, value: Any) -> None:
        self._invalidate()
        super().__setitem__(key, value)

    def __delitem__(self, key: Any) -> None:
        self._invalidate()
        super().__delitem__(key)

    def clear(self) -> None:
        self._invalidate()
        super().clear()

    def pop(self, key: Any, *args: Any) -> Any:
        self._invalidate()
        return super().pop(key, *args)

    def popitem(self) -> Tuple[Any, Any]:
        self._invalidate()
        return super().popitem()

    def setdefault(self, key: Any, default: Any = None) -> Any:
        self._invalidate()
        return super().setdefault(key, default)

    def update(self, *args: Any, **kwargs: Any) -> None:
        self._invalidate()
        super().update(*args, **kwargs)

    def __ior__(self, other: Any) -> "_NormalizedStore":
        self._invalidate()
        super().__ior__(other)
        return self

    def __copy__(self) -> Dict[str, Any]:
        return dict(self)

    def __deepcopy__(self, memo: Dict[int, Any]) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        memo[id(self)] = result
        for key, value in self.items():
            result[copy.deepcopy(key, memo)] = copy.deepcopy(value, memo)
        return result


def _has_normalized_store_provenance(value: Any) -> bool:
    return (
        type(value) is _NormalizedStore
        and value._normalized_store_marker is _NORMALIZED_STORE_MARKER
    )


def _canonical(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()[:24]


def _diagnostic_notify(
        observer: Optional[Callable[[str, Dict[str, Any]], None]],
        phase: str, metadata: Dict[str, Any]) -> None:
    if observer is None:
        return
    try:
        observer(phase, dict(metadata))
    except Exception:
        # Observability is deliberately fail-open and cannot alter cache truth.
        return


def identity_key(market: str, symbol: str, timeframe: str) -> str:
    return ":".join((
        str(market).strip().upper(),
        str(symbol).strip().upper(),
        str(timeframe).strip().lower(),
    ))


def logical_key(
    market: str,
    symbol: str,
    timeframe: str,
    dataset_hash: str,
    method_version: str,
) -> str:
    return ":".join((
        identity_key(market, symbol, timeframe),
        str(dataset_hash),
        str(method_version),
    ))


def empty_store() -> Dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "records": {},
        "current": {},
        "cursor": 0,
        "lastUpdatedAt": None,
    }


def normalize_store(value: Any) -> Dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    store = empty_store()
    records = source.get("records")
    current = source.get("current")
    if isinstance(records, dict):
        store["records"] = {
            str(key): copy.deepcopy(record)
            for key, record in records.items()
            if isinstance(record, dict)
        }
    if isinstance(current, dict):
        store["current"] = {
            str(key): str(pointer)
            for key, pointer in current.items()
            if str(pointer) in store["records"]
        }
    try:
        store["cursor"] = max(0, int(source.get("cursor") or 0))
    except (TypeError, ValueError):
        store["cursor"] = 0
    store["lastUpdatedAt"] = source.get("lastUpdatedAt")
    _prune(store)
    return _NormalizedStore(store)


def _prune(store: Dict[str, Any]) -> None:
    records = store["records"]
    protected = set(store["current"].values())
    if len(records) <= MAX_RECORDS:
        return
    removable = sorted(
        (
            (str(record.get("publishedAt") or ""), key)
            for key, record in records.items()
            if key not in protected
        ),
    )
    for _, key in removable:
        if len(records) <= MAX_RECORDS:
            break
        records.pop(key, None)


def _valid_report(
    report: Any, *, market: str, symbol: str, timeframe: str,
) -> bool:
    if not isinstance(report, dict):
        return False
    if str(report.get("market") or "").upper() != market.upper():
        return False
    if str(report.get("symbol") or "").upper() != symbol.upper():
        return False
    if timeframe not in {"daily", "weekly"}:
        return False
    if str(report.get("status") or "") in {
        "", "error", "mock", "expected_skip",
    }:
        return False
    bars = (report.get("indicators") or {}).get("bars")
    return (
        isinstance(bars, list)
        and bool(bars)
        and len(_canonical(report).encode("utf-8")) <= MAX_PAYLOAD_BYTES
    )


def publish(
    store: Any,
    *,
    market: str,
    symbol: str,
    timeframe: str,
    dataset_hash: str,
    method_version: str,
    report: Dict[str, Any],
    published_at: str,
) -> Tuple[Dict[str, Any], str]:
    original = normalize_store(store)
    out = copy.deepcopy(original)
    market = str(market).upper()
    symbol = str(symbol).upper()
    timeframe = str(timeframe).lower()
    if not dataset_hash or not method_version:
        return out, "identity_incomplete"
    if not _valid_report(
            report, market=market, symbol=symbol, timeframe=timeframe):
        return out, "report_invalid"
    key = logical_key(
        market, symbol, timeframe, dataset_hash, method_version)
    identity = identity_key(market, symbol, timeframe)
    existing_key = out["current"].get(identity)
    if existing_key == key:
        existing = out["records"].get(key) or {}
        if existing.get("payloadHash") == _hash(report):
            return out, "unchanged"
    record = {
        "schemaVersion": SCHEMA_VERSION,
        "logicalKey": key,
        "identityKey": identity,
        "market": market,
        "symbol": symbol,
        "timeframe": timeframe,
        "datasetHash": str(dataset_hash),
        "methodVersion": str(method_version),
        "publishedAt": str(published_at),
        "periodEnd": report.get("periodEnd"),
        "payloadHash": _hash(report),
        "payload": copy.deepcopy(report),
    }
    out["records"][key] = record
    out["current"][identity] = key
    out["lastUpdatedAt"] = str(published_at)
    _prune(out)
    if len(_canonical(out).encode("utf-8")) > MAX_STORE_BYTES:
        return original, "memory_soft_limit"
    return out, "published"


def current(
    store: Any, market: str, symbol: str, timeframe: str,
) -> Dict[str, Any] | None:
    source = store if isinstance(store, dict) else {}
    pointers = source.get("current")
    records = source.get("records")
    if not isinstance(pointers, dict) or not isinstance(records, dict):
        return None
    key = pointers.get(
        identity_key(market, symbol, timeframe))
    record = records.get(key)
    if not isinstance(record, dict):
        return None
    payload = record.get("payload")
    if record.get("payloadHash") != _hash(payload):
        return None
    if not _valid_report(
            payload, market=str(market).upper(),
            symbol=str(symbol).upper(), timeframe=str(timeframe).lower()):
        return None
    return copy.deepcopy(record)


def merge_restored(local: Any, restored: Any) -> Dict[str, Any]:
    out = normalize_store(local)
    incoming = normalize_store(restored)
    for identity, key in incoming["current"].items():
        candidate = incoming["records"].get(key)
        if not isinstance(candidate, dict):
            continue
        current_key = out["current"].get(identity)
        current_record = out["records"].get(current_key) or {}
        if str(candidate.get("publishedAt") or "") < str(
                current_record.get("publishedAt") or ""):
            continue
        payload = candidate.get("payload")
        if candidate.get("payloadHash") != _hash(payload):
            continue
        out["records"][key] = copy.deepcopy(candidate)
        out["current"][identity] = key
    out["cursor"] = max(out["cursor"], incoming["cursor"])
    out["lastUpdatedAt"] = max(
        str(out.get("lastUpdatedAt") or ""),
        str(incoming.get("lastUpdatedAt") or ""),
    ) or None
    _prune(out)
    return out


def state_hash(
        store: Any, *,
        diagnostic_observer: Optional[
            Callable[[str, Dict[str, Any]], None]] = None) -> str:
    observing = diagnostic_observer is not None
    if observing:
        _diagnostic_notify(diagnostic_observer, "hash_enter", {})
    normalized = normalize_store(store)
    if observing:
        _diagnostic_notify(diagnostic_observer, "internal_normalize_complete", {
            "recordCount": len(normalized["records"]),
            "currentCount": len(normalized["current"]),
            "hashNormalizedAlive": True,
        })
    # The round-robin cursor is an operational scheduling detail and advances
    # even when no chart payload changes.  Remote read-back integrity is bound
    # to published reports/pointers, not to that transient cursor.
    material = {
        "schemaVersion": normalized["schemaVersion"],
        "records": normalized["records"],
        "current": normalized["current"],
    }
    if observing:
        _diagnostic_notify(diagnostic_observer, "hash_projection_ready", {
            "recordCount": len(material["records"]),
            "currentCount": len(material["current"]),
        })
    canonical = _canonical(material)
    if observing:
        _diagnostic_notify(diagnostic_observer, "canonical_string_ready", {
            "canonicalCharacterCount": len(canonical),
        })
    encoded = canonical.encode("utf-8")
    del canonical
    if observing:
        _diagnostic_notify(diagnostic_observer, "utf8_bytes_ready", {
            "canonicalByteCount": len(encoded),
        })
    hasher = hashlib.sha256(encoded)
    del encoded
    digest = hasher.hexdigest()[:24]
    if observing:
        _diagnostic_notify(diagnostic_observer, "hash_complete", {
            "digestCharacterCount": len(digest),
        })
    return digest


def state_hash_normalized(
        store: Any, *,
        diagnostic_observer: Optional[
            Callable[[str, Dict[str, Any]], None]] = None) -> str:
    """Hash this module's direct, unmodified ``normalize_store`` result.

    Inputs without this module's live provenance marker fail safely through
    the established raw ``state_hash`` path.
    """
    observing = diagnostic_observer is not None
    if not _has_normalized_store_provenance(store):
        if observing:
            _diagnostic_notify(
                diagnostic_observer, "normalized_input_fallback",
                {"reason": "untrusted_provenance"})
        return state_hash(store, diagnostic_observer=diagnostic_observer)
    if observing:
        _diagnostic_notify(diagnostic_observer, "hash_enter", {})
        _diagnostic_notify(diagnostic_observer, "normalized_input_reused", {
            "recordCount": len(store["records"]),
            "currentCount": len(store["current"]),
            "hashNormalizedAlive": True,
        })
    # Keep the exact raw state_hash projection: cursor and lastUpdatedAt are
    # scheduling metadata and are intentionally excluded from integrity truth.
    material = {
        "schemaVersion": store["schemaVersion"],
        "records": store["records"],
        "current": store["current"],
    }
    if observing:
        _diagnostic_notify(diagnostic_observer, "hash_projection_ready", {
            "recordCount": len(material["records"]),
            "currentCount": len(material["current"]),
        })
    canonical = _canonical(material)
    if observing:
        _diagnostic_notify(diagnostic_observer, "canonical_string_ready", {
            "canonicalCharacterCount": len(canonical),
        })
    encoded = canonical.encode("utf-8")
    del canonical
    if observing:
        _diagnostic_notify(diagnostic_observer, "utf8_bytes_ready", {
            "canonicalByteCount": len(encoded),
        })
    hasher = hashlib.sha256(encoded)
    del encoded
    digest = hasher.hexdigest()[:24]
    if observing:
        _diagnostic_notify(diagnostic_observer, "hash_complete", {
            "digestCharacterCount": len(digest),
        })
    return digest


def read_back_verified(local: Any, remote: Any) -> bool:
    return state_hash(local) == state_hash(remote)
