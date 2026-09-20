"""Preserve provider balances and actual acquisition time for Japan analysis."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date, timedelta, timezone
from typing import Any, Mapping

from jp_market_engine import _instant
from jp_market_dynamics import _number

JQUANTS_MARGIN_SOURCE = "https://api.jquants.com/v2/markets/margin-interest"
MARGIN_FIELDS = {
    "LongVol": "margin.long_balance", "ShrtVol": "margin.short_balance",
    "LongStdVol": "margin.standardized.long_balance", "ShrtStdVol": "margin.standardized.short_balance",
    "LongNegVol": "margin.negotiable.long_balance", "ShrtNegVol": "margin.negotiable.short_balance",
}


def normalize_jquants_margin_snapshot(payload: Mapping[str, Any], *, instrument_id: str,
                                      observed_at: str, response_sha256: str,
                                      volume_unit: str) -> dict[str, Any]:
    """Normalize a fetched response without backdating when ARGUS knew it.

    Date is the balance period, not a publication timestamp. This endpoint
    supplies no timestamp proving its historical vintage. A fresh download is
    available from its actual receipt time only; do not invent a Friday+7 rule.
    The volume unit must be established by the caller's source contract.
    Standardized and negotiable balances remain separate from total balances;
    neither aggregate describes the maturity of individual positions.
    """
    observed = _instant(observed_at)
    if observed is None or len(str(observed_at)) <= 10:
        raise ValueError("actual_observation_time_required")
    if not re.fullmatch(r"[0-9A-Z]{4}", instrument_id):
        raise ValueError("explicit_instrument_required")
    if volume_unit not in {"SHARES", "UNITS"}:
        raise ValueError("explicit_volume_unit_required")
    if not re.fullmatch(r"[0-9a-f]{64}", response_sha256):
        raise ValueError("response_digest_required")
    raw_rows = payload.get("data") if isinstance(payload, Mapping) else None
    if not isinstance(raw_rows, list) or len(raw_rows) > 10000:
        raise ValueError("bounded_provider_rows_required")
    observed_iso = observed.isoformat()
    observed_day = observed.astimezone(timezone(timedelta(hours=9))).date()
    rows, rejected, seen = [], [], set()
    for index, raw in enumerate(raw_rows):
        reason = None
        if not isinstance(raw, Mapping):
            rejected.append({"rowIndex": index, "reason": "invalid_row"})
            continue
        code = str(raw.get("Code", ""))
        period = str(raw.get("Date", ""))
        try:
            period_day = date.fromisoformat(period)
            if period_day.isoformat() != period or period_day > observed_day:
                reason = "invalid_or_future_period"
        except ValueError:
            reason = "invalid_period"
        if code not in {instrument_id, instrument_id + "0"}:
            reason = "different_instrument"
        values = {key: _number(raw[key]) for key in MARGIN_FIELDS if raw.get(key) is not None}
        if not {"LongVol", "ShrtVol"}.issubset(values):
            reason = "missing_total_balance"
        elif any(value is None or value < 0 or not value.is_integer() for value in values.values()):
            reason = "invalid_balance"
        else:
            for side in ("Long", "Shrt"):
                total, standard, negotiable = (values.get(side + suffix) for suffix in ("Vol", "StdVol", "NegVol"))
                if standard is not None and negotiable is not None and standard + negotiable != total:
                    reason = "inconsistent_credit_components"
        if period in seen:
            reason = "duplicate_period"
        if reason:
            rejected.append({"rowIndex": index, "reason": reason})
            continue
        seen.add(period)
        raw_digest = hashlib.sha256(json.dumps(dict(raw), sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()
        for provider_field, value in values.items():
            rows.append({
                "instrumentId": instrument_id, "seriesId": MARGIN_FIELDS[provider_field],
                "balanceKind": "WEEKLY_MARGIN", "periodEnd": period, "date": period,
                "value": value, "unit": volume_unit, "providerCode": code,
                "sourceRef": JQUANTS_MARGIN_SOURCE, "providerField": provider_field,
                "sourceResponseSha256": response_sha256, "sourceRowSha256": raw_digest,
                "observedAt": observed_iso, "knownAt": observed_iso, "availableFrom": observed_iso,
                "publishedAt": None, "availabilityBasis": "ACTUAL_RECEIPT",
                "historicalVintageVerified": False, "adjustmentBasis": "UNADJUSTED_BALANCE",
                "creditTermKnown": False, "validationStatus": "DESCRIPTIVE_NOT_PREDICTIVE",
            })
    # Ambiguous duplicates invalidate that period, including an earlier row.
    duplicates = {str(raw_rows[x["rowIndex"]].get("Date", "")) for x in rejected
                  if x["reason"] == "duplicate_period"}
    rows = [row for row in rows if row["date"] not in duplicates]
    incomplete = bool(payload.get("pagination_key"))
    return {"schemaVersion": "jp-market-margin-source-v1", "instrumentId": instrument_id,
            "observedAt": observed_iso, "rows": sorted(rows, key=lambda row: (row["date"], row["seriesId"])),
            "rejectedRows": rejected, "paginationRemaining": incomplete,
            "status": "PARTIAL" if rejected or incomplete else "AVAILABLE" if rows else "UNAVAILABLE",
            "historicalVintageVerified": False, "actionAuthority": False}


_MARGIN_RECEIPT_FIELDS = {"observedAt", "knownAt", "availableFrom", "sourceResponseSha256", "revision"}
_MARGIN_MAX_ROWS = 12000


def _margin_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _margin_key(row):
    return (row["instrumentId"], row["seriesId"], row["periodEnd"])


def _margin_merge_rows(previous, incoming):
    """Keep original receipts; append true revisions without changing the prefix."""
    from copy import deepcopy
    result = deepcopy(previous)
    latest = {_margin_key(row): row for row in result}
    for row in incoming:
        old = latest.get(_margin_key(row))
        if old:
            identity = lambda value: {k: v for k, v in value.items() if k not in _MARGIN_RECEIPT_FIELDS}
            if identity(old) == identity(row):
                continue
            if _instant(row["knownAt"]) <= _instant(old["knownAt"]):
                raise ValueError("margin_revision_receipt_order")
            row = {**row, "revision": int(old.get("revision", 0)) + 1}
        result.append(deepcopy(row))
        latest[_margin_key(row)] = row
    if len(result) > _MARGIN_MAX_ROWS:
        raise ValueError("margin_retention_maintenance_required")
    return result


def _margin_read(db, instrument_id):
    exists = db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='margin_input_history'").fetchone()
    if not exists:
        return None
    rows = []
    for body, digest in db.execute("SELECT body,sha256 FROM margin_input_history WHERE instrument=? ORDER BY seq", (instrument_id,)):
        if len(rows) >= _MARGIN_MAX_ROWS or hashlib.sha256(body.encode()).hexdigest() != digest:
            raise ValueError("margin_history_integrity_or_bound")
        row = json.loads(body)
        if row.get("instrumentId") != instrument_id or _instant(row.get("knownAt")) is None:
            raise ValueError("margin_history_identity")
        rows.append(row)
    meta = db.execute("SELECT value FROM metadata WHERE key=?", ("margin_snapshot:" + instrument_id,)).fetchone()
    if not meta:
        if rows:
            raise ValueError("margin_history_metadata_missing")
        return None
    envelope = json.loads(meta[0]); document = envelope["document"]
    if hashlib.sha256(_margin_json(document).encode()).hexdigest() != envelope["sha256"]:
        raise ValueError("margin_metadata_integrity")
    if document.get("instrumentId") != instrument_id or document.get("rowCount") != len(rows):
        raise ValueError("margin_metadata_identity")
    return {**document, "rows": rows, "historyStatus": "LOCAL_DURABLE"}


def restore_margin_snapshot(path, instrument_id="1570"):
    """Background-only restore; absent storage never creates a file."""
    from pathlib import Path
    import sqlite3
    target = Path(path)
    if target.is_symlink():
        raise ValueError("margin_store_symlink")
    if not target.exists():
        return None
    db = sqlite3.connect(target.resolve().as_uri() + "?mode=ro", uri=True, timeout=10)
    try:
        return _margin_read(db, instrument_id)
    finally:
        db.close()


def retain_margin_snapshot(candidate, *, previous=None, path=None, raw=None):
    """Use the existing source store for append-only observations and raw receipts.

    A rolling provider response may omit old periods. Omission does not erase
    them. Corrections carry their own actual receipt and monotonically increasing
    revision. A successful identical recheck advances only snapshot freshness.
    """
    from copy import deepcopy
    if not candidate.get("rows"):
        raise ValueError("margin_nonempty_candidate_required")
    instrument = candidate["instrumentId"]
    if previous and previous.get("instrumentId") != instrument:
        raise ValueError("margin_previous_instrument")
    db = None
    try:
        if path:
            from jp_market_acquisition import connect
            db = connect(path)
            db.execute("CREATE TABLE IF NOT EXISTS margin_input_history(seq INTEGER PRIMARY KEY,instrument TEXT NOT NULL,body TEXT NOT NULL,sha256 TEXT NOT NULL)")
            db.execute("BEGIN IMMEDIATE")
            stored = _margin_read(db, instrument)
        else:
            stored = None
        original = (stored or {}).get("rows", [])
        seed = original if stored else (previous or {}).get("rows", [])
        rows = _margin_merge_rows(seed, candidate["rows"])
        result = {**deepcopy(candidate), "rows": rows,
                  "historyStatus": "LOCAL_DURABLE" if path else "PROCESS_CACHE_ONLY"}
        if db:
            if raw is not None:
                raw_hash = hashlib.sha256(raw).hexdigest()
                if len(raw) > 2 * 1024 * 1024 or any(row["sourceResponseSha256"] != raw_hash for row in candidate["rows"]):
                    raise ValueError("margin_raw_receipt_mismatch")
                raw_id = hashlib.sha256((JQUANTS_MARGIN_SOURCE + ':' + raw_hash).encode()).hexdigest()
                db.execute("INSERT OR IGNORE INTO raw_sources VALUES(?,?,?,?,?)", (raw_id, JQUANTS_MARGIN_SOURCE, raw_hash, candidate["observedAt"], raw))
            for row in rows[len(original):]:
                body = _margin_json(row)
                db.execute("INSERT INTO margin_input_history(instrument,body,sha256) VALUES(?,?,?)",
                           (instrument, body, hashlib.sha256(body.encode()).hexdigest()))
            document = {k: v for k, v in result.items() if k != "rows"}
            document["rowCount"] = len(rows)
            envelope = {"document": document, "sha256": hashlib.sha256(_margin_json(document).encode()).hexdigest()}
            db.execute("INSERT OR REPLACE INTO metadata VALUES(?,?)", ("margin_snapshot:" + instrument, _margin_json(envelope)))
            db.commit()
        return result
    finally:
        if db:
            db.close()
