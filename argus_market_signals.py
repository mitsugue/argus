"""ARGUS v13.5.38 — MARKET SIGNALS (owner-facing seven-signal projection).

Pure projection of the seven evidence families (D01-D07) into the owner
vocabulary ``SIG-01`` … ``SIG-07`` with one independent state per signal and a
computed ``x / 7`` count.  This module carries no action authority, no clock,
no environment access, and no provider access: it only re-labels evidence
that the seven-family engine already produced.

Counting rule (``countRule``): a signal counts toward the numerator only when
its family evidence is ``AVAILABLE`` and the condition is met.  A gated,
stale, license-blocked, or missing signal never counts and never silently
becomes a ``CLEAR``; it keeps its own truthful state so the owner can see WHY
the numerator is what it is.
"""
from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

MARKET_SIGNALS_SCHEMA = "argus-market-signals-v1"
MARKET_SIGNALS_LABEL = "MARKET SIGNALS"

# Owner-facing identities, in display order.  ``family`` is the internal
# evidence family the signal is projected from (compatibility adapter; the
# frozen evidence engine keeps its legacy family keys).
SIGNAL_DEFINITIONS = (
    {"id": "SIG-01", "family": "D01", "nameEn": "Margin / Credit Balance",
     "nameJa": "信用残", "sourceRole": "JPX two-market credit ledger"},
    {"id": "SIG-02", "family": "D02", "nameEn": "1570 / Supply-Demand",
     "nameJa": "1570制度信用倍率", "sourceRole": "J-Quants margin (1570, standardized)"},
    {"id": "SIG-03", "family": "D03", "nameEn": "Relative Strength",
     "nameJa": "相対力", "sourceRole": "verified ETF proxy bars (1321 vs SPY)"},
    {"id": "SIG-04", "family": "D04", "nameEn": "Japan Earnings / Valuation",
     "nameJa": "EPS基準・バリュエーション",
     "sourceRole": "ARGUS-derived from licensed J-Quants inputs (no Nikkei non-display PER)"},
    {"id": "SIG-05", "family": "D05", "nameEn": "Foreign Investor Flow",
     "nameJa": "海外フロー", "sourceRole": "published JPX investor-type flow (market ledger)"},
    {"id": "SIG-06", "family": "D06", "nameEn": "VIX / MACD",
     "nameJa": "VIX・MACD", "sourceRole": "VIX OHLCV (Yahoo, FRED fallback) + MACD 12/26/9"},
    {"id": "SIG-07", "family": "D07", "nameEn": "Earnings Reaction",
     "nameJa": "決算反応", "sourceRole": "J-Quants statements / TDnet + verified bars"},
)
SIGNAL_IDS = tuple(row["id"] for row in SIGNAL_DEFINITIONS)
SIGNAL_TOTAL = len(SIGNAL_DEFINITIONS)

SIGNAL_STATES = ("ACTIVE", "CLEAR", "DATA_GATED", "STALE",
                 "LICENSE_BLOCKED", "NOT_APPLICABLE", "UNAVAILABLE")
COUNT_RULE = ("ACTIVE = family status AVAILABLE and conditionMet true; "
              "DATA_GATED, STALE, LICENSE_BLOCKED, NOT_APPLICABLE and UNAVAILABLE "
              "never count")
_ABSENT = "UNAVAILABLE"


def signal_state(row: Optional[Mapping[str, Any]]) -> str:
    """Map one family evidence row to exactly one independent signal state."""
    if not isinstance(row, Mapping):
        return _ABSENT
    status = row.get("status")
    condition = row.get("conditionMet")
    if status == "AVAILABLE":
        if row.get("ruleStatus") == "RULE_NOT_DEFINED":
            return "DATA_GATED"
        if condition is True:
            return "ACTIVE"
        if condition is False:
            return "CLEAR"
        return "DATA_GATED"
    if status == "STALE":
        return "STALE"
    if status == "LICENSE_BLOCKED":
        return "LICENSE_BLOCKED"
    if status == "NOT_APPLICABLE":
        # v13.5.44: the feed was read and holds no applicable event (e.g. no
        # supported earnings disclosure in the window) — distinct from an
        # absent provider.
        return "NOT_APPLICABLE"
    if status in ("PARTIAL", "UNVALIDATED", "DATA_GATED"):
        return "DATA_GATED"
    return _ABSENT


def _gate_note_ja(row: Any, state: str) -> Optional[str]:
    if isinstance(row, Mapping) and row.get("ruleStatus") == "RULE_NOT_DEFINED":
        return "最新PERの警戒基準は未定義。旧方式の19倍判定は使いません。"
    if state != "DATA_GATED" or not isinstance(row, Mapping):
        return None
    # The families reach this projection reduced to status/conditionMet, so
    # the distinction rests on status alone: AVAILABLE means the evidence was
    # read and evaluated and only the activation rule is missing (D04's
    # original defines a ladder, not a multiple); anything else is data.
    if row.get("status") == "AVAILABLE" and row.get("conditionMet") is None:
        return "評価値あり・点灯規則が原典に未定義（参考水準のみ）"
    return "判定に必要なデータが未取得または不完全"


def project_market_signals(
        families: Optional[Mapping[str, Mapping[str, Any]]]) -> Dict[str, Any]:
    """Project family evidence into the owner-facing seven-signal surface."""
    rows = families if isinstance(families, Mapping) else {}
    signals = []
    counts = {state: 0 for state in SIGNAL_STATES}
    for definition in SIGNAL_DEFINITIONS:
        row = rows.get(definition["family"])
        state = signal_state(row)
        counts[state] += 1
        signals.append({
            "id": definition["id"],
            "family": definition["family"],
            "nameEn": definition["nameEn"],
            "nameJa": definition["nameJa"],
            "sourceRole": definition["sourceRole"],
            "state": state,
            "status": row.get("status") if isinstance(row, Mapping) else None,
            "conditionMet": (row.get("conditionMet")
                             if isinstance(row, Mapping) else None),
            "validationStatus": (row.get("validationStatus")
                                 if isinstance(row, Mapping) else None),
            # DATA_GATED covers two different situations; the note tells the
            # owner which one this is, without changing the counting rule.
            "gateNoteJa": _gate_note_ja(row, state),
            **{key: row.get(key) if isinstance(row, Mapping) else None
               for key in ("ruleStatus", "valuationBasis", "conditionRuleJa")},
            # 2026-10-04: the value, its week and when it was published, as a
            # situation summary (never a probability or a trading signal).
            "factNoteJa": (row.get("factNoteJa") if isinstance(row, Mapping)
                           and isinstance(row.get("factNoteJa"), str) else None),
        })
    active = counts["ACTIVE"]
    return {
        "schemaVersion": MARKET_SIGNALS_SCHEMA,
        "label": MARKET_SIGNALS_LABEL,
        "total": SIGNAL_TOTAL,
        "activeCount": active,
        "countLabel": f"{active} / {SIGNAL_TOTAL}",
        "countRule": COUNT_RULE,
        "stateCounts": counts,
        "signals": signals,
        "actionAuthority": False,
    }


__all__ = [
    "COUNT_RULE",
    "MARKET_SIGNALS_LABEL",
    "MARKET_SIGNALS_SCHEMA",
    "SIGNAL_DEFINITIONS",
    "SIGNAL_IDS",
    "SIGNAL_STATES",
    "SIGNAL_TOTAL",
    "project_market_signals",
    "signal_state",
]
