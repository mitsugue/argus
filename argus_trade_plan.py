"""ARGUS V11.18.0 — Entry / Exit Planning Assistant (pure, deterministic).

「今から入っていいか / 買い増ししていいか / 一部利確すべきか / 持ち越して
いいか」に、**計画**で答える層。Scenario/Action Priority/需給/Flow/イベント/
保有リスクを構造化された計画(エントリー条件・待ち条件・利確検討・保有点検)
に変換する。売買指示・注文・自動売買では絶対にない。

HARD RULES:
  - 「今すぐ買え/売れ」「注文を出せ」等の執行語は絶対に出さない
    (FORBIDDEN_WORDING をテストが全出力に対して検査する)。
  - small_add_allowed / small_trial は多層の好条件+注意書き付きのみ。
  - improving_but_heavy は押し目限定(青信号にしない)。
  - squeeze_prone は追いかけ買い注意(自動的な買いにしない)。
  - イベント前は判断ブロック(event_wait)。発表後の確認項目を明示。
  - 集中度が高い保有は買い増しブロック(リスク確認が先)。
  - 市場が閉まっている間はPTS/プレの薄商いで判断しない(警告を必ず出す)。
  - 正確な価格レベルを捏造しない(定性的な確認条件のみ)。
  - 「利確しろ」ではなく trim_consideration / risk_review(検討の局面)。
  - 証拠不足は unknown と正直に言う(計画を捏造しない)。
"""
from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Optional

SCHEMA_VERSION = "trade-plan-v1"

PLAN_TYPES = ("entry", "add", "trim_review", "exit_review", "hold", "wait",
              "avoid_chase", "event_wait", "no_action", "unknown")
HORIZONS = ("intraday", "next_session", "this_week", "medium_term",
            "long_term", "unknown")
STANCES = ("wait", "monitor", "add_only_on_pullback", "small_add_allowed",
           "avoid_chase", "hold_review", "trim_consideration", "risk_review",
           "no_action", "unknown")
ENTRY_MODES = ("not_allowed_now", "pullback_only", "small_trial_only",
               "wait_event", "wait_confirmation", "monitor_only", "unknown")
CHASE_RISKS = ("low", "medium", "high", "unknown")
SIZE_GUIDANCE = ("none", "tiny", "small", "normal_not_recommended", "unknown")
EXIT_MODES = ("no_exit_signal", "trim_review", "risk_reduction_review",
              "event_risk_review", "stop_review", "unknown")
HOLD_MODES = ("hold_ok", "hold_but_monitor", "hold_until_event",
              "hold_with_risk_review", "unknown")
EVIDENCE_QUALITY = ("strong", "medium", "weak", "insufficient")

STANCE_JA = {"wait": "待ち", "monitor": "監視継続",
             "add_only_on_pullback": "買うなら押し目限定",
             "small_add_allowed": "小さく買い増し可(注意付き)",
             "avoid_chase": "追いかけ買い注意", "hold_review": "保有点検",
             "trim_consideration": "一部利確を検討する局面",
             "risk_review": "リスク確認が先", "no_action": "対応不要",
             "unknown": "判定保留"}

COMPLIANCE = "これは計画であり売買指示ではない。注文機能はなく、判断はオーナーが行う。"
PTS_WARNING_JA = ("PTS/プレは流動性が薄く、判断は通常取引時間の出来高と終値位置を"
                  "確認してからです。夜間の値動きだけで追いかけないでください。")
LEVEL_CAVEAT_JA = "これは注文価格ではなく、確認ポイントです。"

# 執行語 — 全出力に対しテストが検査する(計画語彙のみ許可)
FORBIDDEN_WORDING = ("今すぐ買", "今すぐ売", "すぐに買って", "すぐに売って",
                     "buy now", "sell now", "place order", "place this order",
                     "注文を出して", "成行で買", "成行で売", "指値で買", "全力買い")


def _f(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def build_plan(symbol: str, market: str, inputs: Dict[str, Any],
               now_iso: str) -> Dict[str, Any]:
    """inputs (existing-layer facts; None=unknown, never guessed):
      isHeld(bool|None), assetName, sdRank, sdCondition, sdLevel,
      flowClass, scenarioDominant, apCategory, apRank,
      eventPending(bool), eventName, regimeRiskOff(bool),
      weightPct, concentrationRisk, positionRiskLevel, pnlPct,
      priorRunupPct, changePct, marketOpen(bool|None), missing[]
    """
    held = inputs.get("isHeld")
    name = inputs.get("assetName") or symbol
    sd_rank = str(inputs.get("sdRank") or "")
    sd_cond = str(inputs.get("sdCondition") or "")
    sd_level = str(inputs.get("sdLevel") or "")
    flow = str(inputs.get("flowClass") or "")
    scen = str(inputs.get("scenarioDominant") or "")
    ap_cat = str(inputs.get("apCategory") or "")
    event = bool(inputs.get("eventPending"))
    ev_name = inputs.get("eventName") or "重要イベント"
    weight = _f(inputs.get("weightPct"))
    conc = str(inputs.get("concentrationRisk") or "")
    pos_risk = str(inputs.get("positionRiskLevel") or "")
    pnl = _f(inputs.get("pnlPct"))
    runup = _f(inputs.get("priorRunupPct"))
    market_open = inputs.get("marketOpen")
    missing = list(inputs.get("missing") or [])

    heavy = sd_level in ("heavy", "very_heavy")
    squeeze = sd_cond == "squeeze_prone" or flow == "short_covering"
    improving_heavy = sd_cond == "improving_but_heavy"
    sd_bad = sd_rank in ("D", "E")
    flow_bad = flow in ("panic_selling", "distribution")
    overext = runup is not None and runup >= 15
    high_conc = conc in ("high", "critical") or (weight is not None and weight >= 25)
    big_gain = pnl is not None and pnl >= 20
    adverse = int(sd_bad) + int(flow_bad) + int(pos_risk in ("high", "critical")) \
        + int(scen == "bearish")
    favorable = int(sd_rank in ("S", "A", "B") and not squeeze and not heavy) \
        + int(flow == "institutional_accumulation") + int(scen == "bullish")

    has_sd = bool(sd_rank and sd_rank != "Unknown")
    has_flow = bool(flow and flow != "unknown")
    eq = ("strong" if has_sd and has_flow and scen and not missing else
          "medium" if has_sd or has_flow else
          "weak" if scen else "insufficient")

    risk_flags: List[str] = []
    blocking: List[str] = []
    what_not: List[str] = []
    if event:
        blocking.append("event_pending")
        what_not.append(f"{ev_name}の発表前に方向を決め打ちして仕込まない")
    if squeeze:
        risk_flags.append("squeeze_fade_risk")
        what_not.append("急騰局面を追いかけない(買い戻し主導なら一巡後に失速しやすい)")
    if improving_heavy or heavy:
        risk_flags.append("credit_overhang")
        what_not.append("「改善方向」を「需給良好」と読み替えて追加しない")
    if sd_bad:
        blocking.append("supply_demand_bad")
    if flow_bad:
        blocking.append("flow_deterioration")
    if overext:
        risk_flags.append("overextended")
        what_not.append("高値追いしない(急伸直後の新規・追加は不利になりやすい)")
    if high_conc and held:
        blocking.append("concentration_high")
        what_not.append("比率の高い銘柄をさらに厚くしない(全体の振れが大きくなる)")
    if market_open is False:
        risk_flags.append("market_closed_thin_liquidity")
        what_not.append(PTS_WARNING_JA)

    # ── EntryPlan(新規/追加の入り方) ────────────────────────────────────────
    if event:
        allowed, chase = "wait_event", ("high" if overext or squeeze else "medium")
    elif eq == "insufficient":
        allowed, chase = "unknown", "unknown"
    elif sd_bad or flow_bad or adverse >= 2:
        allowed, chase = "not_allowed_now", "medium"
    elif squeeze or overext or ap_cat == "avoid_chase":
        allowed, chase = "wait_confirmation", "high"
    elif improving_heavy or heavy or (high_conc and held):
        allowed, chase = "pullback_only", "medium"
    elif favorable >= 2 and adverse == 0 and eq in ("strong", "medium") \
            and not (held and high_conc):
        allowed, chase = "small_trial_only", "low"
    else:
        allowed, chase = "monitor_only", ("medium" if runup is None else "low")

    size = ("tiny" if allowed == "small_trial_only" and held else
            "small" if allowed == "small_trial_only" else
            "none" if allowed in ("not_allowed_now", "wait_event") else
            "unknown" if allowed == "unknown" else "normal_not_recommended")
    entry_plan = {
        "allowedMode": allowed, "chaseRisk": chase,
        "entryTriggerJa": [t for t in (
            "出来高を伴う押し目が入り、翌日に安値を割らないこと" if allowed in ("pullback_only", "wait_confirmation") else None,
            "上昇の主体が買い戻しから実需買いに入れ替わること" if squeeze else None,
            f"{ev_name}の結果と初動反応(金利・為替・指数)の確認" if event else None,
            "出来高を伴って前日高値を維持できるか" if allowed == "small_trial_only" else None,
        ) if t][:3],
        "confirmationNeededJa": [c for c in (
            "上昇日に出来高を伴って高値圏で引けるか(上値吸収)" if heavy or improving_heavy else None,
            "需給(週次信用残/日次貸借残)の次回更新" if has_sd else "需給データの取得",
            "実測フローで大口買いが続いているか" if favorable else None,
        ) if c][:3],
        "avoidIfJa": [a for a in (
            "出来高を伴わない急伸(その上昇は追わない)",
            "需給D/Eへの悪化・フロー悪化が出た場合" if not sd_bad else "需給D/Eが続く間",
            "寄り直後の飛び付き(寄り後30分の値動きと出来高を確認してから)" if market_open is not False else None,
        ) if a][:3],
        "sizeGuidance": size,
        "sizeCaveatJa": ("入るとしても小さく・分割で。一度に厚くしない。" if size in ("tiny", "small")
                         else PTS_WARNING_JA if market_open is False
                         else "現時点で新規・追加のサイズは推奨なし(条件待ち)。"),
    }

    # ── ExitPlan(利確検討/リスク縮小の点検 — 「売れ」ではない) ────────────────
    exit_mode = "no_exit_signal"
    if held:
        if event and (pos_risk in ("high", "critical") or adverse >= 1):
            exit_mode = "event_risk_review"
        elif adverse >= 2 or (sd_bad and flow_bad):
            exit_mode = "risk_reduction_review"
        elif big_gain and (overext or flow_bad or heavy):
            exit_mode = "trim_review"
        elif scen == "bearish" or pos_risk in ("high", "critical"):
            exit_mode = "risk_reduction_review"
    exit_plan = {
        "exitMode": exit_mode,
        "trimTriggerJa": [t for t in (
            "急騰後にFlow悪化(売り抜け推定)と需給の重さが重なった場合" if big_gain else None,
            "戻り局面で出来高を伴わず売られ続ける場合",
        ) if t][:2],
        "riskReductionTriggerJa": [t for t in (
            "需給D/E×フロー悪化が2営業日続く場合" if sd_bad or flow_bad else None,
            f"{ev_name}の結果が想定と逆で、初動が崩れた場合" if event else None,
            "比率の高さが地合い悪化と重なった場合" if high_conc else None,
        ) if t][:3],
        "holdInvalidationJa": ["保有理由(テーマ/需給改善)が崩れたと確認できた場合",
                               "弱気シナリオが支配的になり無効化条件を満たした場合"],
        "profitProtectionJa": ([f"含み益が大きい局面では、利益を守る観点でポジションサイズの確認を優先"
                                if big_gain else ""] if held else []),
        "caveatJa": "利確・縮小は検討の局面提示であり指示ではない。実行判断と数量はオーナーが決める。",
    }
    exit_plan["profitProtectionJa"] = [x for x in exit_plan["profitProtectionJa"] if x]

    # ── HoldPlan(保有の扱い) ────────────────────────────────────────────────
    if not held:
        hold_mode = "unknown"
    elif event:
        hold_mode = "hold_until_event"
    elif exit_mode in ("risk_reduction_review", "trim_review", "event_risk_review"):
        hold_mode = "hold_with_risk_review"
    elif adverse >= 1 or heavy or improving_heavy or squeeze:
        hold_mode = "hold_but_monitor"
    else:
        hold_mode = "hold_ok"
    hold_plan = {
        "holdMode": hold_mode,
        "holdReasonJa": [r for r in (
            "ベースシナリオが安定しており、致命的な悪材料は確認されていない" if hold_mode == "hold_ok" else None,
            "保有継続は可能だが、監視条件付き" if hold_mode == "hold_but_monitor" else None,
            f"{ev_name}の結果確認まで現状維持が基本" if hold_mode == "hold_until_event" else None,
            "保有継続の前にリスク確認(比率・悪化信号)が先" if hold_mode == "hold_with_risk_review" else None,
        ) if r][:2],
        "monitorConditionsJa": [m for m in (
            "戻り局面で売りが出るか" if adverse else None,
            "上昇日に出来高を伴うか(上値吸収)" if heavy or improving_heavy else None,
            "買い戻し一巡後に失速しないか" if squeeze else None,
            "需給・フローの次回更新",
        ) if m][:3],
        "reviewTimingJa": (f"{ev_name}の結果発表後すぐ" if event else
                           "需給の次回更新時(週次信用残/日次貸借残)と±3%超の動きの日"),
    }

    # ── planType / stance ────────────────────────────────────────────────────
    if eq == "insufficient":
        plan_type, stance = "unknown", "unknown"
    elif event:
        plan_type, stance = "event_wait", "wait"
    elif held and exit_mode == "trim_review":
        plan_type, stance = "trim_review", "trim_consideration"
    elif held and exit_mode in ("risk_reduction_review", "event_risk_review"):
        plan_type, stance = "exit_review", "risk_review"
    elif squeeze or overext or ap_cat == "avoid_chase":
        plan_type, stance = "avoid_chase", "avoid_chase"
    elif improving_heavy or (held and high_conc) or allowed == "pullback_only":
        plan_type, stance = ("add" if held else "entry"), "add_only_on_pullback"
    elif allowed == "small_trial_only":
        plan_type, stance = ("add" if held else "entry"), "small_add_allowed"
    elif held and hold_mode in ("hold_ok", "hold_but_monitor"):
        plan_type, stance = "hold", ("monitor" if hold_mode == "hold_but_monitor" else "no_action")
        if hold_mode == "hold_but_monitor":
            stance = "hold_review" if adverse else "monitor"
    elif allowed == "not_allowed_now":
        plan_type, stance = "wait", "wait"
    else:
        plan_type, stance = "wait", "monitor"

    # ── owner-readable summary ───────────────────────────────────────────────
    disp = f"{symbol} {str(name)[:8]}" if str(symbol)[:1].isdigit() and name != symbol else symbol
    if plan_type == "unknown":
        summary = f"計画：判定保留。{disp}は判断材料(需給/フロー)が不足しており、計画を出せる状態ではありません。"
        why = "証拠不足のまま計画を出すと捏造になるため、データ取得を待ちます。"
    elif event:
        summary = (f"計画：イベント待ち。{ev_name}前のため、{disp}の"
                   f"{'買い増し' if held else '新規'}判断は発表後の金利反応と指数の方向を確認してからです。")
        why = f"{ev_name}の結果次第で前提が変わるため、事前の決め打ちは計画になりません。"
    elif plan_type == "trim_review":
        summary = (f"計画：一部利確を検討する局面です。急騰後にFlowが悪化し需給も重い場合は、"
                   f"利益を守る観点でポジションサイズの確認を優先してください。")
        why = "含み益が大きく、過熱/売り圧力/需給の重さが重なっているため。"
    elif plan_type == "exit_review":
        summary = (f"計画：リスク確認が先です。{disp}に悪化信号が重なっており、"
                   f"買い増しではなく保有リスクの点検(比率・悪化の継続)を先に行ってください。")
        why = "需給・フロー・シナリオの悪化が重なっている保有銘柄のため。"
    elif plan_type == "avoid_chase":
        summary = (f"計画：追いかけ買い注意。{'売り長で踏み上げ余地はありますが、買い戻し主導なら一巡後に失速しやすいです。新規の大口買いが確認できるまで、急騰局面では待ち。' if squeeze else '急伸直後で高値掴みのリスクが高い局面です。出来高を伴う押し目か、上昇主体の入れ替わりを確認してから。'}")
        why = "上昇の持続性(実需買いか)が未確認のため。"
    elif stance == "add_only_on_pullback":
        if improving_heavy:
            summary = ("計画：買うなら押し目限定。需給は改善方向ですが信用買い残はまだ重く、"
                       "A判定ではありません。上昇を追うより、出来高を伴って上値の売りを吸収できるかを確認してください。")
            why = "改善方向≠需給良好。水準が重い間は追加の条件を厳しくするため。"
        elif held and high_conc:
            summary = ("計画：保有継続は可能ですが、買い増しよりリスク確認が先です。"
                       "この銘柄の比率が高く、追加するとポートフォリオ全体の振れが大きくなります。")
            why = "銘柄集中がポートフォリオ全体のリスクを支配するため。"
        else:
            summary = f"計画：買うなら押し目限定。{disp}は追わず、出来高を伴う押し目を待つ方が安全です。"
            why = "土台は悪くないが、追いかけは不利になりやすいため。"
    elif stance == "small_add_allowed":
        summary = (f"計画：小さく{'買い増し' if held else '試し玉'}可(注意付き)。複数レイヤーが好条件ですが、"
                   f"一度に厚くせず小さく分割で。需給悪化・イベント接近が出たら見送りに戻します。")
        why = "需給・フロー・シナリオが揃っているが、計画は常に撤回条件付きのため。"
    elif plan_type == "hold":
        summary = (f"計画：保有継続{'(監視条件付き)' if hold_mode == 'hold_but_monitor' else 'で問題なし'}。"
                   f"{'監視条件は下記の通りです。' if hold_mode == 'hold_but_monitor' else '大きな悪化信号は確認されていません。'}")
        why = "ベースシナリオが安定しており、悪化信号が支配的でないため。"
    else:
        summary = f"計画：待ち。{disp}は現時点で入る条件が揃っておらず、条件の成立を待つ局面です。"
        why = "悪化信号があるか、支持材料が不足しているため。"

    if market_open is False and plan_type in ("entry", "add", "avoid_chase"):
        summary += " " + PTS_WARNING_JA

    conf = {"strong": 0.6, "medium": 0.45, "weak": 0.3, "insufficient": 0.2}[eq]
    return {
        "schemaVersion": SCHEMA_VERSION,
        "id": "tp-" + hashlib.md5(f"{market}:{symbol}:{now_iso[:13]}".encode()).hexdigest()[:10],
        "symbol": str(symbol).upper(), "market": str(market).upper(),
        "assetName": name, "asOf": now_iso,
        "planType": plan_type,
        "planningHorizon": ("next_session" if not event else "this_week"),
        "currentStance": stance, "currentStanceJa": STANCE_JA[stance],
        "ownerReadableSummaryJa": summary[:300],
        "whyJa": why,
        "entryConditionsJa": entry_plan["entryTriggerJa"],
        "addConditionsJa": ([c for c in (
            "出来高を伴う押し目の形成" if stance == "add_only_on_pullback" else None,
            "小さく・分割で(全力は計画外)" if stance == "small_add_allowed" else None,
        ) if c] if held or stance in ("add_only_on_pullback", "small_add_allowed") else []),
        "trimReviewConditionsJa": exit_plan["trimTriggerJa"] if held else [],
        "exitReviewConditionsJa": exit_plan["riskReductionTriggerJa"] if held else [],
        "holdConditionsJa": hold_plan["monitorConditionsJa"] if held else [],
        "invalidationJa": [i for i in (
            f"{ev_name}の結果が想定と逆なら計画を組み直し" if event else None,
            "需給D/Eへの悪化・フロー悪化継続で買い側の計画は無効",
            "出来高を伴う上値更新+需給改善(水準まで軽く)で待ち側の計画は無効",
        ) if i][:3],
        "nextChecksJa": entry_plan["confirmationNeededJa"],
        "whatNotToDoJa": what_not[:4],
        "riskFlags": risk_flags[:5],
        "blockingReasons": blocking[:4],
        "entryPlan": entry_plan, "exitPlan": exit_plan, "holdPlan": hold_plan,
        "sourceEvidence": {
            "scenario": scen or None, "actionPriority": ap_cat or None,
            "supplyDemand": (f"{sd_rank}/{sd_cond}" if has_sd else None),
            "flowAttribution": flow or None,
            "positionExposure": (pos_risk or conc or None) if held else None,
            "marketRegime": ("risk_off" if inputs.get("regimeRiskOff") else None),
            "eventRadar": ev_name if event else None,
        },
        "confidence": conf,
        "evidenceQuality": eq,
        "isHeld": held if held is not None else "unknown",
        "privacyLevel": ("private_local" if held is not None else "public_safe"),
        "priceLevelNoteJa": LEVEL_CAVEAT_JA,
        "sourceLimitNote": "既存レイヤー(シナリオ/優先度/需給/フロー/イベント/保有)の合成であり、"
                           "価格レベルの捏造・注文・自動売買は行わない。",
        "complianceNote": COMPLIANCE,
    }


def portfolio_summary(plans: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Core Portfolio用 — どこで追加可/ブロック/利確検討/イベント待ちか。"""
    def rows(pred):
        return [f"{p['symbol']} {str(p['assetName'])[:8]}" for p in plans if pred(p)][:5]
    n_block = [p for p in plans if p["blockingReasons"]]
    return {
        "schemaVersion": "plan-portfolio-summary-v1",
        "addAllowedSmall": rows(lambda p: p["currentStance"] == "small_add_allowed"),
        "pullbackOnly": rows(lambda p: p["currentStance"] == "add_only_on_pullback"),
        "avoidChase": rows(lambda p: p["currentStance"] == "avoid_chase"),
        "riskReview": rows(lambda p: p["currentStance"] in ("risk_review", "trim_consideration")),
        "eventWait": rows(lambda p: p["planType"] == "event_wait"),
        "blockedCount": len(n_block),
        "summaryJa": (f"計画サマリ: 小さく追加可{sum(1 for p in plans if p['currentStance'] == 'small_add_allowed')}件 / "
                      f"押し目限定{sum(1 for p in plans if p['currentStance'] == 'add_only_on_pullback')}件 / "
                      f"追いかけ注意{sum(1 for p in plans if p['currentStance'] == 'avoid_chase')}件 / "
                      f"リスク確認{sum(1 for p in plans if p['currentStance'] in ('risk_review', 'trim_consideration'))}件 / "
                      f"イベント待ち{sum(1 for p in plans if p['planType'] == 'event_wait')}件"),
        "complianceNote": COMPLIANCE,
    }


def handoff_section(plans: List[Dict[str, Any]]) -> Dict[str, Any]:
    def rows(pred):
        return [f"{p['symbol']} — {p['ownerReadableSummaryJa'][:70]}" for p in plans if pred(p)][:4]
    return {
        "title": "Entry / Exit Planning",
        "entryCandidates": rows(lambda p: p["currentStance"] == "small_add_allowed"),
        "pullbackOnly": rows(lambda p: p["currentStance"] == "add_only_on_pullback"),
        "avoidChase": rows(lambda p: p["currentStance"] == "avoid_chase"),
        "trimRiskReview": rows(lambda p: p["currentStance"] in ("risk_review", "trim_consideration")),
        "eventWaitBlocked": rows(lambda p: p["planType"] == "event_wait"),
        "invalidationJa": "各計画の無効化条件を必ず併読(条件が崩れた計画は捨てる)。",
        "missingEvidence": sorted({m for p in plans if p["evidenceQuality"] == "insufficient"
                                   for m in (p["symbol"],)})[:5],
        "disclaimerJa": COMPLIANCE,
    }


def status_doc(plans: List[Dict[str, Any]], *, now_iso: str,
               sources: Dict[str, bool]) -> Dict[str, Any]:
    return {
        "schemaVersion": "trade-plan-status-v1", "asOf": now_iso,
        "featureEnabled": True, "lastRunAt": now_iso,
        "plansGenerated": len(plans),
        "entryPlanCount": sum(1 for p in plans if p["planType"] in ("entry", "wait")),
        "addPlanCount": sum(1 for p in plans if p["planType"] == "add"),
        "avoidChaseCount": sum(1 for p in plans if p["planType"] == "avoid_chase"),
        "trimReviewCount": sum(1 for p in plans if p["planType"] in ("trim_review", "exit_review")),
        "eventWaitCount": sum(1 for p in plans if p["planType"] == "event_wait"),
        "insufficientEvidenceCount": sum(1 for p in plans
                                         if p["evidenceQuality"] == "insufficient"),
        "storageMode": "public_redacted",
        "publicLeakSafe": True,
        "sourceAvailability": sources,
        "noteJa": "公開側はウォッチリスト水準のみ(保有文脈・数量・損益は端末内)。"
                  "執行語なし・注文機能なし。JPリアルタイム無効は意図的(エラーではない)。",
        "complianceNote": COMPLIANCE,
    }
