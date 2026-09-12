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
