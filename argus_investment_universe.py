"""ARGUS V11.5.3 — Investment Universe (pure, deterministic, stdlib-only).

Core Portfolio is the source of truth for WHAT ARGUS watches. This module encodes
those asset classes (verified against web/src/routes/CorePortfolio.tsx and the
core-action-alerts backend: JP/US individual stocks, GLD, TLT, XLRE, BTC/ETH,
USD/JPY, cash, and the accumulation funds) so C.A.O.S. source coverage and the
Watchtower plan are derived from the portfolio, not from an ad-hoc feed list.

Funds are DCA-policy context, NOT short-term trading signals — no BUY/SELL fund
calls off a daily NAV chart. Cash has no news lead of its own; it is a posture
class driven by rates/volatility/event-risk/visibility.
"""
from __future__ import annotations

from typing import Any, Dict, List

SCHEMA_VERSION = "investment-universe-v1"

ASSET_CLASSES: List[Dict[str, Any]] = [
    {
        "assetClass": "JP_EQUITY", "labelJa": "日本個別株", "enabled": True,
        "corePortfolioLabel": "Japan Individual Stocks",
        "representatives": [],                     # watchlist supplies the symbols
        "primaryIdentifiers": ["ticker", "companyName", "isin"],
        "coreEvents": ["tdnet", "edinet", "earnings", "guidance", "buyback",
                       "dilution", "company_ir"],
        "watchPriority": "high",
        "sourceCoverageRequired": ["official", "professional_media", "market_data", "discovery"],
        "limitationsJa": [],
    },
    {
        "assetClass": "US_EQUITY", "labelJa": "米国個別株", "enabled": True,
        "corePortfolioLabel": "US Individual Stocks",
        "representatives": [],
        "primaryIdentifiers": ["ticker", "companyName"],
        "coreEvents": ["sec_filing", "earnings", "guidance", "buyback", "company_ir"],
        "watchPriority": "high",
        "sourceCoverageRequired": ["official", "professional_media", "market_data", "discovery"],
        "limitationsJa": [],
    },
    {
        "assetClass": "GOLD_GLD", "labelJa": "金 (GLD)", "enabled": True,
        "corePortfolioLabel": "Gold (GLD)",
        "representatives": ["GLD"],
        "primaryIdentifiers": ["ticker"],
        "coreEvents": ["fomc", "cpi", "real_yields", "usd_moves", "risk_off"],
        "watchPriority": "normal",
        "sourceCoverageRequired": ["official", "market_data", "specialist_media"],
        "limitationsJa": ["金は個別ニュースより金利/ドル/リスクイベント駆動として扱う"],
    },
    {
        "assetClass": "BONDS_TLT", "labelJa": "米国債 (TLT)", "enabled": True,
        "corePortfolioLabel": "Bonds (TLT)",
        "representatives": ["TLT"],
        "primaryIdentifiers": ["ticker"],
        "coreEvents": ["fomc", "treasury_auction", "cpi", "nfp", "gdp"],
        "watchPriority": "normal",
        "sourceCoverageRequired": ["official", "market_data", "professional_media"],
        "limitationsJa": [],
    },
    {
        "assetClass": "REITS_XLRE", "labelJa": "REIT (XLRE)", "enabled": True,
        "corePortfolioLabel": "REITs (XLRE)",
        "representatives": ["XLRE"],
        "primaryIdentifiers": ["ticker"],
        "coreEvents": ["fomc", "mortgage_rates", "sec_filing"],
        "watchPriority": "normal",
        "sourceCoverageRequired": ["official", "market_data", "professional_media"],
        "limitationsJa": ["REIT専門メディアの無料APIが無くカバレッジはpartial"],
    },
    {
        "assetClass": "CRYPTO_BTC_ETH", "labelJa": "暗号資産 (BTC/ETH)", "enabled": True,
        "corePortfolioLabel": "Crypto",
        "representatives": ["BTC", "ETH"],
        "primaryIdentifiers": ["ticker"],
        "coreEvents": ["regulatory", "etf_flows", "exchange_incident", "risk_events"],
        "watchPriority": "normal",
        "sourceCoverageRequired": ["market_data", "specialist_media", "official"],
        "limitationsJa": [],
    },
    {
        "assetClass": "FX_USDJPY", "labelJa": "ドル円 (USD/JPY)", "enabled": True,
        "corePortfolioLabel": "USD/JPY",
        "representatives": ["USDJPY"],
        "primaryIdentifiers": ["pair"],
        "coreEvents": ["boj", "fomc", "mof_intervention", "cpi", "nfp"],
        "watchPriority": "high",
        "sourceCoverageRequired": ["official", "market_data", "professional_media"],
        "limitationsJa": [],
    },
    {
        "assetClass": "CASH", "labelJa": "現金・待機資金", "enabled": True,
        "corePortfolioLabel": "Cash",
        "representatives": [],
        "primaryIdentifiers": [],
        "coreEvents": ["fomc", "boj", "event_risk", "visibility_regime"],
        "watchPriority": "low",
        "sourceCoverageRequired": ["official", "market_data"],
        "limitationsJa": ["現金は単独のニュース対象ではなく、金利・ボラ・イベントリスク・可視性で決まる姿勢クラス"],
    },
    {
        "assetClass": "FUND_ACCUMULATION", "labelJa": "積立ファンド", "enabled": True,
        "corePortfolioLabel": "Investment Trusts (積立)",
        "representatives": ["EMAXIS-N225", "EMAXIS-SP500", "EMAXIS-ACWI"],
        "primaryIdentifiers": ["fundCode", "fundName"],
        "coreEvents": ["underlying_index_moves", "fx_usdjpy", "policy_changes"],
        "watchPriority": "low",
        "sourceCoverageRequired": ["market_data"],
        "limitationsJa": ["積立は基準価額チャートの短期判断ではなく、地合い連動の積立方針として扱う"],
    },
]

FUNDS: List[Dict[str, Any]] = [
    {
        "fundCode": "EMAXIS-N225",
        "nameJa": "eMAXIS Slim 国内株式（日経平均）",
        "underlyingExposure": ["JP_EQUITY", "ETF_INDEX"],
        "decisionMode": "dca_policy",
        "noteJa": "積立は基準価額チャートの短期判断ではなく、地合い連動の積立方針として扱う。",
    },
    {
        "fundCode": "EMAXIS-SP500",
        "nameJa": "eMAXIS Slim 米国株式（S&P500）",
        "underlyingExposure": ["US_EQUITY", "ETF_INDEX", "FX_USDJPY"],
        "decisionMode": "dca_policy",
        "noteJa": "米国株指数+為替の複合。日次NAVで売買判断しない。",
    },
    {
        "fundCode": "EMAXIS-ACWI",
        "nameJa": "eMAXIS Slim 全世界株式（オール・カントリー）",
        "underlyingExposure": ["US_EQUITY", "JP_EQUITY", "ETF_INDEX", "FX_USDJPY"],
        "decisionMode": "dca_policy",
        "noteJa": "全世界分散。個別ニュースではなく地合い/金利/為替の複合で扱う。",
    },
]

REQUIRED_CLASSES = [c["assetClass"] for c in ASSET_CLASSES]


def build_universe(now_iso: str) -> Dict[str, Any]:
    """The public-safe universe document. No holdings/amounts — classes only."""
    return {
        "schemaVersion": SCHEMA_VERSION,
        "asOf": now_iso,
        "assetClasses": [dict(c) for c in ASSET_CLASSES],
        "funds": [dict(f) for f in FUNDS],
        "noteJa": "Core Portfolioの資産クラスをC.A.O.S.監視の基準とする。"
                  "保有の有無・金額は含まない(公開安全)。",
    }


def asset_class_of_symbol(symbol: str, market: str = "") -> str:
    """Best-effort class for a symbol (watchlist/mover targeting)."""
    s = str(symbol or "").upper()
    if s in ("GLD",):
        return "GOLD_GLD"
    if s in ("TLT",):
        return "BONDS_TLT"
    if s in ("XLRE",):
        return "REITS_XLRE"
    if s in ("BTC", "ETH"):
        return "CRYPTO_BTC_ETH"
    if s in ("USDJPY", "USD/JPY"):
        return "FX_USDJPY"
    if s.startswith("EMAXIS") or str(market).upper() in ("FUND", "CORE"):
        return "FUND_ACCUMULATION"
    if str(market).upper() == "JP" or (s[:1].isdigit() and len(s) in (4, 5)):
        return "JP_EQUITY"
    if str(market).upper() == "CRYPTO":
        return "CRYPTO_BTC_ETH"
    return "US_EQUITY"
