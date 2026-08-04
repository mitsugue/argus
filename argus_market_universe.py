"""Private registered-symbol universe and public market-truth helpers.

The private universe may contain owner symbols, but this module deliberately
keeps the public telemetry aggregate-only.  It has no network or persistence
side effects so the bridge and backend can share one normalization contract.
"""
from __future__ import annotations

import datetime as dt
import math
import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


SCHEMA_VERSION = "argus-private-symbol-universe-v1"
PUBLIC_SCHEMA_VERSION = "argus-market-transport-v1"
MARKETS = ("JP", "US")

# Market/macro instruments ARGUS itself needs.  PUSH_SYMBOLS remains a bridge-
# local emergency baseline and is merged with these codes, never replaced.
MANDATORY_CODES = (
    "JP.1306", "JP.1321",
    "US.SPY", "US.QQQ", "US.IWM", "US.XLK", "US.XLU", "US.GLD",
    "US.TLT", "US.HYG",
)

_JP = re.compile(r"^[0-9]{4}$|^[0-9]{3}[A-Z]$")
_US = re.compile(r"^[A-Z]{1,5}(?:[.\-][A-Z]{1,2})?$")


def normalize_code(value: Any, market: Optional[str] = None) -> Optional[str]:
    """Return a canonical moomoo code, or ``None`` for unknown input."""
    raw = str(value or "").strip().upper()
    mkt = str(market or "").strip().upper()
    if "." in raw and not mkt:
        mkt, raw = raw.split(".", 1)
    if mkt == "JP" and _JP.fullmatch(raw):
        return f"JP.{raw}"
    if mkt == "US" and _US.fullmatch(raw):
        return f"US.{raw}"
    return None


def member_codes(members: Iterable[Mapping[str, Any]]) -> List[str]:
    out: List[str] = []
    for member in members or ():
        if not isinstance(member, Mapping) or member.get("enabled") is False:
            continue
        code = normalize_code(member.get("symbol"), member.get("market"))
        if code:
            out.append(code)
    return list(dict.fromkeys(out))


def bounded_universe(
    baseline: Iterable[Any], owner_codes: Iterable[Any], *,
    jp_cap: int = 200, us_cap: int = 200,
) -> Tuple[Dict[str, List[str]], Dict[str, Any]]:
    """Merge baseline + private membership, dedupe, split, and cap per market."""
    caps = {"JP": max(1, int(jp_cap)), "US": max(1, int(us_cap))}
    merged = list(baseline or ()) + list(MANDATORY_CODES) + list(owner_codes or ())
    by_market: Dict[str, List[str]] = {"JP": [], "US": []}
    rejected = 0
    for raw in merged:
        code = normalize_code(raw)
        if not code:
            rejected += 1
            continue
        market = code.split(".", 1)[0]
        if code not in by_market[market]:
            by_market[market].append(code)
    before = {m: len(by_market[m]) for m in MARKETS}
    for market in MARKETS:
        by_market[market] = by_market[market][:caps[market]]
    meta = {
        "configuredCount": {m: len(by_market[m]) for m in MARKETS},
        "truncatedCount": {m: max(0, before[m] - len(by_market[m])) for m in MARKETS},
        "rejectedCount": rejected,
        "caps": caps,
    }
    return by_market, meta


def choose_verified_universe(
    payload: Any, *, baseline: Sequence[str], last_verified: Optional[Sequence[str]],
    jp_cap: int = 200, us_cap: int = 200,
) -> Tuple[List[str], str]:
    """Accept only an explicitly verified response; otherwise preserve last-good."""
    preserved = list(last_verified or baseline)
    if not isinstance(payload, Mapping) or payload.get("verified") is not True:
        return preserved, "preserved_last_verified"
    markets = payload.get("markets")
    if not isinstance(markets, Mapping):
        return preserved, "preserved_last_verified"
    remote: List[Any] = []
    for market in MARKETS:
        section = markets.get(market.lower()) or markets.get(market)
        if not isinstance(section, Mapping) or not isinstance(section.get("codes"), list):
            return preserved, "preserved_last_verified"
        remote.extend(section["codes"])
    built, _ = bounded_universe(baseline, remote, jp_cap=jp_cap, us_cap=us_cap)
    codes = built["JP"] + built["US"]
    if not codes:
        return preserved, "preserved_last_verified"
    return codes, "verified"


def _parse_utc(value: Any) -> Optional[dt.datetime]:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(dt.timezone.utc)
    except (TypeError, ValueError):
        return None


def _percentile(values: Sequence[float], fraction: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, math.ceil(fraction * len(ordered)) - 1))
    return round(float(ordered[idx]), 1)


def market_telemetry(
    market: str, configured_codes: Sequence[str], rows: Sequence[Mapping[str, Any]], *,
    now: Optional[dt.datetime] = None, availability: Optional[str] = None,
    stale_after_sec: int = 300,
) -> Dict[str, Any]:
    """Aggregate quote coverage/freshness without exposing symbol membership."""
    market = str(market).upper()
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
    configured = [c for c in configured_codes if str(c).upper().startswith(market + ".")]
    selected = [r for r in rows or () if str(r.get("market") or "").upper() == market]
    ages: List[float] = []
    latest: Optional[dt.datetime] = None
    missing_ts = 0
    for row in selected:
        stamp = _parse_utc(row.get("exchangeTs"))
        if stamp is None:
            missing_ts += 1
            continue
        latest = stamp if latest is None or stamp > latest else latest
        ages.append(max(0.0, (now - stamp).total_seconds()))
    stale = sum(1 for age in ages if age > stale_after_sec) + missing_ts
    fresh = max(0, len(selected) - stale)
    requested = len(configured)
    returned = len(selected)
    unavailable = max(0, requested - returned)

    explicit = str(availability or "").lower()
    if explicit in ("entitlement_unavailable", "service_unavailable", "disabled"):
        status = explicit
    elif requested == 0:
        status = "unknown"
    elif returned == 0:
        status = "service_unavailable"
    elif fresh == 0:
        status = "stale"
    elif returned < requested:
        status = "partial"
    else:
        status = "live"

    if status in ("entitlement_unavailable", "service_unavailable", "disabled") and market == "JP":
        freshness = "EOD"
    elif fresh:
        freshness = "REALTIME"
    elif returned:
        freshness = "DELAYED"
    else:
        freshness = "UNKNOWN"
    rights = sorted({str(row.get("quoteRight") or row.get("entitlement") or "unknown").lower()
                     for row in selected})
    quote_right = rights[0] if len(rights) == 1 else "mixed" if rights else "unknown"
    return {
        "status": status,
        "provider": "moomoo",
        "fallbackProvider": "J-Quants" if market == "JP" and status != "live" else None,
        "freshness": freshness,
        "quoteRight": quote_right,
        "entitlementStatus": (explicit if explicit else
                              "available" if returned else "unknown"),
        "configuredCount": requested,
        "requestedCount": requested,
        "returnedCount": returned,
        "unavailableCount": unavailable,
        "staleCount": stale,
        "missingTimestampCount": missing_ts,
        "coveragePct": round(returned / requested * 100.0, 1) if requested else 0.0,
        "exchangeAsOf": latest.isoformat().replace("+00:00", "Z") if latest else None,
        "sourceAgeP50Sec": _percentile(ages, 0.50),
        "sourceAgeP95Sec": _percentile(ages, 0.95),
    }


def public_transport(transport_status: str, markets: Mapping[str, Any], *,
                     received_at: Optional[str] = None) -> Dict[str, Any]:
    """Create the aggregate-only public heartbeat contract."""
    safe: Dict[str, Any] = {}
    allowed = {
        "status", "provider", "fallbackProvider", "freshness", "configuredCount",
        "requestedCount", "returnedCount", "unavailableCount", "staleCount",
        "missingTimestampCount", "coveragePct", "exchangeAsOf", "sourceAgeP50Sec",
        "sourceAgeP95Sec",
        "quoteRight", "entitlementStatus",
    }
    for market in ("us", "jp"):
        src = markets.get(market) if isinstance(markets, Mapping) else None
        segment: Dict[str, Any] = {}
        if isinstance(src, Mapping):
            for key in allowed:
                if key not in src:
                    continue
                value = src.get(key)
                if isinstance(value, bool) or value is None:
                    segment[key] = value
                elif isinstance(value, (int, float)):
                    segment[key] = value
                elif isinstance(value, str):
                    segment[key] = value[:60]
        safe[market] = segment
    return {
        "schemaVersion": PUBLIC_SCHEMA_VERSION,
        "transportStatus": str(transport_status or "unknown")[:40],
        "receivedAt": received_at,
        "markets": safe,
    }
