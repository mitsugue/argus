"""ARGUS V11.12.0 — Action Priority Engine (pure, deterministic).

ARGUSには層が増えた(イベント/レジーム/機関/フロー/需給/保有/判断品質)。
この層はそれらを束ねて「今日、最優先で見るべきものは何か」に答える —
注意配分(attention routing)であり、売買指示では絶対にない。

HARD RULES:
  - P0 is RARE: held asset × compounded adverse evidence only. A quiet day has
    zero P0s and that is correct output.
  - actionLabel is an attention label (CHECK_NOW/WAIT_EVENT/AVOID_CHASE/…),
    never a trade order. No buy/sell verbs anywhere.
  - Every item carries why + next-check (+ what-would-change when practical) —
    a bare label without explanation is a bug.
  - Missing data on a HELD asset surfaces as a data-warning item; it is never
    hidden and never converted into fake exposure.
  - Decision Quality history modifies confidence MODESTLY (history is short;
    never overfit).
  - Public/backend callers pass is_held=None → items rank watchlist-level and
    stay privacy-safe by construction; the device-local TS port supplies real
    held/weight context.
"""
from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Optional

SCHEMA_VERSION = "action-priority-v1"

RANKS = ("P0", "P1", "P2", "P3", "Watch", "Ignore", "Unknown")
URGENCIES = ("immediate", "today", "this_week", "monitor", "low", "unknown")
CATEGORIES = ("held_risk", "event_wait", "avoid_chase", "add_candidate",
              "add_only_on_pullback", "supply_demand_watch", "flow_watch",
              "institutional_watch", "regime_risk", "position_concentration",
              "decision_review", "data_missing", "no_action", "unknown")
ACTION_LABELS = ("CHECK_NOW", "WAIT_EVENT", "AVOID_CHASE", "ADD_ONLY_ON_PULLBACK",
                 "SMALL_ADD_ALLOWED", "MONITOR", "REVIEW_POSITION", "INVESTIGATE",
                 "IGNORE_TODAY", "NO_ACTION", "UNKNOWN")
BLOCKING = ("event_pending", "data_stale", "missing_position_data", "overextended",
            "concentration_too_high", "supply_demand_bad", "flow_conflict",
            "regime_headwind", "unknown", "none")

RANK_JA = {"P0": "最優先確認", "P1": "今日の優先", "P2": "重要(急がない)",
           "P3": "参考", "Watch": "監視", "Ignore": "今日は重要度低",
           "Unknown": "判定保留"}
LABEL_JA = {"CHECK_NOW": "いま確認", "WAIT_EVENT": "イベント待ち",
            "AVOID_CHASE": "追いかけ買い注意", "ADD_ONLY_ON_PULLBACK": "買うなら押し目限定",
            "SMALL_ADD_ALLOWED": "小さく買い増し可", "MONITOR": "監視継続",
            "REVIEW_POSITION": "ポジション点検", "INVESTIGATE": "要調査",
            "IGNORE_TODAY": "今日は放置可", "NO_ACTION": "対応不要", "UNKNOWN": "判定保留"}

COMPLIANCE = "注意配分の優先度であり売買指示ではない。"


def _f(v) -> Optional[float]:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def build_item(symbol: str, market: str, inputs: Dict[str, Any],
               now_iso: str) -> Dict[str, Any]:
    """One asset's signals → ActionPriorityItem. All inputs optional:
      isHeld (True/False/None), weightPct, concentrationRisk('low'..'critical'),
      positionRiskLevel, readiness (v11.8 add-more), sdRank, sdCondition,
      flowClass, instStance, instDirect, eventPending(bool), eventName,
      regimeRiskOff, changePct, priorRunupPct, dataMissing(list[str]),
      dqNoteJa/dqContradictedAvoidChase(bool), assetName
    """
    held = inputs.get("isHeld")                        # True / False / None(unknown)
    weight = _f(inputs.get("weightPct"))
    conc = inputs.get("concentrationRisk")
    pos_risk = inputs.get("positionRiskLevel")
    readiness = inputs.get("readiness")
    sd_rank = str(inputs.get("sdRank") or "")
    sd_cond = str(inputs.get("sdCondition") or "")
    flow = str(inputs.get("flowClass") or "")
    chg = _f(inputs.get("changePct"))
    runup = _f(inputs.get("priorRunupPct"))
    missing = list(inputs.get("dataMissing") or [])
    event_pending = bool(inputs.get("eventPending"))
    risk_off = bool(inputs.get("regimeRiskOff"))

    score = 0.0
    reasons: List[str] = []
    category, label, blocking = "no_action", "NO_ACTION", "none"
    adverse = 0                                        # count of adverse layers

    if held:
        score += 30
        reasons.append("HELD")
        if weight is not None and weight >= 25:
            score += 10
            reasons.append("LARGE_POSITION")
        if conc in ("high", "critical"):
            score += 15 if conc == "critical" else 8
            reasons.append("CONCENTRATION")
    elif held is None:
        reasons.append("HELD_UNKNOWN")

    # adverse layers
    if flow in ("panic_selling", "distribution"):
        score += 25 if held else 12
        adverse += 1
        reasons.append(f"FLOW_{flow.upper()}")
        category, label = "flow_watch", "CHECK_NOW" if held else "MONITOR"
    if sd_rank in ("D", "E"):
        score += 20 if held else 10
        adverse += 1
        reasons.append(f"SD_{sd_rank}")
        if category == "no_action":
            category, label = "supply_demand_watch", "MONITOR"
        blocking = "supply_demand_bad"
    if pos_risk in ("high", "critical"):
        score += 20
        adverse += 1
        reasons.append("POSITION_RISK")
        category = "held_risk"
    if chg is not None and chg <= -5 and held:
        score += 15
        adverse += 1
        reasons.append("BIG_DROP")
        category = "held_risk"
    if risk_off and held and inputs.get("highBeta", True) and adverse:
        score += 8
        reasons.append("REGIME_HEADWIND")
        if blocking == "none":
            blocking = "regime_headwind"

    # chase / squeeze
    if readiness == "avoid_chase" or flow == "retail_chase" \
            or (runup is not None and runup >= 15):
        score += 15 if held else 12
        reasons.append("CHASE_RISK")
        category, label = "avoid_chase", "AVOID_CHASE"
        if blocking == "none" and runup is not None and runup >= 15:
            blocking = "overextended"
    if sd_cond == "squeeze_prone":
        score += 10
        reasons.append("SQUEEZE_PRONE")
        if category in ("no_action", "supply_demand_watch"):
            category, label = "avoid_chase", "AVOID_CHASE"

    # positive side (never above held risks)
    if readiness == "add_only_on_pullback" or (sd_rank in ("S", "A", "B")
                                               and sd_cond != "squeeze_prone"
                                               and readiness not in ("wait", "unknown")):
        score += 10
        reasons.append("PULLBACK_CANDIDATE")
        if category == "no_action":
            category, label = "add_only_on_pullback", "ADD_ONLY_ON_PULLBACK"
    if readiness == "add_allowed_small" and not adverse and not event_pending:
        score += 6
        reasons.append("SMALL_ADD_OK")
        if category == "no_action":
            category, label = "add_candidate", "SMALL_ADD_ALLOWED"

    # institutional (direct only meaningfully)
    if inputs.get("instStance") in ("bullish", "bearish"):
        score += 8 if inputs.get("instDirect") else 3
        reasons.append("INST_" + ("DIRECT" if inputs.get("instDirect") else "HEADLINE"))
        if category == "no_action":
            category, label = "institutional_watch", "MONITOR"

    # event gate — blocks aggressive labels
    if event_pending:
        score += 15 if held else 8
        reasons.append("EVENT_PENDING")
        blocking = "event_pending"
        if label in ("SMALL_ADD_ALLOWED", "ADD_ONLY_ON_PULLBACK", "NO_ACTION", "MONITOR"):
            category, label = "event_wait", "WAIT_EVENT"

    # missing data on held asset = warning item, never silence
    if held and missing:
        score += 15
        reasons.append("DATA_MISSING_HELD")
        if category == "no_action":
            category, label = "data_missing", "INVESTIGATE"
        if blocking == "none":
            blocking = "missing_position_data" if "保有数量" in " ".join(missing) else "data_stale"

    # decision-quality modifier — MODEST, never dominant
    dq_conf_adj = 0.0
    if inputs.get("dqContradictedAvoidChase"):
        dq_conf_adj = -0.05
        reasons.append("DQ_OVERCONSERVATIVE_HINT")
    elif inputs.get("dqSupported"):
        dq_conf_adj = +0.05
        reasons.append("DQ_EARLY_SUPPORT")

    # ── rank ────────────────────────────────────────────────────────────────
    if held and adverse >= 2 and score >= 70:
        rank, urgency = "P0", "immediate"
    elif held and event_pending and adverse >= 1 and score >= 60:
        rank, urgency = "P0", "today"
    elif score >= 45:
        rank, urgency = "P1", "today"
    elif score >= 25:
        rank, urgency = "P2", "this_week"
    elif score >= 12:
        rank, urgency = ("P3", "monitor")
    elif held is None and not reasons:
        rank, urgency = "Unknown", "unknown"
    else:
        rank, urgency = ("Watch", "monitor") if score >= 6 else ("Ignore", "low")
    if held and rank == "Ignore":
        rank, urgency = "Watch", "monitor"            # held assets are never hidden
    if rank == "P0" and label in ("MONITOR", "NO_ACTION"):
        label = "CHECK_NOW"
    if rank == "Ignore":
        category, label = "no_action", "IGNORE_TODAY"

    conf = min(0.85, max(0.2, 0.35 + score / 200 + dq_conf_adj
                         - (0.1 if missing else 0.0)))

    name = inputs.get("assetName") or symbol
    title, why, check, change = _texts(rank, label, category, name, held, sd_rank,
                                       sd_cond, flow, inputs.get("eventName"),
                                       missing, chg, weight)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "id": "ap-" + hashlib.md5(f"{market}:{symbol}:{now_iso[:13]}".encode()).hexdigest()[:10],
        "symbol": str(symbol).upper(), "market": str(market).upper(),
        "assetName": name, "asOf": now_iso,
        "priorityRank": rank, "priorityRankJa": RANK_JA[rank],
        "priorityScore": round(score, 1),
        "urgency": urgency,
        "category": category,
        "actionLabel": label, "actionLabelJa": LABEL_JA[label],
        "ownerReadableTitleJa": title,
        "ownerReadableWhyJa": why,
        "checkNextJa": check,
        "whatWouldChangeJa": change,
        "confidence": round(conf, 2),
        "evidence": {
            "positionRisk": pos_risk, "exposureRisk": conc,
            "eventRisk": inputs.get("eventName") if event_pending else None,
            "flowSignal": flow or None, "supplyDemandSignal": (sd_rank or None),
            "institutionalSignal": inputs.get("instStance"),
            "marketRegime": ("risk_off" if risk_off else None),
            "priceAction": (f"{chg:+.1f}%" if chg is not None else None),
            "decisionQuality": inputs.get("dqNoteJa"),
            "missingEvidence": missing[:5],
        },
        "reasonCodes": reasons[:10],
        "blockingReason": blocking,
        "timeWindow": ("intraday" if urgency == "immediate" else
                       "next_session" if urgency == "today" else
                       "this_week" if urgency == "this_week" else "unknown"),
        "isHeld": (held if held is not None else "unknown"),
        "privacyLevel": ("private_local" if held is not None else "public_safe"),
        "sourceLimitNote": "既存レイヤー(イベント/レジーム/機関/フロー/需給/保有/判断品質)の"
                           "統合であり、新しい市場データではない。",
        "complianceNote": COMPLIANCE,
    }


def _texts(rank, label, category, name, held, sd_rank, sd_cond, flow,
           event_name, missing, chg, weight):
    held_ja = "保有中の" if held else ""
    if category == "held_risk":
        title = f"最優先確認：{held_ja}{name}にリスク信号が重なっています"
        why = (f"{held_ja}{name}" + (f"が{chg:+.1f}%と大きく動き、" if chg is not None and abs(chg) >= 5 else "に")
               + ("需給・フローの悪化が重なっています。" if sd_rank in ("D", "E") or flow in ("panic_selling", "distribution")
                  else "リスク信号が出ています。"))
        check = "まず下落理由(原因の詳細)と大口フローの継続を確認"
        change = "売り圧力の推定が消えるか、公式材料で原因が確定すれば優先度は下がります"
    elif category == "event_wait":
        ev = event_name or "重要イベント"
        title = f"イベント待ち：{ev}の結果を見てから"
        why = f"{ev}の発表前のため、{name}の積極的な判断は結果と初動反応を確認してからが安全です。"
        check = f"{ev}の結果発表と直後の金利・指数反応を確認"
        change = "イベント通過後、反応が想定内なら通常の優先度に戻ります"
    elif category == "avoid_chase":
        title = f"追いかけ注意：{name}"
        why = ("踏み上げ余地はありますが、買い戻し主導の可能性があり新規の大口買いとは未確定です。"
               if sd_cond == "squeeze_prone" else
               "急伸直後で高値掴みのリスクが高い局面です。この上昇を追う前に保有比率と需給を確認してください。")
        check = "出来高を伴う押し目が来るか、上昇の主体が入れ替わるかを確認"
        change = "押し目形成または実測フローでの大口買い確認で評価が変わります"
    elif category == "add_only_on_pullback":
        title = f"押し目限定候補：{name}"
        why = (f"需給ランク{sd_rank}で土台は悪くありませんが、" if sd_rank in ("S", "A", "B") else "")\
              + "既に上昇している場合は追わず、出来高を伴う押し目を待つ方が安全です。"
        check = "押し目の深さと出来高、需給の次回更新を確認"
        change = "需給悪化またはイベント接近で候補から外れます"
    elif category == "add_candidate":
        title = f"小さく買い増し可：{name}"
        why = "明確なブロック要因はありません。ただし一度に大きく買わず、小さく分けるのが基本です。"
        check = "翌営業日の継続性(出来高を伴うか)を確認"
        change = "需給・フロー・イベントのいずれかが悪化すれば見送りへ"
    elif category == "data_missing":
        title = f"データ確認：{held_ja}{name}"
        why = f"保有銘柄ですが判定に必要なデータが不足しています({' / '.join(missing[:2])})。"
        check = "データ更新後(平日の巡回)に再確認"
        change = "データ取得後に通常の優先度判定に戻ります"
    elif category in ("supply_demand_watch", "flow_watch"):
        title = f"需給/フロー注意：{name}"
        why = (f"需給ランク{sd_rank}" if sd_rank else "フロー") + "に注意信号が出ています。"
        check = "戻り局面で売りが出るか、翌営業日の継続を確認"
        change = "信号が2営業日続けば優先度を上げ、消えれば下げます"
    elif category == "institutional_watch":
        title = f"機関シグナル：{name}"
        why = "機関の公開シグナルがあります(見出しのみの場合は確度低)。"
        check = "本文・複数ソースでの裏取りを確認"
        change = "直接言及や複数ソース確認で重要度が上がります"
    elif category == "no_action" and rank == "Ignore":
        title = f"今日は重要度低：{name}"
        why = "大きな材料・需給変化・保有リスクがありません。"
        check = "定例の巡回のみで十分です"
        change = "±2%超の動き・イベント・需給変化で再浮上します"
    else:
        title = f"{RANK_JA.get(rank, rank)}：{name}"
        why = "複数レイヤーの信号を統合した優先度です。"
        check = "各レイヤーの詳細(需給/フロー/イベント)を確認"
        change = "主要な信号の変化で優先度が変わります"
    return title, why, check, change


def rank_items(items: List[Dict[str, Any]], cap: int = 12) -> List[Dict[str, Any]]:
    order = {r: i for i, r in enumerate(RANKS)}
    out = sorted(items, key=lambda x: (order.get(x["priorityRank"], 9),
                                       -x["priorityScore"]))
    return out[:cap]


def summary(items: List[Dict[str, Any]], now_iso: str,
            market_mode_ja: str = "") -> Dict[str, Any]:
    def n(pred):
        return sum(1 for i in items if pred(i))
    top = next((i for i in items if i["priorityRank"] in ("P0", "P1")), None)
    p0, p1 = n(lambda i: i["priorityRank"] == "P0"), n(lambda i: i["priorityRank"] == "P1")
    brief = ("今日は最優先の確認事項はありません。" if p0 == 0 and p1 == 0 else
             f"今日は P0 {p0}件 / P1 {p1}件。まず「{top['ownerReadableTitleJa']}」から。"
             if top else "")
    return {
        "schemaVersion": "action-priority-summary-v1", "asOf": now_iso,
        "itemsTotal": len(items),
        "p0Count": p0, "p1Count": p1, "p2Count": n(lambda i: i["priorityRank"] == "P2"),
        "heldRiskCount": n(lambda i: i["category"] == "held_risk"),
        "avoidChaseCount": n(lambda i: i["category"] == "avoid_chase"),
        "addCandidateCount": n(lambda i: i["category"] in ("add_candidate", "add_only_on_pullback")),
        "eventWaitCount": n(lambda i: i["category"] == "event_wait"),
        "ignoredCount": n(lambda i: i["priorityRank"] == "Ignore"),
        "dataMissingCount": n(lambda i: i["category"] == "data_missing"),
        "topPriorityJa": top["ownerReadableTitleJa"] if top else None,
        "ownerBriefJa": brief,
        "marketModeJa": market_mode_ja or None,
        "missingDataSummaryJa": (f"データ不足 {n(lambda i: i['category'] == 'data_missing')}件"
                                 if n(lambda i: i["category"] == "data_missing") else None),
        "privacyLevel": ("private_local"
                         if any(i["privacyLevel"] == "private_local" for i in items)
                         else "public_safe"),
        "complianceNote": COMPLIANCE,
    }


def status_doc(items: List[Dict[str, Any]], *, now_iso: str,
               sources: Dict[str, bool]) -> Dict[str, Any]:
    """PUBLIC status — aggregate counts only (watchlist-level items carry no
    holdings by construction)."""
    s = summary(items, now_iso)
    return {
        "schemaVersion": "action-priority-status-v1", "asOf": now_iso,
        "featureEnabled": True, "lastRunAt": now_iso,
        "itemsGenerated": s["itemsTotal"],
        "p0Count": s["p0Count"], "p1Count": s["p1Count"],
        "heldRiskCount": 0,                    # held context is device-local only
        "eventWaitCount": s["eventWaitCount"],
        "avoidChaseCount": s["avoidChaseCount"],
        "addCandidateCount": s["addCandidateCount"],
        "dataMissingCount": s["dataMissingCount"],
        "publicLeakSafe": True,
        "storageMode": "public_redacted",
        "sourceAvailability": sources,
        "noteJa": "公開側はウォッチリスト水準の優先度のみ(保有情報は端末内で加味)。"
                  "JPリアルタイム無効は意図的で欠陥ではない。",
        "complianceNote": COMPLIANCE,
    }


def handoff_section(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    def rows(pred, cap=4):
        return [f"[{i['priorityRank']}] {i['ownerReadableTitleJa']} — {i['ownerReadableWhyJa'][:60]}"
                for i in items if pred(i)][:cap]
    return {
        "title": "Action Priority Summary",
        "top": rows(lambda i: i["priorityRank"] in ("P0", "P1")),
        "blocked": rows(lambda i: i["blockingReason"] == "event_pending"),
        "pullbackAdds": rows(lambda i: i["category"] == "add_only_on_pullback"),
        "avoidChase": rows(lambda i: i["category"] == "avoid_chase"),
        "ignored": rows(lambda i: i["priorityRank"] == "Ignore", cap=3),
        "missingEvidence": sorted({m for i in items
                                   for m in i["evidence"]["missingEvidence"]})[:5],
        "disclaimerJa": COMPLIANCE,
    }
