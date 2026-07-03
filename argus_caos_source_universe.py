"""ARGUS V11.5.3 — C.A.O.S. Professional Source Universe (pure, stdlib-only).

For every Core Portfolio asset class this declares WHICH sources ARGUS watches,
at what tier, under what rights, and how they are collected. Principles:

- Google News (JP/US) is a DISCOVERY LAYER, never a source tier: items resolve to
  their true publisher; an aggregator item can never confirm a cause by itself.
- Unknown SEO sites / video / blogs / social = weak_signal — cannot ground a
  judgment, cannot confirm a cause, cannot be a primary lead.
- Nikkei/Bloomberg/Reuters/WSJ/FT: PUBLIC METADATA ONLY (title+URL+time). Full text
  is licensed_unavailable unless a contract exists — never scraped.
- A source that is not configured says so (not_configured / requires_contract);
  honesty over coverage theater.

The scanner passes `configured` env flags; this module never reads the env itself.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

SCHEMA_VERSION = "caos-source-universe-v1"

# ── source definitions ───────────────────────────────────────────────────────
# collectionMethod: api | rss | sitemap | html_metadata | search_discovery | manual | disabled
# `feeds`: True when the source is in scanner._INTEL_FEEDS (public RSS collected 24/7).
# `env`: env vars that must be configured for the API path.

_S = lambda **kw: kw   # terse literal builder

SOURCES: List[Dict[str, Any]] = [
    # ━━ JP_EQUITY — official / primary ━━
    _S(sourceId="jquants_tdnet", name="TDnet 適時開示 (J-Quants Add-on)",
       assetClasses=["JP_EQUITY"], regions=["JP"], sourceTier="official_regulatory",
       rightsClass="official", collectionMethod="api", provider="J-Quants",
       env=["JQUANTS_API_KEY"], canGroundJudgment=True, canConfirmCause=True,
       canBePrimaryLead=True, isDiscoveryLayer=False, qualityScore=1.0,
       freshnessSlaMin=15, limitationsJa=[]),
    _S(sourceId="edinet", name="EDINET (大量保有・有報)",
       assetClasses=["JP_EQUITY"], regions=["JP"], sourceTier="official_regulatory",
       rightsClass="official", collectionMethod="api", provider="金融庁",
       env=[], canGroundJudgment=True, canConfirmCause=True, canBePrimaryLead=True,
       isDiscoveryLayer=False, qualityScore=1.0, freshnessSlaMin=60, limitationsJa=[]),
    _S(sourceId="jpx_tse", name="JPX/東証 (市場措置・注意喚起)",
       assetClasses=["JP_EQUITY"], regions=["JP"], sourceTier="exchange_or_listing_venue",
       rightsClass="official", collectionMethod="html_metadata", provider="JPX",
       env=["__NOT_CONFIGURED__"], canGroundJudgment=True, canConfirmCause=True,
       canBePrimaryLead=True, isDiscoveryLayer=False, qualityScore=0.95,
       freshnessSlaMin=60, limitationsJa=["公式RSSが無くHTMLメタデータ取得は未構成"]),
    _S(sourceId="company_ir_jp", name="企業IR/適時開示ページ (JP)",
       assetClasses=["JP_EQUITY"], regions=["JP"], sourceTier="official_corporate",
       rightsClass="official", collectionMethod="manual",
       env=["__NOT_CONFIGURED__"], canGroundJudgment=True, canConfirmCause=True,
       canBePrimaryLead=True, isDiscoveryLayer=False, qualityScore=0.95,
       freshnessSlaMin=120, limitationsJa=["TDnet経由で実質カバー(個別IRの直接巡回は未構成)"]),
    _S(sourceId="boj_official", name="日本銀行 公表資料",
       assetClasses=["JP_EQUITY", "FX_USDJPY", "CASH"], regions=["JP"],
       sourceTier="central_bank_or_government", rightsClass="official",
       collectionMethod="rss", provider="BOJ", feeds=True,
       canGroundJudgment=True, canConfirmCause=True, canBePrimaryLead=True,
       isDiscoveryLayer=False, qualityScore=1.0, freshnessSlaMin=30, limitationsJa=[]),
    _S(sourceId="meti_official", name="経済産業省 リリース",
       assetClasses=["JP_EQUITY"], regions=["JP"],
       sourceTier="central_bank_or_government", rightsClass="official",
       collectionMethod="rss", provider="METI", feeds=True,
       canGroundJudgment=True, canConfirmCause=False, canBePrimaryLead=True,
       isDiscoveryLayer=False, qualityScore=0.9, freshnessSlaMin=60, limitationsJa=[]),
    _S(sourceId="mof_jp", name="財務省 (為替介入・国債)",
       assetClasses=["FX_USDJPY", "JP_EQUITY"], regions=["JP"],
       sourceTier="central_bank_or_government", rightsClass="official",
       collectionMethod="html_metadata", env=["__NOT_CONFIGURED__"],
       canGroundJudgment=True, canConfirmCause=True, canBePrimaryLead=True,
       isDiscoveryLayer=False, qualityScore=0.95, freshnessSlaMin=60,
       limitationsJa=["公式RSSが無く直接巡回は未構成(介入はReuters/日経メタデータ経由で検知)"]),
    # ━━ JP_EQUITY — professional media (public metadata) ━━
    _S(sourceId="nikkei_web", name="日経 (公開見出しメタデータ)",
       assetClasses=["JP_EQUITY", "FX_USDJPY"], regions=["JP"],
       sourceTier="reputable_financial_media", rightsClass="public_metadata",
       collectionMethod="rss", provider="Nikkei", feeds=True,
       canGroundJudgment=True, canConfirmCause=False, canBePrimaryLead=True,
       isDiscoveryLayer=False, qualityScore=0.85, freshnessSlaMin=30,
       limitationsJa=["本文は有料(タイトル+URLのみ・本文保存禁止)"]),
    _S(sourceId="reuters_jp", name="ロイター日本語",
       assetClasses=["JP_EQUITY", "FX_USDJPY", "US_EQUITY"], regions=["JP"],
       sourceTier="wire_service", rightsClass="public_metadata",
       collectionMethod="rss", provider="Reuters", feeds=True,
       canGroundJudgment=True, canConfirmCause=False, canBePrimaryLead=True,
       isDiscoveryLayer=False, qualityScore=0.9, freshnessSlaMin=30, limitationsJa=[]),
    _S(sourceId="bloomberg_jp", name="Bloomberg日本語 (公開メタデータ)",
       assetClasses=["JP_EQUITY", "FX_USDJPY"], regions=["JP"],
       sourceTier="reputable_financial_media", rightsClass="public_metadata",
       collectionMethod="sitemap", provider="Bloomberg", feeds=True,
       canGroundJudgment=True, canConfirmCause=False, canBePrimaryLead=True,
       isDiscoveryLayer=False, qualityScore=0.85, freshnessSlaMin=30,
       limitationsJa=["本文は有料(タイトル+URLのみ)"]),
    _S(sourceId="nhk_business", name="NHK 経済ニュース",
       assetClasses=["JP_EQUITY"], regions=["JP"],
       sourceTier="reputable_financial_media", rightsClass="public_metadata",
       collectionMethod="rss", provider="NHK", feeds=True,
       canGroundJudgment=True, canConfirmCause=False, canBePrimaryLead=True,
       isDiscoveryLayer=False, qualityScore=0.8, freshnessSlaMin=30, limitationsJa=[]),
    _S(sourceId="kabutan_minkabu", name="株探/みんかぶ (市況コメンタリー)",
       assetClasses=["JP_EQUITY"], regions=["JP"],
       sourceTier="specialist_industry_media", rightsClass="public_metadata",
       collectionMethod="disabled", env=["__NOT_CONFIGURED__"],
       canGroundJudgment=False, canConfirmCause=False, canBePrimaryLead=False,
       isDiscoveryLayer=False, qualityScore=0.4, freshnessSlaMin=60,
       limitationsJa=["公式RSSなし(403)・市況コメンタリーは公式開示の代替にしない"]),
    _S(sourceId="google_news_jp", name="Google News JP (発見手段)",
       assetClasses=["JP_EQUITY"], regions=["JP"], sourceTier="aggregator_discovery",
       rightsClass="public_metadata", collectionMethod="search_discovery",
       provider="Google", feeds=True,
       canGroundJudgment=False, canConfirmCause=False, canBePrimaryLead=False,
       isDiscoveryLayer=True, qualityScore=0.5, freshnessSlaMin=30,
       limitationsJa=["発見手段であり情報源ではない(真の発行元に解決して評価)"]),
    # ━━ US_EQUITY ━━
    _S(sourceId="sec_edgar", name="SEC EDGAR (提出書類)",
       assetClasses=["US_EQUITY", "REITS_XLRE", "CRYPTO_BTC_ETH"], regions=["US"],
       sourceTier="official_regulatory", rightsClass="official",
       collectionMethod="api", provider="SEC", env=[],
       canGroundJudgment=True, canConfirmCause=True, canBePrimaryLead=True,
       isDiscoveryLayer=False, qualityScore=1.0, freshnessSlaMin=30, limitationsJa=[]),
    _S(sourceId="sec_press", name="SEC プレスリリース",
       assetClasses=["US_EQUITY", "CRYPTO_BTC_ETH"], regions=["US"],
       sourceTier="official_regulatory", rightsClass="official",
       collectionMethod="rss", provider="SEC", feeds=True,
       canGroundJudgment=True, canConfirmCause=True, canBePrimaryLead=True,
       isDiscoveryLayer=False, qualityScore=1.0, freshnessSlaMin=30, limitationsJa=[]),
    _S(sourceId="federal_reserve", name="Federal Reserve (FOMC/プレス)",
       assetClasses=["US_EQUITY", "GOLD_GLD", "BONDS_TLT", "FX_USDJPY", "CASH"],
       regions=["US"], sourceTier="central_bank_or_government", rightsClass="official",
       collectionMethod="rss", provider="Fed", feeds=True,
       canGroundJudgment=True, canConfirmCause=True, canBePrimaryLead=True,
       isDiscoveryLayer=False, qualityScore=1.0, freshnessSlaMin=15, limitationsJa=[]),
    _S(sourceId="bls_bea_fred", name="BLS/BEA/FRED (公式マクロ指標)",
       assetClasses=["US_EQUITY", "GOLD_GLD", "BONDS_TLT", "REITS_XLRE", "FX_USDJPY", "CASH"],
       regions=["US"], sourceTier="central_bank_or_government", rightsClass="official",
       collectionMethod="api", provider="BLS/BEA/FRED", env=["FRED_API_KEY"],
       canGroundJudgment=True, canConfirmCause=True, canBePrimaryLead=True,
       isDiscoveryLayer=False, qualityScore=1.0, freshnessSlaMin=30, limitationsJa=[]),
    _S(sourceId="us_treasury", name="米財務省 (入札・声明)",
       assetClasses=["BONDS_TLT", "GOLD_GLD", "FX_USDJPY"], regions=["US"],
       sourceTier="central_bank_or_government", rightsClass="official",
       collectionMethod="html_metadata", env=["__NOT_CONFIGURED__"],
       canGroundJudgment=True, canConfirmCause=True, canBePrimaryLead=True,
       isDiscoveryLayer=False, qualityScore=0.95, freshnessSlaMin=120,
       limitationsJa=["入札結果APIは未実装(V11.5 result-statusでnot_implemented表示)"]),
    _S(sourceId="nasdaq_public", name="Nasdaq Markets",
       assetClasses=["US_EQUITY"], regions=["US"],
       sourceTier="exchange_or_listing_venue", rightsClass="public_metadata",
       collectionMethod="rss", provider="Nasdaq", feeds=True,
       canGroundJudgment=True, canConfirmCause=False, canBePrimaryLead=True,
       isDiscoveryLayer=False, qualityScore=0.8, freshnessSlaMin=30, limitationsJa=[]),
    _S(sourceId="bloomberg_public", name="Bloomberg EN (公開RSS)",
       assetClasses=["US_EQUITY", "GOLD_GLD", "BONDS_TLT", "FX_USDJPY"], regions=["US"],
       sourceTier="reputable_financial_media", rightsClass="public_metadata",
       collectionMethod="rss", provider="Bloomberg", feeds=True,
       canGroundJudgment=True, canConfirmCause=False, canBePrimaryLead=True,
       isDiscoveryLayer=False, qualityScore=0.85, freshnessSlaMin=30,
       limitationsJa=["本文は有料(タイトル+URLのみ)"]),
    _S(sourceId="cnbc_public", name="CNBC (markets/finance/economy/earnings)",
       assetClasses=["US_EQUITY", "BONDS_TLT", "REITS_XLRE", "FX_USDJPY"], regions=["US"],
       sourceTier="reputable_financial_media", rightsClass="public_metadata",
       collectionMethod="rss", provider="CNBC", feeds=True,
       canGroundJudgment=True, canConfirmCause=False, canBePrimaryLead=True,
       isDiscoveryLayer=False, qualityScore=0.8, freshnessSlaMin=30, limitationsJa=[]),
    _S(sourceId="marketwatch_public", name="MarketWatch",
       assetClasses=["US_EQUITY"], regions=["US"],
       sourceTier="reputable_financial_media", rightsClass="public_metadata",
       collectionMethod="rss", provider="Dow Jones", feeds=True,
       canGroundJudgment=True, canConfirmCause=False, canBePrimaryLead=True,
       isDiscoveryLayer=False, qualityScore=0.75, freshnessSlaMin=30, limitationsJa=[]),
    _S(sourceId="yahoo_finance_public", name="Yahoo Finance",
       assetClasses=["US_EQUITY"], regions=["US"],
       sourceTier="reputable_financial_media", rightsClass="public_metadata",
       collectionMethod="rss", provider="Yahoo", feeds=True,
       canGroundJudgment=True, canConfirmCause=False, canBePrimaryLead=True,
       isDiscoveryLayer=False, qualityScore=0.7, freshnessSlaMin=30, limitationsJa=[]),
    _S(sourceId="wsj_ft_barrons", name="WSJ / FT / Barron's",
       assetClasses=["US_EQUITY", "BONDS_TLT", "GOLD_GLD"], regions=["US"],
       sourceTier="licensed_unavailable", rightsClass="licensed_unavailable",
       collectionMethod="disabled", env=["__REQUIRES_CONTRACT__"],
       canGroundJudgment=False, canConfirmCause=False, canBePrimaryLead=False,
       isDiscoveryLayer=False, qualityScore=0.9, freshnessSlaMin=0,
       limitationsJa=["ライセンス契約なし — 本文取得禁止(公開メタデータの範囲でのみ言及可)"]),
    _S(sourceId="finnhub_company_news", name="Finnhub 企業ニュース",
       assetClasses=["US_EQUITY"], regions=["US"], sourceTier="market_data_provider",
       rightsClass="public_metadata", collectionMethod="api", provider="Finnhub",
       env=["FINNHUB_API_KEY"], canGroundJudgment=True, canConfirmCause=False,
       canBePrimaryLead=True, isDiscoveryLayer=False, qualityScore=0.7,
       freshnessSlaMin=15, limitationsJa=["メディア報道の集約(公式開示ではない)"]),
    _S(sourceId="twelvedata", name="Twelve Data (価格/バー)",
       assetClasses=["US_EQUITY", "GOLD_GLD", "BONDS_TLT", "REITS_XLRE", "FX_USDJPY"],
       regions=["US"], sourceTier="market_data_provider", rightsClass="official",
       collectionMethod="api", provider="TwelveData", env=["TWELVEDATA_API_KEY"],
       canGroundJudgment=True, canConfirmCause=False, canBePrimaryLead=False,
       isDiscoveryLayer=False, qualityScore=0.9, freshnessSlaMin=15, limitationsJa=[]),
    _S(sourceId="google_news_us", name="Google News US (発見手段)",
       assetClasses=["US_EQUITY"], regions=["US"], sourceTier="aggregator_discovery",
       rightsClass="public_metadata", collectionMethod="search_discovery",
       provider="Google", feeds=True,
       canGroundJudgment=False, canConfirmCause=False, canBePrimaryLead=False,
       isDiscoveryLayer=True, qualityScore=0.5, freshnessSlaMin=30,
       limitationsJa=["発見手段であり情報源ではない(真の発行元に解決して評価)"]),
    # ━━ GOLD_GLD ━━
    _S(sourceId="lbma", name="LBMA",
       assetClasses=["GOLD_GLD"], regions=["GLOBAL"], sourceTier="specialist_industry_media",
       rightsClass="public_metadata", collectionMethod="disabled", env=["__NOT_CONFIGURED__"],
       canGroundJudgment=True, canConfirmCause=False, canBePrimaryLead=False,
       isDiscoveryLayer=False, qualityScore=0.8, freshnessSlaMin=1440,
       limitationsJa=["無料の機械可読フィードなし — 未構成"]),
    _S(sourceId="world_gold_council", name="World Gold Council",
       assetClasses=["GOLD_GLD"], regions=["GLOBAL"], sourceTier="specialist_industry_media",
       rightsClass="public_metadata", collectionMethod="disabled", env=["__NOT_CONFIGURED__"],
       canGroundJudgment=True, canConfirmCause=False, canBePrimaryLead=False,
       isDiscoveryLayer=False, qualityScore=0.8, freshnessSlaMin=1440,
       limitationsJa=["無料の機械可読フィードなし — 未構成"]),
    _S(sourceId="kitco", name="Kitco (金専門メディア)",
       assetClasses=["GOLD_GLD"], regions=["GLOBAL"], sourceTier="specialist_industry_media",
       rightsClass="public_metadata", collectionMethod="disabled", env=["__NOT_CONFIGURED__"],
       canGroundJudgment=False, canConfirmCause=False, canBePrimaryLead=False,
       isDiscoveryLayer=False, qualityScore=0.6, freshnessSlaMin=60,
       limitationsJa=["安定した公開RSSを未確認 — 未構成(金は金利/ドル/リスクデータで代替)"]),
    # ━━ CRYPTO ━━
    _S(sourceId="coingecko", name="CoinGecko (価格/市場データ)",
       assetClasses=["CRYPTO_BTC_ETH"], regions=["GLOBAL"], sourceTier="market_data_provider",
       rightsClass="official", collectionMethod="api", provider="CoinGecko", env=[],
       canGroundJudgment=True, canConfirmCause=False, canBePrimaryLead=False,
       isDiscoveryLayer=False, qualityScore=0.85, freshnessSlaMin=15, limitationsJa=[]),
    _S(sourceId="coindesk", name="CoinDesk",
       assetClasses=["CRYPTO_BTC_ETH"], regions=["GLOBAL"],
       sourceTier="specialist_industry_media", rightsClass="public_metadata",
       collectionMethod="rss", provider="CoinDesk", feeds=True,
       canGroundJudgment=True, canConfirmCause=False, canBePrimaryLead=True,
       isDiscoveryLayer=False, qualityScore=0.75, freshnessSlaMin=30, limitationsJa=[]),
    _S(sourceId="cointelegraph", name="Cointelegraph",
       assetClasses=["CRYPTO_BTC_ETH"], regions=["GLOBAL"],
       sourceTier="specialist_industry_media", rightsClass="public_metadata",
       collectionMethod="rss", provider="Cointelegraph", feeds=True,
       canGroundJudgment=True, canConfirmCause=False, canBePrimaryLead=True,
       isDiscoveryLayer=False, qualityScore=0.65, freshnessSlaMin=30,
       limitationsJa=["専門メディア(単独では原因確定不可)"]),
    _S(sourceId="theblock_decrypt", name="The Block / Decrypt",
       assetClasses=["CRYPTO_BTC_ETH"], regions=["GLOBAL"],
       sourceTier="specialist_industry_media", rightsClass="public_metadata",
       collectionMethod="disabled", env=["__NOT_CONFIGURED__"],
       canGroundJudgment=False, canConfirmCause=False, canBePrimaryLead=False,
       isDiscoveryLayer=False, qualityScore=0.6, freshnessSlaMin=60,
       limitationsJa=["未構成(CoinDesk/Cointelegraphでカバー)"]),
    _S(sourceId="cftc_ofac", name="CFTC / OFAC (規制)",
       assetClasses=["CRYPTO_BTC_ETH"], regions=["US"],
       sourceTier="official_regulatory", rightsClass="official",
       collectionMethod="disabled", env=["__NOT_CONFIGURED__"],
       canGroundJudgment=True, canConfirmCause=True, canBePrimaryLead=True,
       isDiscoveryLayer=False, qualityScore=0.95, freshnessSlaMin=240,
       limitationsJa=["直接フィード未構成(SEC/報道メタデータ経由で検知)"]),
    # ━━ REITS ━━
    _S(sourceId="nareit", name="NAREIT / REIT.com",
       assetClasses=["REITS_XLRE"], regions=["US"], sourceTier="specialist_industry_media",
       rightsClass="public_metadata", collectionMethod="disabled", env=["__NOT_CONFIGURED__"],
       canGroundJudgment=True, canConfirmCause=False, canBePrimaryLead=False,
       isDiscoveryLayer=False, qualityScore=0.7, freshnessSlaMin=1440,
       limitationsJa=["無料フィード未確認 — 未構成(金利/SEC/報道でカバー)"]),
    # ━━ FUND_ACCUMULATION ━━
    _S(sourceId="toushin_lib", name="投信総合ライブラリー (基準価額)",
       assetClasses=["FUND_ACCUMULATION"], regions=["JP"], sourceTier="market_data_provider",
       rightsClass="public_metadata", collectionMethod="disabled", env=["__NOT_CONFIGURED__"],
       canGroundJudgment=False, canConfirmCause=False, canBePrimaryLead=False,
       isDiscoveryLayer=False, qualityScore=0.7, freshnessSlaMin=1440,
       limitationsJa=["基準価額APIは未構成 — 積立は指数/為替の複合(dca_policy)として扱う"]),
]


# ── status resolution ────────────────────────────────────────────────────────
def _status_of(src: Dict[str, Any], configured: Dict[str, bool]) -> str:
    env = src.get("env") or []
    if "__REQUIRES_CONTRACT__" in env:
        return "requires_contract"
    if "__NOT_CONFIGURED__" in env:
        return "not_configured"
    if src.get("collectionMethod") == "disabled":
        return "disabled"
    if src.get("feeds"):                      # public RSS collected by the 24/7 cron
        return "live"
    if env and not all(configured.get(e) for e in env):
        return "not_configured"
    return "live"


def build_universe(configured: Optional[Dict[str, bool]], now_iso: str) -> Dict[str, Any]:
    configured = configured or {}
    out = []
    for s in SOURCES:
        d = {k: v for k, v in s.items() if k not in ("env", "feeds")}
        d["configuredEnv"] = [e for e in (s.get("env") or []) if not e.startswith("__")]
        d["status"] = _status_of(s, configured)
        out.append(d)
    by_class: Dict[str, List[str]] = {}
    for s in out:
        for ac in s["assetClasses"]:
            by_class.setdefault(ac, []).append(s["sourceId"])
    return {"schemaVersion": SCHEMA_VERSION, "asOf": now_iso,
            "sources": out, "sourcesByAssetClass": by_class,
            "noteJa": "Google Newsは発見手段(sourceTierではない)。弱いソースは判断の根拠にしない。"
                      "有料本文は権利がない限り取得しない(公開メタデータのみ)。"}


# ── discovery resolution (Google News / aggregator → true publisher) ─────────
_FAMILY_PATTERNS = [
    # (family, tier, rights, patterns on publisher-label/url)
    ("nikkei", "reputable_financial_media", "public_metadata",
     ("日本経済新聞", "日経", "nikkei")),
    ("reuters", "wire_service", "public_metadata", ("reuters", "ロイター")),
    ("bloomberg", "reputable_financial_media", "public_metadata", ("bloomberg", "ブルームバーグ")),
    ("cnbc", "reputable_financial_media", "public_metadata", ("cnbc",)),
    ("nhk", "reputable_financial_media", "public_metadata", ("nhk",)),
    ("marketwatch", "reputable_financial_media", "public_metadata", ("marketwatch",)),
    ("yahoo_finance", "reputable_financial_media", "public_metadata",
     ("yahoo!ファイナンス", "yahoo finance", "yahoo!ニュース", "finance.yahoo")),
    ("wsj", "licensed_unavailable", "licensed_unavailable", ("wall street journal", "wsj")),
    ("ft", "licensed_unavailable", "licensed_unavailable", ("financial times", "ft.com")),
    ("barrons", "licensed_unavailable", "licensed_unavailable", ("barron",)),
    ("kabutan", "specialist_industry_media", "public_metadata", ("株探", "kabutan")),
    ("minkabu", "specialist_industry_media", "public_metadata", ("みんかぶ", "minkabu")),
    ("toyokeizai", "specialist_industry_media", "public_metadata", ("東洋経済",)),
    ("diamond", "specialist_industry_media", "public_metadata", ("ダイヤモンド",)),
    ("coindesk", "specialist_industry_media", "public_metadata", ("coindesk",)),
    ("cointelegraph", "specialist_industry_media", "public_metadata", ("cointelegraph",)),
    ("theblock", "specialist_industry_media", "public_metadata", ("the block",)),
    ("decrypt", "specialist_industry_media", "public_metadata", ("decrypt",)),
    ("kitco", "specialist_industry_media", "public_metadata", ("kitco",)),
    ("sec", "official_regulatory", "official", ("sec.gov", "sec edgar", "u.s. securities")),
    ("federal_reserve", "central_bank_or_government", "official",
     ("federalreserve", "federal reserve", "frb")),
    ("boj", "central_bank_or_government", "official", ("日本銀行", "boj.or.jp", "bank of japan")),
    ("mof", "central_bank_or_government", "official", ("財務省", "mof.go.jp")),
    ("meti", "central_bank_or_government", "official", ("経済産業省", "meti.go.jp")),
    ("jpx", "exchange_or_listing_venue", "official", ("日本取引所", "jpx.co.jp", "東証")),
    ("company_ir", "official_corporate", "official", ("prtimes", "ir資料", "決算説明会")),
]

_WEAK_HINTS = ("youtube", "tiktok", "note.com", "blog", "matome", "5ch", "reddit",
               "twitter", "x.com", "facebook", "instagram", "seekingalpha")  # SA=opinion


def resolve_publisher(title: str = "", source_label: str = "", url: str = "",
                      published_at: str = "") -> Dict[str, Any]:
    """Aggregator item → true publisher classification. Google News titles carry
    'Headline - Publisher'; the publisher decides the tier — the aggregator never
    does. Unknown publisher = weak_signal (can't ground/confirm/lead)."""
    label = (source_label or "").strip()
    is_discovery = ("google_news" in label.lower() or "news.google" in (url or "").lower()
                    or label.lower() in ("google", "googlenewsjp", "googlenews"))
    # candidate publisher text: explicit label first, else the " - Publisher" suffix
    pub_text = label
    if is_discovery or not pub_text:
        m = re.search(r"\s[-–—]\s([^-–—]{2,40})\s*$", title or "")
        pub_text = (m.group(1) if m else "").strip() or label
    hay = f"{pub_text} {url or ''}".lower()
    for family, tier, rights, pats in _FAMILY_PATTERNS:
        if any(p in hay for p in pats):
            licensed = tier == "licensed_unavailable"
            return {"truePublisher": pub_text or family, "sourceFamily": family,
                    "sourceTier": tier, "rightsClass": rights,
                    "isDiscoveryLayer": is_discovery,
                    "canBePrimaryLead": not licensed,
                    "canConfirmCause": tier in ("official_regulatory",
                                                "central_bank_or_government",
                                                "official_corporate",
                                                "exchange_or_listing_venue"),
                    "weakSignal": False}
    weak = (not pub_text) or any(h in hay for h in _WEAK_HINTS)
    if weak:
        return {"truePublisher": pub_text or "unknown", "sourceFamily": "weak_signal",
                "sourceTier": "weak_signal", "rightsClass": "unknown",
                "isDiscoveryLayer": is_discovery, "canBePrimaryLead": False,
                "canConfirmCause": False, "weakSignal": True}
    # named but unrecognised publisher: keep as low-trust single source (not weak-spam,
    # but never a confirmer and only a lead when nothing better exists)
    return {"truePublisher": pub_text, "sourceFamily": "unrecognized_media",
            "sourceTier": "weak_signal", "rightsClass": "public_metadata",
            "isDiscoveryLayer": is_discovery, "canBePrimaryLead": False,
            "canConfirmCause": False, "weakSignal": True}


def corroboration_family_count(items: List[Dict[str, Any]]) -> int:
    """Distinct TRUE-publisher families across items (two syndicated copies of the
    same family count once; weak/unknown families don't count at all)."""
    fams = set()
    for it in items or []:
        r = resolve_publisher(str(it.get("title") or it.get("headline") or ""),
                              str(it.get("source") or it.get("publisher") or ""),
                              str(it.get("url") or it.get("canonicalUrl") or ""))
        if not r["weakSignal"]:
            fams.add(r["sourceFamily"])
    return len(fams)
