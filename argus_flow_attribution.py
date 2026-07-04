"""ARGUS V11.7.0 — Big Money / Flow Attribution Engine (pure, deterministic).

Answers the owner's recurring questions — 「これは大口の新規買いか、買い戻しか？」
「急騰を追っていいのか？」「出来高急増は仕掛けか、逃げか？」 — as an EVIDENCE layer,
never a trading signal.

NO FALSE PRECISION (hard rule):
- 「大口が買っている」とは絶対に言わない。direct flow evidence が無い限り、
  常に「〜の可能性」「推定」「未確定」の語彙を使う。
- Direct evidence (measured flow) is separated from inference (price/volume shape).
- Whenever confidence is below high, missingEvidence is shown explicitly.
- Missing sources (JP margin/short/日証金, realtime JP quotes) yield lower
  confidence + sourceLimitNote — never fabricated numbers.

The scanner supplies an evidence dict (cached-only); this module only scores.
Every record carries deterministic reasonCodes + timestamps so a future backtest
can compare flowClass@T against 1d/3d/5d/20d returns.
"""
from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Optional

SCHEMA_VERSION = "flow-attribution-v1"

FLOW_CLASSES = ("institutional_accumulation", "short_covering", "retail_chase",
                "profit_taking", "distribution", "panic_selling", "rotation_in",
                "rotation_out", "event_driven_buying", "event_driven_selling",
                "liquidity_noise", "mixed", "unknown")
ACTIONS = ("investigate", "wait_for_confirmation", "avoid_chase", "monitor",
           "caution", "no_action")

CLASS_JA = {
    "institutional_accumulation": "大口買い集めの可能性", "short_covering": "買い戻し(踏み上げ)の可能性",
    "retail_chase": "個人の追随買いの可能性", "profit_taking": "利益確定売りの可能性",
    "distribution": "大口の売り抜けの可能性", "panic_selling": "狼狽売りの可能性",
    "rotation_in": "テーマへの資金流入の可能性", "rotation_out": "テーマからの資金流出の可能性",
    "event_driven_buying": "イベント起点の買いの可能性", "event_driven_selling": "イベント起点の売りの可能性",
    "liquidity_noise": "薄商いのノイズの可能性", "mixed": "強弱シグナル混在", "unknown": "証拠不足(判定保留)",
}
ACTION_JA = {"investigate": "要調査", "wait_for_confirmation": "確認待ち",
             "avoid_chase": "追いかけ買い注意", "monitor": "監視継続",
             "caution": "警戒", "no_action": "対応不要"}
DIRECTNESS_JA = {"direct_evidence": "実測データあり", "inferred": "値動きからの推定",
                 "weak_context": "弱い状況証拠", "insufficient": "証拠不足"}

# evidence keys the scanner may supply (all optional — missing = honest gap)
EVIDENCE_KEYS = ("priceActionEvidence", "volumeEvidence", "shortInterestEvidence",
                 "marginEvidence", "institutionalSignalEvidence", "eventEvidence",
                 "marketRegimeEvidence", "newsEvidence")


def _fnum(v) -> Optional[float]:
    return float(v) if isinstance(v, (int, float)) else None


def classify(symbol: str, market: str, ev: Dict[str, Any], now_iso: str) -> Dict[str, Any]:
    """Evidence dict → FlowAttribution record. Deterministic; never fabricates.

    Expected evidence fields (all optional):
      changePct, volumeRatio, priorRunupPct, closeLocation(0..1), gapPct,
      flowBigNetRatio (measured moomoo capital distribution, -1..1),
      shortRatio / shortRatioAvg (JP daily short-sale ratio), marginShortHeavy,
      marginLongChange, instStance('bullish'|'bearish'|None), instDirect(bool),
      regimeLabel, regimeRiskOff(bool), eventToday(bool), eventDirection(+1/-1/0),
      themePeersSame / themePeersTotal, freshNewsCount, turnover, liquidityLow(bool),
      dataAgeMin, sources: {priceVolume/shortInterest/margin/flow/...: bool}
    """
    chg = _fnum(ev.get("changePct"))
    vr = _fnum(ev.get("volumeRatio"))
    runup = _fnum(ev.get("priorRunupPct"))
    close_loc = _fnum(ev.get("closeLocation"))
    gap = _fnum(ev.get("gapPct"))
    flow = _fnum(ev.get("flowBigNetRatio"))
    short_r = _fnum(ev.get("shortRatio"))
    short_avg = _fnum(ev.get("shortRatioAvg"))
    inst_stance = ev.get("instStance")
    reasons: List[str] = []
    evidence: Dict[str, Optional[str]] = {k: None for k in EVIDENCE_KEYS}
    missing: List[str] = []

    src = ev.get("sources") or {}
    has_flow = flow is not None
    has_short = short_r is not None or bool(src.get("shortInterest"))
    has_margin = ev.get("marginShortHeavy") is not None or bool(src.get("margin"))
    if not has_flow:
        missing.append("実測フロー(大口資金分布)")
    if not has_short:
        missing.append("空売り比率")
    if not has_margin:
        missing.append("信用残(日証金/週次信用)")
    if close_loc is None:
        missing.append("日中の終値位置(高値/安値比)")

    # evidence strings (only for what actually exists)
    if chg is not None:
        evidence["priceActionEvidence"] = f"変化率{chg:+.1f}%" + (
            f"・直近{runup:+.0f}%の助走" if runup is not None and abs(runup) >= 8 else "")
    if vr is not None:
        evidence["volumeEvidence"] = f"出来高比 {vr:.1f}倍"
    if has_short and short_r is not None:
        evidence["shortInterestEvidence"] = f"空売り比率 {short_r:.0%}" + (
            f"(平均{short_avg:.0%})" if short_avg is not None else "")
    if ev.get("marginShortHeavy") is not None:
        evidence["marginEvidence"] = ("売り長(ショート過多)" if ev.get("marginShortHeavy")
                                      else "売り長ではない")
    if inst_stance:
        evidence["institutionalSignalEvidence"] = f"機関シグナル: {inst_stance}" + (
            "(直接言及)" if ev.get("instDirect") else "(関連/背景)")
    if ev.get("eventToday"):
        evidence["eventEvidence"] = "本日イベントあり"
    if ev.get("regimeLabel"):
        evidence["marketRegimeEvidence"] = f"レジーム: {ev['regimeLabel']}"
    if ev.get("freshNewsCount"):
        evidence["newsEvidence"] = f"直近24hニュース{int(ev['freshNewsCount'])}件"

    # ── deterministic pattern scores (0..1 each; the max wins) ───────────────
    scores: Dict[str, float] = {}
    up = chg is not None and chg > 0
    down = chg is not None and chg < 0
    big_vol = vr is not None and vr >= 1.8
    some_vol = vr is not None and vr >= 1.3
    strong_close = close_loc is not None and close_loc >= 0.7
    weak_close = close_loc is not None and close_loc <= 0.3
    gap_fade = (gap is not None and gap > 1.5 and close_loc is not None and close_loc < 0.4)
    short_heavy = (bool(ev.get("marginShortHeavy"))
                   or (short_r is not None and short_avg is not None and short_r > short_avg * 1.15)
                   or (short_r is not None and short_r >= 0.45))

    if ev.get("liquidityLow") and (vr is None or vr < 1.2):
        scores["liquidity_noise"] = 0.5
        reasons.append("LOW_LIQUIDITY")

    # A. institutional accumulation candidate. Volume ratio OR measured flow
    # qualifies — US symbols have no cached avg-volume, but the bridge supplies
    # a MEASURED big-money net ratio, which is stronger evidence than volume.
    if up and (some_vol or (flow is not None and flow > 0.12)) and not gap_fade:
        s = 0.35
        if big_vol:
            s += 0.1
            reasons.append("VOL_SPIKE_UP")
        if strong_close:
            s += 0.15
            reasons.append("CLOSE_NEAR_HIGH")
        if flow is not None and flow > 0.12:
            s += 0.25
            reasons.append("MEASURED_BIG_INFLOW")
        if inst_stance == "bullish":
            s += 0.1
            reasons.append("INST_SUPPORT")
        if short_heavy:
            s -= 0.15           # short-cover explains it better
        if runup is not None and runup >= 12 and inst_stance != "bullish" \
                and not (flow is not None and flow > 0.12):
            s -= 0.2            # extended spike w/o institutional footprint = chase-like
        scores["institutional_accumulation"] = min(1.0, s)

    # B. short covering candidate
    if up and short_heavy:
        s = 0.45
        reasons.append("SHORT_HEAVY_BASE")
        if runup is not None and runup < -5:
            s += 0.15
            reasons.append("REBOUND_AFTER_WEAKNESS")
        if chg is not None and chg >= 5:
            s += 0.1
        if not has_short and not has_margin:
            s = min(s, 0.3)     # never confident without short/margin evidence
        scores["short_covering"] = min(1.0, s)
    elif up and runup is not None and runup < -8 and big_vol and not has_short:
        scores["short_covering"] = 0.3      # possible squeeze, evidence missing
        reasons.append("REBOUND_NO_SHORT_DATA")

    # C. retail chase
    if up and runup is not None and runup >= 12 and big_vol \
            and inst_stance != "bullish" and not (flow is not None and flow > 0.12):
        scores["retail_chase"] = 0.5 + (0.1 if chg is not None and chg >= 8 else 0.0)
        reasons.append("EXTENDED_SPIKE_NO_INST")

    # D. distribution / profit taking — volume+weak-close shape, or measured
    # big-money OUTFLOW while price holds/rises (selling into strength).
    if flow is not None and flow < -0.12 and (up or (chg is not None and abs(chg) < 2)):
        scores["distribution"] = max(scores.get("distribution", 0.0), 0.55)
        reasons.append("MEASURED_BIG_OUTFLOW")
    if big_vol and (weak_close or gap_fade) and (up or (chg is not None and abs(chg) < 2)):
        s = 0.45 + (0.15 if gap_fade else 0.0)
        if flow is not None and flow < -0.12:
            s += 0.2
            reasons.append("MEASURED_BIG_OUTFLOW")
        scores["distribution"] = min(1.0, s)
        reasons.append("VOL_UP_WEAK_CLOSE")
    if up and runup is not None and runup >= 15 and weak_close:
        scores["profit_taking"] = 0.45
        reasons.append("RUNUP_THEN_WEAK_CLOSE")

    # E. panic selling. A >=5% drop with volume data missing (vr is None) still
    # scores as a LOW-confidence candidate — a -7% mover must never read as
    # 「対応不要」 just because avg-volume isn't cached (US has no JQ bars).
    if down and chg is not None and chg <= -5 and (big_vol or vr is None):
        s = 0.45 if big_vol else 0.35
        if vr is None:
            reasons.append("PRICE_ONLY_DROP")
        if weak_close:
            s += 0.15
            reasons.append("CLOSE_NEAR_LOW")
        if ev.get("regimeRiskOff"):
            s += 0.1
            reasons.append("RISK_OFF_REGIME")
        scores["panic_selling"] = min(1.0, s)

    # F. rotation in/out — needs multi-asset theme evidence
    tp_same, tp_total = ev.get("themePeersSame"), ev.get("themePeersTotal")
    if isinstance(tp_same, int) and isinstance(tp_total, int) and tp_total >= 3 \
            and tp_same >= 2:
        if up:
            scores["rotation_in"] = 0.4 + (0.1 if inst_stance == "bullish" else 0.0)
            reasons.append("THEME_PEERS_UP")
        elif down:
            scores["rotation_out"] = 0.4
            reasons.append("THEME_PEERS_DOWN")

    # event-driven overlay
    if ev.get("eventToday") and chg is not None and abs(chg) >= 2:
        key = "event_driven_buying" if up else "event_driven_selling"
        scores[key] = max(scores.get(key, 0.0), 0.4)
        reasons.append("EVENT_TODAY")

    # ── pick winner ──────────────────────────────────────────────────────────
    if not scores or chg is None:
        flow_class, base_conf = "unknown", 0.15
        if chg is None:
            missing.append("価格/出来高データ")
    else:
        ranked = sorted(scores.items(), key=lambda kv: -kv[1])
        flow_class, base_conf = ranked[0]
        if len(ranked) >= 2 and ranked[0][1] - ranked[1][1] < 0.1 and ranked[0][1] >= 0.35:
            flow_class, base_conf = "mixed", ranked[0][1] - 0.05
            reasons.append("CONFLICTING_PATTERNS")

    # directness + confidence caps (missing evidence must bite)
    if flow is not None and abs(flow) >= 0.12 and flow_class in (
            "institutional_accumulation", "distribution"):
        directness = "direct_evidence"
    elif flow_class == "unknown":
        directness = "insufficient"
    elif len(missing) >= 3:
        directness = "weak_context"
    else:
        directness = "inferred"
    conf = base_conf
    if directness != "direct_evidence":
        conf = min(conf, 0.6)
    if len(missing) >= 3:
        conf = min(conf, 0.45)
    stale = _fnum(ev.get("dataAgeMin"))
    if stale is not None and stale > 120:
        conf = min(conf, 0.4)
        missing.append("データ鮮度(2時間超)")
    conf = round(max(0.1, conf), 2)

    direction = ("inflow" if flow_class in ("institutional_accumulation", "short_covering",
                                            "retail_chase", "rotation_in", "event_driven_buying")
                 else "outflow" if flow_class in ("profit_taking", "distribution",
                                                  "panic_selling", "rotation_out",
                                                  "event_driven_selling")
                 else "mixed" if flow_class == "mixed"
                 else "neutral" if flow_class == "liquidity_noise" else "unknown")

    action = {"institutional_accumulation": "investigate",
              "short_covering": "wait_for_confirmation",
              "retail_chase": "avoid_chase", "profit_taking": "monitor",
              "distribution": "caution", "panic_selling": "caution",
              "rotation_in": "monitor", "rotation_out": "monitor",
              "event_driven_buying": "wait_for_confirmation",
              "event_driven_selling": "wait_for_confirmation",
              "liquidity_noise": "no_action", "mixed": "wait_for_confirmation",
              "unknown": "no_action"}[flow_class]
    # a MATERIAL move that we cannot classify is a reason to dig, not to relax
    if flow_class == "unknown" and chg is not None and abs(chg) >= 2:
        action = "investigate"
        reasons.append("MATERIAL_MOVE_UNCLASSIFIED")

    why = _why_ja(flow_class, conf, directness, evidence, missing, reasons)
    check = _check_next_ja(flow_class, missing, market)
    ev_score = round(sum(1 for v in evidence.values() if v) / len(EVIDENCE_KEYS), 2)
    risk = round(min(1.0, (0.6 if flow_class in ("retail_chase", "distribution",
                                                 "panic_selling") else 0.3)
                     + (0.2 if len(missing) >= 3 else 0.0)), 2)

    return {
        "schemaVersion": SCHEMA_VERSION,
        "id": "fa-" + hashlib.md5(f"{market}:{symbol}:{now_iso[:13]}".encode()).hexdigest()[:10],
        "symbol": str(symbol).upper(), "market": str(market).upper(),
        "asOf": now_iso, "sourceUpdatedAt": ev.get("sourceUpdatedAt"),
        "price": _fnum(ev.get("price")), "changePct": chg,
        "volume": ev.get("volume"), "volumeRatio": vr,
        "turnover": _fnum(ev.get("turnover")),
        "vwapPosition": _fnum(ev.get("vwapPosition")),
        "intradayRangePct": _fnum(ev.get("intradayRangePct")),
        "gapPct": gap, "closeLocation": close_loc,
        "flowClass": flow_class, "flowClassJa": CLASS_JA[flow_class],
        "direction": direction,
        "confidence": conf, "evidenceScore": ev_score, "riskScore": risk,
        "directness": directness, "directnessJa": DIRECTNESS_JA[directness],
        "evidence": evidence,
        "missingEvidence": missing[:6],
        "reasonCodes": reasons[:8],
        "ownerReadableWhyJa": why,
        "checkNextJa": check,
        "actionImplication": action, "actionImplicationJa": ACTION_JA[action],
        "sourceLimitNote": ("実測フローなし — 値動き/出来高からの推定のみ"
                            if not has_flow else "moomoo資金分布は遅延/口座権限に依存"),
        "complianceNote": "推定であり売買指示ではない。大口の実在はdirect evidenceが無い限り断定しない。",
    }


def _why_ja(flow_class, conf, directness, evidence, missing, reasons=()):
    """NEVER claim evidence we don't hold: each template only names the pieces
    that are actually present (volume spike / weak close / measured flow)."""
    lvl = "高" if conf >= 0.65 else "中" if conf >= 0.45 else "低"
    have = "・".join(v for v in (evidence.get("priceActionEvidence"),
                                 evidence.get("volumeEvidence")) if v)
    miss = "・".join(missing[:2])
    has_vol = bool(evidence.get("volumeEvidence"))
    weak_close = "CLOSE_NEAR_LOW" in reasons or "VOL_UP_WEAK_CLOSE" in reasons
    panic_bits = "急落" + ("+出来高急増" if has_vol else "(出来高は未取得)") \
                 + ("+安値引け" if weak_close else "")
    dist_txt = ("価格が保たれる裏で実測フローが流出超 — 上値で売り抜けられている可能性"
                if "MEASURED_BIG_OUTFLOW" in reasons and not weak_close
                else "出来高増なのに終値が弱く、上値で売り抜けられている可能性")
    base = {
        "institutional_accumulation":
            f"{have}と終値位置は買い集め型。ただし大口の実買いとは断定できない",
        "short_covering": f"{have}。売り長/空売りの積み上がりからの買い戻し(踏み上げ)の型",
        "retail_chase": f"急伸後の{have}に機関の裏付けが薄く、個人の追随買いの型",
        "profit_taking": "上昇後に上値で売られる型(利益確定の推定)",
        "distribution": dist_txt,
        "panic_selling": f"{panic_bits}で、狼狽売りの型",
        "rotation_in": "同テーマの複数銘柄が同時に買われており、テーマへの資金流入の型",
        "rotation_out": "同テーマの複数銘柄が同時に売られており、資金流出の型",
        "event_driven_buying": "本日のイベントを起点とした買いの可能性",
        "event_driven_selling": "本日のイベントを起点とした売りの可能性",
        "liquidity_noise": "商いが薄く、値動きに大きな意味を持たせない",
        "mixed": "買い集めと売り抜けの両方の型が混在(判定を急がない)",
        "unknown": ("大きな動きだが判定に必要な証拠が不足(誰の売買かは未確定)"
                    if have else "判定に必要な証拠が不足"),
    }[flow_class]
    tail = f"。確度{lvl}" + (f"({miss}の確認前)" if miss and conf < 0.65 else "") + "。"
    if directness == "direct_evidence":
        tail = f"。実測フローが方向を支持(確度{lvl})。"
    return (base + tail)[:220]


def _check_next_ja(flow_class, missing, market):
    if flow_class in ("institutional_accumulation", "short_covering") and missing:
        base = "空売り比率・信用残" if market == "JP" else "ショート関連データ"
        return f"{base}と翌日の続き(出来高を伴う継続か失速か)を確認"
    if flow_class == "retail_chase":
        return "上値での売り(高値からの押し戻し)と出来高の質を確認 — 追いかけ買いは高値掴みリスク"
    if flow_class in ("distribution", "profit_taking"):
        return "戻り局面で再び売られるか(戻り売りの有無)を確認"
    if flow_class == "panic_selling":
        return "翌日の寄り付きと公式材料の有無を確認(狼狽の続きか反発か)"
    if flow_class == "unknown":
        return "価格・出来高データの取得と、翌営業日の値動きを待つ"
    return "翌日の継続性(出来高を伴うか)を確認"


def status_doc(records: List[Dict[str, Any]], *, now_iso: str,
               source_availability: Dict[str, bool]) -> Dict[str, Any]:
    return {
        "schemaVersion": "flow-attribution-status-v1", "asOf": now_iso,
        "lastRunAt": now_iso,
        "assetsScanned": len(records),
        "signalsGenerated": sum(1 for r in records if r["flowClass"] != "unknown"),
        "highConfidenceCount": sum(1 for r in records if r["confidence"] >= 0.65),
        "unknownCount": sum(1 for r in records if r["flowClass"] == "unknown"),
        "staleDataCount": sum(1 for r in records
                              if any("鮮度" in m for m in r["missingEvidence"])),
        "missingEvidenceSummary": _missing_summary(records),
        "sourceAvailability": source_availability,
        "noteJa": "JPのmoomooリアルタイムは意図的に無効(米国のみ)。JPは代替データで推定し、"
                  "欠けている証拠はmissingEvidenceとして正直に表示する。",
    }


def _missing_summary(records):
    counts: Dict[str, int] = {}
    for r in records:
        for m in r.get("missingEvidence") or []:
            counts[m] = counts.get(m, 0) + 1
    return sorted(counts.items(), key=lambda kv: -kv[1])[:6]


def handoff_section(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Pro Handoff block: candidates by class + strongest opposing interpretation."""
    def rows(cls):
        return [f"{r['symbol']}({r['market']}) conf={r['confidence']} — {r['ownerReadableWhyJa'][:80]}"
                for r in records if r["flowClass"] == cls][:4]
    return {
        "title": "Big Money / Flow Attribution",
        "likelyAccumulation": rows("institutional_accumulation"),
        "likelyShortCovering": rows("short_covering"),
        "distributionRisks": rows("distribution") + rows("profit_taking"),
        "avoidChase": rows("retail_chase"),
        "missingEvidence": _missing_summary(records),
        "opposingViewJa": "最強の反対解釈: 買い集めに見える動きは、空売りの買い戻し(一過性)や"
                          "指数・テーマ全体の資金移動でも説明できる。実測フロー・信用/空売りデータの"
                          "裏付けが無い限り新規大口買いと断定しない。",
        "disclaimerJa": "推定であり売買指示ではない。",
    }
