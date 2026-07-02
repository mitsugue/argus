"""ARGUS V11.4.1 — Unified dashboard event summary (pure, deterministic).

Merges ImportantEvents + MacroEventAnalysis (pre/actual/post) into ONE display
model so the top event card is the single primary surface and the lower C.A.O.S.
area can de-duplicate against it. Pure: no fetch, no LLM.

State correctness (the NFP bug this fixes): the display state is RE-RESOLVED from
the real release time + actual availability at SERVE time — a record generated
before release but read after release flips to post/pending automatically, never
staying visually "pre".

Discipline (baked in):
  * the ARGUS pre scenario is NEVER called "consensus";
  * after release, the OFFICIAL RESULT and impact are shown before the pre view,
    which becomes "事前シナリオ（当時）";
  * no official result → "公式結果取得中" (never fabricated);
  * post generated but pre never preserved → verdict not_scoreable;
  * public-safe metadata only (no prompts / raw bodies / holdings).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import argus_macro_event_analysis as _MA

SCHEMA_VERSION = "dashboard-event-summary-v1"

# hours after release with no official result before we call the display "stale"
_STALE_AFTER_HOURS = 3.0

_IMPORTANCE = ("critical", "high", "medium", "low")

STATE_LABEL_JA = {
    "pre": "発表前", "imminent": "まもなく",
    "released_pending_result": "発表済み・公式結果取得中",
    "post_result": "発表済み・結果反映済み",
    "post_answer_checked": "答え合わせ済み",
    "stale": "更新遅延", "not_scoreable": "採点不可",
}
STATE_TONE = {
    "pre": "pre", "imminent": "pre", "released_pending_result": "pending",
    "post_result": "post", "post_answer_checked": "checked",
    "stale": "warning", "not_scoreable": "neutral",
}
_VERDICT_JA = {"hit": "概ね当たり", "partial": "部分的", "miss": "外れ",
               "not_scoreable": "採点不可", "not_available": "未確認"}


def _now_dt(now_iso: str):
    return _MA._parse_utc(now_iso)


def _hours_since(iso: Optional[str], now_iso: str) -> Optional[float]:
    a, b = _MA._parse_utc(iso), _MA._parse_utc(now_iso)
    if not a or not b:
        return None
    return (b - a).total_seconds() / 3600.0


def _dedupe_key(event_code: str, event_date: Optional[str], title: str,
                event_time: Optional[str]) -> str:
    code = (event_code or "").upper()
    if code and code != "OTHER" and event_date:
        return f"{code}:{str(event_date)[:10]}"
    if code and code != "OTHER" and event_time:
        return f"{code}:{str(event_time)[:10]}"
    return f"TITLE:{(title or '').strip()[:40]}:{str(event_time or event_date or '')[:10]}"


def _nfp_impact_fallback(metrics: Dict[str, Any]) -> str:
    """Deterministic, metric-aware impact comment when the AI post impact is empty
    but the official result IS available. NOT consensus, NOT a trade instruction —
    a caveated read that ends 'market reaction pending'."""
    chg = metrics.get("nfpChangeK")
    ur = metrics.get("unemploymentRate")
    ur_txt = f"失業率{ur}%は労働市場の急な崩れを示さず、" if ur not in (None, "") else ""
    if isinstance(chg, (int, float)):
        if chg < 100:
            body = ("雇用者数の伸び鈍化は金利低下方向、成長株・AI/半導体には支援材料になり得る一方、"
                    "景気減速懸念も残る。")
        elif chg > 250:
            body = ("雇用者数の強い伸びは金利上昇・ドル高方向で、高PER成長株には短期的な逆風になり得るが、"
                    "景気の底堅さを示す。")
        else:
            body = "雇用者数はおおむね想定内で、金利・ドルへの一方向の圧力は限定的。"
    else:
        body = "雇用統計の結果を踏まえ、金利・ドル・株式の初動を確認する局面。"
    return f"{body}{ur_txt}判断は市場反応の確認待ち。"


def _resolve_state(event_time_utc: Optional[str], event_date: Optional[str],
                   actual_available: bool, post: Dict[str, Any], now_iso: str) -> str:
    """Authoritative display state, RE-RESOLVED at serve time. The macro phase
    (from the real release clock) overrides any stale ImportantEvent lifecycle."""
    phase = _MA.resolve_macro_event_phase(event_time_utc, now_iso,
                                          actual_available=actual_available,
                                          event_date=event_date)
    if phase in ("pre_early", "pre_watch", "pre_final"):
        return "pre"
    if phase == "imminent":
        return "imminent"
    # released territory
    if not actual_available:
        hrs = _hours_since(event_time_utc, now_iso)
        if hrs is not None and hrs > _STALE_AFTER_HOURS:
            return "stale"
        return "released_pending_result"
    # actual available
    verdict = str((post or {}).get("verdict") or "")
    post_generated = bool((post or {}).get("generatedAt"))
    if post_generated and verdict and verdict != "not_available":
        return "post_answer_checked"
    return "post_result"


def build_summary_item(*, important_event: Optional[Dict[str, Any]],
                       macro_record: Optional[Dict[str, Any]], now_iso: str) -> Dict[str, Any]:
    ie = important_event or {}
    rec = macro_record or {}
    pre = rec.get("pre") or {}
    actual = rec.get("actual") or {}
    post = rec.get("post") or {}
    mr = rec.get("marketReaction") or {}

    event_code = str(rec.get("eventCode") or ie.get("eventCode") or "OTHER").upper() or "OTHER"
    event_time = rec.get("eventTimeUtc") or ie.get("eventTimeUtc")
    event_date = rec.get("eventDate") or ie.get("eventDate")
    title = rec.get("title") or ie.get("title") or event_code
    event_id = str(rec.get("eventId") or ie.get("eventId") or ie.get("id") or event_code)
    importance = ie.get("displayImpact") or ie.get("importance") or rec.get("displayImpact") or "medium"
    if importance not in _IMPORTANCE:
        importance = "medium"

    actual_avail = bool(actual.get("available"))
    state = _resolve_state(event_time, event_date, actual_avail, post, now_iso)
    tone = STATE_TONE.get(state, "neutral")

    released = state in ("released_pending_result", "post_result",
                         "post_answer_checked", "stale")
    show_actual_first = state in ("post_result", "post_answer_checked")
    show_pending = state in ("released_pending_result", "stale")

    # impact comment: AI post impact, else a deterministic metric-aware fallback
    # (ONLY when the official result is actually available — never fabricated).
    impact = str(post.get("portfolioImpactJa") or "")
    if actual_avail and not impact:
        impact = (_nfp_impact_fallback(actual.get("metrics") or {})
                  if event_code == "NFP" else
                  "公式結果を踏まえ、金利・ドル・株式の初動を確認する局面。判断は市場反応の確認待ち。")

    verdict = str(post.get("verdict") or ("not_available" if not released else "not_available"))
    answer_check = str(post.get("answerCheckJa") or "")
    pre_exists = bool(pre.get("argusScenarioJa") or pre.get("summaryJa"))

    # primary / secondary display lines
    if show_actual_first:
        primary = str(actual.get("headline") or "公式結果を取得済み")
        secondary = impact or (post.get("marketReactionJa") or "")
    elif show_pending:
        primary = "発表時刻は通過。公式結果の取得待ち。"
        secondary = ("事前シナリオ（当時）: " + (pre.get("argusScenarioJa") or "（保存なし）")) if released else ""
    else:  # pre / imminent
        primary = str(pre.get("argusScenarioJa") or pre.get("summaryJa") or f"{title}（発表前）")
        secondary = str(pre.get("marketPricingJa") or "")

    caos = {
        "preScenarioJa": str(pre.get("argusScenarioJa") or ""),
        "summaryJa": str(pre.get("summaryJa") or ""),
        "marketPricingJa": str(pre.get("marketPricingJa") or ""),
        "whatWouldSurpriseJa": str(pre.get("whatWouldSurpriseJa") or ""),
        "assetsToWatch": list(pre.get("assetsToWatch") or [])[:6],
        "answerCheckJa": answer_check,
        "verdict": verdict,
        "verdictJa": _VERDICT_JA.get(verdict, "未確認"),
        "marketReactionJa": str(post.get("marketReactionJa") or ""),
        "impactCommentJa": impact,
        "whatChangedJa": str(post.get("whatChangedJa") or ""),
        "limitationsJa": list(post.get("limitationsJa") or pre.get("limitationsJa") or [])[:5],
    }
    official = {
        "available": actual_avail,
        "headlineJa": str(actual.get("headline") or "") if actual_avail else "",
        "metrics": actual.get("metrics") or {},
        "source": actual.get("source"),
        "sourceUrl": actual.get("sourceUrl"),
        "releasedAt": actual.get("releasedAt"),
        "limitationsJa": list(actual.get("limitationsJa") or [])[:5],
    }
    # answer-check honesty: released + actual available + no preserved pre → not_scoreable
    if released and actual_avail and not pre_exists and verdict in ("not_available", ""):
        caos["verdict"] = "not_scoreable"
        caos["verdictJa"] = _VERDICT_JA["not_scoreable"]
        caos["answerCheckJa"] = caos["answerCheckJa"] or "事前予想が保存されていないため答え合わせ不可"

    return {
        "displayEventId": f"de-{event_id}",
        "eventId": event_id,
        "eventCode": event_code,
        "title": str(title)[:120],
        "eventTimeUtc": event_time,
        "eventDate": event_date,
        "importance": importance,
        "state": state,
        "stateLabelJa": STATE_LABEL_JA.get(state, state),
        "stateTone": tone,
        "sourceState": {
            "importantEventLifecycle": ie.get("lifecycle") or ie.get("countdown"),
            "macroPhase": rec.get("phase"),
            "releaseClockPassed": released,
            "actualAvailable": actual_avail,
            "postAvailable": bool(post.get("generatedAt")),
        },
        "officialResult": official,
        "caos": caos,
        "display": {
            "primaryLineJa": primary[:200],
            "secondaryLineJa": (secondary or "")[:200],
            "showActualFirst": show_actual_first,
            "showPreProminently": state in ("pre", "imminent"),
            "showPreAsHistorical": released,
            "showPendingResult": show_pending,
            "showImpact": bool(impact) and released,
            "showAnswerCheck": state == "post_answer_checked",
            "showDuplicateCaosBelow": False,
        },
        "marketReaction": {k: mr.get(k) for k in
                           ("us10yMoveBp", "usdJpyMovePct", "spyMovePct", "qqqMovePct",
                            "vixMovePct", "window", "limitationsJa")},
        "dedupeKey": _dedupe_key(event_code, event_date, title, event_time),
        "recordRefs": {
            "macroAnalysisId": rec.get("analysisId"),
            "eventCardId": (rec.get("recordRefs") or {}).get("eventCardId"),
            "evidencePackId": (rec.get("recordRefs") or {}).get("evidencePackId"),
            "ledgerRef": (rec.get("recordRefs") or {}).get("ledgerRef"),
        },
    }


def build_summary(*, important_events: List[Dict[str, Any]],
                  macro_records: List[Dict[str, Any]], now_iso: str,
                  limit: int = 8) -> Dict[str, Any]:
    """Merge important events + macro records into the unified display model.
    Deterministic: same inputs → byte-identical output."""
    # index macro records by eventId AND by dedupe key so an important event can
    # find its analysis even if the ids differ.
    by_id: Dict[str, Dict[str, Any]] = {}
    by_key: Dict[str, Dict[str, Any]] = {}
    for r in (macro_records or []):
        if not isinstance(r, dict):
            continue
        eid = str(r.get("eventId") or "")
        if eid:
            by_id[eid] = r
        k = _dedupe_key(str(r.get("eventCode") or ""), r.get("eventDate"),
                        r.get("title") or "", r.get("eventTimeUtc"))
        by_key.setdefault(k, r)

    items: List[Dict[str, Any]] = []
    seen_keys = set()
    consumed = set()          # id() of macro records already joined to an item
    hidden = 0
    details: List[str] = []

    def _add(ie, rec):
        nonlocal hidden
        if rec is not None:
            consumed.add(id(rec))
        item = build_summary_item(important_event=ie, macro_record=rec, now_iso=now_iso)
        if item["dedupeKey"] in seen_keys:
            hidden += 1
            details.append(f"重複統合: {item['eventCode']} {item.get('eventDate') or ''}")
            return
        seen_keys.add(item["dedupeKey"])
        items.append(item)

    # 1) important events first (they carry importance + ordering), joined to macro
    for ie in (important_events or []):
        if not isinstance(ie, dict):
            continue
        eid = str(ie.get("eventId") or ie.get("id") or "")
        rec = by_id.get(eid)
        if rec is None:
            k = _dedupe_key(str(ie.get("eventCode") or ""), ie.get("eventDate"),
                            ie.get("title") or "", ie.get("eventTimeUtc"))
            rec = by_key.get(k)
        _add(ie, rec)

    # 2) macro records not already joined above (still surface if released/soon).
    # A record whose dedupeKey already exists is a genuine duplicate → hidden.
    for r in (macro_records or []):
        if not isinstance(r, dict) or id(r) in consumed:
            continue
        _add(None, r)

    # order: critical>high>medium>low, then released/pending before far-future pre,
    # then soonest first.
    imp_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    state_rank = {"post_answer_checked": 0, "post_result": 0, "released_pending_result": 1,
                  "stale": 1, "imminent": 2, "pre": 3, "not_scoreable": 1}
    items.sort(key=lambda it: (imp_rank.get(it["importance"], 9),
                               state_rank.get(it["state"], 5),
                               str(it.get("eventTimeUtc") or it.get("eventDate") or "z")))
    items = items[:max(1, limit)]

    return {
        "schemaVersion": SCHEMA_VERSION,
        "asOf": now_iso,
        "items": items,
        "dedupe": {
            "mergedCount": len(items),
            "hiddenDuplicateCount": hidden,
            "detailsJa": details[:10],
        },
    }


def status_counts(summary: Dict[str, Any]) -> Dict[str, Any]:
    items = (summary or {}).get("items") or []
    crit = [it for it in items if it.get("importance") == "critical"]
    return {
        "criticalReleasedPending": sum(1 for it in crit if it["state"] in ("released_pending_result", "stale")),
        "criticalPostResult": sum(1 for it in crit if it["state"] in ("post_result", "post_answer_checked")),
        "criticalStale": sum(1 for it in crit if it["state"] == "stale"),
    }
