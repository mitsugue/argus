"""Market shock materiality engine — v13.5.1 Major News correction.

Detects materially market-moving conditions from authoritative evidence and
classifies severity with an explicit, testable policy. Two evidence families:

* Direct market sensing — long-end US Treasury yields (DGS30) evaluated on
  LEVEL, VELOCITY, EXTREME/PERCENTILE against real observation history.
* News corroboration — themed headline hits (already freshness-truthed by the
  news radar) evaluated on outlet breadth, phrase criticality, and age.

Cross-market context (VIX / USDJPY moves) can raise confidence by at most one
notch per explicit policy. Conflicting or single-outlet information stays
conservative (UNCONFIRMED). Stale evidence never becomes a current alert.

Pure module: no network, no clock (caller supplies now); deterministic and
fully covered by fixture tests. This module NEVER changes SDA semantics — it
produces risk-context information for Today / Alerts surfaces only.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence

import argus_news_intelligence as _news_direction

MARKET_SHOCK_SCHEMA = "argus-market-shock-v1"

# Severity ladder (ordered). Policy constants are explicit so tests and the
# owner can read exactly why a severity was assigned.
SEVERITIES = ("LOW", "MEDIUM", "HIGH", "CRITICAL")

LONG_END_LEVEL_ALERT = 5.0          # % — psychologically/structurally material
LONG_END_VELOCITY_MEDIUM_BP = 20.0  # 5-business-day move
LONG_END_VELOCITY_HIGH_BP = 30.0
LONG_END_PERCENTILE_MEDIUM = 97.0   # trailing-window percentile of level
LONG_END_PERCENTILE_HIGH = 99.0
LONG_END_WINDOW = 252               # trailing observations for percentile/high
LONG_END_STALE_DAYS = 5             # newest observation older than this → gated

NEWS_FRESH_SECONDS = 6 * 3600
NEWS_OUTLETS_MEDIUM = 2             # distinct outlets required to confirm
NEWS_OUTLETS_HIGH = 4

CRITICAL_PHRASES = (
    "strait of hormuz", "hormuz", "oil embargo", "nuclear",
    "declares war", "attack on tanker", "tanker attack",
)
EASING_PHRASES = ("ceasefire", "cease-fire", "truce", "de-escalation")


def _parse_epoch(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)) and value > 0:
        return float(value)
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(
                value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
    return None


def _clean_observations(observations: Sequence[Mapping[str, Any]]) -> List[Dict[str, float]]:
    rows: List[Dict[str, Any]] = []
    for row in observations or ():
        value = row.get("value")
        date = row.get("date")
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if not isinstance(date, str) or not date:
            continue
        rows.append({"date": date, "value": number})
    rows.sort(key=lambda row: row["date"])
    return rows


def evaluate_long_end_rates(observations: Sequence[Mapping[str, Any]],
                            *, now: datetime) -> Dict[str, Any]:
    """LEVEL / VELOCITY / EXTREME evaluation of the US 30Y yield series."""
    rows = _clean_observations(observations)
    if len(rows) < 30:
        return {"status": "DATA_GATED", "reason": "insufficient_observations",
                "observationCount": len(rows)}
    latest = rows[-1]
    latest_date = datetime.strptime(latest["date"], "%Y-%m-%d").replace(
        tzinfo=timezone.utc)
    age_days = (now - latest_date).days
    if age_days > LONG_END_STALE_DAYS:
        return {"status": "DATA_GATED", "reason": "series_stale",
                "latestDate": latest["date"], "ageDays": age_days}
    window = rows[-LONG_END_WINDOW:]
    values = [row["value"] for row in window]
    level = latest["value"]
    change_1d_bp = (level - rows[-2]["value"]) * 100 if len(rows) >= 2 else 0.0
    base_5d = rows[-6]["value"] if len(rows) >= 6 else rows[0]["value"]
    change_5d_bp = (level - base_5d) * 100
    below = sum(1 for value in values if value <= level)
    percentile = below / len(values) * 100
    window_high = max(values)
    is_window_high = level >= window_high

    severity: Optional[str] = None
    reasons: List[str] = []
    if level >= LONG_END_LEVEL_ALERT and (is_window_high
                                          or change_5d_bp >= 25.0):
        severity = "CRITICAL"
        reasons.append("level_above_5pct_at_extreme")
    elif level >= LONG_END_LEVEL_ALERT:
        severity = "HIGH"
        reasons.append("level_above_5pct")
    elif change_5d_bp >= LONG_END_VELOCITY_HIGH_BP:
        severity = "HIGH"
        reasons.append("velocity_5d_extreme")
    elif percentile >= LONG_END_PERCENTILE_HIGH and change_5d_bp >= 15.0:
        severity = "HIGH"
        reasons.append("percentile_extreme_with_velocity")
    elif change_5d_bp >= LONG_END_VELOCITY_MEDIUM_BP:
        severity = "MEDIUM"
        reasons.append("velocity_5d_elevated")
    elif percentile >= LONG_END_PERCENTILE_MEDIUM:
        severity = "MEDIUM"
        reasons.append("percentile_elevated")

    return {
        "status": "EVALUATED",
        "severity": severity,
        "reasons": reasons,
        "level": round(level, 3),
        "change1dBp": round(change_1d_bp, 1),
        "change5dBp": round(change_5d_bp, 1),
        "percentile": round(percentile, 1),
        "isWindowHigh": is_window_high,
        "windowDays": len(window),
        "latestDate": latest["date"],
    }


def evaluate_news_theme(hits: Sequence[Mapping[str, Any]], *,
                        theme_key: str, now_epoch: float) -> Dict[str, Any]:
    """Outlet-breadth + criticality + freshness evaluation of one news theme."""
    fresh: List[Dict[str, Any]] = []
    for hit in hits or ():
        epoch = _parse_epoch(hit.get("sourceEpoch") or hit.get("seen")
                             or hit.get("sourceTimestamp"))
        if epoch is None or now_epoch - epoch > NEWS_FRESH_SECONDS:
            continue
        title = str(hit.get("title") or "")
        domain = str(hit.get("domain") or "")
        if not title or not domain:
            continue
        fresh.append({"title": title, "domain": domain, "epoch": epoch})
    outlets = {hit["domain"] for hit in fresh}
    critical_titles = [hit["title"] for hit in fresh
                       if any(phrase in hit["title"].lower()
                              for phrase in CRITICAL_PHRASES)]
    easing_titles = [hit["title"] for hit in fresh
                     if any(phrase in hit["title"].lower()
                            for phrase in EASING_PHRASES)]
    conflicting = bool(critical_titles) and bool(easing_titles)

    severity: Optional[str] = None
    reasons: List[str] = []
    if not fresh:
        return {"status": "EVALUATED", "severity": None, "reasons": ["no_fresh_hits"],
                "themeKey": theme_key, "outletCount": 0, "headlineCount": 0,
                "conflicting": False, "sample": []}
    if len(outlets) < NEWS_OUTLETS_MEDIUM:
        severity = "LOW"
        reasons.append("single_outlet_unconfirmed")
    elif conflicting:
        severity = "MEDIUM"
        reasons.append("conflicting_reports_conservative")
    elif critical_titles and len(outlets) >= NEWS_OUTLETS_HIGH:
        severity = "HIGH"
        reasons.append("critical_phrases_broadly_corroborated")
    elif critical_titles:
        severity = "MEDIUM"
        reasons.append("critical_phrases_min_corroboration")
    elif len(outlets) >= NEWS_OUTLETS_HIGH:
        severity = "MEDIUM"
        reasons.append("broad_coverage")
    else:
        severity = "LOW"
        reasons.append("limited_coverage")

    return {
        "status": "EVALUATED", "severity": severity, "reasons": reasons,
        "themeKey": theme_key, "outletCount": len(outlets),
        "headlineCount": len(fresh), "conflicting": conflicting,
        "sample": sorted(fresh, key=lambda hit: -hit["epoch"])[:3],
    }


def _notch(severity: Optional[str], up: int) -> Optional[str]:
    # v13.5.28: callers outside the shock lane pass their own severity
    # vocabulary (news "WATCH") — an unknown label upgrades to nothing
    # instead of raising mid-confirmation (latent crash found by the
    # direction-alignment tests).
    if severity is None or up <= 0 or severity not in SEVERITIES:
        return severity
    index = SEVERITIES.index(severity)
    return SEVERITIES[min(index + 1, len(SEVERITIES) - 1)]


def apply_cross_market_confirmation(
        severity: Optional[str], *, vix_change: Optional[float],
        usd_jpy_change: Optional[float], us10y_change_bp: Optional[float],
        expected: Optional[Mapping[str, int]] = None,
) -> Dict[str, Any]:
    """At most ONE notch of upgrade, only on explicit multi-signal confirmation.

    Confirmation = at least two of: VIX up >= 2.0 points, USDJPY absolute move
    >= 1.5, US10Y move >= 8bp in the same session. Cross-market data can never
    CREATE an event, only raise confidence in one detected elsewhere.

    v13.5.28 (external review): when `expected` carries the HYPOTHESIS
    directions ({sensor: +1/-1}), a large move in the OPPOSITE direction is
    MARKET_MOVED evidence, never confirmation — it is reported in
    contradictedSignals and does not count toward the two-signal rule.
    """
    def _sign_matches(key: str, value: float) -> bool:
        want = (expected or {}).get(key)
        if want is None:
            return True
        return (value > 0) == (want > 0)

    signals, contradicted = [], []
    if isinstance(vix_change, (int, float)) and abs(vix_change) >= 2.0             and (expected or {}).get("vix") is not None:
        (signals if _sign_matches("vix", vix_change)
         else contradicted).append("vix_spike")
    elif isinstance(vix_change, (int, float)) and vix_change >= 2.0             and expected is None:
        signals.append("vix_spike")
    if isinstance(usd_jpy_change, (int, float)) and abs(usd_jpy_change) >= 1.5:
        (signals if _sign_matches("usdJpy", usd_jpy_change)
         else contradicted).append("fx_shock")
    if isinstance(us10y_change_bp, (int, float)) and abs(us10y_change_bp) >= 8.0:
        (signals if _sign_matches("us10y", us10y_change_bp)
         else contradicted).append("rates_move")
    confirmed = len(signals) >= 2
    return {
        "confirmed": confirmed,
        "signals": signals,
        "contradictedSignals": contradicted,
        "severity": _notch(severity, 1) if confirmed else severity,
    }


# Shock theme -> news-direction family. Themes whose polarity is inherent in
# the trigger get it from the headline text; unmapped themes stay UNCLEAR.
_SHOCK_THEME_FAMILY = {
    "geopolitics": "WAR_ESCALATION",
    "energy_geopolitics": "HORMUZ",
    "rates_shock": "RATES",
    "fx_policy": "FX",
    "policy_shock": "JAPAN_POLICY",
    "financial_stress": "OTHER_MARKET_RELEVANT",
    "disaster": "OTHER_MARKET_RELEVANT",
}


def build_market_shock_view(*, long_end: Mapping[str, Any],
                            themes: Sequence[Mapping[str, Any]],
                            cross_market: Mapping[str, Any],
                            now_iso: str) -> Dict[str, Any]:
    """Assemble the owner-facing market shock document (Today / Alerts input)."""
    events: List[Dict[str, Any]] = []

    if long_end.get("status") == "EVALUATED" and long_end.get("severity"):
        confirmation = apply_cross_market_confirmation(
            long_end["severity"],
            vix_change=cross_market.get("vixChange"),
            usd_jpy_change=cross_market.get("usdJpyChange"),
            us10y_change_bp=cross_market.get("us10yChangeBp"),
        )
        events.append({
            # Stable condition identity: daily observations revise the same
            # long-end risk, they are not separate news events.
            "eventId": "long-end-rates",
            "eventClass": "LONG_END_RATES",
            "severity": confirmation["severity"],
            "baseSeverity": long_end["severity"],
            "headlineJa": f"米30年債利回り {long_end['level']:.2f}%"
                          + ("・期間内高値" if long_end.get("isWindowHigh") else ""),
            "whyJa": "超長期金利の上昇は株式バリュエーションと円金利連動を通じて"
                     "日本株のリスク許容度に直接影響します。",
            "evidence": dict(long_end),
            "crossMarket": confirmation,
            # v13.5.28 (external review item 3): the official sensor lane
            # carries the SAME direction vocabulary as mail news — the US30Y
            # spike sensor's trigger condition IS the 'up' polarity.
            "impactDirection": _news_direction.direction_for("RATES", "up"),
            "sources": [{"name": "FRED DGS30", "kind": "official_series"}],
            "asOf": long_end.get("latestDate"),
        })

    for theme in themes:
        if theme.get("status") != "EVALUATED" or not theme.get("severity"):
            continue
        if theme["severity"] == "LOW" and not theme.get("conflicting"):
            # LOW single-outlet/limited items stay off the shock surface;
            # the ordinary news digest still carries them.
            continue
        confirmation = apply_cross_market_confirmation(
            theme["severity"],
            vix_change=cross_market.get("vixChange"),
            usd_jpy_change=cross_market.get("usdJpyChange"),
            us10y_change_bp=cross_market.get("us10yChangeBp"),
        )
        sample = theme.get("sample") or []
        events.append({
            "eventId": f"news:{theme['themeKey']}:{int(sample[0]['epoch']) if sample else 0}",
            "eventClass": f"NEWS_{theme['themeKey'].upper()}",
            "severity": confirmation["severity"],
            "baseSeverity": theme["severity"],
            "headlineJa": sample[0]["title"][:120] if sample else theme["themeKey"],
            "whyJa": "複数報道機関の裏付けがある市場影響級ニュースです。"
                     if theme["outletCount"] >= NEWS_OUTLETS_MEDIUM
                     else "単独報道のため未確認情報として扱います。",
            "evidence": {key: theme[key] for key in
                         ("themeKey", "outletCount", "headlineCount",
                          "conflicting", "reasons")},
            "crossMarket": confirmation,
            "impactDirection": _news_direction.evaluate_impact_direction(
                taxonomy={"eventType": _SHOCK_THEME_FAMILY.get(
                    theme["themeKey"], "OTHER_MARKET_RELEVANT")},
                subject=(sample[0]["title"] if sample else theme["themeKey"])),
            "sources": [{"name": hit["domain"], "kind": "news_outlet"}
                        for hit in sample],
            "asOf": now_iso,
        })

    order = {name: index for index, name in enumerate(SEVERITIES)}
    events.sort(key=lambda event: -order.get(event["severity"], -1))
    return {
        "schemaVersion": MARKET_SHOCK_SCHEMA,
        "generatedAt": now_iso,
        "status": "EVALUATED",
        "eventCount": len(events),
        "events": events,
        "longEnd": dict(long_end),
        "automaticAiCalls": 0,
    }
