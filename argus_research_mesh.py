"""ARGUS — Institutional Intelligence + Multi-Source Research Mesh (pure core, v1).

Phase-1 deterministic engine for the research desk: source-rights enforcement,
institution watchlist + entity resolution, IntelligenceItem normalization, story
clustering / syndication dedup, report intelligence (both sides preserved),
targeted query generation, causal-role linkage, and a Narrative Integrity Gate.

Hard epistemic + safety rules (mirrors argus_attribution / argus_research):
  * A NAMED institutional VIEW is never a named TRADING POSITION (categories A–E).
  * FINRA short-sale VOLUME is never short INTEREST.
  * Two outlets repeating one wire are ONE origin, not two confirmations.
  * An item published AFTER the move is never the immediate trigger.
  * Access class is enforced — content the policy forbids is never stored/sent to
    an LLM/displayed.
  * No trade instruction, ever. Decision-support only.
Stdlib-only; no network, no LLM, no secrets.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, List, Optional

SCHEMA = "research-mesh-v1"
CALIB = "uncalibrated_heuristic_v1"

# Feature name (owner-confirmed 2026-06-25). C.A.O.S. = the research desk that turns
# the CHAOS of scattered, repeated, contradictory market chatter into one ordered view.
SYSTEM_NAME = "C.A.O.S."
SYSTEM_NAME_FULL = "Corroborated Analyst & Official Signals"
SYSTEM_TAGLINE_JA = "情報のカオスを、ひとつのARGUSビューへ。"

# ── §2 the five categories ARGUS must never conflate ─────────────────────────
CATEGORIES = {
    "INSTITUTIONAL_RESEARCH_VIEW": "発表された見解(分析・戦略)",
    "ANALYST_ACTION": "格上げ/格下げ/目標株価/予想変更",
    "DISCLOSED_POSITION": "規制開示の保有・空売り・インサイダー",
    "FAST_MARKET_FLOW": "価格・出来高・大口フロー・相対弱さ",
    "PROPRIETARY_TRADING": "機関自身の自己売買(=A/Bからは推論しない)",
}

# ── §4 / §24 access classes + Source Rights Registry ─────────────────────────
ACCESS_CLASSES = {
    "PUBLIC_FULLTEXT", "PUBLIC_METADATA", "SUBSCRIBER_CAPTURE",
    "LICENSED_AI", "LICENSED_DISPLAY", "LINK_ONLY", "UNAVAILABLE",
}

# canStoreFullText / canSendToLLM / canDisplayExcerpt / canRetain per access class.
_CLASS_POLICY = {
    "PUBLIC_FULLTEXT":    {"fulltext": True,  "llm": True,  "excerpt": True,  "retain": True},
    "PUBLIC_METADATA":    {"fulltext": False, "llm": True,  "excerpt": True,  "retain": True},
    "SUBSCRIBER_CAPTURE": {"fulltext": False, "llm": True,  "excerpt": True,  "retain": True},
    "LICENSED_AI":        {"fulltext": True,  "llm": True,  "excerpt": True,  "retain": True},
    "LICENSED_DISPLAY":   {"fulltext": False, "llm": False, "excerpt": True,  "retain": True},
    "LINK_ONLY":          {"fulltext": False, "llm": False, "excerpt": False, "retain": True},
    "UNAVAILABLE":        {"fulltext": False, "llm": False, "excerpt": False, "retain": False},
}

# Default registry. `collection` = how a source is actually ingested:
#   rss          → an active, runtime-validated public RSS feed (LAYER 2)
#   owner_capture→ rights-only entry; reached when the owner Shares an article
#                  (no usable free public RSS — Bloomberg/FT/WSJ killed theirs)
#   official     → official/regulator source (RSS or filing pull)
#   licensed     → DISABLED + UNAVAILABLE until a signed contract + credentials
# A source is NEVER left as a dead 0-item RSS entry: only validated feeds carry
# collection="rss"; everything else is honestly labelled capture/official/licensed.
SOURCE_RIGHTS: Dict[str, Dict[str, Any]] = {
    # ── LAYER 2 active public RSS (validated: HTTP 200 + items, UA argus-research) ──
    "bloomberg_public":     {"accessClass": "PUBLIC_METADATA", "kind": "news", "licenceStatus": "public", "collection": "rss", "notes": "Bloomberg EN public RSS (markets/economics/technology)"},
    "bloomberg_jp":         {"accessClass": "PUBLIC_METADATA", "kind": "news", "licenceStatus": "public", "collection": "rss", "language": "ja", "notes": "Bloomberg 日本語版 official news sitemap (robots-declared public metadata)"},
    "nikkei_web":           {"accessClass": "PUBLIC_METADATA", "kind": "news", "licenceStatus": "public", "collection": "rss", "language": "ja", "notes": "日経 web headlines (metadata only, links back to nikkei.com; via a public 3rd-party RSS aggregator — Nikkei has no official public RSS)"},
    "cnbc_public":          {"accessClass": "PUBLIC_METADATA", "kind": "news", "licenceStatus": "public", "collection": "rss"},
    "marketwatch_public":   {"accessClass": "PUBLIC_METADATA", "kind": "news", "licenceStatus": "public", "collection": "rss"},
    "nasdaq_public":        {"accessClass": "PUBLIC_METADATA", "kind": "news", "licenceStatus": "public", "collection": "rss"},
    "yahoo_finance_public": {"accessClass": "PUBLIC_METADATA", "kind": "news", "licenceStatus": "public", "collection": "rss"},
    # ── official / macro (public-domain gov; RSS validated) ──
    "federal_reserve":      {"accessClass": "PUBLIC_FULLTEXT", "kind": "official", "licenceStatus": "public", "collection": "rss", "notes": "central bank press (macro)"},
    "sec_press":            {"accessClass": "PUBLIC_FULLTEXT", "kind": "official", "licenceStatus": "public", "collection": "rss", "notes": "SEC press releases"},
    # ── rights-only news entries (no free public RSS → owner Share/Capture) ──
    "ft_public":            {"accessClass": "PUBLIC_METADATA", "kind": "news", "licenceStatus": "public", "collection": "owner_capture", "notes": "no public RSS; owner-shared metadata only"},
    "wsj_public":           {"accessClass": "PUBLIC_METADATA", "kind": "news", "licenceStatus": "public", "collection": "owner_capture", "notes": "no public RSS; owner-shared metadata only"},
    # ── official confirmation sources (pulled by existing engines / filings) ──
    "institution_ir":       {"accessClass": "PUBLIC_FULLTEXT", "kind": "official", "licenceStatus": "public", "collection": "official", "notes": "official IR / press release pages"},
    "sec_edgar":            {"accessClass": "PUBLIC_FULLTEXT", "kind": "official", "licenceStatus": "public", "collection": "official"},
    "tdnet":                {"accessClass": "PUBLIC_FULLTEXT", "kind": "official", "licenceStatus": "public", "collection": "official"},
    "edinet":               {"accessClass": "PUBLIC_FULLTEXT", "kind": "official", "licenceStatus": "public", "collection": "official"},
    "jpx":                  {"accessClass": "PUBLIC_FULLTEXT", "kind": "official", "licenceStatus": "public", "collection": "official"},
    "finra":                {"accessClass": "PUBLIC_FULLTEXT", "kind": "official", "licenceStatus": "public", "collection": "official"},
    "owner_capture":        {"accessClass": "SUBSCRIBER_CAPTURE", "kind": "capture", "licenceStatus": "owner", "collection": "owner_capture"},
    # ── LAYER 1 licensed feeds — DISABLED until contracted (§3/§25) ──
    "bloomberg_feed":       {"accessClass": "UNAVAILABLE", "kind": "licensed", "licenceStatus": "not_configured", "collection": "licensed", "vendor": "Bloomberg Event-Driven Feeds"},
    "lseg_mrn":             {"accessClass": "UNAVAILABLE", "kind": "licensed", "licenceStatus": "not_configured", "collection": "licensed", "vendor": "LSEG Machine Readable News"},
    "factiva_ai":           {"accessClass": "UNAVAILABLE", "kind": "licensed", "licenceStatus": "not_configured", "collection": "licensed", "vendor": "Dow Jones Factiva AI"},
    "ravenpack":            {"accessClass": "UNAVAILABLE", "kind": "licensed", "licenceStatus": "not_configured", "collection": "licensed", "vendor": "RavenPack"},
}


def source_rights(source_id: str) -> Dict[str, Any]:
    """Full rights record for a source (enforced everywhere). Unknown → UNAVAILABLE."""
    base = SOURCE_RIGHTS.get(source_id) or {"accessClass": "UNAVAILABLE", "kind": "unknown", "licenceStatus": "unknown"}
    pol = _CLASS_POLICY[base["accessClass"]]
    return {
        "sourceId": source_id, "accessClass": base["accessClass"], "kind": base.get("kind"),
        "licenceStatus": base.get("licenceStatus"), "vendor": base.get("vendor"),
        "collection": base.get("collection", "none"),
        "canStoreFullText": pol["fulltext"], "canSendToLLM": pol["llm"],
        "canDisplayExcerpt": pol["excerpt"], "canRetain": pol["retain"],
        "retentionDays": 365 if pol["retain"] else 0, "notes": base.get("notes", ""),
    }


def enforce_storage(source_id: str, record: Dict[str, Any]) -> Dict[str, Any]:
    """Strip any field the access class forbids BEFORE persistence (§4 enforced in
    code, not just docs). Always keeps title/url/metadata/hash."""
    r = source_rights(source_id)
    out = dict(record)
    if not r["canStoreFullText"]:
        out.pop("fullText", None)
    if not r["canDisplayExcerpt"]:
        out.pop("publicSnippet", None)
    out["accessClass"] = r["accessClass"]
    out["sourceId"] = source_id
    return out


def can_send_to_llm(source_id: str) -> bool:
    return source_rights(source_id)["canSendToLLM"]


# ── §5 Institution Watchlist (default; owner-configurable) ───────────────────
INSTITUTIONS: Dict[str, Dict[str, Any]] = {}


def _inst(iid, name, country, itype, aliases, priority=2):
    INSTITUTIONS[iid] = {
        "institutionId": iid, "canonicalName": name, "country": country,
        "institutionType": itype, "aliases": [a.lower() for a in aliases],
        "priority": priority, "enabled": True, "officialDomains": [], "officialSocialAccounts": [],
    }


for n, a in [("JPMorgan", ["jpmorgan", "jp morgan", "jpm", "j.p. morgan"]), ("Goldman Sachs", ["goldman", "goldman sachs", "gs"]),
             ("Morgan Stanley", ["morgan stanley", "ms"]), ("Bank of America", ["bofa", "bank of america", "merrill"]),
             ("Citi", ["citi", "citigroup"]), ("UBS", ["ubs"]), ("Barclays", ["barclays"]), ("Deutsche Bank", ["deutsche", "deutsche bank"]),
             ("Jefferies", ["jefferies"]), ("Bernstein", ["bernstein", "alliancebernstein"]), ("Evercore ISI", ["evercore", "evercore isi"]),
             ("Wedbush", ["wedbush"]), ("Needham", ["needham"]), ("KeyBanc", ["keybanc"]), ("Wolfe Research", ["wolfe research", "wolfe"]),
             ("Mizuho Americas", ["mizuho americas"]), ("Macquarie", ["macquarie"])]:
    _inst(n.lower().replace(" ", "_"), n, "US/EU", "sell_side", a)
for n, a in [("Nomura Securities", ["nomura", "野村"]), ("Daiwa Securities", ["daiwa", "大和"]), ("SMBC Nikko Securities", ["smbc nikko", "smbc日興", "日興"]),
             ("Mizuho Securities", ["mizuho securities", "みずほ証券"]), ("Mitsubishi UFJ Morgan Stanley Securities", ["mufg morgan stanley", "三菱ufjモルガン"]),
             ("SBI Securities", ["sbi", "sbi証券"]), ("Okasan Securities", ["okasan", "岡三"])]:
    _inst(n.split()[0].lower(), n, "JP", "sell_side", a)
for n, a in [("BlackRock", ["blackrock"]), ("Vanguard", ["vanguard"]), ("Fidelity", ["fidelity"]), ("State Street", ["state street", "ssga"]),
             ("Citadel", ["citadel"]), ("Point72", ["point72", "point 72"]), ("Bridgewater", ["bridgewater"]), ("Elliott", ["elliott management", "elliott"]),
             ("Coatue", ["coatue"]), ("Tiger Global", ["tiger global"])]:
    _inst(n.lower().replace(" ", "_"), n, "Global", "asset_manager", a, priority=2)

# Asset managers / funds are tracked via DISCLOSED holdings/filings/letters, NOT
# sell-side rating actions (§5).
_BUY_SIDE = {iid for iid, v in INSTITUTIONS.items() if v["institutionType"] == "asset_manager"}


def resolve_institution(text: str) -> Optional[str]:
    """Alias → institutionId, longest-alias-first. None when not confidently matched
    (never invent an identity, §6)."""
    t = (text or "").lower()
    best = None
    for iid, v in INSTITUTIONS.items():
        for alias in v["aliases"]:
            if alias and alias in t and (best is None or len(alias) > best[1]):
                best = (iid, len(alias))
    return best[0] if best else None


def resolve_analyst(name: str, institution_id: Optional[str]) -> Dict[str, Any]:
    """Entity record for a named analyst — never merges unknowns into an identity."""
    nm = (name or "").strip()
    if not nm:
        return {"analystId": "unknown", "name": None, "institutionId": institution_id}
    aid = re.sub(r"[^a-z0-9]+", "_", nm.lower()).strip("_") or "unknown"
    return {"analystId": aid, "name": nm, "institutionId": institution_id, "knownAliases": []}


# ── §8 IntelligenceItem normalization ────────────────────────────────────────
CONTENT_TYPES = {
    "RESEARCH_NOTE", "STRATEGY_OUTLOOK", "EARNINGS_PREVIEW", "ANALYST_UPGRADE",
    "ANALYST_DOWNGRADE", "PRICE_TARGET_CHANGE", "ESTIMATE_REVISION", "CONFERENCE_COMMENT",
    "INTERVIEW", "FUND_LETTER", "REGULATORY_FILING", "POSITION_DISCLOSURE",
    "MARKET_NEWS", "RUMOR", "OFFICIAL_RELEASE",
}
_TYPE_KEYWORDS = [
    ("ANALYST_UPGRADE", ["upgrade", "raised to buy", "格上げ"]),
    ("ANALYST_DOWNGRADE", ["downgrade", "cut to sell", "格下げ"]),
    ("PRICE_TARGET_CHANGE", ["price target", "目標株価", "pt to"]),
    ("ESTIMATE_REVISION", ["estimate", "raises estimate", "cuts estimate", "業績予想"]),
    ("EARNINGS_PREVIEW", ["earnings preview", "ahead of earnings", "決算プレビュー"]),
    ("STRATEGY_OUTLOOK", ["outlook", "strategy note", "year ahead", "見通し"]),
    ("FUND_LETTER", ["letter to investors", "fund letter", "投資家向け書簡"]),
    ("REGULATORY_FILING", ["13d", "13g", "13f", "form 4", "大量保有"]),
    ("INTERVIEW", ["interview", "インタビュー"]),
    ("CONFERENCE_COMMENT", ["at the conference", "conference", "登壇"]),
    ("OFFICIAL_RELEASE", ["press release", "ir release", "適時開示"]),
]


def classify_content_type(title: str, snippet: str = "") -> str:
    t = f"{title} {snippet}".lower()
    for ct, kws in _TYPE_KEYWORDS:
        if any(k in t for k in kws):
            return ct
    return "MARKET_NEWS"


def _hash(*parts: str) -> str:
    return hashlib.sha256("|".join(p or "" for p in parts).encode("utf-8")).hexdigest()[:16]


def normalize_item(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Raw collected record → IntelligenceItem (§8), rights-enforced."""
    source_id = raw.get("sourceId") or "unknown"
    title = (raw.get("title") or "").strip()
    snippet = (raw.get("publicSnippet") or "").strip()
    iid = resolve_institution(f"{title} {snippet} {raw.get('author', '')}")
    analyst = resolve_analyst(raw.get("author", ""), iid)
    chash = _hash(raw.get("canonicalUrl", ""), title)
    item = {
        "intelligenceId": _hash(source_id, raw.get("canonicalUrl", ""), title),
        "sourceId": source_id, "sourceType": SOURCE_RIGHTS.get(source_id, {}).get("kind", "news"),
        "accessClass": source_rights(source_id)["accessClass"],
        "canonicalUrl": raw.get("canonicalUrl"), "title": title, "publicSnippet": snippet,
        "language": raw.get("language", "en"), "author": raw.get("author"),
        "institutionId": iid, "analystId": analyst["analystId"],
        "publishedAt": raw.get("publishedAt"), "updatedAt": raw.get("updatedAt"),
        "firstDetectedAt": raw.get("firstDetectedAt"), "fetchedAt": raw.get("fetchedAt"),
        "contentHash": chash, "storyClusterId": None,
        "contentType": classify_content_type(title, snippet),
        "linkedAssets": [s.upper() for s in (raw.get("linkedAssets") or [])],
        "linkedThemes": raw.get("linkedThemes") or [],
        "stance": _stance(title, snippet), "timeHorizon": _horizon(title, snippet),
        "claims": [], "evidenceIds": raw.get("evidenceIds") or [],
        "sourceReliability": 0.0, "novelty": 0.0, "relevance": 0.0, "importance": 0.0,
        "status": "new", "category": "INSTITUTIONAL_RESEARCH_VIEW" if iid else "MARKET_NEWS",
    }
    return enforce_storage(source_id, item)


def _stance(title: str, snippet: str) -> str:
    t = f"{title} {snippet}".lower()
    bear = sum(k in t for k in ["downgrade", "cut", "risk", "weakness", "concern", "underweight", "overvalued", "下落", "懸念", "リスク"])
    bull = sum(k in t for k in ["upgrade", "raise", "strong", "overweight", "beat", "upside", "上昇", "好調"])
    return "cautious" if bear > bull else "constructive" if bull > bear else "neutral"


def _horizon(title: str, snippet: str) -> str:
    t = f"{title} {snippet}".lower()
    if any(k in t for k in ["long-term", "structural", "multi-year", "中長期"]):
        return "long_term"
    if any(k in t for k in ["near-term", "this quarter", "ahead of earnings", "短期"]):
        return "near_term"
    return "unspecified"


# ── §9 story clustering / syndication dedup ──────────────────────────────────
_STOPWORDS = {"the", "a", "an", "of", "to", "in", "on", "for", "and", "as", "is",
              "after", "says", "say", "amid", "with", "its", "by", "at", "from"}


def _title_fingerprint(title: str, n: int = 4) -> str:
    """First N significant title tokens — a deterministic syndication proxy. Two
    outlets repeating the SAME headline share a fingerprint; distinct headlines do
    not (prevents unrelated generic news from collapsing into one mega-cluster)."""
    toks = [t for t in re.findall(r"[a-z0-9]+", (title or "").lower()) if t not in _STOPWORDS]
    return "-".join(toks[:n]) if toks else "_"


def _norm_key(item: Dict[str, Any]) -> str:
    """Canonical event = institution + content-type + salient asset/theme + title
    fingerprint. Wire repeats of ONE story collapse (one origin, not N confirmations);
    genuinely different stories stay separate even when both lack an institution."""
    asset = (item.get("linkedAssets") or ["_"])[0]
    return _hash(item.get("institutionId") or "_", item.get("contentType") or "_",
                 asset, _title_fingerprint(item.get("title", "")))


# Source FAMILIES — many outlets re-syndicate ONE wire, so distinct sourceIds are not
# distinct confirmations. Collapsing to families is what makes "corroborated" honest:
# 5 sites running the same Reuters story = 1 family = NOT independent corroboration.
_SOURCE_FAMILY_KEYS = (
    ("federal_reserve", "official:fed"), ("federalreserve", "official:fed"),
    ("sec_press", "official:sec"), ("sec.gov", "official:sec"),
    ("treasury", "official:treasury"), ("boj", "official:boj"), ("bls", "official:bls"),
    ("reuters", "reuters"), ("bloomberg", "bloomberg"), ("nikkei", "nikkei"),
    ("cnbc", "cnbc"), ("marketwatch", "dowjones"), ("wall street", "dowjones"),
    ("dow jones", "dowjones"), ("barron", "dowjones"), ("nasdaq", "nasdaq"),
    ("yahoo", "yahoo"), ("associated press", "ap"), (" ap ", "ap"),
    ("financial times", "ft"), ("cnn", "cnn"), ("forbes", "forbes"),
    ("business insider", "insider"), ("seeking alpha", "seekingalpha"),
)
# Portals that mostly re-publish others — never counted as an INDEPENDENT family.
_AGGREGATOR_FAMILIES = {"yahoo", "nasdaq", "seekingalpha"}


def source_family(source_id: Optional[str]) -> str:
    """Map a sourceId / publisher name to its source FAMILY (wire of origin)."""
    s = (source_id or "").strip().lower().replace("_public", "").replace("_web", "")
    if not s:
        return "unknown"
    for key, fam in _SOURCE_FAMILY_KEYS:
        if key in s:
            return fam
    return s


def is_official_source(source_id: Optional[str]) -> bool:
    return source_family(source_id).startswith("official:")


def corroboration_level(source_ids) -> str:
    """official (an authoritative source) / corroborated (>=2 independent, non-aggregator
    families) / single. The lever that keeps a lone headline from driving a decision."""
    fams = {source_family(s) for s in source_ids if s}
    if any(f.startswith("official:") for f in fams):
        return "official"
    independent = {f for f in fams if f not in _AGGREGATOR_FAMILIES}
    return "corroborated" if len(independent) >= 2 else "single"


def cluster_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Group into story clusters; mark independent corroboration vs syndication.
    Two items are INDEPENDENT only when they have DIFFERENT source families AND
    neither references the other; otherwise they are syndications of one origin."""
    clusters: Dict[str, Dict[str, Any]] = {}
    for it in items:
        k = _norm_key(it)
        c = clusters.setdefault(k, {"storyClusterId": k, "items": [], "sources": set(),
                                    "earliestDetectedAt": it.get("firstDetectedAt"),
                                    "originalSourceId": None})
        c["items"].append(it)
        c["sources"].add(it.get("sourceId"))
        it["storyClusterId"] = k
        if it.get("firstDetectedAt") and (c["earliestDetectedAt"] is None or it["firstDetectedAt"] < c["earliestDetectedAt"]):
            c["earliestDetectedAt"] = it["firstDetectedAt"]
            c["originalSourceId"] = it.get("sourceId")
    out = []
    for c in clusters.values():
        srcs = {s for s in c["sources"] if s}
        # independent corroboration = distinct NON-aggregator source FAMILIES (wire
        # re-syndication collapses to one family, so it is not counted as confirmation).
        fams = {source_family(s) for s in srcs}
        independent_families = len({f for f in fams if f not in _AGGREGATOR_FAMILIES}) or len(fams)
        level = corroboration_level(srcs)
        note = {"official": "公式ソースで確認",
                "corroborated": "複数の独立系統で確認",
                "single": "単一系統(同一ワイヤーの転載は独立確認ではない)"}[level]
        out.append({
            "storyClusterId": c["storyClusterId"], "count": len(c["items"]),
            "sources": sorted(srcs), "independentSourceCount": len(srcs),
            "independentFamilyCount": independent_families,
            "corroborationLevel": level,
            "syndicationCount": len(c["items"]) - 1,
            "earliestDetectedAt": c["earliestDetectedAt"], "originalSourceId": c["originalSourceId"],
            "items": c["items"],
            "corroborationNote": note,
        })
    return out


# ── §10 report intelligence (preserve BOTH sides) ────────────────────────────
def analyze_report(title: str, body: str = "") -> Dict[str, Any]:
    """Extract bullish + bearish + conditional claims (never reduce to one number)."""
    text = f"{title}. {body}"
    sents = [s.strip() for s in re.split(r"(?<=[.。!?！?])\s+", text) if s.strip()]
    bull, bear, cond, risks = [], [], [], []
    for s in sents:
        sl = s.lower()
        if any(k in sl for k in ["if ", "could ", "may ", "risk of", "もし", "可能性", "懸念"]):
            cond.append(s)
        if any(k in sl for k in ["risk", "weakness", "downside", "concern", "overvalued", "catch-down", "リスク", "下振れ"]):
            bear.append(s)
        if any(k in sl for k in ["support", "strong", "upside", "beat", "tailwind", "好調", "上振れ"]):
            bull.append(s)
        if "risk" in sl or "リスク" in sl:
            risks.append(s)
    return {
        "bullishClaims": bull[:5], "bearishClaims": bear[:5], "conditionalClaims": cond[:5],
        "risks": risks[:5], "timeHorizon": _horizon(title, body),
        "balanced": bool(bull and bear),
        "note": "両論を保持(単一センチメント数値に潰さない)",
    }


# ── §7 targeted query generation ─────────────────────────────────────────────
_ACTION_KEYWORDS = ["upgrade", "downgrade", "price target", "estimate cut", "estimate raise",
                    "earnings preview", "strategy note", "outlook", "valuation concern",
                    "demand weakness", "de-risking", "downside risk", "positioning"]


def generate_queries(context: Dict[str, Any], max_queries: int = 12) -> List[Dict[str, Any]]:
    """Targeted query plans (institution × asset × action) — NOT a broad crawl.
    Priority 1 = held/incident/imminent-event; 2 = watchlist/themes; 3 = broad."""
    out: List[Dict[str, Any]] = []
    insts = [INSTITUTIONS[i]["canonicalName"] for i in (context.get("institutions") or list(INSTITUTIONS)[:6])]
    p1 = list(context.get("heldOrIncident") or [])
    p2 = list(context.get("watchlist") or [])
    themes = list(context.get("themes") or [])
    for prio, assets in ((1, p1), (2, p2)):
        for a in assets:
            for inst in insts[:3]:
                out.append({"query": f"{inst} {a}", "priority": prio, "asset": a, "institution": inst,
                            "actionKeywords": _ACTION_KEYWORDS[:6]})
    for th in themes:
        out.append({"query": f"{insts[0] if insts else 'analyst'} {th}", "priority": 3, "theme": th})
    # dedup + cap (adaptive monitoring — don't query every combination, §7)
    seen, dedup = set(), []
    for q in sorted(out, key=lambda x: x["priority"]):
        if q["query"] not in seen:
            seen.add(q["query"]); dedup.append(q)
    return dedup[:max_queries]


# ── §16 Narrative Integrity Gate ─────────────────────────────────────────────
_FORBIDDEN = [
    (r"完全に原因", "断定的な原因の主張"),
    (r"クジラが数学的に", "数学的クジラ判定の主張"),
    (r"(jpmorgan|goldman|morgan stanley|citadel|[A-Za-z]+)が(売っ|買っ)た", "機関の自己売買を名指し断定"),
    (r"(機関投資家|機関)が完全に売りへ転換", "機関の完全転換の断定"),
    (r"決算が原因", "未発表決算を原因と断定(要・発表確認)"),
    (r"short volume means.*short interest", "空売り出来高=空売り残高の混同"),
    (r"(sold|bought) (by|the) (jpmorgan|goldman|morgan stanley)", "named-institution trade claim"),
]
_REQUIRED_SECTIONS = ["confirmedFacts", "reportedView", "interpretation", "alternative", "notConfirmed"]


def narrative_violations(text: str) -> List[str]:
    """Forbidden phrasing (§16) — returns the human reasons, empty when clean."""
    t = text or ""
    return [reason for pat, reason in _FORBIDDEN if re.search(pat, t, re.IGNORECASE)]


def gate_synthesis(synthesis: Dict[str, Any]) -> Dict[str, Any]:
    """Pass/repair a final ARGUS view before publication (§16). Rejects forbidden
    direction claims and requires the honesty sections + a labelled confidence."""
    blob = " ".join(str(synthesis.get(k, "")) for k in synthesis)
    viol = narrative_violations(blob)
    missing = [s for s in _REQUIRED_SECTIONS if not synthesis.get(s)]
    conf = synthesis.get("confidence", "UNCONFIRMED")
    if conf not in ("HIGH", "MODERATE", "LOW", "UNCONFIRMED"):
        conf = "UNCONFIRMED"
    ok = not viol and not missing
    return {"ok": ok, "violations": viol, "missingSections": missing,
            "confidence": conf,
            "publishable": ok,
            "downgradeReason": ("; ".join(viol + [f"missing:{m}" for m in missing]) if not ok else None)}


# ── §11 link intelligence to a root event (causal role) ──────────────────────
_CAUSAL_ROLES = {"IMMEDIATE_TRIGGER", "LIKELY_RELATED", "VULNERABILITY", "AMPLIFIER",
                 "PROPAGATION_EVIDENCE", "CONFIRMATION", "CONTRADICTION", "BACKGROUND_ONLY", "UNCONFIRMED"}


def link_to_event(item: Dict[str, Any], event: Dict[str, Any]) -> Dict[str, Any]:
    """Decide an intelligence item's causal role vs a root event, with the hard
    timestamp rules (§11): published AFTER the move ≠ immediate trigger; weak asset
    match / unknown timing ≠ trigger. A NAMED VIEW is never a NAMED TRADE."""
    pub = item.get("publishedAt")
    move = event.get("moveStartedAt")
    ev_assets = {a.upper() for a in (event.get("linkedAssets") or [])}
    it_assets = {a.upper() for a in (item.get("linkedAssets") or [])}
    asset_match = bool(ev_assets & it_assets)

    role, reason = "UNCONFIRMED", "時刻・資産関連が不十分"
    if not asset_match:
        role, reason = "BACKGROUND_ONLY", "対象資産との関連が弱い"
    elif not pub or not move:
        role, reason = "LIKELY_RELATED" if asset_match else "UNCONFIRMED", "時刻情報が不足し引き金と断定できない"
    elif pub > move:
        role, reason = "AMPLIFIER", "動意の後に出た情報。元の引き金ではない(増幅/追認)"
    elif item.get("contentType") in ("STRATEGY_OUTLOOK", "RESEARCH_NOTE") and item.get("timeHorizon") == "long_term":
        role, reason = "VULNERABILITY", "背景の脆弱性(長期見解)であり即時の引き金ではない"
    else:
        role, reason = "LIKELY_RELATED", "時刻整合・資産一致だが因果は断定しない"

    # Category clarity (§2): a named institutional VIEW is reported, never a trade.
    is_named_view = bool(item.get("institutionId")) and item.get("category") == "INSTITUTIONAL_RESEARCH_VIEW"
    return {
        "eventId": event.get("eventId"), "intelligenceId": item.get("intelligenceId"),
        "causalRole": role, "reasonJa": reason, "assetMatch": asset_match,
        "category": item.get("category"),
        "isNamedView": is_named_view,
        "notConfirmed": ([] if not is_named_view else ["直接の引き金", "当該機関の建玉/売買の変化"]),
        "institutionId": item.get("institutionId"),
        "relationLabelJa": {"IMMEDIATE_TRIGGER": "即時の引き金", "LIKELY_RELATED": "関連の可能性",
                            "VULNERABILITY": "背景の脆弱性", "AMPLIFIER": "増幅要因",
                            "BACKGROUND_ONLY": "背景", "CONFIRMATION": "追認", "CONTRADICTION": "反証",
                            "PROPAGATION_EVIDENCE": "波及の証拠", "UNCONFIRMED": "因果不明"}.get(role, role),
    }
