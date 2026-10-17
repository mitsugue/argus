"""ARGUS — LAYER 1 licensed real-time feed adapters (DISABLED by default, v1).

Clean provider-agnostic interface (§3) so a contracted feed (Bloomberg Event-Driven,
LSEG MRN, Factiva AI, RavenPack) can later be wired into Event Intelligence WITHOUT
redesign. Every adapter is disabled until a signed contract + credentials + a
successful runtime fetch flip it on. No adapter here fabricates data, pricing, or
liveness. Stdlib-only; no network calls performed at this phase.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


class LicensedNewsProvider:
    """Interface every licensed feed adapter implements. Default state = NOT
    configured: connect()/stream()/fetch_since() raise until credentials + a
    contract flag are supplied. Display/AI/retention rights come from usage_policy()."""

    provider_id = "abstract"
    vendor_name = "abstract"

    def __init__(self, credentials: Optional[Dict[str, str]] = None, contract_signed: bool = False):
        self.credentials = credentials or {}
        self.contract_signed = bool(contract_signed)

    # — lifecycle —
    def _require_enabled(self) -> None:
        if not (self.contract_signed and self.credentials):
            raise RuntimeError(f"{self.vendor_name} not configured (needs signed contract + credentials)")

    def connect(self) -> bool:
        self._require_enabled()
        raise NotImplementedError

    def health(self) -> Dict[str, Any]:
        return {"provider": self.provider_id, "vendor": self.vendor_name,
                "configured": bool(self.contract_signed and self.credentials),
                "status": "NOT_CONFIGURED" if not self.contract_signed else "CONFIGURED",
                "live": False}

    def stream(self):
        self._require_enabled()
        raise NotImplementedError

    def fetch_since(self, cursor: Optional[str]) -> List[Dict[str, Any]]:
        self._require_enabled()
        raise NotImplementedError

    def normalize_item(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """Map a vendor item onto the IntelligenceItem shape, preserving provider
        metadata, timestamps, tags, relevance, importance and licensing class."""
        raise NotImplementedError

    def capabilities(self) -> Dict[str, Any]:
        """What the feed CAN deliver (claimed by vendor; unverified until live)."""
        return {k: None for k in (
            "headlines", "full_text", "institutional_research", "analyst_actions",
            "machine_readable_tags", "sentiment", "relevance", "importance",
            "historical_search", "AI_processing_allowed", "display_allowed",
            "retention_allowed", "latency", "coverage", "entitlement")}

    def usage_policy(self) -> Dict[str, Any]:
        """Contractual rights — drives the Source Rights access class once live."""
        return {"accessClass": "UNAVAILABLE", "ai_processing_allowed": False,
                "display_allowed": False, "retention_allowed": False,
                "redistribution": "prohibited", "notes": "until contract confirms otherwise"}


class _DisabledFeed(LicensedNewsProvider):
    def capabilities(self):
        c = super().capabilities()
        c.update({"institutional_research": "vendor_claimed", "analyst_actions": "vendor_claimed"})
        return c


class BloombergEventDrivenFeed(_DisabledFeed):
    provider_id, vendor_name = "bloomberg_feed", "Bloomberg Event-Driven Feeds"


class LSEGMachineReadableNews(_DisabledFeed):
    provider_id, vendor_name = "lseg_mrn", "LSEG Machine Readable News"


class FactivaAINewsFeed(_DisabledFeed):
    provider_id, vendor_name = "factiva_ai", "Dow Jones Factiva AI News Feed"


class RavenPackAnalytics(_DisabledFeed):
    provider_id, vendor_name = "ravenpack", "RavenPack News Analytics"


REGISTRY = {p.provider_id: p for p in (BloombergEventDrivenFeed, LSEGMachineReadableNews,
                                       FactivaAINewsFeed, RavenPackAnalytics)}


def all_health() -> List[Dict[str, Any]]:
    """Health of every licensed adapter — all NOT_CONFIGURED until contracted."""
    return [cls().health() for cls in REGISTRY.values()]
