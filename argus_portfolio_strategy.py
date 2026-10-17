"""ARGUS V11.19.0 — Portfolio Strategy / FIRE Alignment (pure, deterministic).

短期の計画(明日入るか)と長期の目的(FIRE)を接続する戦略層。
「この銘柄は上がるか」ではなく「このリスクの取り方はFIRE計画に整合しているか」
「短期勝負枠が長期の積立を圧迫していないか」に答える。

HARD RULES:
  - 免許を持つFP/税務/法務の助言ではない(概算の整合チェック)。売買指示でもない。
  - リタイア確率・到達年数などの精密計算は絶対にしない(帯のみ)。
  - 個人の収入・住宅ローン・キャッシュフローは入力が無ければ「不足データ」と
    正直に言う(捏造しない)。
  - 保有詳細を使う戦略は端末/暗号化vaultのみ。公開はredactedステータスのみ。
  - 「売れ」ではなく rebalance_review / trim_review / risk_reduction_review。
"""
from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Optional

SCHEMA_VERSION = "portfolio-strategy-v1"

STRATEGY_MODES = ("fire_growth", "balanced_growth", "capital_preservation",
                  "tactical_aggressive", "income_oriented", "unknown")
OWNER_GOALS = ("fire", "wealth_building", "capital_preservation",
               "short_term_trading", "unknown")
FIRE_STATUSES = ("aligned", "mostly_aligned", "stretched", "misaligned", "unknown")
SCORE_BANDS = ("strong", "moderate", "weak", "insufficient_data")
RISK_LEVELS = ("low", "medium", "high", "critical", "unknown")
TACTICAL_BUDGETS = ("underused", "appropriate", "stretched", "exceeded", "unknown")
ROLES = ("core", "satellite", "tactical", "hedge", "cash_like", "watch_only", "unknown")
HORIZONS = ("short_term", "medium_term", "long_term", "unknown")
CONVICTIONS = ("high", "medium", "low", "unknown")
STRATEGY_FITS = ("strong", "acceptable", "stretched", "weak", "unknown")
ADD_POLICIES = ("systematic_accumulation", "pullback_only", "small_tactical_only",
                "no_add_until_risk_reduces", "monitor_only", "unknown")
TRIM_POLICIES = ("not_needed", "if_overweight", "if_scenario_breaks",
                 "if_event_risk_rises", "if_profit_protection_needed", "unknown")

ROLE_JA = {"core": "コア(長期)", "satellite": "サテライト", "tactical": "戦術枠(短期)",
           "hedge": "ヘッジ", "cash_like": "現金相当", "watch_only": "監視のみ",
           "unknown": "未分類"}
FIRE_JA = {"aligned": "整合", "mostly_aligned": "概ね整合", "stretched": "やや無理あり",
           "misaligned": "不整合", "unknown": "判定保留"}

HIGH_BETA_THEMES = ("ai_infrastructure", "physical_ai_robotics", "semiconductor_photonics")
AI_THEMES = HIGH_BETA_THEMES

COMPLIANCE = ("概算の戦略整合チェックであり、免許を持つFP・税務・法務の助言ではない。"
              "売買指示でも自動売買でもない。")
NO_PRECISION_NOTE = "精密なゴール達成見込みの計算はしない(帯のみ・捏造しない)。"


def _f(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def classify_role(symbol: str, market: str, inputs: Dict[str, Any]) -> Dict[str, Any]:
    """inputs: assetName, theme(existing THEMES key), assetType(stock/fund/crypto),
    isHeld(bool|None), weightPct(float|None), eventPending(bool)."""
    theme = str(inputs.get("theme") or "other")
    atype = str(inputs.get("assetType") or "stock")
    held = bool(inputs.get("isHeld"))
    w = _f(inputs.get("weightPct")) or 0.0

    if theme == "index_core" or atype == "fund":
        role, horizon = "core", "long_term"
        reason = "インデックス/投信はFIREの土台(コア)。日々の判断より継続が主役です。"
    elif theme == "gold":
        role, horizon = "hedge", "long_term"
        reason = "金はリターン源というよりヘッジ(全体の値動きを和らげる役割)として扱うのが自然です。"
    elif not held:
        role, horizon = "watch_only", "unknown"
        reason = "監視のみ(保有なし)。役割はエントリー時に確定します。"
    elif theme == "crypto":
        role = "tactical" if w >= 10 else "satellite"
        horizon = "short_term" if role == "tactical" else "medium_term"
        reason = ("暗号資産の比率が大きく、値動きの荒さから戦術枠扱いです。" if role == "tactical"
                  else "暗号資産はボラティリティが高く、コアではなくサテライト扱いです。")
    elif theme in HIGH_BETA_THEMES and w >= 15:
        role, horizon = "tactical", "short_term"
        reason = "高ベータのAI関連で比率も大きいため、戦術枠(短期勝負)として扱います。"
    else:
        role, horizon = "satellite", "medium_term"
        reason = "個別株はコアではなくサテライト。買い増しは全体比率を確認してからです。"

    single_critical = str(inputs.get("concentrationRisk") or "") in ("high", "critical")
    fit = ("strong" if role in ("core", "hedge") else
           "weak" if single_critical else
           "stretched" if role == "tactical" and w >= 15 else
           "acceptable" if role in ("satellite", "tactical") else "unknown")
    add = ("systematic_accumulation" if role == "core" else
           "monitor_only" if role in ("hedge", "watch_only") else
           "no_add_until_risk_reduces" if fit in ("stretched", "weak") else
           "small_tactical_only" if role == "tactical" else "pullback_only")
    trim = ("not_needed" if role in ("core", "hedge", "watch_only") and not single_critical else
            "if_overweight" if fit in ("stretched", "weak") else
            "if_event_risk_rises" if inputs.get("eventPending") else
            "if_scenario_breaks")
    return {
        "symbol": str(symbol).upper(), "market": str(market).upper(),
        "assetName": inputs.get("assetName") or symbol,
        "role": role, "roleJa": ROLE_JA[role],
        "timeHorizon": horizon,
        "conviction": "unknown",       # owner input non-existent — never guessed
        "roleReasonJa": reason,
        "strategyFit": fit,
        "addPolicy": add,
        "trimReviewPolicy": trim,
        "weightPct": w if held else None,
    }


def build_strategy(inputs: Dict[str, Any], now_iso: str) -> Dict[str, Any]:
    """inputs (device-side facts; None=unknown, never guessed):
      roles[] (from classify_role, held rows carry weightPct),
      byThemePct {theme: pct}, jpyPct, usdPct, top1Symbol, top1Pct,
      singleNameRisk(str|None), knownCoverage(0-1|None), unpricedCount,
      noHoldings(bool), eventPending(bool), regimeRiskOff(bool),
      recurringAccumulationKnown(bool|None)
    """
    roles = list(inputs.get("roles") or [])
    themes = dict(inputs.get("byThemePct") or {})
    no_hold = bool(inputs.get("noHoldings"))
    coverage = _f(inputs.get("knownCoverage"))
    single = str(inputs.get("singleNameRisk") or "")
    top1 = inputs.get("top1Symbol")
    top1_pct = _f(inputs.get("top1Pct"))

    def alloc(pred):
        return round(sum((_f(r.get("weightPct")) or 0.0) for r in roles if pred(r)), 1)

    core = alloc(lambda r: r["role"] == "core")
    sat = alloc(lambda r: r["role"] == "satellite")
    tac = alloc(lambda r: r["role"] == "tactical")
    hedge = alloc(lambda r: r["role"] == "hedge")
    gold = round(_f(themes.get("gold")) or 0.0, 1)
    crypto = round(_f(themes.get("crypto")) or 0.0, 1)
    index_a = round(_f(themes.get("index_core")) or 0.0, 1)
    ai_sum = round(sum(_f(themes.get(t)) or 0.0 for t in AI_THEMES), 1)

    # ── risk budget ──────────────────────────────────────────────────────────
    if no_hold:
        tac_budget = "unknown"
    elif tac > 40:
        tac_budget = "exceeded"
    elif tac > 25:
        tac_budget = "stretched"
    elif tac >= 10:
        tac_budget = "appropriate"
    else:
        tac_budget = "underused"
    theme_risk = ("critical" if ai_sum >= 60 else "high" if ai_sum >= 45 else
                  "medium" if ai_sum >= 30 else "low") if not no_hold else "unknown"
    single_risk = (single if single in RISK_LEVELS else
                   "critical" if (top1_pct or 0) >= 40 else
                   "high" if (top1_pct or 0) >= 25 else
                   "medium" if (top1_pct or 0) >= 15 else
                   "low") if not no_hold else "unknown"
    total_risk = ("critical" if "critical" in (theme_risk, single_risk) or tac_budget == "exceeded" else
                  "high" if "high" in (theme_risk, single_risk) or tac_budget == "stretched" else
                  "medium" if not no_hold else "unknown")
    dd_sens = ("high" if ai_sum >= 50 or crypto >= 20 else
               "medium" if ai_sum >= 30 else "low") if not no_hold else "unknown"
    risk_budget = {
        "totalRiskLevel": total_risk,
        "tacticalRiskBudget": tac_budget,
        "singleNameRisk": single_risk, "themeRisk": theme_risk,
        "currencyRisk": ("medium" if max(_f(inputs.get("jpyPct")) or 0,
                                         _f(inputs.get("usdPct")) or 0) >= 80 else "low")
        if not no_hold else "unknown",
        "liquidityRisk": "unknown",     # 板/出来高の個人別評価はしない(捏造回避)
        "eventRisk": "high" if inputs.get("eventPending") else "low",
        "leverageRisk": "unknown",      # 信用取引の入力なし — 不明のまま
        "drawdownSensitivity": dd_sens,
        "ownerReadableRiskJa": (
            "短期勝負枠が大きくなっているため、追加よりも既存ポジションの整理・押し目限定が優先です。"
            if tac_budget in ("stretched", "exceeded") else
            f"AI関連への集中(約{ai_sum:.0f}%)が下落感応度を高めています。同時に下がる前提での比率確認を。"
            if dd_sens == "high" else
            "リスク配分は現時点で極端な偏りは確認されていません(不明項目は下記)。"
            if not no_hold else
            "保有数量が未入力のため、リスク予算は判定できません(捏造しません)。"),
        "riskControlsJa": [c for c in (
            "戦術枠の新規追加を止め、既存の集中度を先に確認" if tac_budget in ("stretched", "exceeded") else None,
            "テーマ集中を上げる追加は押し目限定+小口のみ" if theme_risk in ("high", "critical") else None,
            f"1銘柄({top1}目安)の比率上限を決めて超過分は増やさない" if single_risk in ("high", "critical") and top1 else None,
            "イベント通過までポートフォリオ全体で新規判断を抑制" if inputs.get("eventPending") else None,
        ) if c][:3],
        "riskFlags": [f for f in (
            "tactical_budget_" + tac_budget if tac_budget in ("stretched", "exceeded") else None,
            "theme_concentration_" + theme_risk if theme_risk in ("high", "critical") else None,
            "single_name_" + single_risk if single_risk in ("high", "critical") else None,
            "drawdown_sensitivity_high" if dd_sens == "high" else None,
        ) if f][:4],
    }

    # ── FIRE alignment (bands only — no probability, no retirement math) ────
    core_like = core + hedge      # 長期側 = コア+ヘッジ
    if no_hold or (coverage is not None and coverage < 0.5):
        fire_status, band = "unknown", "insufficient_data"
    elif tac_budget == "exceeded" or single_risk == "critical" \
            or (core_like < 10 and tac > 30):
        fire_status, band = "misaligned", "weak"
    elif tac_budget == "stretched" or theme_risk in ("high", "critical") or core_like < 25:
        fire_status, band = "stretched", "weak" if theme_risk == "critical" else "moderate"
    elif core_like >= 40 and tac <= 25 and single_risk not in ("high", "critical"):
        fire_status, band = "aligned", "strong"
    else:
        fire_status, band = "mostly_aligned", "moderate"

    # v11.19.1: FIRE Core文脈(投信=本丸資産・端末側argus_fire_coreが供給)
    fcx = dict(inputs.get("fireCore") or {})
    fc_known = fcx.get("known")
    fc_band = str(fcx.get("tacticalToCoreBand") or "unknown")
    fc_contrib = fcx.get("contributionKnown")

    missing = [m for m in (
        "投資信託(FIRE Core)の評価額が未入力 — Core Portfolioで入力可" if fc_known is False else None,
        "現金比率(証券口座外の現金は未入力)",
        "毎月の積立額・入金力(未入力)" if not inputs.get("recurringAccumulationKnown")
        and fc_contrib is not True else None,
        "住宅ローン・生活キャッシュフロー(未入力)",
        "NISA/iDeCo口座区分(未入力)",
        f"価格未取得{inputs.get('unpricedCount')}銘柄" if (inputs.get("unpricedCount") or 0) > 0 else None,
    ) if m]

    fire = {
        "status": fire_status, "statusJa": FIRE_JA[fire_status],
        "scoreBand": band,
        "coreProgressJa": (
            f"コア(インデックス/投信)+ヘッジは既知資産の約{core_like:.0f}%です。"
            if not no_hold else "保有数量が未入力のため、コア比率は判定できません。"),
        "riskFitJa": risk_budget["ownerReadableRiskJa"],
        "cashFlowFitJa": "住宅ローン・入金力が未入力のため、キャッシュフロー整合は判定保留です(捏造しません)。",
        "concentrationFitJa": (
            f"1銘柄集中は{single_risk}、AIテーマ合計は約{ai_sum:.0f}%です。"
            if not no_hold else "判定保留。"),
        "longTermContributionFitJa": (
            "積立の継続状況が未入力のため、長期の入金整合は確認できません。"
            if not inputs.get("recurringAccumulationKnown")
            else "積立方針は登録済み — 継続していれば長期側の土台は機能します。"),
        "warningJa": [w for w in (
            "短期勝負枠が大きく、FIREの土台(コア積立)を圧迫する構成です。" if tac_budget in ("stretched", "exceeded") else None,
            "長期のFIRE目的に対して、コア資産の比率が不足している可能性があります。個別株の追加判断とは別に、インデックス積立の継続確認が必要です。" if not no_hold and core_like < 25 else None,
            "AI/フィジカルAI関連への集中が高まっています。テーマが当たれば伸びますが、金利上昇やAI投資鈍化のニュースに弱くなります。" if theme_risk in ("high", "critical") else None,
        ) if w][:3],
        "whatWouldImproveJa": [w for w in (
            "コア(インデックス)比率の引き上げ、または戦術枠の縮小" if fire_status in ("stretched", "misaligned") else None,
            "テーマ集中を上げない形での分散(現金/金/インデックス)" if theme_risk in ("high", "critical") else None,
            "毎月の積立額を入力すると長期整合の判定精度が上がります" if not inputs.get("recurringAccumulationKnown") else None,
        ) if w][:3],
        "missingEvidence": missing[:4],
    }

    # ── strategy mode & summary ──────────────────────────────────────────────
    if no_hold:
        mode = "unknown"
    elif tac_budget in ("stretched", "exceeded"):
        mode = "tactical_aggressive"
    elif core_like >= 40:
        mode = "fire_growth"
    else:
        mode = "balanced_growth"

    summary = (
        "保有数量が未入力のため、戦略判定は保留です(Watchlistで入力すると端末内で判定します)。"
        if no_hold else
        f"現在の構成は{'戦術寄り' if mode == 'tactical_aggressive' else 'FIRE成長型' if mode == 'fire_growth' else 'バランス型'}"
        f"(コア+ヘッジ約{core_like:.0f}% / サテライト約{sat:.0f}% / 戦術枠約{tac:.0f}%)。"
        f"FIRE整合は「{FIRE_JA[fire_status]}」、短期勝負枠は{'超過' if tac_budget == 'exceeded' else '大きめ' if tac_budget == 'stretched' else '許容内' if tac_budget == 'appropriate' else '余裕あり' if tac_budget == 'underused' else '判定保留'}です。")

    warnings = fire["warningJa"] + [w for w in (
        f"1銘柄({top1})への集中が{single_risk}水準です。" if single_risk in ("high", "critical") and top1 else None,
        f"暗号資産が約{crypto:.0f}%と大きめです(戦術枠として管理)。" if crypto >= 15 else None,
        "戦術枠がFIRE Coreに対して大きくなっています。個別株の勝負がFIRE計画全体を振らす構成です。"
        if fc_band in ("stretched", "exceeded") else None,
        "毎月積立額が未入力のため、長期入金整合は判定保留です。"
        if fc_known is True and fc_contrib is False else None,
    ) if w]
    opportunities = [o for o in (
        "個別株の利益が出た場合、一定部分をFIRE Coreへ移す検討余地があります。"
        if fc_band in ("elevated", "stretched", "exceeded") else None,
        "金の比率はポートフォリオの値動きを和らげる役割があります。ただしリターン源というよりヘッジとして扱う方が自然です。" if gold > 0 else None,
        "戦術枠に余裕があります。ただし使い切る必要はありません(見送りも選択肢)。" if tac_budget == "underused" else None,
        "コア比率が確保できており、短期の分岐に振り回されにくい構成です。" if fire_status == "aligned" else None,
    ) if o]

    return {
        "schemaVersion": SCHEMA_VERSION,
        "id": "ps-" + hashlib.md5(f"strategy:{now_iso[:13]}".encode()).hexdigest()[:10],
        "asOf": now_iso, "portfolioId": "default",
        "strategyMode": mode,
        "ownerGoal": "fire",           # アプリの明示目的(北極星) — 個人データではない
        "totalKnownPortfolioValue": None,   # 公開系に金額を出さない(端末側UIのみ既存表示)
        "knownDataCoverage": coverage,
        "unknownExposureShare": (round(1 - coverage, 2) if coverage is not None else None),
        "coreAllocation": core, "satelliteAllocation": sat,
        "tacticalAllocation": tac, "cashAllocation": None,   # 未入力 — 捏造しない
        "goldAllocation": gold, "cryptoAllocation": crypto,
        "indexAllocation": index_a,
        "jpEquityAllocation": _f(inputs.get("jpyPct")),
        "usEquityAllocation": _f(inputs.get("usdPct")),
        "themeExposure": {k: round(_f(v) or 0.0, 1) for k, v in themes.items()},
        "currencyExposure": {"JPY": _f(inputs.get("jpyPct")), "USD": _f(inputs.get("usdPct"))},
        "concentrationSummary": {"top1Symbol": top1, "top1Pct": top1_pct,
                                 "singleNameRisk": single_risk, "aiThemePct": ai_sum},
        "riskBudgetSummary": risk_budget,
        "fireAlignment": fire,
        "ownerReadableSummaryJa": summary[:280],
        "strategicWarningsJa": warnings[:4],
        "strategicOpportunitiesJa": opportunities[:3],
        "portfolioStressNotesJa": [s for s in (
            f"AI調整局面: AI関連約{ai_sum:.0f}%が同時に下がる想定(個別の分散は効きにくい)" if ai_sum >= 30 else None,
            "円高/ドル安局面: 米国株・ドル資産の円建て評価が同方向に動く" if (_f(inputs.get("usdPct")) or 0) >= 40 else None,
            "金利ショック: 高ベータ(AI/暗号資産)ほど下落感応度が高い" if dd_sens in ("medium", "high") else None,
            "イベント直後: 戦術枠の含み損益が最も振れやすい" if tac > 0 else None,
        ) if s][:4] if not no_hold else [],
        "nextChecksJa": [c for c in (
            "戦術枠の比率が下がったか(次回スナップショット比較)" if tac_budget in ("stretched", "exceeded") else None,
            "積立(コア)の継続 — 個別株の判断とは独立に確認",
            "テーマ集中と1銘柄集中の週次確認",
        ) if c][:3],
        "missingDataJa": missing[:5],
        "assetRoles": roles,
        "privacyLevel": "private_local",
        "sourceLimitNote": "既存レイヤー(保有リスク/計画/シナリオ/テーマ)の合成。現金・入金力・"
                           "ローン等の未入力項目は判定に使わず不足と明示。",
        "complianceNote": COMPLIANCE,
        "precisionNote": NO_PRECISION_NOTE,
    }


def handoff_section(strategy: Dict[str, Any]) -> Dict[str, Any]:
    fire = strategy.get("fireAlignment") or {}
    rb = strategy.get("riskBudgetSummary") or {}
    return {
        "title": "Portfolio Strategy / FIRE Alignment",
        "balanceJa": strategy.get("ownerReadableSummaryJa", ""),
        "concentrationJa": [w for w in strategy.get("strategicWarningsJa") or []],
        "fireCaveatsJa": (fire.get("warningJa") or []) + [fire.get("cashFlowFitJa", "")],
        "nextActionsJa": strategy.get("nextChecksJa") or [],
        "missingDataJa": strategy.get("missingDataJa") or [],
        "opposingJa": "最強の反対view: この整合判定は入力済みデータのみに基づく概算であり、"
                      "現金・入金力・ローン次第で結論が変わり得る。戦術枠の縮小が常に正しい"
                      "わけでもない(機会損失側の検証はLearning Dashboardで)。",
        "riskBudgetJa": rb.get("ownerReadableRiskJa", ""),
        "disclaimerJa": COMPLIANCE,
    }


def public_status(*, now_iso: str, sources: Dict[str, bool]) -> Dict[str, Any]:
    """PUBLIC — feature/architecture flags ONLY. Strategy details (allocations,
    roles, FIRE state) are computed and stored ON DEVICE; the server holds none."""
    return {
        "schemaVersion": "portfolio-strategy-status-v1", "asOf": now_iso,
        "featureEnabled": True, "lastRunAt": now_iso,
        "strategyComputed": "on_device_only",
        "serverKnowsHoldings": False,
        "serverKnowsStrategyDetails": False,
        "missingDataCount": None,          # device-side detail stays on device
        "storageMode": "public_redacted",
        "publicLeakSafe": True,
        "sourceAvailability": sources,
        "noteJa": "戦略・FIRE整合・リスク予算は端末内でのみ合成される。サーバーは保有・"
                  "口座区分・収入・ローン・比率を一切知らない。免許業の助言ではない。",
        "complianceNote": COMPLIANCE,
    }
