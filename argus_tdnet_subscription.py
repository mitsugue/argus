"""ARGUS v13.7 — the declared subscription state of the official J-Quants TDnet Add-on.

2026-09-29: the owner cancelled the TDnet/Company Disclosure Add-on (the most expensive
line on the J-Quants bill). Disclosures keep arriving through the free yanoshin mirror,
which scanner.py already prefers-then-falls-back to, so nothing goes dark. What changes
is the STATUS the system reports about itself, and that is what this module fixes.

Without a declaration, a cancelled add-on is indistinguishable from a broken one: the
probe returns HTTP 403, the honest reading of a 403 is "entitlement_missing", and the
source registry then tells the owner to go to the J-Quants dashboard and check for the
[ご利用中] badge — forever, about a purchase they deliberately ended. A console that
cries about an intended state teaches its owner to stop reading it, which is worse than
the feed it lost. So the owner DECLARES the state, and the system reports it as declared.

Two hard limits on this module:

  * It never manufactures officialness. Declaring the add-on off means there is no
    official confirmation, so `has_official` stays False, `corroboration_level` can
    never reach official/official_and_market_confirmed, `resolve_trigger_role` can never
    return confirmed_cause, and `cache:tdnet:not_official` stays in missingConfirmations.
    Cancelling a feed lowers what may be claimed; it must never raise it.
  * It is not a suppressor. "off" is louder than a green tick, not quieter: the registry
    says the capability is intentionally unsubscribed and names the lower-tier substitute.

Stdlib only, no network, no scanner import — the glue lives in scanner.py.
"""
import os
from typing import Any, Dict, Mapping, Optional

SCHEMA_VERSION = "argus-tdnet-subscription-v1"

#: The environment variable the owner sets. Absent ⇒ AUTO (probe as before).
ENV_VAR = "ARGUS_TDNET_ADDON"

MODE_AUTO = "auto"
MODE_OFF = "off"

# Spelled generously in both directions: the owner sets this by hand in the Render
# dashboard, months apart, and a typo must not silently probe a cancelled add-on.
_OFF_WORDS = {"off", "0", "false", "no", "none", "cancelled", "canceled",
              "unsubscribed", "not_subscribed"}
_AUTO_WORDS = {"", "auto", "on", "1", "true", "yes", "probe", "subscribed"}

#: Registry/probe status for a declared cancellation. Deliberately NOT one of the
#: failure words (entitlement_missing / unavailable / endpoint_not_found): this is a
#: decision, and a status vocabulary that cannot say "by decision" will say "broken".
STATUS_NOT_SUBSCRIBED = "not_subscribed"
ENTITLEMENT_NOT_SUBSCRIBED = "not_subscribed"

NOTE_JA = (
    "公式TDnet Add-onはオーナー判断で解約済み（意図的・障害ではありません）。"
    "適時開示は無料のyanoshinミラー（official=false／下位ティア）で継続取得します。"
    "公式確認は付かないため、確定原因(confirmed_cause)には昇格しません。"
)
REGISTRY_ENTITLEMENT_JA = "解約済み(意図的)"


def mode(env: Optional[Mapping[str, str]] = None) -> str:
    """MODE_OFF only when the owner said so; anything unrecognised stays MODE_AUTO.

    Unrecognised values fall back to AUTO on purpose: the failure mode of guessing
    "off" from a stray value is a paid feed silently ignored, which is worse than an
    extra probe.
    """
    raw = (env if env is not None else os.environ).get(ENV_VAR)
    token = str(raw or "").strip().lower()
    if token in _OFF_WORDS:
        return MODE_OFF
    if token in _AUTO_WORDS:
        return MODE_AUTO
    return MODE_AUTO


def is_declared_off(env: Optional[Mapping[str, str]] = None) -> bool:
    return mode(env) == MODE_OFF


def snapshot_fields() -> Dict[str, Any]:
    """The build_snapshot kwargs for a declared cancellation.

    `official=True` is provider identity (this row describes the official provider),
    exactly as the not_configured row already uses it. Usability is decided by the
    caller and is always False here, so get_tdnet_recent falls through to the
    fallback whose own `official` flag is False.
    """
    return {"status": STATUS_NOT_SUBSCRIBED, "official": True,
            "provider": "jquants-tdnet", "entitlement": ENTITLEMENT_NOT_SUBSCRIBED,
            "note_ja": NOTE_JA}


def registry_row() -> Dict[str, str]:
    """(status, entitlement, note) for the public source registry."""
    return {"status": STATUS_NOT_SUBSCRIBED,
            "entitlement": REGISTRY_ENTITLEMENT_JA,
            "noteJa": NOTE_JA}


def is_failure_status(status: Optional[str]) -> bool:
    """False for a declared cancellation, True for every real fault.

    The Data Quality console and the registry use this to grade: a declared
    cancellation is not a fault to escalate, an unreachable endpoint is.
    """
    return bool(status) and status != STATUS_NOT_SUBSCRIBED and status not in (
        "official_tdnet_live", "live")
