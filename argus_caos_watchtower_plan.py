"""ARGUS V11.5.3 — C.A.O.S. Watchtower Plan (pure, deterministic, stdlib-only).

Builds the near-real-time patrol target list from what actually matters to the
owner: active movers (urgent/high) > watchlist symbols (high/normal) > macro-event
linked assets (high) > Core Portfolio baseline classes (normal). Gold/Bonds/USDJPY/
Crypto exist as baseline targets even when not on the watchlist; CASH is a
posture/rates/visibility target (no news ticker of its own); funds inherit their
underlying exposures rather than getting their own news patrol.

Pure: the scanner supplies watchlist/movers/events; this only assembles targets.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import argus_caos_source_universe as SU
import argus_investment_universe as IU

SCHEMA_VERSION = "caos-watchtower-plan-v1"

_CADENCE_MIN = {"urgent": 5, "high": 15, "normal": 30, "low": 60}

_BASELINE_TARGETS = [
    # (assetClass, symbol, name)
    ("GOLD_GLD", "GLD", "Gold (GLD)"),
    ("BONDS_TLT", "TLT", "Bonds (TLT)"),
    ("REITS_XLRE", "XLRE", "REITs (XLRE)"),
    ("CRYPTO_BTC_ETH", "BTC", "Bitcoin"),
    ("CRYPTO_BTC_ETH", "ETH", "Ethereum"),
    ("FX_USDJPY", "USDJPY", "USD/JPY"),
]


def _sources_for(asset_class: str, universe_sources: List[Dict[str, Any]]) -> List[str]:
    return [s["sourceId"] for s in universe_sources
            if asset_class in (s.get("assetClasses") or [])
            and s.get("status") in ("live", "partial")]


def _mk_target(asset_class: str, symbol: str, name: str, priority: str, reason: str,
               sources: List[str], queries: List[str], now_iso: str,
               limitations: Optional[List[str]] = None) -> Dict[str, Any]:
    return {
        "targetId": f"wt-{asset_class}-{symbol or 'CLASS'}",
        "assetClass": asset_class, "symbol": symbol, "name": name,
        "themes": [], "priority": priority,
        "sources": sources, "queries": queries,
        "refreshCadenceMin": _CADENCE_MIN.get(priority, 30),
        "lastCheckedAt": None, "nextCheckAt": now_iso,
        "reason": reason, "limitationsJa": limitations or [],
    }


def build_plan(*, watchlist_jp: List[Dict[str, Any]], watchlist_us: List[Dict[str, Any]],
               movers: List[Dict[str, Any]], macro_events: List[Dict[str, Any]],
               universe_sources: List[Dict[str, Any]], now_iso: str) -> Dict[str, Any]:
    """Assemble the patrol plan. movers = today's mover-cause records; macro_events =
    unified dashboard events (eventCode/displayImpact/state)."""
    targets: Dict[str, Dict[str, Any]] = {}

    def put(t: Dict[str, Any]):
        prev = targets.get(t["targetId"])
        rank = {"urgent": 0, "high": 1, "normal": 2, "low": 3}
        if prev is None or rank[t["priority"]] < rank[prev["priority"]]:
            targets[t["targetId"]] = t

    # 1) active movers — urgent when |chg| >= 7 or cause unresolved+big, else high
    for m in movers or []:
        sym = str(m.get("symbol") or "").upper()
        if not sym:
            continue
        mkt = str(m.get("market") or "JP").upper()
        ac = IU.asset_class_of_symbol(sym, mkt)
        chg = m.get("changePct")
        big = isinstance(chg, (int, float)) and abs(chg) >= 7
        unresolved = m.get("causeStatus") in ("candidate_catalyst", "no_lead_yet")
        prio = "urgent" if (big or (unresolved and isinstance(chg, (int, float)) and abs(chg) >= 4)) else "high"
        nm = str(m.get("name") or sym)
        put(_mk_target(ac, sym, nm, prio, "active_mover",
                       _sources_for(ac, universe_sources),
                       [f'"{nm}" (株価 OR 決算 OR 材料)' if mkt == "JP" else f'"{nm}" stock news'],
                       now_iso))

    # 2) watchlist symbols — high (JP/US equities the owner actually watches)
    for wl, mkt in ((watchlist_jp or [], "JP"), (watchlist_us or [], "US")):
        for w in wl:
            sym = str((w.get("symbol") if isinstance(w, dict) else w) or "").upper()
            if not sym:
                continue
            nm = str((w.get("name") if isinstance(w, dict) else "") or sym)
            ac = IU.asset_class_of_symbol(sym, mkt)
            put(_mk_target(ac, sym, nm, "high", "watchlist",
                           _sources_for(ac, universe_sources),
                           [f'"{nm}" (株価 OR 決算 OR 材料)' if mkt == "JP" else f'"{nm}" stock'],
                           now_iso))

    # 3) macro critical events → linked asset classes get high
    for ev in macro_events or []:
        if str(ev.get("displayImpact") or "") not in ("critical", "high"):
            continue
        code = str(ev.get("eventCode") or "")
        for ac in ("BONDS_TLT", "FX_USDJPY", "GOLD_GLD") if code in (
                "FOMC", "CPI", "NFP", "PCE", "GDP", "JOLTS", "BOJ") else []:
            put(_mk_target(ac, {"BONDS_TLT": "TLT", "FX_USDJPY": "USDJPY",
                                "GOLD_GLD": "GLD"}[ac],
                           {"BONDS_TLT": "Bonds (TLT)", "FX_USDJPY": "USD/JPY",
                            "GOLD_GLD": "Gold (GLD)"}[ac],
                           "high", "dashboard_event",
                           _sources_for(ac, universe_sources), [code], now_iso))

    # 4) Core Portfolio baseline — every class is watched even with no watchlist entry
    for ac, sym, nm in _BASELINE_TARGETS:
        put(_mk_target(ac, sym, nm, "normal", "core_portfolio",
                       _sources_for(ac, universe_sources), [], now_iso))
    # cash: posture target (rates/vol/event-risk/visibility — not a news ticker)
    put(_mk_target("CASH", "", "現金・待機資金", "low", "core_portfolio",
                   _sources_for("CASH", universe_sources), [],
                   now_iso,
                   ["現金は金利・ボラ・イベントリスク・可視性で決まる姿勢クラス(ニュース銘柄ではない)"]))
    # funds: inherit underlying exposure, no direct news trading signals
    for f in IU.FUNDS:
        put(_mk_target("FUND_ACCUMULATION", str(f["fundCode"]), str(f["nameJa"]),
                       "low", "core_portfolio",
                       sorted({sid for ue in f.get("underlyingExposure") or []
                               for sid in _sources_for(ue if ue in IU.REQUIRED_CLASSES else "US_EQUITY",
                                                       universe_sources)}),
                       [], now_iso,
                       ["積立は地合い連動の積立方針(dca_policy) — 日次NAVで売買判断しない"]))

    ordered = sorted(targets.values(),
                     key=lambda t: ({"urgent": 0, "high": 1, "normal": 2, "low": 3}[t["priority"]],
                                    t["targetId"]))
    by_class: Dict[str, int] = {}
    for t in ordered:
        by_class[t["assetClass"]] = by_class.get(t["assetClass"], 0) + 1
    return {"schemaVersion": SCHEMA_VERSION, "asOf": now_iso,
            "targets": ordered, "count": len(ordered), "byAssetClass": by_class,
            "noteJa": "急変銘柄>ウォッチリスト>マクロ連動>Core Portfolio基線の順に巡回。"
                      "near-real-time監視でありBloomberg/Reuters端末の完全代替ではない。"}
