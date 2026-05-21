"""A.R.G.U.S. prediction ledger.

Append-only JSON Lines store. Each line is a single PredictionEntry whose
shape matches the TS PredictionEntry on the React frontend, so the
/api/argus/calibration endpoint can return the aggregate directly with
no shape conversion in between.

Storage path is controlled by the ARGUS_LEDGER_PATH env var so a
persistent disk (e.g. Render Disk mounted at /data) can be plugged in
without touching code.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

LEDGER_PATH = Path(os.environ.get("ARGUS_LEDGER_PATH", "data/predictions.jsonl"))


def _ensure_path() -> Path:
    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    return LEDGER_PATH


def _now_ms() -> int:
    return int(time.time() * 1000)


def _new_id() -> str:
    return "pred-" + uuid.uuid4().hex[:12]


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
    entry = {
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
    path = _ensure_path()
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
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


def _write_all(entries: List[Dict[str, Any]]) -> None:
    path = _ensure_path()
    tmp = path.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    tmp.replace(path)


PriceLookup = Callable[[str, int], Optional[float]]


def resolve_outcomes(price_lookup: PriceLookup) -> int:
    """For every pending entry whose resolvesAt is in the past, resolve it.

    `price_lookup(code, ts_ms)` should return the close-enough price for
    that ticker around that timestamp, or None if unavailable (in which
    case the entry stays pending and will be retried later).

    Returns the number of newly-resolved entries.
    """
    entries = _read_all()
    if not entries:
        return 0
    now = _now_ms()
    resolved_count = 0
    changed = False
    for e in entries:
        if e.get("outcome") != "pending":
            continue
        if e.get("resolvesAt", 0) > now:
            continue
        try:
            actual = price_lookup(e["code"], e["resolvesAt"])
        except Exception:
            actual = None
        if actual is None:
            continue
        base = e.get("priceAtPrediction", 0) or 1e-9
        move_pct = (actual - base) / base * 100
        is_hit = (
            (e["direction"] == "up" and move_pct > 0)
            or (e["direction"] == "down" and move_pct < 0)
        )
        e["outcome"] = "hit" if is_hit else "miss"
        e["resolvedAt"] = now
        e["priceAtResolution"] = round(float(actual), 4)
        e["movePct"] = round(move_pct, 4)
        resolved_count += 1
        changed = True
    if changed:
        _write_all(entries)
    return resolved_count


def aggregate_stats(window_days: int = 30) -> Dict[str, Any]:
    """Compute the CalibrationStats over the rolling window."""
    DAY_MS = 24 * 60 * 60 * 1000
    now = _now_ms()
    cutoff = now - window_days * DAY_MS
    entries = _read_all()
    in_window = [e for e in entries if e.get("predictedAt", 0) >= cutoff]
    resolved = [e for e in in_window if e.get("outcome") != "pending"]
    pending = [e for e in in_window if e.get("outcome") == "pending"]
    hits = [e for e in resolved if e.get("outcome") == "hit"]

    hit_rate = (len(hits) / len(resolved)) if resolved else 0.0
    expected_rate = (
        sum(float(e.get("probability", 0)) for e in resolved) / len(resolved)
        if resolved else 0.0
    )
    brier = (
        sum(
            (float(e.get("probability", 0)) - (1.0 if e.get("outcome") == "hit" else 0.0)) ** 2
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
            e for e in resolved
            if day_start <= e.get("predictedAt", 0) < day_end
        ]
        day_hits = sum(1 for e in day_entries if e.get("outcome") == "hit")
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
            e for e in resolved
            if lo <= float(e.get("probability", 0)) < (hi + (0.001 if hi_inclusive else 0))
        ]
        bucket_hits = sum(1 for e in bucket if e.get("outcome") == "hit")
        bins.append({
            "predictedProb": (lo + hi) / 2,
            "count": len(bucket),
            "actualRate": (bucket_hits / len(bucket)) if bucket else 0.0,
        })

    return {
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
    entries = _read_all()
    return sorted(
        entries,
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
