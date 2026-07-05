"""ARGUS V11.19.1 — Mutual Fund / FIRE Core Tracker (pure, deterministic).

オーナー方針: 「投資信託の合計額をFIRE用の本丸資産として扱います。個別株の
利益は、将来的にこのFIRE Coreへ移す候補として見ます。」

この層は投資信託(+iDeCo/NISA長期/インデックスETF)をFIRE Coreとして明示追跡し、
戦術枠とのバランス・積立状況・評価額の鮮度を判定する。

HARD RULES:
  - 基準価額・口数・取得コスト・積立額を絶対に捏造しない(欠落は欠落と言う)。
  - リアルタイム価格は不要(日次/手動更新で十分。古ければstaleと明示)。
  - 現在評価額のみ入力なら、それを使いコスト/損益はunknown。
  - コスト欠落時は損益を計算しない。
  - 証券会社ログイン・口座連携・認証情報の要求は一切しない。
  - FIRE達成確率・到達年の計算はしない(帯・比率のみ)。
  - 投信の詳細(銘柄名・口数・評価額・積立額・口座区分)は端末/暗号化vaultのみ。
    公開はredactedフラグのみ。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

SCHEMA_VERSION = "fire-core-v1"

ASSET_CLASSES = ("mutual_fund", "index_fund", "ideco", "nisa_long_term", "etf",
                 "jp_stock", "us_stock", "crypto", "gold", "cash", "other")
ACCOUNT_TYPES = ("nisa", "ideco", "taxable", "corporate", "unknown")
CONTRIB_FREQS = ("monthly", "weekly", "irregular", "none", "unknown")
DATA_SOURCES = ("manual", "imported", "estimated", "existing_argus", "unknown")
CONTRIB_STATUSES = ("complete", "partial", "missing", "stale", "unknown")
VALUATION_STATUSES = ("current", "stale", "manual", "missing", "unknown")
RATIO_BANDS = ("ok", "elevated", "stretched", "exceeded", "unknown")

STALE_DAYS = 7          # 評価額がこれより古ければstale(投信は日次NAVで十分)
OWNER_RULE_JA = ("投資信託の合計額をFIRE用の本丸資産として扱います。"
                 "個別株の利益は、将来的にこのFIRE Coreへ移す候補として見ます。")
COMPLIANCE = ("FIRE Coreの追跡は概算であり、免許を持つFP・税務・法務の助言ではない。"
              "売買指示・自動売買・口座連携もない。")


def _f(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def normalize_position(raw: Dict[str, Any], now_iso: str) -> Dict[str, Any]:
    """MutualFundPosition正規化 — 捏造せず、計算できるものだけ計算する。
    units×NAVがあれば評価額を計算。現在評価額のみならそれを採用。
    コストが無ければ損益はNone(unknown)のまま。"""
    units = _f(raw.get("units"))
    nav = _f(raw.get("navPrice"))
    manual_value = _f(raw.get("marketValue"))
    avg_cost = _f(raw.get("averageCost"))
    total_cost = _f(raw.get("totalCost"))
    if total_cost is None and avg_cost is not None and units is not None:
        total_cost = avg_cost * units

    if units is not None and nav is not None:
        market_value = units * nav
        value_source = "units_x_nav"
    elif manual_value is not None:
        market_value = manual_value
        value_source = "manual_value"
    else:
        market_value = None
        value_source = "missing"

    pnl = pnl_pct = None
    if market_value is not None and total_cost is not None and total_cost > 0:
        pnl = market_value - total_cost
        pnl_pct = round(pnl / total_cost * 100, 1)

    nav_date = raw.get("navDate") or raw.get("lastUpdatedAt")
    stale = None
    if nav_date:
        try:
            age_days = (int(now_iso[8:10]) - int(str(nav_date)[8:10])) \
                if str(nav_date)[:7] == now_iso[:7] else 99
            # month-boundary safe approximation via full date compare
            from datetime import date
            d1 = date.fromisoformat(str(nav_date)[:10])
            d2 = date.fromisoformat(now_iso[:10])
            age_days = (d2 - d1).days
            stale = age_days > STALE_DAYS
        except Exception:
            stale = None
    acct = raw.get("accountType") if raw.get("accountType") in ACCOUNT_TYPES else "unknown"
    freq = raw.get("contributionFrequency") \
        if raw.get("contributionFrequency") in CONTRIB_FREQS else "unknown"
    return {
        "schemaVersion": "mutual-fund-position-v1",
        "id": raw.get("id") or f"mf-{str(raw.get('symbol') or raw.get('fundName') or 'x')[:12]}",
        "fundName": raw.get("fundName") or raw.get("symbol") or "不明ファンド",
        "fundCode": raw.get("fundCode"), "symbol": raw.get("symbol"),
        "accountType": acct,
        "units": units, "averageCost": avg_cost, "totalCost": total_cost,
        "navPrice": nav, "navDate": nav_date,
        "marketValue": market_value, "valueSource": value_source,
        "unrealizedPnl": pnl, "unrealizedPnlPct": pnl_pct,
        "monthlyContribution": _f(raw.get("monthlyContribution")),
        "contributionDay": raw.get("contributionDay"),
        "contributionFrequency": freq,
        "currency": raw.get("currency") or "JPY",
        "dataSource": raw.get("dataSource") if raw.get("dataSource") in DATA_SOURCES else "unknown",
        "staleDataFlag": stale,
        "lastUpdatedAt": raw.get("lastUpdatedAt") or nav_date,
        "ownerNote": raw.get("ownerNote"),
        "privacyLevel": "private_local",
    }


def build_summary(inputs: Dict[str, Any], now_iso: str) -> Dict[str, Any]:
    """inputs: positions[](normalized), tacticalTotal/satelliteTotal/hedgeTotal
    (JPY, device-side; None=unknown), fireCoreEtfTotal(long-term core ETFs)."""
    positions = [normalize_position(p, now_iso) if p.get("schemaVersion") != "mutual-fund-position-v1"
                 else p for p in (inputs.get("positions") or [])]
    valued = [p for p in positions if p["marketValue"] is not None]
    mf_total = sum(p["marketValue"] for p in valued) if valued else None

    by_acct = lambda a: sum(p["marketValue"] for p in valued if p["accountType"] == a) \
        if valued else None
    etf_core = _f(inputs.get("fireCoreEtfTotal")) or 0.0
    fire_core_total = (mf_total or 0.0) + etf_core if mf_total is not None or etf_core else None

    contribs = [p["monthlyContribution"] for p in positions]
    known_contribs = [c for c in contribs if c is not None]
    monthly = sum(known_contribs) if known_contribs else None
    contrib_status = ("complete" if known_contribs and len(known_contribs) == len(positions) else
                      "partial" if known_contribs else
                      "missing" if positions else "unknown")

    stales = [p for p in positions if p["staleDataFlag"] is True]
    missing_val = [p for p in positions if p["marketValue"] is None]
    valuation_status = ("missing" if positions and not valued else
                        "stale" if stales else
                        "manual" if any(p["valueSource"] == "manual_value" for p in valued) else
                        "current" if valued else "unknown")

    tactical = _f(inputs.get("tacticalTotal"))
    satellite = _f(inputs.get("satelliteTotal"))
    hedge = _f(inputs.get("hedgeTotal"))
    total_known = sum(x for x in (fire_core_total, tactical, satellite, hedge)
                      if x is not None) or None
    core_share = (round(fire_core_total / total_known * 100, 1)
                  if fire_core_total is not None and total_known else None)

    def ratio(x):
        if x is None or fire_core_total is None:
            return None, "unknown"
        if fire_core_total <= 0:
            return None, "exceeded" if x > 0 else "unknown"
        r = round(x / fire_core_total, 2)
        band = ("ok" if r <= 0.3 else "elevated" if r <= 0.6 else
                "stretched" if r <= 1.0 else "exceeded")
        return r, band
    tac_ratio, tac_band = ratio(tactical)
    sat_ratio, sat_band = ratio(satellite)

    warnings = [w for w in (
        "戦術枠がFIRE Coreに対して大きくなっています。個別株の勝負がFIRE計画全体を振らす構成です。"
        if tac_band in ("stretched", "exceeded") else None,
        f"FIRE Coreの評価額が未更新です({len(stales)}件が{STALE_DAYS}日超)。投資信託の現在価値を更新すると、戦術枠の取りすぎを正確に判定できます。"
        if stales else None,
        "投資信託の評価額が未入力のため、FIRE Coreを判定できません。"
        if valuation_status == "missing" else None,
        "毎月積立額が未入力のため、長期入金整合は判定保留です。"
        if contrib_status in ("missing", "unknown") and positions else None,
    ) if w]
    opportunities = [o for o in (
        "個別株の利益が出た場合、一定部分をFIRE Coreへ移す検討余地があります。"
        if tac_band in ("elevated", "stretched", "exceeded") and fire_core_total is not None else None,
        "積立額が登録済みです。継続していれば長期側の土台は機能します(将来見込みの精密計算はしません)。"
        if contrib_status == "complete" else None,
    ) if o]

    if fire_core_total is None:
        summary = ("FIRE Core(投資信託)の評価額が未入力です。"
                   "Watchlistで投信の口数を入力するか、Core Portfolioで現在評価額を手動入力してください。")
    else:
        summary = (f"FIRE Core合計は既知資産の{core_share:.0f}%です。" if core_share is not None else "")
        summary += (f"戦術枠/FIRE Core比は{tac_ratio:.2f}({'許容内' if tac_band == 'ok' else 'やや大きめ' if tac_band == 'elevated' else '大きい' if tac_band == 'stretched' else '超過'})。"
                    if tac_ratio is not None else "")
        summary += "投資信託はFIREの本丸資産として追跡中です。"

    return {
        "schemaVersion": SCHEMA_VERSION, "asOf": now_iso,
        "positionsCount": len(positions),
        "mutualFundTotal": mf_total,
        "indexCoreTotal": mf_total,          # 現状は投信=インデックス系(区分入力は将来)
        "idecoTotal": by_acct("ideco"),
        "nisaLongTermTotal": by_acct("nisa"),
        "etfCoreTotal": etf_core or None,
        "fireCoreTotal": fire_core_total,
        "monthlyContributionTotal": monthly,
        "annualContributionEstimate": (monthly * 12 if monthly is not None else None),
        "fireCoreShare": core_share,
        "tacticalTotal": tactical, "satelliteTotal": satellite, "hedgeTotal": hedge,
        "tacticalToCoreRatio": tac_ratio, "tacticalToCoreBand": tac_band,
        "satelliteToCoreRatio": sat_ratio, "satelliteToCoreBand": sat_band,
        "contributionDataStatus": contrib_status,
        "valuationDataStatus": valuation_status,
        "staleCount": len(stales), "missingValueCount": len(missing_val),
        "ownerReadableSummaryJa": summary[:280],
        "ownerRuleJa": OWNER_RULE_JA,
        "warningJa": warnings[:4],
        "opportunityJa": opportunities[:2],
        "nextChecksJa": [c for c in (
            "投信の評価額(基準価額)の更新" if valuation_status in ("stale", "missing") else None,
            "毎月積立額の入力" if contrib_status in ("missing", "partial") else None,
            "戦術枠/FIRE Core比の週次確認" if tac_band not in ("ok", "unknown") else None,
            "積立(コア)の継続 — 個別株の判断とは独立に確認",
        ) if c][:3],
        "missingDataJa": [m for m in (
            f"評価額未入力{len(missing_val)}件" if missing_val else None,
            "毎月積立額(未入力)" if contrib_status in ("missing", "partial") else None,
            "口座区分(未入力あり)" if any(p["accountType"] == "unknown" for p in positions) else None,
        ) if m][:3],
        "privacyLevel": "private_local",
        "complianceNote": COMPLIANCE,
    }


def public_status(*, now_iso: str) -> Dict[str, Any]:
    """PUBLIC — flags only. Fund names/units/NAV/values/contributions/accounts
    live on device; the server holds and returns none of them."""
    return {
        "schemaVersion": "fire-core-status-v1", "asOf": now_iso,
        "featureEnabled": True,
        "trackingComputed": "on_device_only",
        "serverKnowsFundData": False,
        "manualInputSupported": True,
        "realtimePricingRequired": False,
        "storageMode": "public_redacted",
        "publicLeakSafe": True,
        "noteJa": "投資信託・FIRE Coreの追跡は端末内で完結する。サーバーはファンド名・"
                  "口数・評価額・積立額・口座区分を一切知らない。証券会社連携もしない。",
        "complianceNote": COMPLIANCE,
    }
