"""ARGUS V11.5.4 — Maximum Available Source Sweep (pure, deterministic, stdlib-only).

The owner's directive: go as far as the PUBLIC web allows — official documents,
public article bodies, metadata, search, RSS/sitemap, schema.org, canonical, AMP,
IR pages, regulator releases, and sibling outlets. Never decide "this is enough".
When a source blocks us (403 / login / subscription), we do NOT bypass it — we
record it as blocked and immediately chase alternatives (official disclosure,
other reputable outlets, primary documents).

This module is the PURE half: HTML metadata extraction, block detection, item
classification, sweep-result assembly. The scanner owns all fetching and passes
raw bytes/records in. Nothing here stores full article text — extraction returns
title / publishedAt / snippet (<=240 chars) / facts only.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Dict, List, Optional

import argus_caos_source_universe as SU
import argus_news_freshness as NF

SCHEMA_VERSION = "caos-source-sweep-v1"

SNIPPET_MAX = 240          # hard cap — we keep extracts, never bodies

# ── block detection ──────────────────────────────────────────────────────────
# Paywall/regwall markers (public-page heuristics; JP + EN). A match on a page
# that also lacks a readable article body means: blocked → chase alternatives.
_PAYWALL_MARKERS = (
    "有料会員", "会員限定", "この記事は会員", "無料会員登録", "残り", "続きを読むには",
    "ログインして", "会員の方はログイン",
    "subscribe to read", "subscription required", "subscribe now to read",
    "sign in to read", "log in to continue", "register to continue",
    "this article is for subscribers", "premium subscribers only",
)
_LOGIN_MARKERS = ("ログインが必要", "sign in required", "please log in", "login required")


def detect_block(status_code: Optional[int], html: str = "",
                 is_accessible_flag: Optional[bool] = None) -> str:
    """ok | forbidden | login_required | subscription_required | not_found |
    unreachable. isAccessibleForFree=false (schema.org) is an explicit publisher
    signal and wins over marker heuristics."""
    if status_code is None:
        return "unreachable"
    if status_code == 404:
        return "not_found"
    if status_code in (401, 407):
        return "login_required"
    if status_code in (402,):
        return "subscription_required"
    if status_code == 403:
        return "forbidden"
    if status_code >= 500:
        return "unreachable"
    if is_accessible_flag is False:
        return "subscription_required"
    low = (html or "")[:200_000].lower()
    if any(m in low for m in _LOGIN_MARKERS):
        return "login_required"
    if any(m.lower() in low for m in _PAYWALL_MARKERS):
        return "subscription_required"
    return "ok"


# ── article metadata extraction (schema.org / OpenGraph / canonical / AMP) ───
_META_RE = re.compile(
    r'<meta[^>]+(?:property|name)=["\']([^"\']+)["\'][^>]+content=["\']([^"\']*)["\']',
    re.IGNORECASE)
_META_RE_REV = re.compile(
    r'<meta[^>]+content=["\']([^"\']*)["\'][^>]+(?:property|name)=["\']([^"\']+)["\']',
    re.IGNORECASE)
_LINK_RE = re.compile(
    r'<link[^>]+rel=["\']([^"\']+)["\'][^>]+href=["\']([^"\']+)["\']', re.IGNORECASE)
_TITLE_RE = re.compile(r"<title[^>]*>([^<]{1,300})</title>", re.IGNORECASE)
_JSONLD_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")


def _jsonld_articles(html: str) -> List[Dict[str, Any]]:
    out = []
    for m in _JSONLD_RE.finditer(html or ""):
        try:
            data = json.loads(m.group(1).strip())
        except Exception:
            continue
        nodes = data if isinstance(data, list) else \
            data.get("@graph", [data]) if isinstance(data, dict) else []
        for n in nodes:
            if isinstance(n, dict) and str(n.get("@type", "")).endswith(
                    ("Article", "NewsArticle", "ReportageNewsArticle")):
                out.append(n)
    return out


def extract_article_metadata(html: str, url: str = "") -> Dict[str, Any]:
    """Public-page metadata: title / publishedAt / snippet / canonical / AMP /
    publisher / isAccessibleForFree. Never returns body text — snippet <= 240."""
    html = (html or "")[:400_000]
    metas: Dict[str, str] = {}
    for m in _META_RE.finditer(html):
        metas.setdefault(m.group(1).lower(), m.group(2))
    for m in _META_RE_REV.finditer(html):
        metas.setdefault(m.group(2).lower(), m.group(1))
    links: Dict[str, str] = {}
    for m in _LINK_RE.finditer(html):
        links.setdefault(m.group(1).lower(), m.group(2))
    title = metas.get("og:title") or ""
    if not title:
        tm = _TITLE_RE.search(html)
        title = tm.group(1).strip() if tm else ""
    published = (metas.get("article:published_time")
                 or metas.get("og:article:published_time")
                 or metas.get("article:modified_time") or "")
    desc = metas.get("og:description") or metas.get("description") or ""
    publisher = metas.get("og:site_name") or ""
    accessible: Optional[bool] = None
    for art in _jsonld_articles(html):
        title = title or str(art.get("headline") or "")
        published = published or str(art.get("datePublished") or "")
        desc = desc or str(art.get("description") or "")
        if not publisher and isinstance(art.get("publisher"), dict):
            publisher = str(art["publisher"].get("name") or "")
        flag = art.get("isAccessibleForFree")
        if flag is not None:
            accessible = str(flag).lower() not in ("false", "0", "no")
    return {
        "title": _TAG_RE.sub("", title)[:200].strip(),
        "publishedAt": published[:40],
        "snippet": _TAG_RE.sub("", desc)[:SNIPPET_MAX].strip(),
        "canonicalUrl": links.get("canonical") or url,
        "ampUrl": links.get("amphtml") or "",
        "publisher": publisher[:60],
        "isAccessibleForFree": accessible,
    }


def headline_keywords(title: str, max_terms: int = 5) -> List[str]:
    """Significant terms from a headline for alternative-source chasing (drop
    stop-ish words; keep names/numbers/CJK chunks)."""
    s = re.sub(r"\s[-–—]\s[^-–—]{2,40}\s*$", "", str(title or ""))   # strip " - Publisher"
    toks = re.findall(r"[A-Za-z0-9%$¥.]{3,}|[぀-ヿ㐀-䶵一-鿋ーァ-ヶ]{2,}", s)
    stop = {"the", "and", "for", "with", "after", "into", "over", "from", "says",
            "stock", "stocks", "news", "shares", "こと", "ため", "など", "について"}
    out = []
    for t in toks:
        tl = t.lower()
        if tl in stop or tl in out:
            continue
        out.append(t)
        if len(out) >= max_terms:
            break
    return out


# ── item classification / assembly ───────────────────────────────────────────
_OFFICIAL_TIERS = {"official_regulatory", "official_corporate",
                   "central_bank_or_government", "exchange_or_listing_venue"}
_PROFESSIONAL_TIERS = {"wire_service", "reputable_financial_media",
                       "specialist_industry_media", "market_data_provider"}


def classify_item(item: Dict[str, Any], now_iso: str) -> Dict[str, Any]:
    """Resolve publisher + freshness for one found item (metadata only)."""
    title = str(item.get("title") or item.get("headline") or "")
    pub = SU.resolve_publisher(title, str(item.get("source") or item.get("sourceId") or ""),
                               str(item.get("url") or item.get("canonicalUrl") or ""))
    fr = NF.classify(item.get("publishedAt") or item.get("datetime"), now_iso)
    return {
        "title": title[:200],
        "url": str(item.get("url") or item.get("canonicalUrl") or "")[:300],
        "publishedAt": str(item.get("publishedAt") or "")[:40],
        "snippet": str(item.get("snippet") or "")[:SNIPPET_MAX],
        "sourceFamily": pub["sourceFamily"], "sourceTier": pub["sourceTier"],
        "truePublisher": pub["truePublisher"], "weakSignal": pub["weakSignal"],
        "isDiscoveryLayer": pub["isDiscoveryLayer"],
        "freshness": fr["freshness"], "ageHours": fr["ageHours"],
        "eligibleAsPrimaryLead": fr["eligibleAsPrimaryLead"] and not pub["weakSignal"],
    }


def sweep_id(symbol: str, now_iso: str) -> str:
    return "sweep-" + hashlib.md5(f"{symbol}|{now_iso}".encode()).hexdigest()[:10]


def build_sweep_result(*, symbol: str, market: str, asset_class: str, now_iso: str,
                       searched_sources: List[str], found_items: List[Dict[str, Any]],
                       blocked_sources: List[Dict[str, Any]],
                       alternative_sources_checked: List[str],
                       status: str = "completed", elapsed_ms: int = 0,
                       limitations: Optional[List[str]] = None) -> Dict[str, Any]:
    """Assemble the audit-ready sweep result. found_items are RAW dicts; this
    classifies them (publisher + freshness), splits official/professional/public-
    text/fresh, and states explicitly what was NOT found. No full text anywhere."""
    classified = [classify_item(i, now_iso) for i in found_items or []]
    # de-dup by title hash (syndicated copies collapse)
    seen, items = set(), []
    for c in classified:
        h = hashlib.md5(c["title"].encode()).hexdigest()[:12]
        if not c["title"] or h in seen:
            continue
        seen.add(h)
        items.append(c)
    # v11.5.6 owner rule: every displayed news list is newest-first (unknown-time
    # items sink to the bottom — they must never sit above dated fresh items)
    items.sort(key=lambda c: (c["ageHours"] is None, c["ageHours"] or 0.0))
    fresh = [c for c in items if c["freshness"] in ("fresh", "recent")]
    official = [c for c in items if c["sourceTier"] in _OFFICIAL_TIERS]
    professional = [c for c in items if c["sourceTier"] in _PROFESSIONAL_TIERS]
    public_text = [c for c in items if c.get("snippet")]
    not_found: List[str] = []
    if not fresh:
        not_found.append("直近24時間以内の新規材料は見つからなかった")
    if not official:
        not_found.append("本日の公式開示・規制当局発表は確認できなかった")
    best = ""
    for c in fresh:
        if c["eligibleAsPrimaryLead"]:
            best = c["title"]
            break
    return {
        "schemaVersion": SCHEMA_VERSION,
        "sweepId": sweep_id(symbol, now_iso),
        "symbol": symbol, "market": market, "assetClass": asset_class,
        "asOf": now_iso, "status": status,
        "searchedSources": searched_sources[:40],
        "foundItems": items[:20],
        "freshItems": fresh[:10],
        "officialItems": official[:10],
        "professionalItems": professional[:10],
        "publicTextItems": public_text[:10],
        "blockedSources": blocked_sources[:10],
        "alternativeSourcesChecked": alternative_sources_checked[:15],
        "notFoundJa": not_found,
        "latestFreshLeadJa": best[:160],
        "limitationsJa": (limitations or []) + (
            ["ログイン/有料壁は突破しない(blockedとして記録し代替ソースを追跡)"]),
        "elapsedMs": int(elapsed_ms),
    }
