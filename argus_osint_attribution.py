"""ARGUS V12.0.8 — OSINT / Catalyst Attribution Review (pure, deterministic).

「浜松ホトニクスの下落にSamsung/Anthropic系AI半導体バリューチェーン懸念が絡んで
いたかもしれないのに、ARGUSは無関係/古いニュースを出した」(オーナー報告)への
根治レイヤー。値動きの候補原因を 直接材料 / セクター・テーマ連想 / バリュー
チェーン / マクロ / 古い背景 / 不明 に分離し、鮮度・ソース多様性から OSINT確度
(high/medium/low/unknown)と「この推定が外れている可能性」(whyWrongJa)を必ず付ける。

HARD RULES:
  - 14日超の記事は絶対に主要因(primary)にしない。
  - 主要因候補は原則3営業日(近似96h)以内。当日再報道(fetchedAtが当日)は例外で許可。
  - publishedAt欠落は firstDetectedAt→fetchedAt でフォールバック。全て欠落なら
    primary不可(カテゴリはstale_background/unknown側)。
  - 弱いテーマ連想を事実として書かない — 必ず「〜の候補」「テーマ連想」と明示。
  - ソース・日付を捏造しない(与えられた候補のメタデータのみ使用)。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import argus_news_freshness

SCHEMA_VERSION = "osint-attribution-v1"

CATEGORIES = ("direct_official", "direct_news", "value_chain", "sector_theme",
              "macro", "stale_background", "unknown")
CATEGORY_JA = {
    "direct_official": "直接材料(公式開示)",
    "direct_news": "直接材料(報道)",
    "value_chain": "バリューチェーン(顧客/供給網)",
    "sector_theme": "セクター/テーマ連想",
    "macro": "マクロ/イベント",
    "stale_background": "古い背景材料",
    "unknown": "不明",
}
CONFIDENCES = ("high", "medium", "low", "unknown")
CONFIDENCE_JA = {"high": "高", "medium": "中", "low": "低", "unknown": "不明"}

SOURCE_CLASSES = ("official", "credible_news", "aggregator", "price_confirmation", "unknown")

_OFFICIAL_SOURCES = ("tdnet", "official", "edinet", "sec_edgar", "bls", "bea")
_CREDIBLE_SOURCES = ("nikkei", "reuters", "nhk", "bloomberg", "cnbc", "wsj",
                     "coindesk", "cointelegraph", "kabutan", "finnhub")
_AGGREGATOR_SOURCES = ("google_news", "googlenews", "rss", "yahoo")

_MACRO_WORDS = ("CPI", "FOMC", "雇用統計", "NFP", "金利", "国債入札", "日銀", "PCE",
                "GDP", "利下げ", "利上げ", "為替介入")

PRIMARY_MAX_AGE_H = 96.0          # ≈3営業日の近似(週末を跨ぐ場合は再報道例外で救済)
STALE_AGE_H = 14 * 24.0           # これ超えは絶対にprimary不可


def _source_class(source: str) -> str:
    s = (source or "").lower()
    if any(k in s for k in _OFFICIAL_SOURCES):
        return "official"
    if any(k in s for k in _CREDIBLE_SOURCES):
        return "credible_news"
    if any(k in s for k in _AGGREGATOR_SOURCES):
        return "aggregator"
    return "unknown"


def _age_hours(c: Dict[str, Any], now_iso: str) -> Optional[float]:
    return argus_news_freshness.age_hours(
        c.get("publishedAt") or c.get("firstDetectedAt") or c.get("fetchedAt"), now_iso)


def _refetched_today(c: Dict[str, Any], now_iso: str) -> bool:
    f = argus_news_freshness.age_hours(c.get("fetchedAt"), now_iso)
    return f is not None and f <= 24.0


def _category(c: Dict[str, Any], company_names: List[str], theme_words: List[str],
              age_h: Optional[float]) -> str:
    title = str(c.get("titleJa") or c.get("titleOriginal") or c.get("title") or "")
    src_cls = _source_class(str(c.get("source") or c.get("sourceId") or ""))
    if age_h is not None and age_h > STALE_AGE_H:
        return "stale_background"
    named = any(n and n in title for n in company_names)
    if named and src_cls == "official":
        return "direct_official"
    if named:
        return "direct_news"
    if c.get("valueChainRelation"):          # 明示タグがある時だけ(推測で付けない)
        return "value_chain"
    if any(w in title for w in _MACRO_WORDS):
        return "macro"
    if any(w and w in title for w in theme_words):
        return "sector_theme"
    return "unknown"


def _why_wrong_ja(cat: str, symbol_names: List[str]) -> str:
    name = symbol_names[0] if symbol_names else "この銘柄"
    return {
        "direct_official": "公式開示でも、値動きの主因が別(地合い/需給)の可能性は残る。",
        "direct_news": "単一報道の場合、誤報・旧材料の再掲・織り込み済みの可能性がある。",
        "value_chain": f"{name}への影響度は未実証 — 取引関係の規模次第で無関係の可能性。",
        "sector_theme": f"{name}固有の開示・報道は見つかっていない — セクター/テーマ連想であり直接材料ではない。",
        "macro": "個別材料ではなく市場全体要因 — 銘柄固有の説明にはならない可能性。",
        "stale_background": "古い記事 — 当日の値動きの主因にはならない(背景参考のみ)。",
        "unknown": "裏付けソースがない — 原因不明として扱うのが正直。",
    }[cat]


def _primary_eligible(cat: str, age_h: Optional[float], refetched: bool) -> bool:
    if cat in ("stale_background", "unknown"):
        return False
    if age_h is None:
        return False                          # 日付不明はprimary不可
    if age_h > STALE_AGE_H:
        return False
    if age_h > PRIMARY_MAX_AGE_H and not refetched:
        return False
    return True


def _confidence(fresh_count: int, has_official_or_credible: bool,
                sector_confirm: bool, cat: str) -> str:
    if cat in ("stale_background", "unknown"):
        return "unknown"
    if fresh_count >= 2 and sector_confirm:
        return "high"
    if fresh_count >= 1 and has_official_or_credible:
        return "medium"
    if cat in ("sector_theme", "value_chain", "macro"):
        return "low"
    return "low"


def review(symbol: str, market: str, change_pct: Optional[float],
           candidates: List[Dict[str, Any]], *,
           company_names: Optional[List[str]] = None,
           theme_words: Optional[List[str]] = None,
           sector_confirm: bool = False,
           now_iso: str = "") -> Dict[str, Any]:
    """candidates: [{titleJa/titleOriginal/title, source|sourceId, publishedAt,
    firstDetectedAt, fetchedAt, url?, valueChainRelation?}] — 与えられたメタデータ
    のみで判定(fetchなし・捏造なし)。"""
    names = [n for n in (company_names or []) if n]
    themes = [t for t in (theme_words or []) if t]
    rank_order = {"direct_official": 0, "direct_news": 1, "value_chain": 2,
                  "sector_theme": 3, "macro": 4, "unknown": 5, "stale_background": 6}
    rows = []
    for c in (candidates or [])[:12]:
        age_h = _age_hours(c, now_iso)
        cat = _category(c, names, themes, age_h)
        refetched = _refetched_today(c, now_iso)
        eligible = _primary_eligible(cat, age_h, refetched)
        rows.append({
            "titleJa": str(c.get("titleJa") or c.get("titleOriginal") or c.get("title") or "")[:160],
            "source": str(c.get("source") or c.get("sourceId") or "")[:40],
            "sourceClass": _source_class(str(c.get("source") or c.get("sourceId") or "")),
            "publishedAt": c.get("publishedAt"),
            "ageHours": round(age_h, 1) if age_h is not None else None,
            "category": cat, "categoryJa": CATEGORY_JA[cat],
            "primaryEligible": eligible,
            "refetchedToday": refetched,
            "whyWrongJa": _why_wrong_ja(cat, names),
        })
    rows.sort(key=lambda r: (rank_order.get(r["category"], 9),
                             r["ageHours"] if r["ageHours"] is not None else 9e9))
    for i, r in enumerate(rows, 1):
        r["rank"] = i

    eligible_rows = [r for r in rows if r["primaryEligible"]]
    fresh_count = len({(r["sourceClass"], r["source"]) for r in eligible_rows})
    has_strong = any(r["sourceClass"] in ("official", "credible_news") for r in eligible_rows)
    primary = eligible_rows[0] if eligible_rows else None
    conf = _confidence(fresh_count, has_strong, bool(sector_confirm),
                       primary["category"] if primary else "unknown")

    if primary is None:
        headline = "原因不明(裏付けソースなし) — 憶測で断定しません。"
    elif primary["category"] in ("sector_theme", "value_chain"):
        headline = f"{CATEGORY_JA[primary['category']]}の候補: {primary['titleJa']}(直接材料ではなくテーマ連想)"
    elif primary["category"] == "macro":
        headline = f"マクロ要因の候補: {primary['titleJa']}"
    else:
        headline = f"候補原因: {primary['titleJa']}"

    return {
        "schemaVersion": SCHEMA_VERSION,
        "symbol": str(symbol).upper(), "market": str(market).upper(),
        "changePct": change_pct,
        "causes": rows[:8],
        "primary": primary,
        "osintConfidence": conf, "osintConfidenceJa": CONFIDENCE_JA[conf],
        "headlineJa": headline,
        "sourcesMissingJa": ([] if any(r["sourceClass"] == "official" for r in rows)
                             else ["公式開示(TDnet/EDINET)での裏付けは未確認"]),
        "sectorConfirm": bool(sector_confirm),
        "complianceNote": "候補原因の分類であり事実の断定ではない。売買指示ではない。",
    }
