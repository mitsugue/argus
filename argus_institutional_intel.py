"""ARGUS V11.6.0 — Institutional Intelligence Layer (pure, deterministic, stdlib-only).

Turns the C.A.O.S. intel mesh's normalized items (argus_research_mesh) into FORMAL
InstitutionalSignal records a novice owner can read: who said it, what kind of claim,
bullish/bearish/mixed/conditional, direct catalyst vs related signal vs background,
why it matters (Japanese), and what to do about it — where "do" is never a trade:
watch / wait / hold / caution / investigate / avoid_chase / no_action only.

HONESTY RULES (must never be weakened):
- No fabrication: every field derives from the PUBLIC headline/snippet/metadata we
  actually stored. When only a headline is available the signal is marked
  headlineOnly with confidence capped and a visible "headline-only / limited
  confidence" note.
- Paywalled sources (FT/WSJ/Barron's/Nikkei full text) are metadata-only by design.
- These are context, not trade instructions — the disclaimer rides on every payload.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Set

import argus_news_freshness
import argus_research_mesh as MESH

SCHEMA_VERSION = "institutional-signal-v1"

DISCLAIMER_JA = ("これは公開されている機関・メディアのシグナルであり、文脈情報です。"
                 "自動売買の指示ではありません。")
DISCLAIMER_EN = ("These are public institutional/media signals. They are context, "
                 "not automatic trade instructions.")

STANCES = ("bullish", "bearish", "neutral", "mixed", "conditional", "unknown")
CLAIM_TYPES = ("upgrade", "downgrade", "initiation", "macro_view", "earnings_view",
               "sector_view", "policy_view", "flow_view", "risk_warning",
               "event_preview", "event_reaction", "other")
DIRECTNESS = ("direct_cause", "related_signal", "background", "weak_context")
ACTIONS = ("watch", "wait", "hold", "caution", "investigate", "avoid_chase", "no_action")

STANCE_JA = {"bullish": "強気", "bearish": "弱気", "neutral": "中立", "mixed": "強弱混在",
             "conditional": "条件付き", "unknown": "不明"}
DIRECTNESS_JA = {"direct_cause": "直接材料", "related_signal": "関連シグナル",
                 "background": "背景情報", "weak_context": "弱い文脈"}
ACTION_JA = {"watch": "監視継続", "wait": "確認待ち", "hold": "現状維持",
             "caution": "警戒", "investigate": "要調査", "avoid_chase": "追いかけ買い注意",
             "no_action": "対応不要"}
CLAIM_JA = {"upgrade": "格上げ/目標引き上げ", "downgrade": "格下げ/目標引き下げ",
            "initiation": "新規カバレッジ", "macro_view": "マクロ見解",
            "earnings_view": "業績見解", "sector_view": "セクター見解",
            "policy_view": "政策見解", "flow_view": "需給/フロー見解",
            "risk_warning": "リスク警告", "event_preview": "イベント前見解",
            "event_reaction": "イベント後反応", "other": "その他"}


# ── source registry (spec groups; honesty about what is actually configured) ──
def build_source_registry() -> Dict[str, Any]:
    """The monitored-source registry. Banks/brokers are detected in HEADLINES via
    the mesh's institution resolver (they publish through media, not RSS of their
    own). Media/official entries mirror what the collector actually fetches —
    paywalled or unconfigured sources say so instead of pretending."""
    banks = []
    for iid, v in MESH.INSTITUTIONS.items():
        if v.get("institutionType") != "sell_side":
            continue
        banks.append({"sourceName": v["canonicalName"], "sourceType":
                      ("broker" if v.get("country") == "JP" and v["canonicalName"].split()[0]
                       in ("SBI", "Rakuten", "Monex") else "investment_bank"),
                      "sourceTier": "high", "region": "JP" if v.get("country") == "JP" else "US",
                      "status": "headline_detection",
                      "noteJa": "自社RSSは無い — 公開メディア見出し中の言及を検出"})
    media = [
        ("Reuters", "reuters_jp", "live", "公開RSS(日本語)"),
        ("Bloomberg (public)", "bloomberg_public", "live", "公開RSS(EN)+日本語sitemap(メタデータのみ)"),
        ("CNBC", "cnbc_public", "live", "公開RSS"),
        ("Nikkei (public metadata)", "nikkei_web", "live", "公開見出しのみ・本文は有料(取得しない)"),
        ("MarketWatch", "marketwatch_public", "live", "公開RSS"),
        ("Yahoo Finance", "yahoo_finance_public", "live", "公開RSS"),
        ("NHK Business", "nhk_business", "live", "公開RSS"),
        ("Financial Times", "ft_public", "metadata_only", "paywall — 公開メタデータ/見出しのみ(本文取得禁止)"),
        ("Wall Street Journal", "wsj_public", "metadata_only", "paywall — 公開メタデータ/見出しのみ(本文取得禁止)"),
        ("Barron's", None, "disabled", "未構成(paywall・公開フィードなし)"),
        ("Investing.com", None, "disabled", "未構成(公開フィード未検証)"),
    ]
    official = [
        ("Federal Reserve", "federal_reserve", "central_bank", "live", "公式RSS"),
        ("Bank of Japan", "boj_official", "central_bank", "live", "公式RSS"),
        ("U.S. Treasury", None, "government", "disabled", "未構成(V11.5でnot_implemented)"),
        ("BLS", "bls_api", "government", "live", "公式API(マクロ指標)"),
        ("BEA", "bea_api", "government", "live", "公式API(FRED経由)"),
        ("SEC / EDGAR", "sec_edgar", "official_institution", "live", "公式API+プレスRSS"),
        ("JPX", None, "exchange", "disabled", "未構成(公式RSSなし — TDnet経由で実質カバー)"),
        ("TSE (TDnet)", "tdnet", "exchange", "live", "J-Quants TDnet Add-on(公式適時開示)"),
        ("FSA Japan", None, "government", "disabled", "未構成"),
        ("Ministry of Finance Japan", None, "government", "disabled", "未構成(介入は報道メタデータで検知)"),
        ("METI", "meti_official", "government", "live", "公式RSS"),
    ]
    return {
        "schemaVersion": "institutional-source-registry-v1",
        "banks": banks,
        "media": [{"sourceName": n, "sourceId": sid, "sourceType": "financial_media",
                   "sourceTier": "medium", "status": st, "noteJa": note}
                  for n, sid, st, note in media],
        "official": [{"sourceName": n, "sourceId": sid, "sourceType": st_type,
                      "sourceTier": "primary", "status": st, "noteJa": note}
                     for n, sid, st_type, st, note in official],
        "noteJa": "銀行/証券は見出し内検出。paywall/未構成ソースはmetadata_only/disabledと正直に表示。"
                  "アクセス制限を破る取得は行わない。",
    }


# ── keyword tables (deterministic; JA+EN) ────────────────────────────────────
_KW = {
    "upgrade": ("upgrade", "raises target", "raised target", "price target to", "overweight from",
                "格上げ", "目標株価引き上げ", "投資判断引き上げ"),
    "downgrade": ("downgrade", "cuts target", "lowered target", "underweight from",
                  "格下げ", "目標株価引き下げ", "投資判断引き下げ"),
    "initiation": ("initiates", "initiation", "begins coverage", "starts coverage",
                   "新規カバレッジ", "カバレッジ開始"),
    "risk_warning": ("warns", "warning", "bubble", "correction risk", "crash", "downside risk",
                     "警告", "暴落", "急落リスク", "バブル", "調整リスク"),
    "event_preview": ("ahead of", "preview", "before the", "next week's", "upcoming",
                      "を前に", "を控え", "見通し", "プレビュー"),
    "event_reaction": ("after the", "reaction to", "following the", "in response",
                       "を受けて", "を受け", "受けた"),
    "earnings_view": ("earnings", "quarter", "guidance", "revenue", "profit",
                      "決算", "業績", "ガイダンス", "通期"),
    "policy_view": ("policy", "regulation", "tariff", "sanction", "antitrust",
                    "政策", "規制", "関税", "制裁"),
    "flow_view": ("flows", "positioning", "buyback", "inflow", "outflow", "short interest",
                  "資金流入", "資金流出", "需給", "自社株買い", "ポジション"),
    "sector_view": ("sector", "industry", "chipmakers", "banks", "utilities",
                    "セクター", "業界", "半導体株", "銀行株"),
    "macro_view": ("fed", "boj", "rates", "rate cut", "rate hike", "inflation", "cpi", "gdp",
                   "recession", "yield", "金利", "利下げ", "利上げ", "インフレ", "景気", "国債"),
}
_CONDITIONAL = ("if ", " unless ", "would depend", "provided that", "contingent",
                "次第", "場合には", "であれば", "を条件に")
_BULL = ("upgrade", "raise", "strong", "overweight", "beat", "upside", "bullish", "buy",
         "上昇", "好調", "強気", "買い推奨")
_BEAR = ("downgrade", "cut", "risk", "weakness", "concern", "underweight", "overvalued",
         "bearish", "sell", "下落", "懸念", "リスク", "弱気", "売り")
_THEME_KW = {
    "risk_on": ("risk-on", "risk on", "rally", "melt-up", "リスクオン", "上昇相場"),
    "risk_off": ("risk-off", "risk off", "flight to safety", "haven", "リスクオフ", "安全資産"),
    "rate_cut": ("rate cut", "cuts rates", "easing", "利下げ", "緩和"),
    "rate_hike": ("rate hike", "raises rates", "tightening", "利上げ", "引き締め"),
    "ai_capex": ("ai capex", "ai spending", "data center", "datacenter", "ai investment",
                 "ai infrastructure", "ai投資", "データセンター", "ai設備投資"),
    "sector_rotation": ("rotation", "rotate into", "rotate out", "ローテーション", "資金シフト"),
    "jp_flow": ("japan equities", "japanese stocks", "nikkei", "topix", "日本株", "東京株"),
}
_EVENT_CODES = ("NFP", "CPI", "PPI", "FOMC", "PCE", "GDP", "JOLTS", "BOJ")

_OFFICIAL_TYPE = {"federal_reserve": "central_bank", "boj_official": "central_bank",
                  "meti_official": "government", "sec_press": "official_institution",
                  "sec_edgar": "official_institution", "tdnet": "exchange",
                  "edinet": "official_institution", "jpx": "exchange"}


def _text(item: Dict[str, Any]) -> str:
    return f"{item.get('title') or ''} {item.get('publicSnippet') or ''}".lower()


def classify_claim_type(text: str) -> str:
    for ct in ("upgrade", "downgrade", "initiation", "risk_warning",
               "event_preview", "event_reaction", "earnings_view", "policy_view",
               "flow_view", "sector_view", "macro_view"):
        if any(k in text for k in _KW[ct]):
            return ct
    return "other"


def classify_stance(text: str) -> str:
    bull = sum(k in text for k in _BULL)
    bear = sum(k in text for k in _BEAR)
    conditional = any(k in text for k in _CONDITIONAL)
    # conditional wins over mixed: "bullish IF the Fed cuts" is a conditional call,
    # not a bull-vs-bear disagreement ("cut" alone would false-read as bearish).
    if conditional and (bull or bear):
        return "conditional"
    if bull and bear:
        return "mixed"
    if bull:
        return "bullish"
    if bear:
        return "bearish"
    return "neutral" if text.strip() else "unknown"


def classify_horizon(text: str) -> str:
    if any(k in text for k in ("today", "intraday", "本日", "きょう")):
        return "intraday"
    if any(k in text for k in ("near-term", "this week", "this quarter", "短期", "今週")):
        return "short_term"
    if any(k in text for k in ("long-term", "structural", "multi-year", "中長期", "長期")):
        return "long_term"
    if any(k in text for k in ("months", "next year", "半年", "数カ月", "来年")):
        return "medium_term"
    return "unknown"


def classify_directness(item: Dict[str, Any], claim_type: str,
                        owner_assets: Set[str]) -> str:
    assets = {str(a).upper() for a in (item.get("linkedAssets") or [])}
    hit = assets & owner_assets
    if hit and claim_type in ("upgrade", "downgrade", "initiation", "earnings_view"):
        return "direct_cause"
    if hit:
        return "related_signal"
    if claim_type in ("macro_view", "sector_view", "policy_view", "flow_view",
                      "risk_warning", "event_preview", "event_reaction"):
        return "background"
    return "weak_context"


def _source_type(item: Dict[str, Any]) -> str:
    iid = item.get("institutionId")
    if iid:
        inst = MESH.INSTITUTIONS.get(iid) or {}
        if inst.get("institutionType") == "sell_side":
            return ("broker" if inst.get("country") == "JP"
                    and inst.get("canonicalName", "").split()[0] in ("SBI", "Rakuten", "Monex")
                    else "investment_bank")
        return "other"
    sid = str(item.get("sourceId") or "")
    if sid in _OFFICIAL_TYPE:
        return _OFFICIAL_TYPE[sid]
    if MESH.is_official_source(sid):
        return "official_institution"
    return "financial_media"


def _source_tier_label(item: Dict[str, Any], source_type: str) -> str:
    if source_type in ("central_bank", "government", "official_institution", "exchange"):
        return "primary"
    if item.get("institutionId"):
        return "high"
    t = str(item.get("sourceTier") or "")
    if t in ("wire", "official"):
        return "medium"
    return "medium" if t in ("reputable", "media") else "low"


def _region(item: Dict[str, Any]) -> str:
    sid = str(item.get("sourceId") or "")
    if item.get("language") == "ja" or sid in ("reuters_jp", "nikkei_web", "nhk_business",
                                               "boj_official", "meti_official", "tdnet",
                                               "google_news_jp", "bloomberg_jp"):
        return "JP"
    if sid in ("federal_reserve", "sec_press", "sec_edgar", "cnbc_public",
               "marketwatch_public", "nasdaq_public", "google_news_us"):
        return "US"
    return "Global"


def _related_events(text: str) -> List[str]:
    up = text.upper()
    return [c for c in _EVENT_CODES if c in up or
            {"BOJ": "日銀", "FOMC": "FOMC"}.get(c, "\x00") in text]


def _why_ja(source_name: str, claim_type: str, stance: str, directness: str,
            assets: List[str], headline_only: bool) -> str:
    """Deterministic owner-readable "why it matters" — describes the PATHWAY the
    claim type implies. Never invents content beyond the classified headline."""
    a = "・".join(assets[:3]) if assets else ""
    prefix = "(見出しベース・限定確度) " if headline_only else ""
    if claim_type in ("upgrade", "downgrade"):
        d = "引き上げ" if claim_type == "upgrade" else "引き下げ"
        return (f"{prefix}{source_name}の評価{d}に関する見出し。対象銘柄({a})の需給に"
                f"短期的な影響が出やすい。内容の確認前に飛びつかないこと。")
    if claim_type == "risk_warning":
        return (f"{prefix}{source_name}のリスク警告。大手機関が慎重姿勢を出すと、"
                "業績が変わらなくても高バリュエーション銘柄は売られやすくなる。")
    if claim_type == "macro_view":
        return (f"{prefix}{source_name}のマクロ見解。金利・景気の見方が変わると"
                "株全体の地合い(特に高PER銘柄と円相場)に波及する。")
    if claim_type == "policy_view":
        return (f"{prefix}{source_name}の政策・規制に関する見解。対象セクターの"
                "前提が変わる可能性がある(単発報道では断定しない)。")
    if claim_type == "flow_view":
        return (f"{prefix}{source_name}の需給・フロー見解。ファンダメンタルズと無関係に"
                "値動きが増幅されることがある。")
    if claim_type == "event_preview":
        return (f"{prefix}{source_name}のイベント前見解。結果次第で反応が変わるため、"
                "イベント通過までは新規の動きを控えるのが基本。")
    if claim_type == "event_reaction":
        return (f"{prefix}{source_name}のイベント後の解釈。初動が行き過ぎることもあるため"
                "市場反応の持続を確認する。")
    if claim_type == "earnings_view":
        return (f"{prefix}{source_name}の業績見解。{a or '対象銘柄'}の決算前後は"
                "値動きが荒れやすい。")
    if claim_type == "sector_view":
        return (f"{prefix}{source_name}のセクター見解。個別銘柄でなく業界全体の"
                "資金の流れに関わる({DIRECT}目線)。").replace("{DIRECT}", DIRECTNESS_JA.get(directness, ""))
    return (f"{prefix}{source_name}の公開シグナル。{DIRECTNESS_JA.get(directness, '文脈')}として"
            "参考にする(単独で判断を変えない)。")


def _action(claim_type: str, stance: str, directness: str) -> str:
    if claim_type == "risk_warning":
        return "caution"
    if directness == "direct_cause":
        if stance == "bearish":
            return "caution"
        if stance == "bullish":
            return "investigate"          # never buy — verify the content first
        return "investigate"
    if claim_type == "event_preview":
        return "wait"
    if claim_type == "event_reaction":
        return "watch"
    if stance == "bullish" and directness == "related_signal":
        return "avoid_chase"
    if directness == "weak_context":
        return "no_action"
    return "watch"


def _check_next_ja(claim_type: str, directness: str) -> str:
    if claim_type in ("upgrade", "downgrade", "initiation"):
        return "元レポートの要旨と対象銘柄の出来高反応を確認"
    if claim_type == "event_preview":
        return "イベント結果の発表と初動の市場反応を確認"
    if claim_type == "risk_warning":
        return "同趣旨の警告が他機関からも出るか(単発か合唱か)を確認"
    if directness == "direct_cause":
        return "公式開示・複数ソースでの裏取りを確認"
    return "同テーマの続報と価格反応の有無を確認"


def build_signal(item: Dict[str, Any], *, owner_assets: Set[str], now_iso: str) -> Dict[str, Any]:
    """One normalized IntelligenceItem → one InstitutionalSignal. Pure."""
    text = _text(item)
    headline_only = not (item.get("publicSnippet") or "").strip()
    claim = classify_claim_type(text)
    stance = classify_stance(text)
    directness = classify_directness(item, claim, owner_assets)
    stype = _source_type(item)
    tier = _source_tier_label(item, stype)
    iid = item.get("institutionId")
    source_name = (MESH.INSTITUTIONS.get(iid, {}).get("canonicalName") if iid
                   else str(item.get("sourceId") or "unknown"))
    assets = [str(a).upper() for a in (item.get("linkedAssets") or [])]
    owner_hits = [a for a in assets if a in owner_assets]
    fr = argus_news_freshness.classify(item.get("publishedAt") or item.get("firstDetectedAt"),
                                       now_iso)
    conf = {"primary": 0.8, "high": 0.65, "medium": 0.5, "low": 0.3}[tier]
    if headline_only:
        conf = min(conf, 0.4)
    if fr["freshness"] in ("stale", "old"):
        conf = min(conf, 0.35)
    importance = round(min(1.0, conf
                           + (0.2 if directness == "direct_cause" else
                              0.1 if directness == "related_signal" else 0.0)
                           + (0.1 if owner_hits else 0.0)
                           - (0.3 if fr["freshness"] in ("stale", "old") else 0.0)), 2)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "id": item.get("intelligenceId"),
        "sourceName": source_name, "sourceType": stype, "sourceTier": tier,
        "region": _region(item),
        "publishedAt": item.get("publishedAt"), "fetchedAt": item.get("fetchedAt"),
        "headline": (item.get("title") or "")[:200],
        "summary": (item.get("publicSnippet") or "")[:240],
        "url": item.get("canonicalUrl"),
        "tickers": assets[:8], "sectors": [], "themes": item.get("linkedThemes") or [],
        "relatedEvents": _related_events(item.get("title") or ""),
        "stance": stance, "stanceJa": STANCE_JA[stance],
        "claimType": claim, "claimTypeJa": CLAIM_JA[claim],
        "impactHorizon": classify_horizon(text),
        "confidence": round(conf, 2), "importance": importance,
        "affectedAssets": (owner_hits + [a for a in assets if a not in owner_hits])[:6],
        "ownerAssetHit": bool(owner_hits),
        "rootEventId": None,
        "directness": directness, "directnessJa": DIRECTNESS_JA[directness],
        "headlineOnly": headline_only,
        "freshness": fr["freshness"],
        "ownerReadableWhy": _why_ja(source_name, claim, stance, directness,
                                    owner_hits or assets, headline_only),
        "checkNextJa": _check_next_ja(claim, directness),
        "actionImplication": _action(claim, stance, directness),
        "actionImplicationJa": ACTION_JA[_action(claim, stance, directness)],
        "complianceNote": ("headline-only / limited confidence — 本文非取得のため見出しのみで分類"
                           if headline_only else
                           "public metadata/headline classification(本文の保存なし)"),
    }


def build_signals(items: Iterable[Dict[str, Any]], *, owner_assets: Set[str],
                  now_iso: str, cap: int = 40) -> List[Dict[str, Any]]:
    """Relevant items → deduped, importance-ranked signals. A signal qualifies when
    a named institution was resolved, the source is official, or the claim is a
    typed one (not 'other'). Old items are excluded from the CURRENT list."""
    out, seen = [], set()
    for it in items or []:
        if not isinstance(it, dict) or not it.get("title"):
            continue
        sig = build_signal(it, owner_assets=owner_assets, now_iso=now_iso)
        if not (it.get("institutionId") or sig["sourceType"] in
                ("central_bank", "government", "official_institution", "exchange")
                or sig["claimType"] != "other"):
            continue
        if sig["freshness"] in ("old",):
            continue                       # 過去材料はcurrentに出さない(v11.5.3規律)
        key = f"{sig['sourceName']}|{MESH._title_fingerprint(sig['headline'])}"
        if key in seen:
            continue
        seen.add(key)
        out.append(sig)
    out.sort(key=lambda s: (-s["importance"], s["id"] or ""))
    return out[:cap]


def regime_themes(signals: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Institutional regime commentary counts (risk-on/off, rates, AI capex,
    rotation, JP flow) with one example headline each. Deterministic keywords."""
    counts: Dict[str, Dict[str, Any]] = {k: {"count": 0, "exampleJa": None, "example": None}
                                         for k in _THEME_KW}
    for s in signals:
        text = f"{s.get('headline') or ''} {s.get('summary') or ''}".lower()
        for theme, kws in _THEME_KW.items():
            if any(k in text for k in kws):
                counts[theme]["count"] += 1
                if counts[theme]["example"] is None:
                    # owner rule: display text is Japanese-first when available
                    counts[theme]["example"] = (s.get("displayTitleJa")
                                                or s["headline"])[:120]
    return counts


def handoff_summary(signals: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Pro Handoff / AI Review sheet block: supportive vs opposing vs conditional,
    missing evidence, direct-vs-background separation. Text stays sourced."""
    def line(s):
        return f"[{s['sourceName']}/{s['stance']}] {s['headline'][:110]}"
    supportive = [line(s) for s in signals if s["stance"] == "bullish"][:5]
    opposing = [line(s) for s in signals if s["stance"] in ("bearish",)][:5]
    conditional = [line(s) for s in signals if s["stance"] in ("conditional", "mixed")][:5]
    missing = []
    ho = sum(1 for s in signals if s["headlineOnly"])
    if ho:
        missing.append(f"{ho}件はheadline-only(本文未確認・限定確度)")
    if not any(s["sourceTier"] == "primary" for s in signals):
        missing.append("公式一次ソースの裏付けなし(メディア/機関見出しのみ)")
    return {
        "title": "Institutional Intelligence Summary",
        "supportive": supportive, "opposing": opposing, "conditional": conditional,
        "missingEvidence": missing,
        "directCount": sum(1 for s in signals if s["directness"] == "direct_cause"),
        "relatedCount": sum(1 for s in signals if s["directness"] == "related_signal"),
        "backgroundCount": sum(1 for s in signals if s["directness"] == "background"),
        "disclaimerJa": DISCLAIMER_JA,
    }
