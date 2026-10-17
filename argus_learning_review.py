"""ARGUS V11.15.0 — Learning Dashboard / Decision Review (pure, deterministic).

蓄積された判断記録(Decision Quality)を「学び」として読める形にする。
これはバックテスターでも成績自慢でもない — 学習と点検のダッシュボード。

HARD RULES (sample discipline is the product):
  - n < 5  → 「履歴不足」。強い結論は計算しない。
  - n 5-19 → 初期傾向のみ(confidence low)。
  - n 20-49→ 中程度(confidence medium)。
  - n >= 50→ 強め(それでも慎重)(confidence high)。
  - 勝率は n>=20 まで前面に出さない。
  - すべての出力に「まだ履歴が少ないため、成績としては扱わないでください。」系の
    caveat を必ず添える。
  - improving_but_heavy は絶対に A/good 系に合流させず独立追跡する。
  - P0/P1 は「価格が動かなかった=誤り」と判定しない(注意配分の妥当性は別)。
  - 歴史的証拠は変更しない — 既存レコードからの集計のみ。
  - Private data stays device-local; the server computes nothing over records
    (it never has them). Public status is redacted feature flags only.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

SCHEMA_VERSION = "learning-review-v1"

METRIC_TYPES = ("decision_context", "supply_demand_rank", "supply_demand_condition",
                "flow_class", "action_priority", "notification_type", "session_mode",
                "institutional_stance", "owner_action", "symbol", "theme", "market")
CONFIDENCES = ("low", "medium", "high", "insufficient")
REVIEW_STATUSES = ("too_early", "promising", "noisy", "caution", "needs_review",
                   "inconclusive")
INSIGHT_TYPES = ("useful_label", "noisy_label", "over_conservative", "too_aggressive",
                 "risk_warning_worked", "missed_opportunity", "data_gap",
                 "owner_behavior", "insufficient_history")

MIN_SAMPLE = 5
CAVEAT_JA = "まだ履歴が少ないため、成績としては扱わないでください。"
CAVEAT_GENERAL_JA = "これは学習用の傾向であり、将来を保証する成績ではありません。"


def _avg(xs: List[float]) -> Optional[float]:
    xs = [x for x in xs if isinstance(x, (int, float))]
    return round(sum(xs) / len(xs), 2) if xs else None


def _median(xs: List[float]) -> Optional[float]:
    xs = sorted(x for x in xs if isinstance(x, (int, float)))
    if not xs:
        return None
    n = len(xs)
    return round(xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2, 2)


def confidence_for(n: int) -> str:
    if n < MIN_SAMPLE:
        return "insufficient"
    if n < 20:
        return "low"
    if n < 50:
        return "medium"
    return "high"


def compute_metric(metric_type: str, label: str,
                   records: List[Dict[str, Any]], now_iso: str) -> Dict[str, Any]:
    """records = DecisionQualityRecord-shaped dicts (with optional 'outcome').
    Aggregates ONLY — never mutates evidence, never fabricates returns."""
    outs = [r.get("outcome") or {} for r in records]
    judged = [o for o in outs if o.get("outcomeInterpretation") in
              ("supported", "contradicted", "mixed", "inconclusive")]
    n = len(records)
    conf = confidence_for(n)
    r5s = [o.get("outcomeReturn5d") for o in outs if o.get("outcomeReturn5d") is not None]
    win5 = (round(sum(1 for x in r5s if x > 0) / len(r5s), 2)
            if len(r5s) >= 20 else None)          # 勝率はn>=20まで出さない
    m = {
        "schemaVersion": SCHEMA_VERSION,
        "id": f"lm-{metric_type}-{label}",
        "asOf": now_iso,
        "metricType": metric_type, "label": label,
        "sampleCount": n,
        "enoughSamples": n >= MIN_SAMPLE,
        "minSampleThreshold": MIN_SAMPLE,
        "supportedCount": sum(1 for o in judged if o.get("outcomeInterpretation") == "supported"),
        "contradictedCount": sum(1 for o in judged if o.get("outcomeInterpretation") == "contradicted"),
        "mixedCount": sum(1 for o in judged if o.get("outcomeInterpretation") == "mixed"),
        "inconclusiveCount": sum(1 for o in judged if o.get("outcomeInterpretation") == "inconclusive"),
        "avgReturn1d": _avg([o.get("outcomeReturn1d") for o in outs]),
        "avgReturn3d": _avg([o.get("outcomeReturn3d") for o in outs]),
        "avgReturn5d": _avg([o.get("outcomeReturn5d") for o in outs]),
        "avgReturn20d": _avg([o.get("outcomeReturn20d") for o in outs]),
        "medianReturn5d": _median([o.get("outcomeReturn5d") for o in outs]),
        "avgMaxDrawdown5d": _avg([o.get("maxDrawdown5d") for o in outs]),
        "avgMaxRunup5d": _avg([o.get("maxRunup5d") for o in outs]),
        "winRate5d": win5,
        "confidence": conf,
        "privacyLevel": "private_local",
    }
    m["interpretationJa"], m["caveatJa"] = interpret_metric(m)
    return m


def interpret_metric(m: Dict[str, Any]) -> Tuple[str, str]:
    """Cautious Japanese — never proof-speak; insufficient history dominates."""
    n = m["sampleCount"]
    label = m["label"]
    mtype = m["metricType"]
    if n < MIN_SAMPLE:
        return (f"「{label}」はまだ履歴不足です(n={n})。傾向の判定は保留します。",
                CAVEAT_JA)
    sup, con = m["supportedCount"], m["contradictedCount"]
    judged = sup + con
    r5, dd5, ru5 = m["avgReturn5d"], m["avgMaxDrawdown5d"], m["avgMaxRunup5d"]
    early = "(初期傾向・" + f"n={n})" if n < 20 else f"(n={n})"

    if mtype == "decision_context" and label == "avoid_chase":
        if judged >= 3 and sup > con and (dd5 is not None and dd5 <= -2):
            txt = f"追いかけ注意は今のところ有効に見えます。急騰後に一度押すケースが多いです{early}。"
        elif judged >= 3 and con > sup:
            txt = f"追いかけ注意が保守的すぎる可能性があります。ただし履歴数が十分か確認が必要です{early}。"
        else:
            txt = f"追いかけ注意の有効性はまだ判定中です{early}。"
    elif mtype == "decision_context" and label == "add_only_on_pullback":
        if judged >= 3 and sup > con:
            txt = f"押し目限定は機能しています(実際に押し目が発生)。{early}"
        elif judged >= 3 and con > sup:
            txt = f"押し目待ちで機会を逃している可能性があります{early}。"
        else:
            txt = f"押し目限定の有効性はまだ判定中です{early}。"
    elif mtype == "supply_demand_rank" and label in ("S", "A", "B"):
        if r5 is not None and r5 >= 1.5 and sup >= con:
            txt = f"需給{label}は継続上昇の補助材料として機能している可能性があります{early}。"
        elif r5 is not None and r5 < 0:
            txt = f"需給{label}だけでは上昇継続を説明できない可能性があります{early}。"
        else:
            txt = f"需給{label}のその後は中立圏です{early}。"
    elif mtype == "supply_demand_rank" and label in ("D", "E"):
        if r5 is not None and r5 <= -1:
            txt = f"需給{label}の後は弱含みやすい傾向が出ています{early}。"
        else:
            txt = f"需給{label}の警戒が過剰だった可能性を確認中です{early}。"
    elif mtype == "supply_demand_condition" and label == "improving_but_heavy":
        if ru5 is not None and r5 is not None and ru5 >= 2 and r5 < ru5 - 1.5:
            txt = f"「改善中だが買い残が重い」は上昇しても戻り売りで失速しやすい傾向です{early}。"
        elif r5 is not None and r5 >= 2:
            txt = f"「改善中だが買い残が重い」でも続伸したケースが出ています(重さを消化中の可能性){early}。"
        else:
            txt = f"「改善中だが買い残が重い」の帰結を追跡中です — 続伸か戻り売り失速かを確認{early}。"
    elif mtype == "supply_demand_condition" and label == "squeeze_prone" \
            or mtype == "flow_class" and label == "short_covering":
        if ru5 is not None and r5 is not None and ru5 >= 3 and r5 < ru5 - 2:
            txt = f"踏み上げ候補は短期上昇後に失速しやすい傾向が出ています{early}。"
        else:
            txt = f"踏み上げ候補は短期上昇後に失速しやすいかを確認中です{early}。"
    elif mtype == "action_priority" and label in ("P0", "P1"):
        # 価格が動かなくても「注意配分として誤り」とは判定しない
        moved = (dd5 is not None and dd5 <= -3) or (ru5 is not None and ru5 >= 3)
        txt = (f"{label}の後に有意な変動が観測されています — 注意配分は妥当だった可能性{early}。"
               if moved else
               f"{label}の後の変動は限定的でしたが、注意喚起自体の妥当性は別途評価します{early}。")
    elif mtype == "notification_type":
        txt = f"通知「{label}」の有用性は評価中です(閉じられた回数も今後の指標にします){early}。"
    elif mtype == "session_mode":
        txt = f"セッションモード「{label}」の妥当性を追跡中です{early}。"
    elif mtype == "owner_action":
        txt = f"あなたの行動「{label}」のその後を記録中です(自己確認用・評価はしません){early}。"
    else:
        txt = f"「{label}」の傾向を追跡中です{early}。"
    caveat = CAVEAT_JA if n < 20 else CAVEAT_GENERAL_JA
    return txt, caveat


def label_review(metric: Dict[str, Any],
                 examples: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    n = metric["sampleCount"]
    sup, con = metric["supportedCount"], metric["contradictedCount"]
    judged = sup + con
    if n < MIN_SAMPLE:
        status = "too_early"
    elif judged < 3:
        status = "inconclusive"
    elif sup >= 2 * max(con, 1):
        status = "promising"
    elif con >= 2 * max(sup, 1):
        status = "noisy" if metric["metricType"] != "decision_context" else "needs_review"
    else:
        status = "caution"
    exs = examples or []
    def _fmt(e):
        o = e.get("outcome") or {}
        r5 = o.get("outcomeReturn5d")
        return {"symbol": e.get("symbol"), "asOf": str(e.get("asOf", ""))[:10],
                "return5d": r5, "interpretation": o.get("outcomeInterpretation")}
    best = max(exs, key=lambda e: ((e.get("outcome") or {}).get("outcomeReturn5d") or -999),
               default=None)
    worst = min(exs, key=lambda e: ((e.get("outcome") or {}).get("outcomeReturn5d") or 999),
                default=None)
    return {
        "label": metric["label"], "labelType": metric["metricType"],
        "sampleCount": n, "status": status,
        "ownerReadableSummaryJa": metric["interpretationJa"],
        "strongestExample": _fmt(best) if best else None,
        "weakestExample": _fmt(worst) if worst else None,
        "recentExamples": [_fmt(e) for e in exs[:3]],
        "whatToCheckNextJa": ("履歴が5件を超えるまで判定を保留" if status == "too_early" else
                              "サンプルが増えた時に傾向が維持されるかを確認"),
        "caveatJa": metric["caveatJa"],
    }


def build_insights(metrics: List[Dict[str, Any]], now_iso: str,
                   cap: int = 6) -> List[Dict[str, Any]]:
    out = []
    def add(t, title, body, rec, conf):
        out.append({"schemaVersion": "decision-review-insight-v1",
                    "id": f"in-{t}-{len(out)}", "asOf": now_iso,
                    "insightType": t, "titleJa": title, "bodyJa": body,
                    "evidence": None, "recommendationJa": rec,
                    "confidence": conf, "privacyLevel": "private_local"})
    insufficient = [m for m in metrics if m["confidence"] == "insufficient"]
    if insufficient:
        add("insufficient_history", f"履歴不足のラベルが{len(insufficient)}件",
            "多くのラベルはまだ判定に必要な履歴が貯まっていません。",
            "毎日Todayを開いて記録を積み上げる(自動)。数週間で初期傾向が見え始めます。",
            "high")
    for m in metrics:
        if m["confidence"] == "insufficient":
            continue
        sup, con = m["supportedCount"], m["contradictedCount"]
        if sup + con >= 3 and sup > 2 * max(con, 1):
            add("useful_label", f"「{m['label']}」は有効に見えます",
                m["interpretationJa"], "この傾向がサンプル増でも維持されるか確認。", m["confidence"])
        elif sup + con >= 3 and con > 2 * max(sup, 1):
            t = "over_conservative" if m["label"] in ("avoid_chase", "add_only_on_pullback",
                                                      "wait") else "noisy_label"
            add(t, f"「{m['label']}」は見直し候補",
                m["interpretationJa"], "閾値/条件の見直しを検討(ただし履歴を増やしてから)。",
                m["confidence"])
    return out[:cap]


def summary_doc(metrics: List[Dict[str, Any]], now_iso: str) -> Dict[str, Any]:
    return {
        "schemaVersion": "learning-summary-v1", "asOf": now_iso,
        "metricsGenerated": len(metrics),
        "enoughSampleMetrics": sum(1 for m in metrics if m["enoughSamples"]),
        "insufficientSampleMetrics": sum(1 for m in metrics if not m["enoughSamples"]),
        "tooEarlyNoteJa": (CAVEAT_JA if any(not m["enoughSamples"] for m in metrics)
                           else CAVEAT_GENERAL_JA),
    }


def public_status(*, now_iso: str, sources: Dict[str, bool]) -> Dict[str, Any]:
    """PUBLIC — feature flags only. Records live device-local; the server
    computes and stores nothing over them."""
    return {
        "schemaVersion": "learning-review-status-v1", "asOf": now_iso,
        "featureEnabled": True,
        "minSampleThreshold": MIN_SAMPLE,
        "sampleDiscipline": {"insufficient": "<5", "low": "5-19",
                             "medium": "20-49", "high": ">=50"},
        "storageMode": "local_only+encrypted_vault",
        "serverStoresRecords": False,
        "publicLeakSafe": True,
        "sourceAvailability": sources,
        "noteJa": "学習レビューは端末内の判断記録から端末内で計算される。"
                  "サーバーは記録を保持しない。少ないサンプルを成績として扱わない。"
                  "JPリアルタイム無効は意図的で欠陥ではない。",
        "complianceNote": "学習用の傾向であり売買指示でも将来保証でもない。",
    }
