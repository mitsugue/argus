"""Legacy local prediction projection, preserved for its three real consumers.

This is no longer a Prediction Ledger authority.  New rows are append-only
issued/outcome *projection events*, are always ``unknown_legacy`` mode, and are
never eligible for live calibration.  Historical mutable rows remain readable;
they are not rewritten or silently upgraded.  The canonical sealed contract is
``argus_decision_ledger`` v2.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

LEDGER_PATH = Path(os.environ.get("ARGUS_LEDGER_PATH", "data/predictions.jsonl"))
LEGACY_SCHEMA_VERSION = "argus-legacy-prediction-projection-v2"
LEGACY_MODE = "unknown_legacy"
_APPEND_LOCK = threading.Lock()


def _ensure_path() -> Path:
    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    return LEDGER_PATH


def _now_ms() -> int:
    return int(time.time() * 1000)


def _new_id() -> str:
    return "pred-" + uuid.uuid4().hex[:12]


def _canonical_hash(value: Dict[str, Any]) -> str:
    raw = json.dumps(value, ensure_ascii=False, allow_nan=False,
                     sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _append_event(event: Dict[str, Any]) -> None:
    path = _ensure_path()
    line = json.dumps(event, ensure_ascii=False, allow_nan=False,
                      sort_keys=True, separators=(",", ":")) + "\n"
    with _APPEND_LOCK:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())


HORIZON_MS = {
    "10m": 10 * 60 * 1000,
    "1h": 60 * 60 * 1000,
    "open": 6 * 60 * 60 * 1000,
    "1d": 24 * 60 * 60 * 1000,
}


def log_prediction(
    *,
    code: str,
    direction: str,
    probability: float,
    horizon: str,
    price_at_prediction: float,
    name: Optional[str] = None,
    reason_code: Optional[str] = None,
) -> Dict[str, Any]:
    """Append a new prediction. Returns the entry."""
    if direction not in ("up", "down"):
        raise ValueError(f"direction must be 'up' or 'down', got {direction!r}")
    if horizon not in HORIZON_MS:
        raise ValueError(f"unknown horizon {horizon!r}")
    now = _now_ms()
    body = {
        "schemaVersion": LEGACY_SCHEMA_VERSION,
        "recordType": "issued_projection",
        "authorityClass": "LEGACY_DUPLICATE",
        "mode": LEGACY_MODE,
        "id": _new_id(),
        "predictedAt": now,
        "resolvesAt": now + HORIZON_MS[horizon],
        "resolvedAt": None,
        "code": code,
        "name": name,
        "direction": direction,
        "probability": round(float(probability), 4),
        "horizon": horizon,
        "priceAtPrediction": round(float(price_at_prediction), 4),
        "priceAtResolution": None,
        "movePct": None,
        "outcome": "pending",
        "reasonCode": reason_code,
    }
    entry = {**body, "integrityHash": _canonical_hash(body)}
    _append_event(entry)
    return entry


def _read_all() -> List[Dict[str, Any]]:
    if not LEDGER_PATH.exists():
        return []
    out: List[Dict[str, Any]] = []
    with LEDGER_PATH.open("r", encoding="utf-8") as f:
        for raw in f:
            raw = raw.strip()
            if not raw:
                continue
            try:
                out.append(json.loads(raw))
            except json.JSONDecodeError:
                # Skip malformed lines rather than crash the whole pipeline
                continue
    return out


PriceLookup = Callable[[str, int], Any]


def _issued_events(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [entry for entry in entries
            if entry.get("recordType") in (None, "issued_projection")
            and entry.get("code")]


def _outcome_by_prediction(entries: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    out = {}
    for entry in entries:
        if entry.get("recordType") == "outcome_projection" and entry.get("predictionId"):
            out[str(entry["predictionId"])] = entry
    return out


def _exact_target_truth(value: Any, resolves_at: int) -> Optional[Dict[str, Any]]:
    """Accept only an explicitly target-bound lookup result, never a bare latest price."""
    if not isinstance(value, dict):
        return None
    try:
        price = float(value.get("price"))
        as_of_ms = int(value.get("asOfMs"))
        known_at_ms = int(value.get("knownAtMs"))
    except (TypeError, ValueError):
        return None
    target_session_id = str(value.get("targetSessionId") or "")
    truth_id = str(value.get("truthObservationId") or "")
    if not (price > 0 and as_of_ms == int(resolves_at)
            and known_at_ms >= as_of_ms and target_session_id and truth_id):
        return None
    return {"price": price, "asOfMs": as_of_ms, "knownAtMs": known_at_ms,
            "targetSessionId": target_session_id,
            "truthObservationId": truth_id}


def resolve_outcomes(price_lookup: PriceLookup) -> int:
    """Append one outcome projection for each matured issued projection.

    A bare number/current price is explicitly unscorable.  Exact resolution
    requires a mapping containing price, exact ``asOfMs == resolvesAt``,
    ``knownAtMs``, targetSessionId, and truthObservationId.  Missing proof is
    appended as UNSCORABLE rather than synthesized as a zero return.
    """
    events = _read_all()
    entries = _issued_events(events)
    if not entries:
        return 0
    now = _now_ms()
    resolved_count = 0
    existing_outcomes = _outcome_by_prediction(events)
    for e in entries:
        # Historical in-place rows remain historical evidence. Never append a
        # second interpretation or call them canonical.
        if e.get("outcome") != "pending":
            continue
        if e.get("resolvesAt", 0) > now:
            continue
        if str(e.get("id")) in existing_outcomes:
            continue
        try:
            candidate = price_lookup(e["code"], e["resolvesAt"])
        except Exception:
            candidate = None
        truth = _exact_target_truth(candidate, int(e.get("resolvesAt") or 0))
        body: Dict[str, Any] = {
            "schemaVersion": LEGACY_SCHEMA_VERSION,
            "recordType": "outcome_projection",
            "authorityClass": "LEGACY_DUPLICATE",
            "mode": LEGACY_MODE,
            "predictionId": e.get("id"),
            "recordedAt": now,
            "status": "unscorable",
            "missingReason": "target_session_truth_unbound",
            "targetTruthBound": False,
            "priceAtResolution": None,
            "movePct": None,
            "outcome": "unscorable",
        }
        if truth is not None:
            base = float(e.get("priceAtPrediction") or 0)
            if base > 0:
                move_pct = (truth["price"] - base) / base * 100.0
                is_hit = ((e.get("direction") == "up" and move_pct > 0)
                          or (e.get("direction") == "down" and move_pct < 0))
                body.update({
                    "status": "resolved",
                    "missingReason": None,
                    "targetTruthBound": True,
                    "truthObservationId": truth["truthObservationId"],
                    "targetSessionId": truth["targetSessionId"],
                    "outcomeAsOfMs": truth["asOfMs"],
                    "knownAtMs": truth["knownAtMs"],
                    "priceAtResolution": round(truth["price"], 4),
                    "movePct": round(move_pct, 4),
                    "outcome": "hit" if is_hit else "miss",
                })
                resolved_count += 1
        body["id"] = "legacy-outcome-" + _canonical_hash(body)[:24]
        event = {**body, "integrityHash": _canonical_hash(body)}
        _append_event(event)
    return resolved_count


def aggregate_stats(window_days: int = 30) -> Dict[str, Any]:
    """Compute the CalibrationStats over the rolling window."""
    DAY_MS = 24 * 60 * 60 * 1000
    now = _now_ms()
    cutoff = now - window_days * DAY_MS
    events = _read_all()
    entries = _issued_events(events)
    outcomes = _outcome_by_prediction(events)
    in_window = [e for e in entries if e.get("predictedAt", 0) >= cutoff]
    resolved = [outcomes[str(e.get("id"))] for e in in_window
                if str(e.get("id")) in outcomes
                and outcomes[str(e.get("id"))].get("status") == "resolved"
                and outcomes[str(e.get("id"))].get("targetTruthBound") is True]
    pending = [e for e in in_window if str(e.get("id")) not in outcomes]
    hits = [e for e in resolved if e.get("outcome") == "hit"]

    hit_rate = (len(hits) / len(resolved)) if resolved else 0.0
    expected_rate = (
        sum(float(next((p.get("probability", 0) for p in in_window
                       if p.get("id") == e.get("predictionId")), 0))
            for e in resolved) / len(resolved)
        if resolved else 0.0
    )
    brier = (
        sum(
            (float(next((p.get("probability", 0) for p in in_window
                        if p.get("id") == e.get("predictionId")), 0))
             - (1.0 if e.get("outcome") == "hit" else 0.0)) ** 2
            for e in resolved
        ) / len(resolved)
        if resolved else 0.0
    )

    # Daily sparkline
    daily: List[Dict[str, Any]] = []
    for day in range(window_days - 1, -1, -1):
        day_start = now - (day + 1) * DAY_MS
        day_end = now - day * DAY_MS
        day_entries = [
            e for e in in_window
            if day_start <= e.get("predictedAt", 0) < day_end
            and (outcomes.get(str(e.get("id"))) or {}).get("status") == "resolved"
        ]
        day_hits = sum(1 for e in day_entries
                       if (outcomes.get(str(e.get("id"))) or {}).get("outcome") == "hit")
        daily.append({
            "day": time.strftime("%m-%d", time.gmtime(day_start / 1000)),
            "rate": (day_hits / len(day_entries)) if day_entries else 0.0,
            "n": len(day_entries),
        })

    # Calibration bins
    bins: List[Dict[str, Any]] = []
    num_bins = 5
    for b in range(num_bins):
        lo = b / num_bins
        hi = (b + 1) / num_bins
        hi_inclusive = b == num_bins - 1
        bucket = [
            e for e in in_window
            if (outcomes.get(str(e.get("id"))) or {}).get("status") == "resolved"
            and lo <= float(e.get("probability", 0)) < (hi + (0.001 if hi_inclusive else 0))
        ]
        bucket_hits = sum(1 for e in bucket
                          if (outcomes.get(str(e.get("id"))) or {}).get("outcome") == "hit")
        bins.append({
            "predictedProb": (lo + hi) / 2,
            "count": len(bucket),
            "actualRate": (bucket_hits / len(bucket)) if bucket else 0.0,
        })

    return {
        "schemaVersion": LEGACY_SCHEMA_VERSION,
        "mode": LEGACY_MODE,
        "calibrationEligible": False,
        "windowDays": window_days,
        "resolvedCount": len(resolved),
        "pendingCount": len(pending),
        "hitCount": len(hits),
        "hitRate": round(hit_rate, 4),
        "expectedRate": round(expected_rate, 4),
        "brierScore": round(brier, 4),
        "dailyHitRate": daily,
        "bins": bins,
    }


def list_recent(limit: int = 50) -> List[Dict[str, Any]]:
    events = _read_all()
    entries = _issued_events(events)
    outcomes = _outcome_by_prediction(events)
    projected = []
    for entry in entries:
        outcome = outcomes.get(str(entry.get("id")))
        if outcome is None:
            projected.append(entry)
            continue
        projected.append({**entry,
                          "resolvedAt": outcome.get("recordedAt"),
                          "priceAtResolution": outcome.get("priceAtResolution"),
                          "movePct": outcome.get("movePct"),
                          "outcome": outcome.get("outcome"),
                          "outcomeEventId": outcome.get("id"),
                          "targetTruthBound": outcome.get("targetTruthBound")})
    return sorted(
        projected,
        key=lambda e: e.get("predictedAt", 0),
        reverse=True,
    )[:limit]


def score_to_probability(score: Optional[float], *, default: float = 0.65) -> float:
    """Map a 0..100 combined score onto a calibrated probability in [0.45, 0.92].

    Conservative band so brand-new predictions never claim near-certainty.
    """
    if score is None:
        return default
    try:
        s = float(score)
    except (TypeError, ValueError):
        return default
    # Linear-ish map: 0 → 0.45, 50 → 0.65, 100 → 0.85
    p = 0.45 + (s / 100.0) * 0.40
    return max(0.45, min(0.92, p))
