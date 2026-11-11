"""OpenAI Flex processing for the automatic lanes (owner cost decision 2026-11-11).

The owner chose 【AIを割引の窓口で】: the same model through the Flex service
tier, priced at Batch rates (half of Standard on the official price page,
checked 2026-11-11), in exchange for slower answers and occasional
"resource unavailable" refusals. A refusal (HTTP 429 that is not a quota or
spend limit) is not charged, so that one request is sent again on the
Standard tier. A model or tool that does not accept Flex (HTTP 400 naming
service_tier) is remembered until restart and goes Standard from then on.
A timeout is never repeated: the request may have been accepted and billed.

Only automatic, unattended lanes use Flex. The owner's button press
(owner_dialogue) stays Standard so the owner is not kept waiting.
"""
import threading

FLEX_PURPOSES = frozenset({"market_brief", "news_intel", "ai_judgment",
                           "event_analysis", "market_position_check"})
# Flex answers are slower. The brief holds the shared heavy-task lane while it
# waits, so the wait is bounded; its update times (08:00, 12:00, 15:45) are
# outside the continuous trading sessions.
FLEX_TIMEOUT_SECONDS = 300
FLEX_PRICE_FACTOR = 0.5
_QUOTA_CODES = frozenset({"insufficient_quota", "credit_balance_exhausted",
                          "organization_spend_limit_exceeded", "project_spend_limit_exceeded",
                          "organization_usage_limit_exceeded"})
# The account's own request rate: another tier cannot restore it.
_RATE_CODES = frozenset({"rate_limit_exceeded", "slow_down"})


def _error_code(exc):
    body = getattr(exc, "body", None)
    detail = body.get("error", body) if isinstance(body, dict) else None
    if not isinstance(detail, dict):
        return None, None
    code = detail.get("code")
    text = " ".join(str(detail.get(key) or "") for key in ("message", "param"))
    return (code if isinstance(code, str) else None), text


def flex_refusal(exc):
    """Why a Flex request may be sent again on Standard, or None to re-raise."""
    status = getattr(exc, "status_code", None)
    code, text = _error_code(exc)
    if status == 429 and code not in _QUOTA_CODES and code not in _RATE_CODES:
        # Only the Flex capacity refusal is sent again; an unexplained 429 is
        # treated like any uncertain failure and is never resubmitted.
        words = f"{code or ''} {text or ''}".lower()
        if any(word in words for word in ("resource_unavailable", "resource unavailable",
                                          "capacity", "flex")):
            return "resource_unavailable"
        return None
    if status == 400:
        # A rejected request is not charged. Any 400 on Flex (the tier itself,
        # or a parameter such as a tool or cache option the tier does not
        # take) goes Standard once; a 400 there is raised as before.
        return "flex_not_supported"
    return None


class TierState:
    """Per-process counts of requested and served tiers; reset by a restart."""

    def __init__(self, enabled=True):
        self.enabled = bool(enabled)
        self._lock = threading.Lock()
        self._unsupported = set()
        self._counts = {}

    def wants_flex(self, purpose, model, tool_kind=None):
        with self._lock:
            return (self.enabled and purpose in FLEX_PURPOSES
                    and (model, tool_kind) not in self._unsupported)

    def _row(self, purpose):
        return self._counts.setdefault(purpose, {"flexRequested": 0, "flexServed": 0,
            "flexAnsweredOtherTier": 0, "standardAfterRefusal": 0, "refusals": {}})

    def served(self, purpose, tier):
        with self._lock:
            row = self._row(purpose)
            row["flexRequested"] += 1
            row["flexServed" if tier == "flex" else "flexAnsweredOtherTier"] += 1

    def refused(self, purpose, model, tool_kind, reason):
        with self._lock:
            row = self._row(purpose)
            row["flexRequested"] += 1
            row["standardAfterRefusal"] += 1
            row["refusals"][reason] = row["refusals"].get(reason, 0) + 1
            if reason == "flex_not_supported":
                self._unsupported.add((model, tool_kind))

    def view(self):
        with self._lock:
            return {"enabled": self.enabled, "purposes": sorted(FLEX_PURPOSES),
                    "timeoutSeconds": FLEX_TIMEOUT_SECONDS,
                    "unsupported": sorted(f"{m}|{t or 'text'}" for m, t in self._unsupported),
                    "counts": {k: {**v, "refusals": dict(v["refusals"])} for k, v in self._counts.items()}}


def create(state, *, purpose, model, kwargs, call, tool_kind=None):
    """Send one request, Flex first for automatic lanes.

    `call(kwargs, tier)` performs exactly one provider request and returns the
    response. At most one Standard request follows, and only after a refusal
    the provider does not charge for.
    """
    if state.wants_flex(purpose, model, tool_kind):
        flex = {**kwargs, "service_tier": "flex",
                "timeout": max(float(kwargs.get("timeout") or 0), FLEX_TIMEOUT_SECONDS)}
        try:
            response = call(flex, "flex")
        except Exception as exc:
            reason = flex_refusal(exc)
            if reason is None:
                raise
            state.refused(purpose, model, tool_kind, reason)
        else:
            state.served(purpose, getattr(response, "service_tier", None))
            return response
    return call(dict(kwargs), "standard")


def served_cost(cost, response):
    """The estimate at the tier the provider reports it served."""
    if cost is None or getattr(response, "service_tier", None) != "flex":
        return cost
    return round(cost * FLEX_PRICE_FACTOR, 6)
