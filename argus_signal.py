"""ARGUS — Action Level signal resolver (pure, backend mirror of
web/src/domain/actionLevel.ts), v10.124.

So APIs and ledgers carry the structured signal {code, level, permissions,
legacyAction, schemaVersion} — consumers and the calibration ledger don't have to
infer permissions from a text label, and new records can be grouped by schema.
Decision-support only — nothing here trades or sizes a position.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

SIGNAL_SCHEMA_VERSION = "action-level-v1"

# code -> (level, permissions). level: 1 EXIT … 7 ENTER (higher = less defensive).
_SIGNALS: Dict[str, Dict[str, Any]] = {
    "EXIT":      {"level": 1, "permissions": {"newEntry": "blocked", "add": "blocked", "existingPosition": "exit"}},
    "DEFEND":    {"level": 2, "permissions": {"newEntry": "blocked", "add": "blocked", "existingPosition": "reduce_risk"}},
    "REVIEW":    {"level": 3, "permissions": {"newEntry": "blocked", "add": "blocked", "existingPosition": "reassess"}},
    "PAUSE":     {"level": 4, "permissions": {"newEntry": "blocked", "add": "blocked", "existingPosition": "monitor"}},
    "HOLD_ONLY": {"level": 5, "permissions": {"newEntry": "blocked", "add": "blocked", "existingPosition": "maintain"}},
    "PREPARE":   {"level": 6, "permissions": {"newEntry": "blocked", "add": "blocked", "existingPosition": "maintain"}},
    "ENTER":     {"level": 7, "permissions": {"newEntry": "allowed", "add": "allowed", "existingPosition": "maintain"}},
}

_LEGACY = {
    "EXIT": "EXIT", "TRIM": "DEFEND", "WAIT": "PAUSE", "HOLD": "HOLD_ONLY",
    "WAIT_FOR_PULLBACK": "PREPARE", "ADD": "ENTER",
    "CONTINUE": "HOLD_ONLY", "GRADUAL_ADD": "ENTER", "DEFER_LUMP_SUM": "PAUSE", "NO_SELL_ACTION": "HOLD_ONLY",
}
_OVERRIDE = {
    "REVIEW_REQUIRED": "REVIEW", "DO_NOT_ADD": "REVIEW", "TRIM_WATCH": "DEFEND",
    "EXIT_WATCH": "DEFEND", "HOLD_CAUTION": "HOLD_ONLY", "WAIT": "PAUSE",
}
_BAD_DQ = {"STALE", "MOCK", "UNKNOWN", "UNAVAILABLE"}


def _more_defensive(a: str, b: str) -> str:
    return a if _SIGNALS[a]["level"] <= _SIGNALS[b]["level"] else b


def resolve_signal(legacy_action: str, *, downside_override: Optional[str] = None,
                   data_quality: str = "LIVE", material_downside: bool = False,
                   gates_pass: bool = False, exit_confirmed: bool = False) -> Dict[str, Any]:
    """Mirror of the frontend resolver — same mapping, override, and data-quality
    gates. Returns the structured signal object for APIs/ledgers."""
    dq = (data_quality or "LIVE").upper()
    reason = "legacy map"

    if legacy_action == "BUY_DIP":
        ok = gates_pass and not downside_override and dq not in _BAD_DQ
        code = "ENTER" if ok else "PREPARE"
        reason = "BUY_DIP gates passed" if ok else "BUY_DIP gates not met"
    else:
        code = _LEGACY.get(legacy_action, "PAUSE")

    if downside_override:
        ov = _OVERRIDE.get(downside_override, "REVIEW")
        if downside_override == "EXIT_WATCH" and exit_confirmed:
            ov = "EXIT"
        code = _more_defensive(code, ov)
        reason = f"override {downside_override}"

    if code == "ENTER" and dq in ("STALE", "MOCK"):
        code = "PREPARE"
        reason = f"{dq} cannot ENTER"
    if material_downside and dq in ("PARTIAL", "DELAYED", "UNKNOWN", "UNAVAILABLE", "STALE"):
        code = _more_defensive(code, "REVIEW")
        reason = f"material downside + {dq}"

    sig = _SIGNALS[code]
    return {
        "code": code, "level": sig["level"], "permissions": dict(sig["permissions"]),
        "legacyAction": legacy_action, "schemaVersion": SIGNAL_SCHEMA_VERSION,
        "dataQuality": dq, "mappingReason": reason,
    }
