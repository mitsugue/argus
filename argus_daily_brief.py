"""ARGUS — §21 Owner-only Daily Institutional Brief (pure, deterministic).

WHY: the research mesh collects a lot of IntelligenceItems, but a holder does not
want a generic news digest — they want the SHORT, relevance-first read of what
*institutions* did/said overnight that touches their watchlist and live events.
This module folds already-collected IntelligenceItems into a compact brief:

  * newAnalystActions       — fresh rating / price-target / estimate moves
  * newInstitutionalReports — named-institution research/strategy/preview notes
  * majorStrategyThemes     — most-cited themes across institutional items
  * watchlistRelevance      — items touching the owner's symbols (capped, ranked)
  * activeEventLinks         — items matching each live event's assets
  * unresolvedClaims        — directional institutional views with NO official
                              corroboration in their cluster → labelled UNCONFIRMED
  * sourcesUnavailable       — licensed feeds (UNAVAILABLE) + RSS feeds that
                              produced zero items this run

Hard product boundary (mirrors argus_research_mesh / argus_downside):
  * A NAMED institutional VIEW is reported, never a NAMED TRADE.
  * Nothing here is calibrated — directional views are labelled UNCONFIRMED, not
    "confirmed", and never reduced to a single confidence number.
  * No order / size / broker surface. Owner-only (the CALLER enforces auth).

Pure: every input is an argument. We only import argus_research_mesh for its
already-implemented vocabulary (content-type sets, source rights, clustering).
Stdlib-only otherwise; no network, no LLM, no secrets, no scanner reach-in.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import argus_research_mesh as M

SCHEMA = "daily-brief-v1"
CALIB = "uncalibrated_heuristic_v1"  # 自己採点なし。方向性見解はUNCONFIRMED表記

# Default cap for every list — a brief is SHORT by design (relevance + novelty).
_CAP = 8

# ── content-type buckets (single source of truth, drawn from the mesh §8) ─────
# 格上げ/格下げ/目標株価/予想変更 = アナリストの「行動」
ANALYST_ACTION_TYPES = {
    "ANALYST_UPGRADE", "ANALYST_DOWNGRADE", "PRICE_TARGET_CHANGE", "ESTIMATE_REVISION",
}
# 名指し機関による「見解」レポート(行動ではなく分析・戦略)
INSTITUTIONAL_REPORT_TYPES = {
    "RESEARCH_NOTE", "STRATEGY_OUTLOOK", "EARNINGS_PREVIEW",
    "CONFERENCE_COMMENT", "FUND_LETTER", "INTERVIEW",
}
# 公式/規制ソース = クラスタ内の「裏取り」になりうる確定情報
OFFICIAL_CONTENT_TYPES = {"OFFICIAL_RELEASE", "REGULATORY_FILING"}
# 方向性のある(=裏取りを要する)スタンス
_DIRECTIONAL_STANCE = {"cautious", "constructive"}


# ── small helpers ─────────────────────────────────────────────────────────────
def _assets(item: Dict[str, Any]) -> set:
    """Item's linked assets as an UPPER set (defensive against non-upper input)."""
    return {str(a).upper() for a in (item.get("linkedAssets") or [])}


def _is_official(item: Dict[str, Any]) -> bool:
    """An item that constitutes official corroboration (公式/規制の確定情報).
    Either its content-type is official, OR its source is an official/licensed-free
    public-domain source per the rights registry (IR / SEC / TDnet / EDINET …)."""
    if item.get("contentType") in OFFICIAL_CONTENT_TYPES:
        return True
    return M.source_rights(item.get("sourceId") or "")["kind"] == "official"


def _novelty_key(item: Dict[str, Any]) -> str:
    """Detection timestamp used to sort 'most recent / novel first'. Empty sorts
    last so undated items never crowd out dated ones."""
    return item.get("firstDetectedAt") or item.get("publishedAt") or ""


def _brief_view(item: Dict[str, Any]) -> Dict[str, Any]:
    """Compact, display-safe projection of an IntelligenceItem for the brief.
    Carries ONLY metadata the rights class already permits (the mesh stripped any
    forbidden fields on normalize); never a trade, never a calibrated number."""
    iid = item.get("institutionId")
    inst_name = (M.INSTITUTIONS.get(iid) or {}).get("canonicalName") if iid else None
    return {
        "intelligenceId": item.get("intelligenceId"),
        "sourceId": item.get("sourceId"),
        "accessClass": item.get("accessClass"),
        "title": item.get("title"),
        "publicSnippet": item.get("publicSnippet"),
        "institutionId": iid,
        "institutionName": inst_name,
        "contentType": item.get("contentType"),
        "category": item.get("category"),
        "stance": item.get("stance"),
        "timeHorizon": item.get("timeHorizon"),
        "linkedAssets": sorted(_assets(item)),
        "linkedThemes": list(item.get("linkedThemes") or []),
        "publishedAt": item.get("publishedAt"),
        "firstDetectedAt": item.get("firstDetectedAt"),
        # 機関の「見解」はトレードではない。表示側にもこの境界を渡す。
        "isNamedView": bool(iid) and item.get("category") == "INSTITUTIONAL_RESEARCH_VIEW",
    }


def _by_novelty(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Newest detection first; stable for equal timestamps."""
    return sorted(items, key=_novelty_key, reverse=True)


# ── main entry point ──────────────────────────────────────────────────────────
def build_daily_brief(
    intel_items: List[Dict[str, Any]],
    watchlist_symbols: List[str],
    active_events: Optional[List[Dict[str, Any]]] = None,
    now_iso: Optional[str] = None,
    *,
    rss_item_counts: Optional[Dict[str, int]] = None,
    cap: int = _CAP,
) -> Dict[str, Any]:
    """Fold already-collected IntelligenceItems into a compact, relevance-first
    owner brief. PURE — all inputs are arguments; the caller enforces owner auth.

    intel_items        : list of normalized IntelligenceItems (mesh §8 shape).
    watchlist_symbols  : owner symbols (case-insensitive; matched UPPER).
    active_events      : optional [{eventId, linkedAssets, ...}] live events.
    now_iso            : optional ISO stamp recorded as asOf (no clock read here).
    rss_item_counts    : optional {sourceId: itemCount} for THIS run; an rss source
                         mapped to 0 (or absent for a known rss source) is reported
                         as unavailable-this-run.
    cap                : per-list cap (briefs are short — relevance + novelty).
    """
    items = list(intel_items or [])
    watch = {str(s).upper() for s in (watchlist_symbols or [])}
    events = list(active_events or [])
    counts_in = dict(rss_item_counts or {})

    # cluster once — used for corroboration lookup (no official source in a
    # directional item's cluster ⇒ unresolved/UNCONFIRMED).
    clusters = M.cluster_items(items)
    cluster_has_official: Dict[str, bool] = {}
    for c in clusters:
        cid = c["storyClusterId"]
        cluster_has_official[cid] = any(_is_official(it) for it in c["items"])

    # ── A. new analyst ACTIONS (rating/PT/estimate) ──────────────────────────
    analyst_actions = _by_novelty(
        [it for it in items if it.get("contentType") in ANALYST_ACTION_TYPES]
    )

    # ── B. new INSTITUTIONAL reports (named institution + a report type) ──────
    institutional_reports = _by_novelty(
        [it for it in items
         if it.get("institutionId") and it.get("contentType") in INSTITUTIONAL_REPORT_TYPES]
    )

    # ── C. major STRATEGY themes — most-cited themes across institutional items
    theme_freq: Dict[str, int] = {}
    for it in institutional_reports:
        for th in (it.get("linkedThemes") or []):
            key = str(th).strip()
            if key:
                theme_freq[key] = theme_freq.get(key, 0) + 1
    major_themes = [
        {"theme": th, "count": n}
        # 頻度降順、同数はテーマ名で安定ソート
        for th, n in sorted(theme_freq.items(), key=lambda kv: (-kv[1], kv[0]))
    ][:cap]

    # ── D. watchlist RELEVANCE — items touching owner symbols, ranked ─────────
    relevant = [it for it in items if _assets(it) & watch]
    # rank: 名指し機関の見解 → アナリスト行動 → 新しさ(直近検知が上)
    def _relevance_rank(it: Dict[str, Any]):
        has_inst = 1 if it.get("institutionId") else 0
        is_action = 1 if it.get("contentType") in ANALYST_ACTION_TYPES else 0
        return (has_inst + is_action, _novelty_key(it))
    relevant.sort(key=_relevance_rank, reverse=True)

    # ── E. active EVENT links — items whose assets match each live event ──────
    event_links = []
    for ev in events:
        ev_assets = {str(a).upper() for a in (ev.get("linkedAssets") or [])}
        if not ev_assets:
            continue
        matched = _by_novelty([it for it in items if _assets(it) & ev_assets])
        if matched:
            event_links.append({
                "eventId": ev.get("eventId"),
                "linkedAssets": sorted(ev_assets),
                "items": [_brief_view(it) for it in matched[:cap]],
                "matchCount": len(matched),
            })

    # ── F. UNRESOLVED claims — directional institutional view, no official
    #        corroboration in its cluster → UNCONFIRMED (裏取りなし) ───────────
    unresolved = []
    for it in items:
        if not it.get("institutionId"):
            continue
        if it.get("stance") not in _DIRECTIONAL_STANCE:
            continue
        if _is_official(it):
            continue  # the item itself is official → already confirmed, not a claim
        cid = it.get("storyClusterId")
        if cluster_has_official.get(cid):
            continue  # an official source shares its cluster → corroborated
        view = _brief_view(it)
        view["status"] = "UNCONFIRMED"
        view["reasonJa"] = "公式ソースによる裏取りが同一クラスタ内に無い(方向性見解は未確認扱い)"
        unresolved.append(view)
    unresolved = _by_novelty(unresolved)

    # ── G. SOURCES UNAVAILABLE — licensed feeds + zero-item rss feeds ─────────
    sources_unavailable = _sources_unavailable(items, counts_in)

    return {
        "schema": SCHEMA,
        "calibration": CALIB,
        "asOf": now_iso,
        "ownerOnly": True,  # caller enforces auth; flagged so UI never leaks it
        "newAnalystActions": [_brief_view(it) for it in analyst_actions[:cap]],
        "newInstitutionalReports": [_brief_view(it) for it in institutional_reports[:cap]],
        "majorStrategyThemes": major_themes,
        "watchlistRelevance": [_brief_view(it) for it in relevant[:cap]],
        "activeEventLinks": event_links[:cap],
        "unresolvedClaims": [v for v in unresolved][:cap],
        "sourcesUnavailable": sources_unavailable,
        "counts": {
            "totalItems": len(items),
            "analystActions": len(analyst_actions),
            "institutionalReports": len(institutional_reports),
            "themes": len(theme_freq),
            "watchlistRelevant": len(relevant),
            "activeEventLinks": len(event_links),
            "unresolvedClaims": len(unresolved),
            "sourcesUnavailable": len(sources_unavailable),
        },
        "boundaryNote": "意思決定の補助。機関の見解であって売買指示ではない。方向性見解は未確認(UNCONFIRMED)。",
    }


def _sources_unavailable(
    items: List[Dict[str, Any]],
    rss_item_counts: Dict[str, int],
) -> List[Dict[str, Any]]:
    """Sources the owner should KNOW were silent: every UNAVAILABLE licensed feed
    in the rights registry, plus any collection='rss' source that produced zero
    items this run (per the passed-in count map, defaulting to 0 when absent)."""
    out: List[Dict[str, Any]] = []
    seen = set()

    # 1) licensed feeds — UNAVAILABLE until contracted (§3/§25).
    for sid, rec in M.SOURCE_RIGHTS.items():
        if rec.get("accessClass") == "UNAVAILABLE":
            r = M.source_rights(sid)
            out.append({
                "sourceId": sid,
                "reason": "LICENSED_NOT_CONFIGURED",
                "accessClass": r["accessClass"],
                "kind": r["kind"],
                "vendor": r.get("vendor"),
                "licenceStatus": r.get("licenceStatus"),
                "reasonJa": "ライセンス契約前のため無効(契約・資格情報で有効化)",
            })
            seen.add(sid)

    # 2) public RSS feeds that produced zero items this run.
    produced = {it.get("sourceId") for it in items}
    for sid, rec in M.SOURCE_RIGHTS.items():
        if sid in seen or rec.get("collection") != "rss":
            continue
        # count map wins; absence of a known rss source ⇒ treated as 0 this run.
        n = rss_item_counts.get(sid, 0)
        if n <= 0 and sid not in produced:
            r = M.source_rights(sid)
            out.append({
                "sourceId": sid,
                "reason": "RSS_ZERO_ITEMS",
                "accessClass": r["accessClass"],
                "kind": r["kind"],
                "vendor": None,
                "licenceStatus": r.get("licenceStatus"),
                "reasonJa": "今回の取得でアイテム0件(フィード沈黙/一時的不通の可能性)",
            })
            seen.add(sid)

    return out
