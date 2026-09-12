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
import math
import hashlib
import json
from datetime import datetime
from urllib.parse import urlsplit
from typing import Any, Dict, List, Mapping, Optional, Sequence

BRIEF_SCHEMA = "argus-market-brief-v1"
BRIEF_FACT_LIMIT = 16
UNIFIED_FACT_LIMIT = 20
PRIORITIES = ("P0", "P1", "P2", "P3")
VERIFICATIONS = ("VERIFIED", "CORROBORATED", "UNCONFIRMED")

_DIRECTION_JA = {"BULLISH": "強気", "BEARISH": "弱気", "MIXED": "強弱混在",
                 "UNCLEAR": "方向未確定"}
_IMPACT_JA = {"critical": "最重要", "high": "重要", "medium": "中", "low": "小"}

# Vocabulary the composer AND the AI polish must never emit (RC discipline:
# no execution orders, no invented probabilities/targets).
_FORBIDDEN_BRIEF_PATTERNS = (
    "買え", "売れ", "全力", "今すぐ買", "今すぐ売", "確実に", "必ず",
    "暴騰確率", "上昇確率", "%の確率", "％の確率",
)


def _digits_of(text: str) -> set:
    # Formatting an existing value with thousands separators does not invent
    # a new number. Only correctly grouped numeric tokens are normalized.
    value = re.sub(r"(?<![\d,])\d{1,3}(?:,\d{3})+(?:\.\d+)?(?![\d,])",
                   lambda match: match.group(0).replace(",", ""), str(text or ""))
    return set(re.findall(r"\d+(?:\.\d+)?", value))


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
    return row


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
            f"買残変化の寄与{change['longContribution']:+.4f}、売残変化の寄与{change['shortContribution']:+.4f}。"
            "実際の買い戻し注文は未観測。買いサインではない。",
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
        f"差引{current['netContracts']:+}枚。前週差は買{change['longContracts']:+}・売{change['shortContracts']:+}枚。"
        "現在の建玉は未観測。買い越しでも売り建玉は残る。",
        "P1", "official_weekly_position", "UNCONFIRMED" if failed or document["status"] == "STALE" else "VERIFIED", origin)]


def compose_brief(*, now_iso: str,
                  market_view_summary: Optional[Mapping[str, Any]] = None,
                  margin_dynamics: Optional[Mapping[str, Any]] = None,
                  jpy_position: Optional[Mapping[str, Any]] = None,
                  shock_events: Sequence[Mapping[str, Any]] = (),
                  news_events: Sequence[Mapping[str, Any]] = (),
                  imminent_events: Sequence[Mapping[str, Any]] = (),
                  next_events: Sequence[Mapping[str, Any]] = (),
                  ) -> Dict[str, Any]:
    """Deterministic NOW/WHY/NEXT + chips + prioritized fact list.

    All inputs are already-verified ARGUS stores (Market Truth, trusted mail,
    official sensors, calendar). Missing inputs produce honest omissions,
    never invented content. Works fully without any AI."""
    facts: List[Dict[str, str]] = []

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
            f"{headline[:60]}"
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
            f"（{event.get('countdown') or '近日'}"
            f"{'・' + impact if impact else ''}）",
            "P0", "calendar", "VERIFIED", event))

    # ── P1: 現在の相場方向 ──
    view_label = str((market_view_summary or {}).get("label") or "").strip()
    if view_label:
        facts.append(_fact(f"市場観（検証前の参考）: {view_label[:70]}",
                           "P1", "market_view", "VERIFIED"))
    news_line = _news_direction_summary(material_news or news_events)
    facts.append(_fact(f"ニュース方向: {news_line}", "P1",
                       "trusted_mail", "CORROBORATED"
                       if any(e.get("confirmationState") == "MARKET_CONFIRMED"
                              for e in material_news) else "UNCONFIRMED"))

    facts.extend(_margin_facts(margin_dynamics))
    facts.extend(_jpy_position_facts(jpy_position))

    # ── P2: なぜそうなっているか ──
    for event in material_news[:2]:
        path = ((event.get("impactDirection") or {}).get("transmissionJa")
                or (event.get("impactDirection") or {}).get("transmission"))
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
            f"（{event.get('countdown') or event.get('whenJa') or '予定'}）",
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
    now_line = ("。".join(t.split("（")[0] for t in p0_texts[:2])
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
        "chart": view_label[:40] or "市場観 取得中（検証前・参考）",
        "news": news_line,
        "nextEvent": (f"{str(nearest.get('title') or '')[:26]}"
                      f" · {nearest.get('countdown') or '近日'}"
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


UNIFIED_SECTIONS = ("view", "reasons", "changes", "impact", "next", "invalidation")


def calculation_identity(calculations):
    """Ignore read timestamps, retaining price/input/definition changes."""
    def stable(value):
        if isinstance(value, Mapping):
            return {key: stable(item) for key, item in value.items()
                    if key not in {"informationCutoff", "lastSuccessfulAcquisitionAt"}}
        if isinstance(value, list):
            return [stable(item) for item in value]
        return value
    return hashlib.sha256(json.dumps(stable(calculations), sort_keys=True,
        separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def calculation_facts(calculations):
    """Explain each saved horizon using engine values, without probability claims."""
    facts = []
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
        facts.append(_fact(f"日経平均・{chart['anchorDate']}基準の{horizon}営業日先: "
            f"{unit}の参考計算値{value:.2f}。現在は過去の価格形状による部分比較で、有効性は未検証。"
            "他の期間の見立てと合算せず、確定した未来とは扱わない。",
            "P2", "price_path_calculation", "UNCONFIRMED", {
                "eventId": f"n225-price-path-{horizon}", "asOf": chart["anchorDate"],
                "sourceLabelJa": "日本株分析エンジン・価格経路計算",
                "sourceReceivedAt": result.get("lastSuccessfulAcquisitionAt"),
                "sourceRowSha256": identity}))
    return facts


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
                material["provenance"] = dict(fact["provenance"])
            if material["source"] in {"market_view", "policy"} or material["priority"] == "P2":
                material["verification"] = "UNCONFIRMED"
            identity = hashlib.sha256(json.dumps(material, ensure_ascii=False,
                sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            rows.append({"evidenceId": "brief-fact-" + identity, **material})
        return rows
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
    body["contextId"] = hashlib.sha256(json.dumps(body, ensure_ascii=False,
        sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return body


def validate_unified_ai(value: Any, context: Mapping[str, Any], *, diagnostic=None) -> Optional[Dict[str, Any]]:
    """Reject unsupported numbers, references and claims of observed inference.

    This is a structural constraint, not proof that every sentence is correct.
    Source inspection and semantic evaluation remain required before acceptance.
    """
    def rejected(reason, section=None):
        if isinstance(diagnostic, dict):
            diagnostic.update(status="REJECTED", reason=reason, section=section)
        return None
    if not isinstance(value, Mapping) or set(value) != set(UNIFIED_SECTIONS):
        return rejected("six_section_schema_required")
    current = {r["evidenceId"]: r for r in context.get("facts", [])}
    prior = {r["evidenceId"]: r for r in context.get("previousFacts", [])}
    sections = {}
    for key in UNIFIED_SECTIONS:
        row = value[key]
        if not isinstance(row, Mapping) or set(row) != {"textJa", "evidenceIds", "kind"}:
            return rejected("section_schema_invalid", key)
        text, refs, kind = row["textJa"], row["evidenceIds"], row["kind"]
        if not isinstance(text, str) or not text.strip() or len(text) > 240 or \
                kind not in {"FACT", "INFERENCE", "UNKNOWN"} or \
                not isinstance(refs, list) or len(refs) > 6 or \
                any(not isinstance(ref, str) for ref in refs) or len(set(refs)) != len(refs):
            return rejected("section_field_invalid", key)
        allowed = {**prior, **current} if key == "changes" else current
        if any(ref not in allowed for ref in refs):
            return rejected("unknown_evidence_reference", key)
        if kind != "UNKNOWN" and not refs:
            return rejected("evidence_reference_required", key)
        if key == "impact" and not context.get("ownerContextAvailable") and kind != "UNKNOWN":
            return rejected("owner_context_unavailable", key)
        if key == "changes" and not context.get("changes", {}).get("comparisonAvailable") and kind != "UNKNOWN":
            return rejected("previous_context_unavailable", key)
        if kind == "FACT" and (key in {"view", "impact", "next", "invalidation"} or
                any(allowed[ref].get("verification") != "VERIFIED" for ref in refs)):
            return rejected("fact_requires_verified_references", key)
        if any(p in text for p in _FORBIDDEN_BRIEF_PATTERNS) or "確率" in text:
            return rejected("unsupported_authority_or_probability", key)
        allowed_digits = set().union(*(_digits_of(allowed[ref]["text"]) for ref in refs)) if refs else set()
        unsupported = _digits_of(text) - allowed_digits
        if unsupported:
            result = rejected("unsupported_numeric_tokens", key)
            if isinstance(diagnostic, dict):
                diagnostic["unsupportedNumericTokens"] = sorted(unsupported)[:20]
            return result
        if key == "impact" and not context.get("ownerContextAvailable"):
            text = "この市場全体の説明には保有情報を含めていません。銘柄ごとの保有状況と合わせた影響は未確認です。"
        if key == "changes" and not context.get("changes", {}).get("comparisonAvailable"):
            text = "比較できる前回の見立てをまだ取得していません。"
        sections[key] = {"textJa": text.strip(), "evidenceIds": list(refs), "kind": kind}
    if isinstance(diagnostic, dict):
        diagnostic.update(status="ACCEPTED", reason=None, section=None)
    return {"schemaVersion": "argus-unified-brief-v1", "contextId": context["contextId"],
            "sections": sections, "actionAuthority": False,
            "ownerContextAvailable": context["ownerContextAvailable"],
            "historyStatus": context["historyStatus"]}
