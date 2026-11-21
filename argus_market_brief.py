# -*- coding: utf-8 -*-
"""ARGUS v13.5.36 — MARKET SITUATION BRIEF (pure composer).

Owner directive 2026-08-26 (+external review conditions): a single Today-top
card that answers 「今の市場は何が起きているか」 in three parts —
NOW / WHY / NEXT — plus four glance chips (CHART / NEWS / NEXT EVENT /
MAIN RISK).

Discipline (non-negotiable):
- The AI is the EDITOR, never the reporter: a deterministic composer selects
  and orders the facts (P0 今日これだけは知るべき → P1 相場方向 → P2 なぜ →
  P3 次に確認), and the model may only compress them into short Japanese.
- 盛らない: no number, probability or forecast may appear unless it came in
  through a fact input. validate_ai_brief() rejects AI text that introduces
  digits/percentages absent from the fact base, execution vocabulary, or
  probability claims.
- Every fact carries a verification tag: VERIFIED (measured market data) /
  CORROBORATED (market-confirmed news) / UNCONFIRMED (pending).
- This document is evidence for a human reader. sdaAuthority is False by
  construction and no SDA input reads it.
"""
from __future__ import annotations

import re
import argus_jp_market_research
import math
import hashlib
import json
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit
from typing import Any, Dict, List, Mapping, Optional, Sequence

from argus_explanation_contract import (
    UNIFIED_FACT_LIMIT, UNIFIED_SECTIONS, _FORBIDDEN_BRIEF_PATTERNS,
    _digits_of, validate_unified_ai, calculation_identity, prompt_references,
    prompt_fact_reuse, validate_theme_views, render_event_references,
    UNIFIED_REPLY_EXTRAS, attach_unified_tone)

BRIEF_SCHEMA = "argus-market-brief-v1"
BRIEF_FACT_LIMIT = 16
PRIORITIES = ("P0", "P1", "P2", "P3")
VERIFICATIONS = ("VERIFIED", "CORROBORATED", "UNCONFIRMED")

_DIRECTION_JA = {"BULLISH": "強気", "BEARISH": "弱気", "MIXED": "強弱混在",
                 "UNCLEAR": "方向未確定"}
_IMPACT_JA = {"critical": "最重要", "high": "重要", "medium": "中", "low": "小"}


def _event_when_ja(event: Mapping[str, Any]) -> str:
    """Use only source-carried schedule precision; never invent a clock time."""
    direct = str(event.get("whenJa") or event.get("jstTime") or "").strip()
    if direct:
        return direct.replace(" JST", "（日本時間）")
    instant = str(event.get("eventTimeUtc") or "").strip()
    if instant:
        try:
            parsed = datetime.fromisoformat(instant.replace("Z", "+00:00"))
            return parsed.astimezone(timezone(timedelta(hours=9))).strftime("%Y/%m/%d %H:%M（日本時間）")
        except ValueError:
            pass
    date = str(event.get("date") or event.get("sqDate") or "").strip()
    return date.replace("-", "/") + "・時刻未公表" if re.fullmatch(r"\d{4}-\d{2}-\d{2}", date) else "日時未確認"

# Vocabulary the composer AND the AI polish must never emit (RC discipline:
# no execution orders, no invented probabilities/targets).




def validate_ai_brief(ai: Any, fact_texts: Sequence[str]) -> Optional[Dict[str, str]]:
    """Strict gate for the AI-compressed NOW/WHY/NEXT. Fails closed to None
    (the deterministic lines then render instead)."""
    if not isinstance(ai, Mapping):
        return None
    out: Dict[str, str] = {}
    allowed_digits = set()
    for t in fact_texts or []:
        allowed_digits |= _digits_of(t)
    for key in ("nowJa", "whyJa", "nextJa"):
        value = ai.get(key)
        if not isinstance(value, str) or not value.strip() or len(value) > 220:
            return None
        if any(p in value for p in _FORBIDDEN_BRIEF_PATTERNS):
            return None
        # 盛らない: every number in the AI text must exist in the fact base.
        if _digits_of(value) - allowed_digits:
            return None
        out[key] = value.strip()
    return out


def _source_reference(origin: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """Only explicit public provenance; missing publication time stays missing.

    Receipt is when ARGUS received the item, not the publisher's timestamp.
    No mailbox identifiers, article bodies, credentials or arbitrary fields.
    """
    origin = origin or {}
    result = {"scope": "published_metadata_snapshot", "eventId": None,
              "revision": None, "publishedAt": None, "receivedAt": None,
              "observedAt": None, "url": None, "sourceLabel": None}
    event_id = origin.get("eventId")
    if isinstance(event_id, str) and re.fullmatch(r"[a-zA-Z0-9_.:-]{1,160}", event_id):
        result["eventId"] = event_id
    revision = origin.get("revision")
    if type(revision) is int and revision >= 0:
        result["revision"] = revision
    for target, source in (("publishedAt", "sourcePublishedAt"),
                           ("receivedAt", "sourceReceivedAt"), ("observedAt", "asOf")):
        value = origin.get(source)
        if isinstance(value, str) and len(value) <= 40:
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if parsed.tzinfo is not None or (target == "observedAt" and len(value) == 10):
                    result[target] = value
            except ValueError:
                pass
    for key in ("sourceResponseSha256", "sourceRowSha256"):
        value = origin.get(key)
        if isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value):
            result[key] = value
    url = origin.get("sourceUrl")
    if isinstance(url, str) and len(url) <= 2048:
        try:
            parts = urlsplit(url)
            if parts.scheme == "https" and parts.hostname and not parts.username and not parts.password:
                result["url"] = url
        except ValueError:
            pass
    label = origin.get("sourceLabelJa") or origin.get("source")
    if not label and isinstance(origin.get("sources"), list):
        label = " / ".join(str(row.get("name") or "") for row in origin["sources"][:3] if isinstance(row, Mapping))
    if isinstance(label, str) and label.strip():
        result["sourceLabel"] = label[:160]
    return result


def _fact(text: str, priority: str, source: str,
          verification: str, origin: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    row = {"text": str(text)[:160], "priority": priority, "source": source,
           "verification": verification if verification in VERIFICATIONS else "UNCONFIRMED"}
    if origin is not None:
        row["provenance"] = _source_reference(origin)
    if source == "calendar" and origin:
        label = str(origin.get("title") or "")[:50] + "（" + _event_when_ja(origin) + "）"
        # The exact name/time must already occur in the fact; no source or
        # missing-time guess is introduced by the outbound rendering contract.
        if label[:-1] in row["text"]:
            row["eventLabelJa"] = label
    return row


PAGE_FACT_LIMIT = 64   # the page rejects a whole brief above this


def bound_facts(facts: Sequence[Mapping[str, Any]], limit: int = PAGE_FACT_LIMIT) -> List[Mapping[str, Any]]:
    """Keep the brief readable by the page: drop the least important facts last
    added, never a P0, and keep the original order of what remains."""
    rows = list(facts)
    if len(rows) <= limit:
        return rows
    rank = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
    keep = sorted(range(len(rows)), key=lambda i: (rank.get(rows[i].get("priority"), 3), i))[:limit]
    return [rows[i] for i in sorted(keep)]


NEWS_DETAIL_FACT_LIMIT = 6


def news_detail_facts(news_events: Sequence[Mapping[str, Any]], *,
                      limit: int = NEWS_DETAIL_FACT_LIMIT) -> List[Dict[str, Any]]:
    """Received news with the points the mail analysis extracted (2026-10-15).

    The view read only two material headlines, so a story such as fuel prices
    lifting CPI, rate-hike worry and falling stocks never reached it. Each row
    keeps the article's own headline and its validated short facts; it is
    reporting, not a causal verdict. The two P0 headlines are not repeated.
    """
    material = [e for e in news_events
                if e.get("severity") in ("HIGH", "CRITICAL")
                and str(e.get("staleness") or "").upper() != "STALE"][:2]
    shown = {id(e) for e in material}
    rows: List[Dict[str, Any]] = []
    for event in news_events:
        if len(rows) >= max(0, int(limit)):
            break
        headline = str(event.get("headlineJa") or "").strip()
        if not headline or headline == "翻訳処理中":
            continue
        points = [str(f).strip() for f in (event.get("facts") or [])
                  if isinstance(f, str) and str(f).strip()][:3]
        if id(event) in shown and not points:
            continue
        label = event.get("sourceLabelJa") or event.get("sourceFamily") or "報道"
        text = f"{label}の報道: {headline[:120]}"
        if points:
            text += "（要点: " + " / ".join(p[:120] for p in points) + "）"
        row = _fact(text, "P1", "trusted_mail",
                    "CORROBORATED" if event.get("confirmationState") == "MARKET_CONFIRMED"
                    else "UNCONFIRMED", event)
        row["text"] = text[:400]
        rows.append(row)
    return rows


def _news_direction_summary(events: Sequence[Mapping[str, Any]]) -> str:
    bear = sum(1 for e in events if "BEARISH" in set(
        ((e.get("impactDirection") or {}).get("directionByTarget")
         or {}).values()))
    bull = sum(1 for e in events if set(
        ((e.get("impactDirection") or {}).get("directionByTarget")
         or {}).values()) == {"BULLISH"})
    if bear and not bull:
        return "弱気材料が優勢"
    if bull and not bear:
        return "強気材料が優勢"
    if bear and bull:
        return "強弱材料が混在"
    return "方向材料は限定的"


def _margin_facts(document: Optional[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Received balances and computed differences; no observed covering orders."""
    if not isinstance(document, Mapping) or document.get("actionAuthority") is not False:
        return []
    current, change = document.get("current"), document.get("change") or {}
    if not isinstance(current, Mapping) or current.get("unit") != "UNITS":
        return []
    def finite(value):
        return type(value) in (int, float) and math.isfinite(value)
    if not all(finite(current.get(k)) for k in ("longBalance", "shortBalance", "ratio")):
        return []
    source = (current.get("sourceRows") or {}).get("long") or {}
    origin = {"sourceLabelJa": "J-Quants信用取引週末残高", "sourceUrl": source.get("sourceRef"),
              "sourceReceivedAt": source.get("observedAt"), "asOf": current.get("periodEnd"),
              "sourceResponseSha256": source.get("sourceResponseSha256"),
              "sourceRowSha256": source.get("sourceRowSha256")}
    failed = document.get("acquisitionStatus") not in ("AVAILABLE", "PARTIAL")
    prefix = "更新失敗・前回取得" if failed else "一部取得" if document.get("sourceStatus") == "PARTIAL" else "取得済み"
    rows = [_fact(
        f"日経レバ信用残（{prefix}、{current.get('periodEnd')}）: "
        f"買残{current['longBalance']:.0f}口・売残{current['shortBalance']:.0f}口、倍率{current['ratio']:.4f}倍。",
        "P1", "licensed_market_data", "UNCONFIRMED" if failed else "VERIFIED", origin)]
    if change.get("status") == "AVAILABLE" and all(finite(change.get(k)) for k in
            ("ratioChange", "longContribution", "shortContribution")):
        previous = document.get("previous") or {}
        rows.append(_fact(
            f"{previous.get('periodEnd')}からの倍率差{change['ratioChange']:+.4f}倍: "
            f"買残変化の寄与{change['longContribution']:+.4f}、売残変化の寄与{change['shortContribution']:+.4f}。",
            "P1", "derived_margin_change", "UNCONFIRMED", origin))
    return rows


def _jpy_position_facts(document):
    if not isinstance(document, Mapping) or document.get("status") not in ("AVAILABLE", "STALE"):
        return []
    if document.get("reportType") != "LEGACY_FUTURES_ONLY" or document.get("actionAuthority") is not False:
        return []
    current, change = document.get("current") or {}, document.get("change") or {}
    if not all(type(row.get(field)) is int for row in (current, change)
               for field in ("longContracts", "shortContracts", "netContracts", "spreadContracts")):
        return []
    failed = (document.get("acquisition") or {}).get("status") == "FAILED"
    prefix = "更新失敗・保存分" if failed else "古い保存分" if document["status"] == "STALE" else "週次の観測"
    origin = {"eventId": "cftc-jpy:" + document["reportId"],
              "sourceLabelJa": "CFTC・円先物の非商業建玉", "sourceUrl": document["sourceRef"],
              "sourcePublishedAt": document.get("publishedAt"), "sourceReceivedAt": document["receivedAt"],
              "asOf": document["positionDate"], "sourceResponseSha256": document["sourceResponseSha256"]}
    return [_fact(
        f"CFTC円先物・非商業（{prefix}、{document['positionDate']}）: 買{current['longContracts']}・売{current['shortContracts']}・"
        f"差引{current['netContracts']:+}枚。前週差は買{change['longContracts']:+}・売{change['shortContracts']:+}枚。",
        "P1", "official_weekly_position", "UNCONFIRMED" if failed or document["status"] == "STALE" else "VERIFIED", origin)]


def compose_brief(*, now_iso: str,
                  market_view_summary: Optional[Mapping[str, Any]] = None,
                  margin_dynamics: Optional[Mapping[str, Any]] = None,
                  jpy_position: Optional[Mapping[str, Any]] = None,
                  shock_events: Sequence[Mapping[str, Any]] = (),
                  news_events: Sequence[Mapping[str, Any]] = (),
                  released_events: Sequence[Mapping[str, Any]] = (),
                  imminent_events: Sequence[Mapping[str, Any]] = (),
                  next_events: Sequence[Mapping[str, Any]] = (),
                  ) -> Dict[str, Any]:
    """Deterministic NOW/WHY/NEXT + chips + prioritized fact list.

    All inputs are already-verified ARGUS stores (Market Truth, trusted mail,
    official sensors, calendar). Missing inputs produce honest omissions,
    never invented content. Works fully without any AI."""
    facts: List[Dict[str, str]] = []

    # Received official results are material even with no matching news mail.
    for result in list(released_events)[:2]:
        facts.append(_fact(str(result.get('headlineJa') or ''), 'P0',
                           'official_macro_result', 'VERIFIED', result))

    # ── P0: 今日これだけは知るべき ──
    material_news = [e for e in news_events
                     if e.get("severity") in ("HIGH", "CRITICAL")
                     and str(e.get("staleness") or "").upper() != "STALE"]
    for event in material_news[:2]:
        confirmed = event.get("confirmationState") == "MARKET_CONFIRMED"
        headline = str(event.get("headlineJa") or "").strip()
        if not headline or headline == "翻訳処理中":
            headline = "重要発表（日本語要約 処理中）"
        facts.append(_fact(
            f"{event.get('sourceLabelJa') or event.get('sourceFamily') or '公式'}: "
            f"{headline[:160]}"
            f"（{'市場確認済み' if confirmed else '市場確認待ち'}）",
            "P0", "trusted_mail",
            "CORROBORATED" if confirmed else "UNCONFIRMED", event))
    active_shocks = [s for s in shock_events
                     if s.get("severity") in ("HIGH", "CRITICAL")]
    for shock in active_shocks[:2]:
        facts.append(_fact(
            "市場ショック: "
            f"{str(shock.get('headlineJa') or shock.get('titleJa') or shock.get('title') or '')[:60]}",
            "P0", "official_sensor", "VERIFIED", shock))
    for event in list(imminent_events)[:2]:
        impact = _IMPACT_JA.get(str(event.get("displayImpact") or ""), "")
        facts.append(_fact(
            f"目前イベント: {str(event.get('title') or '')[:50]}"
            f"（{_event_when_ja(event)}・{event.get('countdown') or '近日'}"
            f"{'・' + impact if impact else ''}）",
            "P0", "calendar", "VERIFIED", event))

    # ── P1: 現在の相場方向 ──
    view_label = str((market_view_summary or {}).get("label") or "").strip()
    if view_label:
        cutoff = (market_view_summary or {}).get("informationCutoff")
        origin = None
        if isinstance(cutoff, str) and cutoff:
            # 2026-10-22 (N-17): when the market view was read, and an identity
            # of exactly what the fact states (label and that time).
            origin = {"eventId": "market-view", "asOf": cutoff,
                      "sourceRowSha256": hashlib.sha256(json.dumps(
                          {"label": view_label[:70], "informationCutoff": cutoff},
                          sort_keys=True, ensure_ascii=False).encode()).hexdigest()}
        facts.append(_fact(f"市場観: {view_label[:70]}",
                           "P1", "market_view", "VERIFIED", origin))
    news_line = _news_direction_summary(material_news or news_events)
    facts.append(_fact(f"ニュース方向: {news_line}", "P1",
                       "trusted_mail", "CORROBORATED"
                       if any(e.get("confirmationState") == "MARKET_CONFIRMED"
                              for e in material_news) else "UNCONFIRMED"))

    facts.extend(_margin_facts(margin_dynamics))
    facts.extend(_jpy_position_facts(jpy_position))

    # ── P2: なぜそうなっているか ──
    for result in list(released_events)[:2]:
        facts.append(_fact(str(result.get('whyJa') or '') + ' 市場予想差・下落寄与は未確認。',
                           'P2', 'official_macro_result', 'UNCONFIRMED', result))
    for event in material_news[:2]:
        direction = event.get("impactDirection") or {}
        # The news engine writes the path as "transmissionChain" (a list of
        # steps). Reading only the two older names left this fact always empty.
        chain = direction.get("transmissionChain")
        path = (direction.get("transmissionJa") or direction.get("transmission")
                or (" → ".join(str(step) for step in chain if str(step).strip())
                    if isinstance(chain, (list, tuple)) else ""))
        if path:
            facts.append(_fact(f"波及経路: {str(path)[:90]}", "P2",
                               "trusted_mail", "UNCONFIRMED", event))
    for shock in active_shocks[:1]:
        why = shock.get("whyJa") or shock.get("noteJa")
        if why:
            facts.append(_fact(f"背景: {str(why)[:90]}", "P2",
                               "official_sensor", "UNCONFIRMED", shock))

    # ── P3: 次に何を確認するか ──
    for event in list(next_events)[:2]:
        facts.append(_fact(
            f"次: {str(event.get('title') or '')[:50]}"
            f"（{_event_when_ja(event)}・{event.get('countdown') or '予定'}）",
            "P3", "calendar", "VERIFIED", event))
    if material_news:
        facts.append(_fact("次: 上記ニュースの市場確認センサー"
                           "（金利・株価指数・為替）の反応を確認", "P3",
                           "policy", "VERIFIED"))

    # v13.5.54 (owner 2026-09-04). Two DIFFERENT Treasury releases both render
    # to 「米財務省: 重要発表（日本語要約 処理中）（市場確認待ち）」 while their
    # Japanese summaries are still pending, so Today read 「今: 米財務省: 重要
    # 発表。米財務省: 重要発表」 — the same sentence twice, which reads as a bug
    # and says nothing the first sentence did not. Collapse identical rendered
    # lines, keeping the first. The event COUNT is not lost: the news surface
    # states it separately (「重大2件」), and nothing here invents a distinction
    # the pending translation has not given us yet.
    seen_fact_texts: set = set()
    deduped: List[Dict[str, str]] = []
    for fact in facts:
        if fact["text"] in seen_fact_texts:
            continue
        seen_fact_texts.add(fact["text"])
        deduped.append(fact)
    facts = deduped

    # ── deterministic NOW / WHY / NEXT（AI不在でも成立する行） ──
    p0_facts = [f for f in facts if f["priority"] == "P0"]
    # v13.5.53 (owner 2026-09-04): 「今」 took the first two P0 facts in
    # insertion order, and news is appended before the calendar. On a day with
    # two material headlines the D/D-1 event fact was silently dropped — the
    # owner's Today read 「今: OFAC…。Nikkei…」 with no mention of that day's
    # US Employment Situation, the single event most likely to move the book.
    # A same-day event is one short clause and must never lose its slot: keep
    # the first P0 fact, then guarantee the imminent-calendar fact the second.
    p0_imminent = [f for f in p0_facts if f["source"] == "calendar"]
    if p0_imminent and p0_imminent[0] not in p0_facts[:2]:
        p0_facts = [p0_facts[0], p0_imminent[0]]
    p0_texts = [f["text"] for f in p0_facts]
    now_line = ("。".join(t for t in p0_texts[:2])
                or (view_label and f"大きな新規材料なし。{view_label[:40]}")
                or "大きな新規材料は検知していません")
    p2_texts = [f["text"] for f in facts if f["priority"] == "P2"]
    why_line = ("。".join(t[:70] for t in p2_texts[:2])
                or f"ニュース方向: {news_line}")
    p3_texts = [f["text"] for f in facts if f["priority"] == "P3"]
    next_line = ("。".join(t[3:70] if t.startswith("次: ") else t[:70]
                           for t in p3_texts[:2])
                 or "新しい確定情報の到着を待って再評価")

    nearest = (list(imminent_events) or list(next_events) or [None])[0]
    chips = {
        "chart": view_label[:40] or "市場観 取得中",
        "news": news_line,
        "nextEvent": (f"{str(nearest.get('title') or '')[:26]}"
                      f"（{_event_when_ja(nearest)}） · {nearest.get('countdown') or '近日'}"
                      if nearest else "直近の重要イベントなし"),
        "mainRisk": (str((active_shocks[0].get("headlineJa")
                          or active_shocks[0].get("titleJa")
                          or active_shocks[0].get("title") or ""))[:30]
                     if active_shocks else
                     (f"{material_news[0].get('sourceLabelJa') or ''}"
                      f"関連の未確認リスク" if material_news
                      else "特定の集中リスク検知なし")),
    }

    has_critical = (any(e.get("severity") == "CRITICAL"
                        for e in material_news)
                    or any(s.get("severity") == "CRITICAL"
                           for s in active_shocks))
    return {
        "schemaVersion": BRIEF_SCHEMA,
        "generatedAt": now_iso,
        "hasCritical": has_critical,
        "now": now_line[:220], "why": why_line[:220], "next": next_line[:220],
        "aiText": None,           # scanner fills after validate_ai_brief
        "aiModel": None,
        "chips": chips,
        "facts": facts[:BRIEF_FACT_LIMIT],
        "priorityOrderJa": "P0 今日これだけは知るべき / P1 相場方向 / "
                           "P2 なぜ / P3 次に確認",
        "noteJa": "事実はARGUS検証済みストアの優先順位圧縮。AIは要約のみで"
                  "取材しません。数値・確率の創作は構造的に排除。"
                  "売買権限はありません。",
        "authority": "MARKET_BRIEF_EVIDENCE",
        "sdaAuthority": False,
        "automaticAiCalls": 0,
    }





def calculation_facts(calculations):
    """Explain each saved horizon using engine values, without probability claims."""
    facts = []
    snapshot = (calculations.get("5") or {}).get("marketFeatureSnapshot") or {}
    labels = {
        "credit.ratio": "二市場の信用買残÷売残（倍）",
        "credit.ratio_change": "二市場信用倍率の前週差（倍）",
        "credit.loss_pct": "信用評価損率（損失を正とする%）",
        "margin1570.ratio": "日経レバ信用買残÷売残（倍）",
        "margin1570.long_change_pct": "日経レバ信用買残の前週変化率（%）",
        "margin1570.short_change_pct": "日経レバ信用売残の前週変化率（%）",
        "relative_jp_us.return20": "日経平均とS&P500の各市場20営業日騰落率差（ポイント）",
        "vix.level": "VIX終値",
        "vix.change5": "VIXの5営業日変化（ポイント）",
        "vix.macd_histogram": "VIX MACDヒストグラム（12・26・9）",
        "foreign_flow.net4w": "海外投資家の4週純売買合計（円）",
        "fx.usdjpy_change5": "ドル円の5営業日変化率（%）",
        "rate.jp10y_change5": "日本10年金利の5営業日変化（ポイント）",
        "rate.us10y_change5": "米国10年金利の5営業日変化（ポイント）",
        "nt.ratio_change5": "NT倍率の5営業日変化率（%）",
        "event.sq_sessions": "SQまでの営業日数",
    }
    for row in snapshot.get("features", []):
        label = labels.get(row.get("seriesId")); value = row.get("value")
        if not label or type(value) not in (int, float) or not math.isfinite(value):
            continue
        facts.append(_fact(f"{row['date']}時点、{label}: {value:.4f}。",
            "P1", "market_feature_calculation", "UNCONFIRMED", {
                "eventId": "market-feature-" + row["seriesId"], "asOf": row["date"],
                "sourceLabelJa": "日本株分析エンジン・市場条件計算",
                "sourceReceivedAt": snapshot.get("informationCutoff"),
                "sourceRowSha256": hashlib.sha256(json.dumps(row, sort_keys=True,
                    ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()}))
    if snapshot.get("features"):
        facts.append(_fact("相対力は買い戻し注文の観測ではなく、売残減少も全てが買い戻しとは限らない。NT倍率だけで高配当株の強さを判断しない。VIX一日変化とMACD転換は別。警戒と回復を合算しない。",
            "P1", "market_feature_interpretation", "UNCONFIRMED"))
    for horizon in (1, 5, 10, 20):
        result = calculations.get(str(horizon)) or {}
        chart = result.get("comparison") or {}
        forecast = chart.get("forecast") or {}
        line = [p for p in forecast.get("line", []) if p.get("offsetSessions") == horizon]
        if len(line) != 1 or forecast.get("horizonSessions") != horizon:
            continue
        value = line[0].get("value")
        if type(value) not in (int, float) or not math.isfinite(value):
            continue
        unit = "基準100" if chart.get("unit") == "ANCHOR_100" else "円建て指数値" if chart.get("unit") == "JPY_INDEX_POINTS" else None
        if not unit:
            continue
        identity = calculation_identity({str(horizon): result})
        valuation = result.get("valuation") or {}
        scale_note = ""
        if valuation.get("status") == "AVAILABLE" and all(
                type(valuation.get(k)) in (int, float) and math.isfinite(valuation[k]) for k in ("eps", "per")):
            scale_note = f"指数ベースPER{valuation['per']:.2f}倍・同日終値から逆算したEPS{valuation['eps']:.2f}円で換算。"
        has_states = bool(((chart.get("marketEvidence") or {}).get("currentCounts") or {}).get("states"))
        scope = "価格形状と取得済み市場条件による部分比較" if has_states else "価格形状による部分比較"
        facts.append(_fact(f"日経平均・{chart['anchorDate']}基準の{horizon}営業日先: "
            f"{unit}の参考計算値{value:.2f}。現在は過去の{scope}で、有効性は未検証。"
            "他の期間の見立てと合算せず、確定した未来とは扱わない。" + scale_note,
            "P2", "price_path_calculation", "UNCONFIRMED", {
                "eventId": f"n225-price-path-{horizon}", "asOf": chart["anchorDate"],
                "sourceLabelJa": "日本株分析エンジン・価格経路計算",
                "sourceReceivedAt": result.get("lastSuccessfulAcquisitionAt"),
                "sourceRowSha256": identity}))
    return facts


# ── 2026-11-21 owner【足す】: five materials the view did not read ──────────
# FUTURE MAP, the PER level map, the overnight Nikkei future, the breakdown of
# the six signs and the view's own issued-forecast record. Each builder takes a
# value ARGUS already holds; a missing or malformed value adds nothing. All are
# P1 so bound_facts never lets them push out a P0, and each text stays within
# the 160-character fact limit by leaving optional parts out (never by cutting
# a number in half).
FACT_TEXT_LIMIT = 160


def _row_sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(",", ":"), default=str).encode()).hexdigest()


def _finite_number(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def _join_within(head: str, parts: Sequence[str], tail: str = "") -> str:
    """head + as many optional parts as fit (in order) + tail; "" when even the head is too long."""
    if len(head) + len(tail) > FACT_TEXT_LIMIT:
        return ""
    text = head
    for part in parts:
        if len(text) + len(part) + len(tail) <= FACT_TEXT_LIMIT:
            text += part
    return text + tail


# FUTURE MAP tags are the external table's words. 売り時 reads as a trading
# instruction, so the view receives a neutral wording of the same mark.
_FUTURE_MAP_TAG_JA = {"売り時": "高値警戒"}


def future_map_facts(display: Optional[Mapping[str, Any]], *,
                     scoring: Optional[Mapping[str, Any]] = None,
                     read_at: Optional[str] = None) -> List[Dict[str, Any]]:
    """The external FUTURE MAP table (argus_future_map.for_display output).

    It is a list of external views, not ARGUS's judgment (argusValidated is
    False); the fact says so. `scoring` is ARGUS's own touch scoring of the
    first received rows (argus_future_map_scoring.summarize), shown only when
    it was computed.
    """
    if not isinstance(display, Mapping) or display.get("externalViewsOnly") is not True:
        return []
    status = display.get("status") or {}
    position = status.get("position")
    if not isinstance(position, str) or not position.strip():
        return []
    updated = str(display.get("updatedAt") or "")
    origin = {"eventId": "future-map", "sourceLabelJa": "FUTURE MAP（外部の見立て・ARGUS未検証）",
              "sourceReceivedAt": read_at, "asOf": updated or None}
    head = f"FUTURE MAP（外部の見立てでARGUSは未検証{'・' + updated[:10] + '更新' if updated[:10] else ''}）: 現在の位置「{position}」。"
    parts = []
    for key, label in (("nextAlert", "次の注意"), ("nextBottom", "次の底")):
        row = status.get(key) or {}
        if isinstance(row.get("date"), str) and isinstance(row.get("label"), str):
            parts.append(f"{label} {row['date']}「{row['label']}」。")
    facts = [_fact(_join_within(head, parts), "P1", "future_map", "UNCONFIRMED",
                   {**origin, "sourceRowSha256": _row_sha(status)})]
    now = next((row for row in display.get("rows") or []
                if isinstance(row, Mapping) and row.get("isNow")), None)
    if now and all(isinstance(now.get(k), str) for k in ("periodLabel", "start", "end", "view", "tag")):
        tag = _FUTURE_MAP_TAG_JA.get(now["tag"], now["tag"])
        head = f"FUTURE MAPの今の行（外部の見立て）: {now['periodLabel']}（{now['start']}〜{now['end']}）{now['view']}［{tag}］。"
        parts = []
        level = now.get("level") or {}
        low, high = _finite_number(level.get("low")), _finite_number(level.get("high"))
        if low and high:
            parts.append(f"水準{low:,.0f}〜{high:,.0f}円。")
        if isinstance(scoring, Mapping) and type(scoring.get("scored")) is int and type(scoring.get("reached")) is int \
                and scoring["scored"] > 0:
            note = "10件未満で判断できない" if scoring["scored"] < 10 else "有効性は未検証"
            parts.append(f"ARGUSの答え合わせ: 採点{scoring['scored']}件中{scoring['reached']}件が到達（{note}）。")
        facts.append(_fact(_join_within(head, parts), "P1", "future_map", "UNCONFIRMED",
                           {**origin, "eventId": "future-map-now",
                            "sourceRowSha256": _row_sha({"row": now, "scoring": scoring})}))
    return [row for row in facts if row["text"]]


def jst_day(value: Any) -> Optional[str]:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone(timedelta(hours=9))).date().isoformat()


LEVEL_MAP_MAX_AGE_DAYS = 7   # an older morning map is not today's map
# The next session's map is fixed right after the close (about 16:10 JST), so
# in the evening and over a holiday the latest map is for a later morning.
LEVEL_MAP_MAX_AHEAD_DAYS = 10


def level_map_facts(morning: Optional[Mapping[str, Any]], *, now_iso: str) -> List[Dict[str, Any]]:
    """The latest stored morning PER level map (jp_market_level_map.morning_map).

    Lines come from ARGUS's estimated EPS, not the official value; the fact
    says so. Only the nearest map line on each side is named. The map may be
    for the next session's morning (built from the latest close); its date is
    stated.
    """
    if not isinstance(morning, Mapping):
        return []
    day, today = morning.get("morningOf"), jst_day(now_iso)
    close, eps, per = (_finite_number(morning.get(k)) for k in ("previousClose", "eps", "per"))
    if not (isinstance(day, str) and today and close and eps and per and close > 0 and eps > 0):
        return []
    try:
        age = (datetime.fromisoformat(today).date() - datetime.fromisoformat(day).date()).days
    except ValueError:
        return []
    if not -LEVEL_MAP_MAX_AHEAD_DAYS <= age <= LEVEL_MAP_MAX_AGE_DAYS:
        return []
    lines = []
    for side, label in (("UP", "上の線"), ("DOWN", "下の線")):
        rows = [r for r in morning.get("rows") or [] if isinstance(r, Mapping) and r.get("side") == side
                and _finite_number(r.get("price")) and _finite_number(r.get("distancePct")) is not None
                and _finite_number(r.get("multiple"))]
        if not rows:
            continue
        row = min(rows, key=lambda r: abs(r["distancePct"]))
        multiple = float(row["multiple"])
        shown = f"{multiple:.0f}" if multiple == int(multiple) else f"{multiple:.2f}"
        lines.append(f"{label} PER{shown}倍＝{row['price']:,.0f}円（{row['distancePct']:+.1f}%）。")
    if not lines:
        return []
    head = (f"PER水準の地図（{day}朝・ARGUS推計EPS{eps:,.2f}円で公式値ではない）: "
            f"{morning.get('previousSession') or '前日'}終値{close:,.0f}円はPER{per:.2f}倍。")
    origin = {"eventId": "level-map-" + day, "sourceLabelJa": "PER水準の地図（ARGUS推計EPS）",
              "sourceReceivedAt": morning.get("createdAt"),
              "asOf": morning.get("previousSession") if isinstance(morning.get("previousSession"), str) else None,
              "sourceRowSha256": _row_sha({k: morning.get(k) for k in
                  ("recordId", "morningOf", "previousClose", "eps", "per", "rows")})}
    text = _join_within(head, lines)
    return [_fact(text, "P1", "level_map_calculation", "UNCONFIRMED", origin)] if text and text != head else []


OVERNIGHT_FUTURES_MAX_DAYS = 4   # the same window as Today's overnight row


def overnight_futures_facts(futures: Optional[Mapping[str, Any]], *, close: Optional[float],
                            close_day: Optional[str], close_at: Optional[str],
                            tokyo_session_open: bool) -> List[Dict[str, Any]]:
    """The CME Nikkei future read outside the Tokyo session, against the close it followed.

    Mirrors Today's overnight row (web/src/lib/todayDecision.ts overnightGap):
    nothing while Tokyo is open, nothing when the future traded before that
    close or more than four days after it.
    """
    if tokyo_session_open or not isinstance(futures, Mapping) or futures.get("symbol") != "NKD=F":
        return []
    price, close = _finite_number(futures.get("price")), _finite_number(close)
    if not (price and close and price > 0 and close > 0 and isinstance(close_day, str)):
        return []
    try:
        traded = datetime.fromisoformat(str(futures.get("tradedAt")).replace("Z", "+00:00"))
        closed = datetime.fromisoformat(str(close_at).replace("Z", "+00:00"))
    except ValueError:
        return []
    if traded.tzinfo is None or closed.tzinfo is None:
        return []
    if traded <= closed or traded - closed > timedelta(days=OVERNIGHT_FUTURES_MAX_DAYS):
        return []
    gap = (price / close - 1) * 100
    local = traded.astimezone(timezone(timedelta(hours=9)))
    text = (f"日経先物（CME・遅延、{local.month}/{local.day} {local:%H:%M}時点）: {price:,.0f}。"
            f"{close_day}の日経平均{close:,.0f}円との差{gap:+.2f}%（東京の取引時間外の値）。")
    origin = {"eventId": "nikkei-cme-futures", "sourceLabelJa": "CME日経先物（Yahoo Finance・遅延）",
              "sourceReceivedAt": futures.get("receivedAt"), "asOf": futures.get("tradedAt"),
              "sourceRowSha256": _row_sha({"price": price, "tradedAt": futures.get("tradedAt"),
                                           "close": close, "closeDay": close_day})}
    return [_fact(text, "P1", "overnight_futures", "VERIFIED", origin)]


# The page's six signs (web/src/domain/marketSignals.ts, warning path): the
# closed seventh condition (D07) is left out, and a row counts as 点灯/消灯
# only under the same gates the page applies.
_SIGN_STATE_JA = {"ACTIVE": "点灯", "CLEAR": "消灯", "DATA_GATED": "判定不能", "STALE": "古い",
                  "LICENSE_BLOCKED": "要ライセンス", "NOT_APPLICABLE": "該当なし", "UNAVAILABLE": "欠測"}
_SIGN_FAMILIES = ("D01", "D02", "D03", "D04", "D05", "D06", "D07")
_SIGN_SHOWN = ("D01", "D02", "D03", "D04", "D05", "D06")


def _sign_instant(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not re.search(r"T.*(?:Z|[+-]\d{2}:\d{2})$", value):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def warning_sign_facts(projection: Optional[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Each of the six signs and its state, as the screen shows them."""
    if not isinstance(projection, Mapping):
        return []
    warning = projection.get("warningSignals")
    if not isinstance(warning, Mapping):
        return []
    adopted = warning.get("schemaVersion") == "jp-warning-conditions-v3"
    cutoff = warning.get("informationCutoff")
    limit = _sign_instant(cutoff)
    rows = warning.get("signals")
    if (limit is None or not (adopted or warning.get("schemaVersion") == "jp-warning-conditions-v2")
            or warning.get("countPredictsCrash") is not False or warning.get("actionAuthority") is not False
            or warning.get("rejectedEvidence") is not False or cutoff != projection.get("informationCutoff")
            or not isinstance(rows, list) or len(rows) != 7):
        return []
    by_family = {}
    for row in rows:
        if isinstance(row, Mapping) and row.get("family") in _SIGN_FAMILIES:
            by_family.setdefault(row["family"], []).append(row)
    if any(len(by_family.get(f, [])) != 1 for f in _SIGN_FAMILIES):
        return []
    shown = []
    for family in _SIGN_SHOWN:
        row = by_family[family][0]
        state = row.get("state") if row.get("state") in _SIGN_STATE_JA else "UNAVAILABLE"
        if family in ("D03", "D04") and (not adopted or row.get("lineage") != "ARGUS_VALIDATION_RULE") \
                and state in ("ACTIVE", "CLEAR"):
            state = "DATA_GATED"
        if row.get("ruleStatus") == "RULE_NOT_DEFINED" and state in ("ACTIVE", "CLEAR"):
            state = "DATA_GATED"
        if state in ("ACTIVE", "CLEAR"):
            known = _sign_instant(row.get("knowledgeTime"))
            if (row.get("status") != "AVAILABLE" or row.get("conditionMet") is not (state == "ACTIVE")
                    or _finite_number(row.get("value")) is None or known is None or known > limit):
                state = "DATA_GATED"
        name = row.get("nameJa") if isinstance(row.get("nameJa"), str) and row["nameJa"] else family
        shown.append((name[:20], state))
    active = sum(state == "ACTIVE" for _, state in shown)
    head = f"6サインの内訳（点灯{active}/6）: "
    text = head + "、".join(f"{name}={_SIGN_STATE_JA[state]}" for name, state in shown) + "。"
    if len(text) > FACT_TEXT_LIMIT:
        return []
    origin = {"eventId": "six-signs", "sourceLabelJa": "日本株分析エンジン・6サイン（警戒条件）",
              "asOf": cutoff, "sourceRowSha256": _row_sha(shown)}
    return [_fact(text, "P1", "market_view", "VERIFIED", origin)]


def track_record_facts(record: Optional[Mapping[str, Any]], *,
                       checked_at: Optional[str] = None) -> List[Dict[str, Any]]:
    """The direction record of the Nikkei paths ARGUS actually issued.

    Read from argus_analysis_history.track_record (the same tally as the
    chart's 「実際に出した…見通しの成績」). Frequencies of past issued paths
    against 「いつも多数派の方向」, never a statement about the next one.
    """
    if not isinstance(record, Mapping) or record.get("instrumentId") != "NIKKEI_225_INDEX":
        return []
    horizons = record.get("horizons") or {}
    parts, last = [], []
    for key in ("1", "5", "10", "20"):
        row = horizons.get(key)
        if not isinstance(row, Mapping):
            continue
        n, hits = row.get("directionalForecasts"), row.get("hits")
        if type(n) is not int or type(hits) is not int or n <= 0:
            continue
        if isinstance(row.get("lastTargetDate"), str):
            last.append(row["lastTargetDate"])
        naive = _finite_number(row.get("naiveMajorityRate"))
        if row.get("status") == "INSUFFICIENT_SAMPLE" or naive is None:
            parts.append(f"{key}日後{n}件採点・{record.get('minimumDirectionalForecasts', 20)}件未満。")
        else:
            verdict = "上回る" if row.get("status") == "ABOVE_BASELINE" else "上回らず"
            parts.append(f"{key}日後{n}件中{hits}件一致・多数派{naive * 100:.0f}%を{verdict}。")
    if not parts:
        return []
    head = "ARGUS見通しの成績（日経平均・営業日後の方向一致を常に多数派と統計比較）: "
    text = _join_within(head, parts)
    if not text or text == head:
        return []
    origin = {"eventId": "forecast-track-record", "sourceLabelJa": "ARGUSの見立ての答え合わせ",
              "sourceReceivedAt": checked_at, "asOf": max(last) if last else None,
              "sourceRowSha256": _row_sha(horizons)}
    return [_fact(text, "P1", "forecast_track_record", "UNCONFIRMED", origin)]


_PAGE_INSTANT_KEYS = ("publishedAt", "receivedAt", "observedAt")
_PAGE_EVENT_ID = re.compile(r"^[a-zA-Z0-9_.:-]{1,160}$")
_PAGE_SHA256 = re.compile(r"^[a-f0-9]{64}$")


def _page_instant(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def page_provenance(value: Mapping[str, Any]) -> Dict[str, Any]:
    """The provenance shape the page accepts, keeping every valid field as is.

    The page rejects the whole brief when one fact's provenance lacks this
    shape (2026-10-04: facts carried over from a brief stored before their
    producers were fixed). Missing or malformed fields become null; nothing
    is invented.
    """
    out = dict(value)
    out["scope"] = "published_metadata_snapshot"
    if not (out.get("eventId") is None or (isinstance(out.get("eventId"), str)
                                           and _PAGE_EVENT_ID.match(out["eventId"]))):
        out["eventId"] = None
    out.setdefault("eventId", None)
    revision = out.get("revision")
    if not (isinstance(revision, int) and not isinstance(revision, bool) and revision >= 0):
        out["revision"] = None
    label = out.get("sourceLabel", out.get("sourceLabelJa"))
    out["sourceLabel"] = label[:160] if isinstance(label, str) and label else None
    for key in _PAGE_INSTANT_KEYS:
        if not _page_instant(out.get(key)):
            out[key] = None
    for key in ("sourceResponseSha256", "sourceRowSha256"):
        if key in out and not (isinstance(out[key], str) and _PAGE_SHA256.match(out[key])):
            del out[key]
    url = out.get("url")
    if not (isinstance(url, str) and url.startswith("https://") and len(url) <= 2048 and "@" not in url.split("/")[2]):
        out["url"] = None
    return out


def headline_context(context, *, as_of):
    """Request-time comparison aids, without choosing the model's lead story.

    The source timestamps keep their meanings. A newly read old article is
    not newly published, and an updated position summary is not a new event.
    This is added only to the outgoing request, not the source-input digest.
    """
    prior = {row.get("evidenceId") for row in context.get("previousFacts", [])}
    candidates = []
    for row in context.get("facts", []):
        if row.get("priority") != "P0" or not row.get("evidenceId"):
            continue
        provenance = row.get("provenance") or {}
        candidates.append({
            "evidenceId": row["evidenceId"], "source": row.get("source"),
            "verification": row.get("verification"),
            "publishedAt": provenance.get("publishedAt"),
            "receivedAt": provenance.get("receivedAt"),
            "observedAt": provenance.get("observedAt"),
            "changedEvidenceSincePrevious": row["evidenceId"] not in prior,
        })
    return {"schemaVersion": "brief-headline-comparison-v1", "asOf": as_of,
            "previousAt": context.get("previousAt"), "candidates": candidates,
            "selectionBy": "INTEGRATED_AI", "fixedWinner": None,
            "receiptIsPublication": False, "changedEvidenceIsNewEvent": False}


def unified_context(brief: Mapping[str, Any], previous: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """Bind explanation references to the exact fact snapshot supplied to GPT.

    Public market context contains no private positions. Process memory is not
    represented as durable judgment history or a previous-day observation.
    """
    def references(document):
        rows = []
        for fact in (document or {}).get("facts", [])[:UNIFIED_FACT_LIMIT]:
            material = {key: str(fact.get(key) or "") for key in
                        ("text", "source", "priority", "verification")}
            if isinstance(fact.get("provenance"), Mapping):
                # Composer already selected a bounded public metadata snapshot.
                material["provenance"] = page_provenance(fact["provenance"])
            if isinstance(fact.get("validationSubject"), Mapping):
                material["validationSubject"] = dict(fact["validationSubject"])
            if (fact.get("source") == "calendar" and isinstance(fact.get("eventLabelJa"), str)
                    and fact["eventLabelJa"][:-1] in material["text"]):
                material["eventLabelJa"] = fact["eventLabelJa"]
            if material["source"] in {"market_view", "policy"} or material["priority"] == "P2":
                material["verification"] = "UNCONFIRMED"
            identity = hashlib.sha256(json.dumps(material, ensure_ascii=False,
                sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            rows.append({"evidenceId": "brief-fact-" + identity, **material})
        # 2026-11-18: the same material twice has one identity; a repeated
        # reference made the presentation check refuse the whole explanation.
        # The copy carries nothing new, so the first one is kept.
        seen = set()
        return [row for row in rows
                if not (row["evidenceId"] in seen or seen.add(row["evidenceId"]))]
    current, prior = references(brief), references(previous)
    current_ids, prior_ids = {r["evidenceId"] for r in current}, {r["evidenceId"] for r in prior}
    body = {"schemaVersion": "argus-unified-brief-context-v1", "scope": "PUBLIC_MARKET",
            "facts": current, "previousFacts": prior,
            "previousAt": (previous or {}).get("generatedAt"),
            "changes": {"comparisonAvailable": bool(prior),
                        "addedEvidenceIds": sorted(current_ids - prior_ids) if prior else [],
                        "removedEvidenceIds": sorted(prior_ids - current_ids) if prior else []},
            "ownerContextAvailable": False, "historyStatus": "PROCESS_MEMORY_ONLY",
            "sourceTraceScope": "exact_brief_fact_and_available_public_metadata",
            "actionAuthority": False}
    # Prior interpretation is context, never a newly received source fact.
    body["priorAssessments"] = [
        {"themeId": row["themeId"], "assessment": dict(row["view"])}
        for row in (brief.get("marketPosition") or {}).get("themes", [])
        if row.get("themeId") and isinstance(row.get("view"), Mapping)]
    if isinstance(brief.get("numericalResearch"), Mapping):
        body["researchPackages"] = argus_jp_market_research.context_references(brief["numericalResearch"])
    if isinstance(brief.get("fiscalEnvironment"), Mapping):
        body["fiscalEnvironment"] = dict(brief["fiscalEnvironment"])
    if isinstance(brief.get("creditConditions"), Mapping):
        body["creditConditions"] = {k: brief["creditConditions"][k] for k in
            ("schemaVersion", "snapshotId", "dimensions", "overallState", "actionAuthority") if k in brief["creditConditions"]}
    body["contextId"] = hashlib.sha256(json.dumps(body, ensure_ascii=False,
        sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return body
