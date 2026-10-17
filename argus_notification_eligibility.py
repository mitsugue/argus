"""Fail-closed owner-universe eligibility for outbound Push notifications.

This module is deliberately pure.  The caller resolves the existing private
Layer-2B membership contract and passes only the one symbol's non-monetary
flags.  No owner symbols, quantities, costs, or P/L are logged or returned by
the public diagnostics layer.
"""
from __future__ import annotations

from typing import Any, Dict, Mapping, Optional


INDIVIDUAL_SECURITY = "individual_security"
NON_SECURITY_SCOPES = frozenset({"macro", "system", "portfolio", "digest"})
HOLDING_STATES = frozenset({"held", "protected"})
MARKED_STATES = frozenset({"watch", "active"})


def normalize_symbol(symbol: Any) -> str:
    """Return the private-membership key without guessing aliases."""
    return str(symbol or "").strip().upper()


def evaluate_push_eligibility(
    *,
    scope: str,
    symbol: Any = None,
    owner_membership: Optional[Mapping[str, Mapping[str, Any]]] = None,
    membership_status: str = "fresh",
) -> Dict[str, Any]:
    """Return one central, fail-closed Push decision.

    ``owner_membership`` is the caller's private in-memory map.  The decision
    intentionally omits the symbol and all membership contents so it is safe to
    aggregate into count-only public diagnostics.
    """
    if scope in NON_SECURITY_SCOPES:
        return {
            "pushEligible": True,
            "reason": "non_security_notification",
            "ownerRelationship": "none",
        }

    if scope != INDIVIDUAL_SECURITY:
        return {
            "pushEligible": False,
            "reason": "notification_scope_unknown",
            "ownerRelationship": "none",
        }

    sym = normalize_symbol(symbol)
    if not sym:
        return {
            "pushEligible": False,
            "reason": "individual_symbol_missing",
            "ownerRelationship": "none",
        }
    if membership_status != "fresh" or owner_membership is None:
        return {
            "pushEligible": False,
            "reason": ("owner_membership_stale" if membership_status == "stale"
                       else "owner_membership_unavailable"),
            "ownerRelationship": "none",
        }

    flags = owner_membership.get(sym)
    if not isinstance(flags, Mapping):
        return {
            "pushEligible": False,
            "reason": "symbol_not_in_owner_universe",
            "ownerRelationship": "none",
        }

    owner_state = str(flags.get("ownerState") or "").lower()
    holding = owner_state in HOLDING_STATES
    marked = owner_state in MARKED_STATES or flags.get("explicitlyMarked") is True
    if holding and marked:
        relationship = "holding_and_marked"
    elif holding:
        relationship = "holding"
    elif marked:
        relationship = "marked"
    else:
        return {
            "pushEligible": False,
            "reason": "owner_membership_state_ineligible",
            "ownerRelationship": "none",
        }
    return {
        "pushEligible": True,
        "reason": "symbol_in_owner_universe",
        "ownerRelationship": relationship,
    }
