"""ARGUS V11.17.0 — Scenario Engine (pure, deterministic).

「明日どうなる?」に単一予測で答えない — 証拠から組んだ**条件付きの分岐**
(ベース/強気/弱気/踏み上げ→失速/イベント待ち)と、無効化条件・次の確認・
何が変われば判断が変わるか、で答える。売買指示では絶対にない。

HARD RULES:
  - 正確な確率(%)は実証済みモデルなしに絶対に使わない。帯のみ:
    high/medium/low/unknown(「〜優勢」「成立条件付き」「材料待ち」語彙)。
  - 証拠がなければシナリオを作らない(missing明示・evidenceQuality低下)。
  - 保有は監視銘柄と別扱い(保有リスクを捏造しない/隠さない)。
  - squeeze上昇は「買い戻し主導なら一巡後に失速しやすい」を必ず併記。
  - improving_but_heavy はA扱いに絶対しない(「上値吸収の確認まで」)。
  - イベント前は攻めの支配シナリオを出さない(wait_event)。
  - 各ケースに invalidation / nextChecks / whatWouldChange を必ず付ける。
"""
from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Optional

SCHEMA_VERSION = "scenario-v1"

CASE_LABELS = ("bullish", "base", "bearish", "squeeze_then_fade", "event_upside",
               "event_downside", "wait_event", "range_bound", "unknown")
BANDS = ("high", "medium", "low", "unknown")
BAND_JA = {"high": "優勢", "medium": "中程度", "low": "成立条件付き", "unknown": "判定保留"}
DOMINANTS = ("bullish", "base", "bearish", "mixed", "wait_event", "unknown")
EVIDENCE_QUALITY = ("strong", "medium", "weak", "insufficient")
ACTIONS = ("monitor", "wait", "avoid_chase", "add_only_on_pullback",
           "small_add_allowed", "review_position", "caution", "no_action", "unknown")
COMPLIANCE = "条件付きシナリオであり予測でも売買指示でもない。"


def _f(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _case(label, title, narrative, band, behavior, conditions, supporting,
          opposing, risks, action, caveat):
    return {"id": f"sc-{label}", "label": label, "titleJa": title,
            "narrativeJa": narrative[:260],
            "probabilityBand": band, "probabilityBandJa": BAND_JA[band],
            "expectedBehaviorJa": behavior[:160],
            "conditionsJa": conditions[:4],
            "supportingEvidence": supporting[:4], "opposingEvidence": opposing[:3],
            "riskFlags": risks[:4],
            "actionImplication": action,
            "confidence": {"high": 0.6, "medium": 0.45, "low": 0.3, "unknown": 0.2}[band],
            "caveatJa": caveat}


def build_scenario_set(symbol: str, market: str, inputs: Dict[str, Any],
                       now_iso: str) -> Dict[str, Any]:
    """inputs (existing-layer facts; None=unknown, never guessed):
      isHeld(bool|None), assetName, sdRank, sdCondition, sdLevel, sdDirection,
      flowClass, instStance, instDirect, eventPending, eventName, regimeRiskOff,
      changePct, priorRunupPct, concentrationRisk, positionRiskLevel, missing[]
    """
    held = inputs.get("isHeld")
    name = inputs.get("assetName") or symbol
    disp = f"{symbol} {str(name)[:8]}" if str(symbol)[:1].isdigit() and name != symbol else symbol
    sd_rank = str(inputs.get("sdRank") or "")
    sd_cond = str(inputs.get("sdCondition") or "")
    sd_level = str(inputs.get("sdLevel") or "")
    flow = str(inputs.get("flowClass") or "")
    chg = _f(inputs.get("changePct"))
    runup = _f(inputs.get("priorRunupPct"))
    event = bool(inputs.get("eventPending"))
    ev_name = inputs.get("eventName") or "重要イベント"
    risk_off = bool(inputs.get("regimeRiskOff"))
    missing = list(inputs.get("missing") or [])
    heavy = sd_level in ("heavy", "very_heavy")
    squeeze = sd_cond == "squeeze_prone" or flow == "short_covering"
    improving_heavy = sd_cond == "improving_but_heavy"
    adverse = (sd_rank in ("D", "E")) + (flow in ("panic_selling", "distribution")) \
        + (inputs.get("positionRiskLevel") in ("high", "critical"))
    supportive = (sd_rank in ("S", "A", "B") and not squeeze and not heavy) \
        + (flow == "institutional_accumulation") \
        + (inputs.get("instStance") == "bullish" and bool(inputs.get("instDirect")))
    overextended = runup is not None and runup >= 15

    has_sd = bool(sd_rank and sd_rank != "Unknown")
    has_flow = bool(flow and flow != "unknown")
    eq = ("strong" if has_sd and has_flow and not missing else
          "medium" if has_sd or has_flow else
          "weak" if chg is not None else "insufficient")

    cases: List[Dict[str, Any]] = []
    caveat = COMPLIANCE

    # ── base ─────────────────────────────────────────────────────────────────
    if improving_heavy:
        base_narr = (f"需給は改善方向ですが、信用買い残の水準はまだ重いです。上昇しても"
                     f"戻り売りが出やすいため、追いかけ買いより押し目で出来高を伴って"
                     f"吸収できるか確認です。上値吸収を確認するまでA扱いしません。")
        base_action = "add_only_on_pullback"
    elif event:
        base_narr = f"{ev_name}前のため、積極判断は発表後の金利・為替・株価反応を確認してからです。"
        base_action = "wait"
    elif adverse >= 2:
        base_narr = "需給・フローの悪化が重なっており、戻りは売られやすい前提で確認を優先します。"
        base_action = "caution"
    elif supportive >= 1 and not overextended:
        base_narr = "土台(需給/フロー)は悪くありませんが、決め打ちせず出来高を伴う継続を確認します。"
        base_action = "monitor"
    else:
        base_narr = "強い偏りは確認できず、現状維持で材料と需給の更新を待つ局面です。"
        base_action = "no_action" if not held else "monitor"
    cases.append(_case("base", f"ベースシナリオ：{disp}", base_narr,
                       "medium" if eq in ("strong", "medium") else "unknown",
                       "レンジ内での推移と材料待ちが中心",
                       ["大きな新規材料が出ない", "需給・フローが現状維持"],
                       [s for s in (f"需給{sd_rank}" if has_sd else None,
                                    f"フロー:{flow}" if has_flow else None) if s],
                       [], ["データ更新待ち"] if missing else [], base_action, caveat))

    # ── bullish ──────────────────────────────────────────────────────────────
    bull_ok = supportive >= 1 and not event and not overextended and adverse == 0
    bull_band = "medium" if bull_ok and eq == "strong" else "low"
    if squeeze:
        bull_narr = ("売り長のため踏み上げが続く可能性があります。ただし買い戻し主導なら"
                     "一巡後に失速しやすく、新規大口買いとは未確定です。")
    elif improving_heavy:
        bull_narr = ("買い残の消化が進み、上昇日に出来高を伴って高値圏で引けられれば、"
                     "需給評価の引き上げ余地があります(現時点では条件付き)。")
    else:
        bull_narr = ("需給・フローの支えが続き、出来高を伴って上値を消化できれば"
                     "続伸シナリオが成立します(成立条件付き)。")
    cases.append(_case("bullish", f"強気シナリオ：{disp}", bull_narr, bull_band,
                       "出来高を伴う続伸・押し目が浅い",
                       ["出来高を伴う上値更新", "需給悪化が出ない", "イベント通過"],
                       [s for s in (f"需給{sd_rank}" if sd_rank in ("S", "A", "B") else None,
                                    "実測フロー流入" if flow == "institutional_accumulation" else None) if s],
                       ["買い戻し主導の可能性" if squeeze else "買い残の重さ" if heavy else ""],
                       ["踏み上げ失速リスク"] if squeeze else [],
                       "avoid_chase" if (squeeze or overextended) else "add_only_on_pullback",
                       caveat))

    # ── bearish ──────────────────────────────────────────────────────────────
    bear_band = ("medium" if adverse >= 1 or (risk_off and held) or heavy else "low")
    bear_narr = ("需給が重く(買い残過多)、戻り局面で売りに押されやすいシナリオです。"
                 if heavy or sd_rank in ("D", "E") else
                 "売り圧力(フロー悪化)が続けば、戻りが売られる展開を想定します。"
                 if flow in ("panic_selling", "distribution") else
                 "地合い悪化や外部材料次第で下押しするシナリオです(現時点では条件付き)。")
    cases.append(_case("bearish", f"弱気シナリオ：{disp}", bear_narr, bear_band,
                       "戻り売り・安値引けが増える",
                       ["戻りが出来高薄で売られる", "需給D/Eへの悪化", "リスクオフ地合いの継続"],
                       [s for s in (f"需給{sd_rank}" if sd_rank in ("D", "E") else None,
                                    f"フロー:{flow}" if flow in ("panic_selling", "distribution") else None,
                                    "買い残重い" if heavy else None) if s],
                       [], [], "review_position" if held else "wait", caveat))

    # ── special cases ────────────────────────────────────────────────────────
    if squeeze:
        cases.append(_case("squeeze_then_fade", f"踏み上げ→失速シナリオ：{disp}",
                           "売り長の買い戻しで短期急伸した後、買い戻し一巡とともに失速する"
                           "パターンです。上昇の主体が実需買いに入れ替わるかが分岐点です。",
                           "medium" if eq != "insufficient" else "unknown",
                           "急伸→出来高減とともに伸び悩み",
                           ["買い戻し一巡", "実需買いの不在"],
                           ["売り長(貸借倍率<1)"], ["実測大口買いの確認"],
                           ["高値掴みリスク"], "avoid_chase", caveat))
    if event:
        cases.append(_case("wait_event", f"イベント待ち：{ev_name}",
                           f"{ev_name}の結果と初動(金利・為替・指数)が方向を決めます。"
                           "発表前の仕込みは結果次第で無効化されます。",
                           "high", "発表までは方向感なし",
                           [f"{ev_name}の結果待ち"], [], [], [], "wait", caveat))

    # ── dominant ─────────────────────────────────────────────────────────────
    if event:
        dominant = "wait_event"
    elif adverse >= 2 or (heavy and flow in ("panic_selling", "distribution")):
        dominant = "bearish"
    elif bull_ok and supportive >= 2:
        dominant = "bullish"
    elif adverse >= 1 and supportive >= 1:
        dominant = "mixed"
    elif eq == "insufficient":
        dominant = "unknown"
    else:
        dominant = "base"

    held_note = ("保有中のため、同じ変化でも監視銘柄より優先度が高いです。"
                 if held else "")
    summary = {
        "wait_event": f"{ev_name}前のため判断保留が支配的です。{held_note}",
        "bearish": f"現時点では弱気シナリオ優勢 — 戻り売り前提で確認を優先。{held_note}",
        "bullish": f"強気シナリオ優勢(ただし成立条件付き)。追いかけず条件の成立を確認。{held_note}",
        "mixed": f"強弱が拮抗 — 決め打ちせず分岐条件(出来高・需給更新)を確認。{held_note}",
        "unknown": "証拠不足のためシナリオは判定保留です。",
        "base": f"現時点ではベースシナリオ優勢 — 材料と需給の更新を待って判断。{held_note}",
    }[dominant]

    next_checks = [c for c in (
        f"{ev_name}の結果と初動反応" if event else None,
        "上昇日に出来高を伴って高値圏で引けるか(上値吸収)" if heavy or improving_heavy else None,
        "買い戻し一巡後に失速しないか" if squeeze else None,
        "戻り局面で売りが出るか" if adverse else None,
        "需給(週次信用残/日次貸借残)の次回更新" if has_sd else "需給データの取得",
    ) if c][:4]
    invalidation = [c for c in (
        "強気: 出来高を伴わない上昇/押し目割れで無効" ,
        "弱気: 出来高を伴う上値更新と需給改善(水準まで軽く)で無効",
        f"全体: {ev_name}の結果が想定と逆なら組み直し" if event else None,
    ) if c]
    what_changes = [c for c in (
        "実測フローで大口買いが確認されれば強気側へ",
        "信用買い残の水準が普通まで軽くなれば評価引き上げ" if heavy or improving_heavy else None,
        "需給D/Eへの悪化・フロー悪化継続なら弱気側へ",
    ) if c][:3]

    triggers = [t for t in (
        {"triggerType": "event_result", "descriptionJa": f"{ev_name}の結果発表",
         "sourceModule": "event_radar", "effectOnScenarioJa": "wait_event解除・方向決定"} if event else None,
        {"triggerType": "volume_confirmation", "descriptionJa": "上昇日の出来高増(平均比1.5倍目安)",
         "sourceModule": "supply_demand", "effectOnScenarioJa": "強気シナリオの成立条件"},
        {"triggerType": "flow_change", "descriptionJa": "実測フローの流入/流出転換",
         "sourceModule": "flow_attribution", "effectOnScenarioJa": "強気/弱気の入れ替え"},
        {"triggerType": "supply_demand_change", "descriptionJa": "週次信用残・日次貸借残の更新",
         "sourceModule": "supply_demand", "effectOnScenarioJa": "水準・方向の再判定"},
    ) if t]

    return {
        "schemaVersion": SCHEMA_VERSION,
        "id": "sn-" + hashlib.md5(f"{market}:{symbol}:{now_iso[:13]}".encode()).hexdigest()[:10],
        "symbol": str(symbol).upper(), "market": str(market).upper(),
        "assetName": name, "asOf": now_iso,
        "scenarioType": "asset", "timeHorizon": "next_session",
        "cases": cases,
        "dominantScenario": dominant,
        "confidence": {"strong": 0.55, "medium": 0.45, "weak": 0.3,
                       "insufficient": 0.2}[eq],
        "evidenceQuality": eq,
        "ownerReadableSummaryJa": summary[:200],
        "nextChecksJa": next_checks,
        "whatWouldChangeJa": what_changes,
        "invalidationJa": invalidation[:3],
        "missingEvidence": missing[:4],
        "isHeld": held if held is not None else "unknown",
        "privacyLevel": ("private_local" if held is not None else "public_safe"),
        "triggers": triggers[:4],
        "sourceLimitNote": "既存レイヤー(需給/フロー/イベント/レジーム/保有)の合成であり新データではない。",
        "complianceNote": COMPLIANCE,
    }


def market_scenario(regime_label: Optional[str], risk_off: bool,
                    event_names: List[str], now_iso: str) -> Dict[str, Any]:
    ev = "/".join([e for e in event_names if e][:2])
    if ev:
        dom, summ = "wait_event", f"{ev}待ち — 発表後の金利・為替反応が方向を決めます。イベント前の追いかけ買いは抑制。"
    elif risk_off:
        dom, summ = "bearish", "リスク回避寄りの地合い — 高ベータの戻りは売られやすい前提で。"
    elif regime_label == "RISK_ON":
        dom, summ = "base", "リスクオン寄りの地合い。ただし過熱銘柄の追いかけ買いは別問題(需給を確認)。"
    else:
        dom, summ = "base", "地合いは中立圏 — 個別の需給・材料が優先されます。"
    return {"schemaVersion": "market-scenario-v1", "asOf": now_iso,
            "scenarioType": "market_regime", "regimeLabel": regime_label,
            "dominantScenario": dom, "ownerReadableSummaryJa": summ,
            "complianceNote": COMPLIANCE}


def handoff_section(sets: List[Dict[str, Any]]) -> Dict[str, Any]:
    rows = []
    for s in sets[:5]:
        rows.append(f"[{s['dominantScenario']}] {s['symbol']} — {s['ownerReadableSummaryJa'][:70]}")
    return {"title": "Scenario Set",
            "top": rows,
            "opposingJa": "最強の反対シナリオ: 支配シナリオの根拠(需給/フロー)は公表遅延データであり、"
                          "実測フローの転換一つで入れ替わる。invalidation条件を必ず併読。",
            "disclaimerJa": COMPLIANCE}


def status_doc(sets: List[Dict[str, Any]], *, now_iso: str,
               sources: Dict[str, bool]) -> Dict[str, Any]:
    return {"schemaVersion": "scenario-status-v1", "asOf": now_iso,
            "featureEnabled": True, "lastRunAt": now_iso,
            "scenarioSetsGenerated": len(sets),
            "assetScenarioCount": sum(1 for s in sets if s.get("scenarioType") == "asset"),
            "eventWaitCount": sum(1 for s in sets if s.get("dominantScenario") == "wait_event"),
            "insufficientEvidenceCount": sum(1 for s in sets
                                             if s.get("evidenceQuality") == "insufficient"),
            "storageMode": "public_redacted",
            "publicLeakSafe": True,
            "sourceAvailability": sources,
            "noteJa": "公開側はウォッチリスト水準のみ(保有文脈は端末内で合成)。"
                      "確率は帯のみで%断定はしない。JPリアルタイム無効は意図的。",
            "complianceNote": COMPLIANCE}
