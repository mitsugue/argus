"""ARGUS V11.8.0 — Position / Exposure Engine (pure, deterministic).

Answers the owner's portfolio questions — 「偏りすぎか」「買い増ししてよいか」
「ここで追っていいか」「保有中だから逃げるべきか」 — as a RISK/decision-support
layer. No trading, no broker, no orders.

PRIVACY BY DESIGN (unchanged architecture): actual quantities / average costs
live ONLY in the owner's device (frontend localStorage). This module is pure
math over whatever position list the CALLER supplies:
  - the frontend calls the TypeScript port with real device-local holdings;
  - the backend calls this module ONLY with the public watchlist (no
    quantities), so public endpoints structurally cannot leak holdings.

HONESTY RULES:
  - total portfolio unknown → concentration = unknown, never "high".
  - quantity or cost missing → no P&L, no fabricated weights; say 未入力.
  - stale price → staleDataFlag + confidence down.
  - "trim_consideration" is a risk-review label, never a sell instruction.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

SCHEMA_VERSION = "position-exposure-v1"

ASSET_CLASSES = ("jp_stock", "us_stock", "etf", "mutual_fund", "crypto", "cash", "other")
ACCOUNT_TYPES = ("taxable", "nisa", "ideco", "corporate", "unknown")
RISK_LEVELS = ("low", "medium", "high", "critical", "unknown")
RISK_TYPES = ("concentration", "drawdown", "chase_risk", "event_risk", "regime_mismatch",
              "liquidity", "theme_overcrowding", "currency", "valuation", "data_stale", "unknown")
ACTIONS = ("hold", "monitor", "wait", "avoid_chase", "trim_consideration",
           "add_only_on_pullback", "add_allowed_small", "investigate", "no_action", "unknown")
ACTION_JA = {
    "hold": "保有継続", "monitor": "監視継続", "wait": "見送り",
    "avoid_chase": "追いかけ買い注意", "trim_consideration": "比率見直し検討(売り指示ではない)",
    "add_only_on_pullback": "買い増しは押し目限定", "add_allowed_small": "小さく買い増し可",
    "investigate": "要調査", "no_action": "対応不要", "unknown": "判定保留(データ未入力)",
}

THEMES = ("ai_infrastructure", "physical_ai_robotics", "semiconductor_photonics",
          "defense_heavy_industry", "telecom_platform", "trading_commodity",
          "gold", "crypto", "index_core", "other")
THEME_JA = {
    "ai_infrastructure": "AIインフラ", "physical_ai_robotics": "フィジカルAI/ロボット",
    "semiconductor_photonics": "半導体/光技術", "defense_heavy_industry": "防衛/重工",
    "telecom_platform": "通信/プラットフォーム", "trading_commodity": "商社/資源",
    "gold": "金", "crypto": "暗号資産", "index_core": "インデックス積立", "other": "その他",
}
# Conservative symbol→theme map (public tickers only — no owner data). Unknown
# symbols fall to "other"; we never over-classify on weak evidence.
THEME_MAP = {
    # AI infrastructure (datacenter / AI capex complex incl. cable)
    "NVDA": "ai_infrastructure", "AVGO": "ai_infrastructure", "TSM": "ai_infrastructure",
    "SMH": "ai_infrastructure", "MSFT": "ai_infrastructure", "AMZN": "ai_infrastructure",
    "GOOGL": "ai_infrastructure", "GOOG": "ai_infrastructure", "SMCI": "ai_infrastructure",
    "9984": "ai_infrastructure",   # SoftBank G (AI investment holding)
    "5803": "ai_infrastructure", "5801": "ai_infrastructure",   # Fujikura/Furukawa (DC cable)
    "6920": "ai_infrastructure",   # Lasertec
    "IONQ": "ai_infrastructure",
    # physical AI / robotics / EV
    "TSLA": "physical_ai_robotics", "6954": "physical_ai_robotics",
    "6506": "physical_ai_robotics", "6584": "physical_ai_robotics",   # Sanoh
    # semiconductor devices / photonics
    "285A": "semiconductor_photonics",  # Kioxia
    "6965": "semiconductor_photonics",  # Hamamatsu Photonics
    "6857": "semiconductor_photonics",  # Advantest
    "6146": "semiconductor_photonics",  # Disco
    "8035": "semiconductor_photonics",  # Tokyo Electron
    "AMD": "semiconductor_photonics", "MU": "semiconductor_photonics",
    # defense / heavy industry
    "7011": "defense_heavy_industry", "7012": "defense_heavy_industry",
    "7013": "defense_heavy_industry",
    # telecom / platform / consumer tech
    "AAPL": "telecom_platform", "META": "telecom_platform",
    "9432": "telecom_platform", "9433": "telecom_platform", "9434": "telecom_platform",
    # trading company / commodity
    "8058": "trading_commodity", "8001": "trading_commodity", "8031": "trading_commodity",
    # gold
    "314A": "gold", "1540": "gold", "GLD": "gold",
}
_GOLD_WORDS = ("ゴールド", "gold", "金価格", "純金")
_INDEX_WORDS = ("s&p", "sp500", "オルカン", "全世界", "all country", "インデックス",
                "index", "topix", "日経225", "nasdaq100")

# Explicit, overridable thresholds (fractions of total portfolio value).
DEFAULT_THRESHOLDS = {
    "single_name_medium": 0.15, "single_name_high": 0.25, "single_name_critical": 0.40,
    "theme_medium": 0.25, "theme_high": 0.40,
    "crypto_high": 0.20, "currency_high": 0.80,
    "stale_minutes": 24 * 60,
}


def classify_theme(symbol: str, market: str = "", asset_type: str = "", name: str = "") -> str:
    symu = str(symbol or "").upper()
    if symu in THEME_MAP:
        return THEME_MAP[symu]
    if str(market).upper() == "CRYPTO" or asset_type == "crypto":
        return "crypto"
    low = (name or "").lower()
    if any(w in low for w in _GOLD_WORDS):
        return "gold"
    if asset_type in ("core_fund", "manual_fund", "mutual_fund") \
            or any(w in low for w in _INDEX_WORDS):
        return "index_core"
    return "other"


def _asset_class(market: str, asset_type: str = "") -> str:
    m = str(market).upper()
    if asset_type in ("core_fund", "manual_fund", "mutual_fund"):
        return "mutual_fund"
    if asset_type == "listed_etf":
        return "etf"
    if m == "JP":
        return "jp_stock"
    if m == "US":
        return "us_stock"
    if m == "CRYPTO":
        return "crypto"
    if m == "CASH":
        return "cash"
    return "other"


def _f(v) -> Optional[float]:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def normalize_position(raw: Dict[str, Any], now_iso: str) -> Dict[str, Any]:
    """Raw entry → Position. NEVER fabricates: value/P&L only when quantity,
    cost and a usable price all exist."""
    sym = str(raw.get("symbol") or "").upper()
    market = str(raw.get("market") or "").upper()
    qty, cost, price = _f(raw.get("quantity")), _f(raw.get("averageCost")), _f(raw.get("currentPrice"))
    if qty is not None and qty <= 0:
        qty = None
    currency = raw.get("currency") or ("JPY" if market == "JP" else "USD")
    stale = bool(raw.get("staleDataFlag"))
    mv = round(qty * price, 2) if (qty is not None and price is not None) else None
    cb = round(qty * cost, 2) if (qty is not None and cost is not None) else None
    pnl = round(mv - cb, 2) if (mv is not None and cb is not None) else None
    pnl_pct = round(pnl / cb * 100, 2) if (pnl is not None and cb and cb > 0) else None
    conf = 0.9 if (qty is not None and cost is not None and price is not None) else \
           0.5 if price is not None else 0.2
    if stale:
        conf = min(conf, 0.4)
    return {
        "id": raw.get("id") or f"pos-{market}-{sym}",
        "symbol": sym, "market": market,
        "name": raw.get("name") or sym,
        "assetClass": _asset_class(market, raw.get("assetType") or ""),
        "accountType": (raw.get("accountType") if raw.get("accountType") in ACCOUNT_TYPES
                        else "unknown"),
        "theme": classify_theme(sym, market, raw.get("assetType") or "", raw.get("name") or ""),
        "quantity": qty, "averageCost": cost, "currency": currency,
        "currentPrice": price, "marketValue": mv, "costBasis": cb,
        "unrealizedPnl": pnl, "unrealizedPnlPct": pnl_pct,
        "realizedPnl": _f(raw.get("realizedPnl")),
        "held": qty is not None,
        "lastUpdatedAt": raw.get("lastUpdatedAt") or now_iso,
        "dataSource": (raw.get("dataSource") if raw.get("dataSource") in
                       ("manual", "csv", "existing_argus", "fallback", "unknown") else "existing_argus"),
        "confidence": conf, "staleDataFlag": stale,
        "ownerNote": raw.get("ownerNote"),
    }


def compute_exposure(positions: List[Dict[str, Any]], usd_jpy: Optional[float] = None,
                     thresholds: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    """Aggregate exposure in JPY terms. Positions without value are counted in
    unknownExposureShare, never guessed. Without usd_jpy, USD legs stay unknown."""
    th = dict(DEFAULT_THRESHOLDS, **(thresholds or {}))
    held = [p for p in positions if p.get("held")]
    valued: List[Dict[str, Any]] = []
    unknown_ct = 0
    for p in held:
        mv = p.get("marketValue")
        if mv is None:
            unknown_ct += 1
            continue
        if p.get("currency") == "USD":
            if usd_jpy is None:
                unknown_ct += 1
                continue
            mv = mv * usd_jpy
        valued.append(dict(p, _jpy=mv))
    total = round(sum(p["_jpy"] for p in valued), 2) if valued else None

    def _by(key_fn):
        agg: Dict[str, float] = {}
        for p in valued:
            k = key_fn(p)
            agg[k] = agg.get(k, 0.0) + p["_jpy"]
        if not total:
            return {}
        return {k: round(v / total, 4) for k, v in sorted(agg.items(), key=lambda kv: -kv[1])}

    ranked = sorted(valued, key=lambda p: -p["_jpy"])
    def _top(n):
        return round(sum(p["_jpy"] for p in ranked[:n]) / total, 4) if total else None

    by_theme = _by(lambda p: p["theme"])
    by_ccy = _by(lambda p: p["currency"])
    top1 = _top(1)
    ai_th = round(sum(v for k, v in by_theme.items()
                      if k in ("ai_infrastructure", "physical_ai_robotics",
                               "semiconductor_photonics")), 4) if by_theme else None
    n_held = len(held)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "positionsHeld": n_held, "positionsValued": len(valued),
        "totalMarketValue": total, "totalCurrency": "JPY",
        "byAssetClass": _by(lambda p: p["assetClass"]),
        "byCurrency": by_ccy,
        "byMarket": _by(lambda p: p["market"]),
        "bySector": {},                      # no sector feed yet — honest empty
        "byTheme": by_theme,
        "byRiskFactor": {}, "byTimeHorizon": {}, "byLiquidity": {}, "byConviction": {},
        "concentrationTop1": top1, "concentrationTop3": _top(3), "concentrationTop5": _top(5),
        "topPositions": [{"symbol": p["symbol"], "theme": p["theme"],
                          "weight": round(p["_jpy"] / total, 4)} for p in ranked[:5]] if total else [],
        "singleNameRisk": (None if top1 is None else
                           "critical" if top1 >= th["single_name_critical"] else
                           "high" if top1 >= th["single_name_high"] else
                           "medium" if top1 >= th["single_name_medium"] else "low"),
        "themeConcentrationRisk": (None if not by_theme else
                                   "high" if max(by_theme.values()) >= th["theme_high"] else
                                   "medium" if max(by_theme.values()) >= th["theme_medium"]
                                   else "low"),
        "currencyRisk": (None if not by_ccy else
                         "high" if max(by_ccy.values()) >= th["currency_high"] else "low"),
        "rateSensitivity": ("high" if ai_th is not None and ai_th >= 0.4 else
                            "medium" if ai_th is not None and ai_th >= 0.2 else
                            "low" if ai_th is not None else None),
        "growthFactorExposure": ai_th,
        "AIThemeExposure": ai_th,
        "JapanEquityExposure": (by_ccy.get("JPY") if by_ccy else None),
        "USDExposure": (by_ccy.get("USD") if by_ccy else None),
        "cryptoExposure": (by_theme.get("crypto") if by_theme else None),
        "goldExposure": (by_theme.get("gold") if by_theme else None),
        "cashBuffer": None,                  # not tracked yet — honest null
        "unknownExposureShare": (round(unknown_ct / n_held, 4) if n_held else None),
        "usdJpyUsed": usd_jpy,
        "thresholds": {k: th[k] for k in ("single_name_medium", "single_name_high",
                                          "single_name_critical", "theme_medium", "theme_high")},
        "noteJa": (None if valued else
                   "ポジション数量・取得単価が未入力のため、保有リスクは暫定です"
                   "(ウォッチリストのテーマ露出のみ表示)。"),
    }


# ── position risk signals + add-more readiness ──────────────────────────────

def position_risk_signals(positions, exposure, ctx=None, cap=8):
    """Deterministic held-position risks. ctx (all optional):
    regimeRiskOff, regimeLabel, flowBySymbol {SYM: flowClass}, eventSymbols set,
    runupBySymbol {SYM: pct}. Watch-only entries never produce held-position
    risk — they stay watchlist signals."""
    ctx = ctx or {}
    out = []
    total = exposure.get("totalMarketValue")
    weights = {t["symbol"]: t["weight"] for t in exposure.get("topPositions") or []}
    by_theme = exposure.get("byTheme") or {}
    th = dict(DEFAULT_THRESHOLDS)
    flow_by = {k.upper(): v for k, v in (ctx.get("flowBySymbol") or {}).items()}
    events = {str(s).upper() for s in (ctx.get("eventSymbols") or [])}

    for p in positions:
        if not p.get("held"):
            continue
        sym = p["symbol"]
        w = weights.get(sym)
        # concentration
        if w is not None and w >= th["single_name_medium"]:
            lvl = ("critical" if w >= th["single_name_critical"] else
                   "high" if w >= th["single_name_high"] else "medium")
            out.append(_sig(sym, lvl, "concentration",
                            f"この1銘柄がポートフォリオの約{round(w*100)}%を占めています。"
                            f"値動き1つで全体が大きく揺れる比率です。",
                            "比率を意識し、買い増しよりも分散を優先するか検討",
                            "trim_consideration" if lvl != "medium" else "monitor",
                            0.8, [f"weight={w}"], []))
        # theme overcrowding (attach to the largest position of the heavy theme)
        tw = by_theme.get(p["theme"])
        if tw is not None and tw >= th["theme_high"] and w is not None:
            out.append(_sig(sym, "high", "theme_overcrowding",
                            f"{THEME_JA.get(p['theme'], p['theme'])}テーマ合計が約{round(tw*100)}%。"
                            f"テーマ全体の巻き戻しに弱い構成です。",
                            "同テーマの追加購入は押し目確認後に限定し、他テーマとの比率を確認",
                            "add_only_on_pullback", 0.75, [f"theme={p['theme']} {tw}"], []))
        # drawdown on a held name
        pnl_pct = p.get("unrealizedPnlPct")
        if pnl_pct is not None and pnl_pct <= -15:
            out.append(_sig(sym, "high" if pnl_pct <= -25 else "medium", "drawdown",
                            f"取得単価から約{abs(round(pnl_pct))}%の含み損。ナンピンの前に"
                            f"下落原因(原因の詳細)を確認すべき水準です。",
                            "原因の詳細とイベント予定を確認してから対応を判断",
                            "investigate", 0.8, [f"pnlPct={pnl_pct}"], []))
        # flow overlay — held position + adverse flow reading is a HELD risk
        fc = (flow_by.get(sym) or {}).get("flowClass") if isinstance(flow_by.get(sym), dict) \
            else flow_by.get(sym)
        if fc in ("panic_selling", "distribution", "profit_taking"):
            out.append(_sig(sym, "high" if fc == "panic_selling" else "medium",
                            "regime_mismatch" if ctx.get("regimeRiskOff") else "event_risk",
                            f"保有中の銘柄に売り圧力の推定({fc})が出ています。"
                            f"監視銘柄なら様子見で済みますが、保有中のため優先確認対象です。",
                            "翌営業日の続き(戻りが売られるか)と公式材料を確認",
                            "monitor", 0.6, [f"flow={fc}"],
                            ["実測フローの裏付け(推定ベース)"]))
        if fc == "retail_chase":
            out.append(_sig(sym, "medium", "chase_risk",
                            "個人の追随買いの型が出ています。保有分は維持しつつ、"
                            "ここからの買い増しは高値掴みリスクがあります。",
                            "押し目まで待てるかを確認", "avoid_chase", 0.6,
                            [f"flow={fc}"], []))
        # event risk on held name
        if sym in events:
            out.append(_sig(sym, "medium", "event_risk",
                            "保有中の銘柄に本日〜直近の重要イベントがあります。"
                            "イベント通過までポジションを増やさないのが基本です。",
                            "イベント結果と初動反応を確認", "wait", 0.7, ["event=today"], []))
        # stale data
        if p.get("staleDataFlag"):
            out.append(_sig(sym, "unknown", "data_stale",
                            "価格データが古いため、この銘柄の評価・リスク判定は暫定です。",
                            "市場再開後の実価格で再確認", "monitor", 0.3, [],
                            ["最新価格"]))
        # held but size unknown
        if p.get("quantity") is None:
            out.append(_sig(sym, "unknown", "unknown",
                            "保有数量・取得単価が未入力のため、ポジションリスクは判定できません。",
                            "Watchlistの銘柄行に数量と取得単価を入力(端末内のみ・送信されない)",
                            "unknown", 0.2, [], ["保有数量", "取得単価"]))
    if total is None and not out:
        out.append(_sig("PORTFOLIO", "unknown", "unknown",
                        "ポジション数量・取得単価が未入力のため、保有リスクは暫定です。",
                        "Watchlistで保有数量・取得単価を入力すると、集中度・テーマ偏りを判定します",
                        "unknown", 0.2, [], ["保有数量", "取得単価"]))
    sev = {"critical": 0, "high": 1, "medium": 2, "low": 3, "unknown": 4}
    out.sort(key=lambda s: (sev.get(s["riskLevel"], 9), -s["confidence"]))
    return out[:cap]


def _sig(sym, level, rtype, why, check, action, conf, evidence, missing):
    return {"symbol": sym, "riskLevel": level, "riskType": rtype,
            "ownerReadableWhyJa": why, "checkNextJa": check,
            "actionImplication": action, "actionImplicationJa": ACTION_JA[action],
            "confidence": conf, "evidence": evidence, "missingEvidence": missing,
            "complianceNote": "リスク点検のラベルであり売買指示ではない。"}


def add_more_readiness(position, exposure, ctx=None):
    """買い増し余地 — risk-based, never an order. Deterministic ladder from the
    strongest blocker down."""
    ctx = ctx or {}
    sym = position["symbol"]
    held = position.get("held")
    if held and position.get("quantity") is None:
        return _ready("unknown", "保有数量が未入力のため買い増し余地は判定できません。")
    weights = {t["symbol"]: t["weight"] for t in exposure.get("topPositions") or []}
    w = weights.get(sym)
    by_theme = exposure.get("byTheme") or {}
    tw = by_theme.get(position.get("theme"))
    fc = ctx.get("flowClass")
    runup = ctx.get("priorRunupPct")
    if held and exposure.get("totalMarketValue") is None:
        return _ready("unknown", "ポートフォリオ総額が不明のため判定保留(数量・単価の入力が必要)。")
    if fc in ("retail_chase",) or (runup is not None and runup >= 15):
        return _ready("avoid_chase",
                      "急騰直後で追いかけ買いの高値掴みリスクが高い局面です。"
                      "この上昇を追うより、保有比率とテーマ集中を先に確認すべきです。")
    if sym in {str(s).upper() for s in (ctx.get("eventSymbols") or [])}:
        return _ready("wait", "重要イベント直前のため、結果を見てから判断するのが安全です。")
    if w is not None and w >= DEFAULT_THRESHOLDS["single_name_high"]:
        return _ready("wait",
                      f"既にこの1銘柄で約{round(w*100)}%と大きいため、買い増しより分散が先です。")
    if tw is not None and tw >= DEFAULT_THRESHOLDS["theme_high"]:
        return _ready("add_only_on_pullback",
                      f"{THEME_JA.get(position.get('theme'), '')}テーマの比率が高いため、"
                      f"買い増すなら小さく、押し目確認後に限定した方が安全です。")
    if ctx.get("regimeRiskOff") and position.get("theme") in (
            "ai_infrastructure", "physical_ai_robotics", "semiconductor_photonics", "crypto"):
        return _ready("add_only_on_pullback",
                      "リスクオフ寄りの地合いでは高グロース/高ベータの買い増しは押し目限定が安全です。")
    if fc in ("panic_selling", "distribution"):
        return _ready("wait", "売り圧力の推定が出ているため、落ち着くまで見送りが安全です。")
    if not held:
        return _ready("monitor", "監視銘柄です(保有なし)。エントリー判断はシグナルとイベントを確認。")
    return _ready("add_allowed_small",
                  "明確なブロック要因はありません。ただし一度に大きく買わず、小さく分けるのが基本です。")


def _ready(action, why):
    return {"readiness": action, "readinessJa": ACTION_JA[action], "whyJa": why,
            "complianceNote": "リスクベースの目安であり売買指示ではない。"}


def regime_sensitivity(exposure, regime_label: str = "") -> Dict[str, Any]:
    """今日のレジーム × 現在のポートフォリオ — headwind/tailwind の言語化。"""
    ai = exposure.get("AIThemeExposure")
    gold = exposure.get("goldExposure") or 0
    crypto = exposure.get("cryptoExposure") or 0
    usd = exposure.get("USDExposure")
    lines, headwinds, tailwinds = [], [], []
    if ai is None:
        lines.append("保有データ未入力のため、レジーム感応度はウォッチリスト構成からの参考値です。")
    else:
        if ai >= 0.4:
            headwinds.append("金利上昇・AI設備投資懸念(グロース/AI比率が高い)")
            lines.append(f"AI関連テーマが約{round(ai*100)}%と高く、金利上昇やAI投資減速の局面では"
                         "逆風を受けやすい構成です。")
        if regime_label in ("RISK_OFF", "EVENT_WAIT") and (ai or 0) + crypto >= 0.4:
            headwinds.append("リスクオフ地合い(高ベータ比率が高い)")
            lines.append("今日の地合いはリスク回避寄りのため、高ベータ中心の構成には向かい風です。")
        if gold >= 0.05:
            tailwinds.append("金の保有が下落時のクッションになる")
            lines.append(f"金を約{round(gold*100)}%持っており、急落時の下支えになります。")
        if usd is not None and usd >= 0.5:
            headwinds.append("円高局面では米ドル資産の円換算が目減り")
    return {"regimeLabel": regime_label or None, "headwinds": headwinds,
            "tailwinds": tailwinds,
            "summaryJa": " ".join(lines) or "現在の構成に対する明確なレジーム逆風は検出されていません。"}


# ── watchlist-level (NO quantities) — safe for public endpoints ────────────

def watchlist_theme_exposure(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Counts only (symbol/theme), no values — structurally leak-free."""
    counts: Dict[str, int] = {}
    for it in items:
        t = classify_theme(str(it.get("symbol") or ""), str(it.get("market") or ""),
                           str(it.get("assetType") or ""), str(it.get("name") or ""))
        counts[t] = counts.get(t, 0) + 1
    total = sum(counts.values())
    heavy = [t for t, c in counts.items()
             if total >= 4 and c / total >= 0.4 and t != "other"]
    return {"schemaVersion": "watchlist-theme-exposure-v1",
            "totalSymbols": total,
            "byTheme": dict(sorted(counts.items(), key=lambda kv: -kv[1])),
            "byThemeJa": {THEME_JA[t]: c for t, c in
                          sorted(counts.items(), key=lambda kv: -kv[1])},
            "heavyThemes": heavy,
            "noteJa": ("ウォッチリストの銘柄数ベースの偏りです(保有数量ではありません)。"
                       "実際の保有比率は端末内でのみ計算されます。")}


def handoff_section(watchlist_exposure: Dict[str, Any]) -> Dict[str, Any]:
    """Backend Pro Handoff block — watchlist-level ONLY. Actual holdings are
    device-local; the app appends the real summary client-side."""
    heavy = watchlist_exposure.get("heavyThemes") or []
    return {
        "title": "Position / Exposure Summary (watchlist-level)",
        "byThemeJa": watchlist_exposure.get("byThemeJa") or {},
        "heavyThemes": [THEME_JA.get(t, t) for t in heavy],
        "privacyNoteJa": "実際の保有数量・取得単価・評価額は端末内のみで管理され、"
                         "サーバーは保有を一切知りません。実保有サマリはアプリが"
                         "コピー時にローカルで付加します。",
        "opposingViewJa": "最強の反対解釈: ウォッチリストの偏り=保有の偏りではない。"
                          "実保有が未入力の間、集中リスクの断定はできない。",
        "disclaimerJa": "リスク点検であり売買指示ではない。",
    }
