"""ARGUS V11.4.0 — Learning Memory (pure, deterministic, stdlib-only).

ARGUS Pro's "growth" is NOT fine-tuning and NOT auto-trading. It is a small,
auditable memory layer that aggregates ARGUS's OWN public-safe history (official
events, macro pre/post, mover-cause outcomes, calibration, decision-value,
visibility downgrades) into cohort lessons that flow back into the next
judgment's Evidence Pack as CAUTION/CONTEXT — never as a fresh fact and never as
a BUY/SELL trigger.

Non-negotiable discipline (baked in, not left to callers):
  * pending / unscored records are NEVER counted as hit/miss/value;
  * n < 10 is burn_in and can never produce a strong signal or a strong cap;
  * current official evidence + fresh market confirmation beat any historical
    pattern — Learning Memory can only cap confidence or add caution;
  * no lesson is fabricated where n is too small (burn_in ⇒ signal=insufficient);
  * model weights are never claimed to change.

The scanner turns public-safe ledger snapshots into a flat list of Observations
and a context dict; this module does the aggregation. It never fetches, never
calls an LLM, and never sees private holdings / P&L / cost basis.
"""
from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Optional

SCHEMA_VERSION = "learning-memory-v1"
COMPACT_SCHEMA_VERSION = "learning-memory-compact-v1"

# Sample-size ladder (spec §1). Stage gates how strongly a lesson may be used.
BURN_IN_MAX = 10        # n < 10        → burn_in       (never strong)
EARLY_MAX = 30          # 10 <= n < 30  → early_signal
USABLE_MAX = 100        # 30 <= n < 100 → usable
#                         n >= 100       → mature

COHORT_TYPES = ["eventType", "sourceTier", "sourceFamily", "market", "symbol",
                "causeCategory", "macroEventCode", "visibilityReason", "policyId"]

_STAGE_ORDER = {"none": 0, "burn_in": 1, "early_signal": 2, "usable": 3, "mature": 4}

_COHORT_LABEL_JA = {
    "eventType": "イベント種別", "sourceTier": "情報源ティア", "sourceFamily": "情報源",
    "market": "市場", "symbol": "銘柄", "causeCategory": "原因カテゴリ",
    "macroEventCode": "マクロイベント", "visibilityReason": "可視性理由",
    "policyId": "ポリシー",
}


def stage_for(n: int) -> str:
    if n <= 0:
        return "none"
    if n < BURN_IN_MAX:
        return "burn_in"
    if n < EARLY_MAX:
        return "early_signal"
    if n < USABLE_MAX:
        return "usable"
    return "mature"


def _outcome_value(outcome: Any) -> Optional[float]:
    """hit=1.0, partial=0.5, miss=0.0; anything else (pending/None/unknown) = None."""
    o = str(outcome or "").lower()
    return {"hit": 1.0, "partial": 0.5, "miss": 0.0}.get(o)


def _lesson_id(cohort_type: str, cohort_key: str) -> str:
    h = hashlib.md5(f"{cohort_type}|{cohort_key}".encode("utf-8")).hexdigest()[:10]
    return f"lm-{cohort_type}-{h}"


def _confidence(n: int, hit_rate: float) -> float:
    """Small-sample-safe confidence. burn_in → 0.0 (can never create a strong cap).
    Scales with BOTH separation from 0.5 and sample size."""
    if n < BURN_IN_MAX:
        return 0.0
    separation = min(1.0, abs(hit_rate - 0.5) * 2.0)     # 0 (coin flip) .. 1 (decisive)
    size_factor = min(1.0, n / 100.0)                    # full weight only at mature
    return round(min(0.9, separation * size_factor), 2)


def _signal(n: int, hit_rate: float) -> str:
    if n < BURN_IN_MAX:
        return "insufficient"
    if hit_rate >= 0.6:
        return "positive"
    if hit_rate <= 0.4:
        return "negative"
    return "mixed"


def _lesson_text(cohort_type: str, cohort_key: str, signal: str, n: int,
                 hit_rate: float) -> Dict[str, str]:
    label = _COHORT_LABEL_JA.get(cohort_type, cohort_type)
    pct = int(round(hit_rate * 100))
    if signal == "insufficient":
        return {
            "lessonJa": f"{label}「{cohort_key}」は採点済みサンプルが{n}件で不足(burn-in)。傾向は未確定。",
            "howToUseJa": "参考程度に留め、判断を動かさない。",
            "doNotOveruseJa": "サンプル不足のため、この履歴で確信度を上げ下げしない。",
        }
    if signal == "positive":
        return {
            "lessonJa": f"{label}「{cohort_key}」は過去{n}件で整合率{pct}%と良好。ARGUSの読みが概ね当たっている領域。",
            "howToUseJa": "同種の状況では通常どおり評価してよいが、あくまで文脈情報。",
            "doNotOveruseJa": "過去の好成績を根拠に新規のBUY/ADDを作らない。現在の公式証拠が優先。",
        }
    if signal == "negative":
        return {
            "lessonJa": f"{label}「{cohort_key}」は過去{n}件で整合率{pct}%と低い。この領域のARGUSの読みは外れやすい。",
            "howToUseJa": "この領域が主要根拠のときは確信度を下げ、裏取りを増やす。",
            "doNotOveruseJa": "過去の不振を理由に現在の明確な公式証拠を無視しない。",
        }
    return {  # mixed
        "lessonJa": f"{label}「{cohort_key}」は過去{n}件で整合率{pct}%と一定せず(まちまち)。",
        "howToUseJa": "確定材料として扱わず、他の証拠と合わせて判断する。",
        "doNotOveruseJa": "まちまちな履歴を都合よく片側だけ引用しない。",
    }


def _aggregate(observations: List[Dict[str, Any]], now_iso: str) -> List[Dict[str, Any]]:
    """Group SCORED observations by (cohortType, cohortKey). Pending excluded."""
    buckets: Dict[tuple, Dict[str, float]] = {}
    for obs in observations or []:
        if not isinstance(obs, dict):
            continue
        ct, ck = obs.get("cohortType"), obs.get("cohortKey")
        if ct not in COHORT_TYPES or not ck:
            continue
        if obs.get("pending"):
            continue                                     # never count pending as a result
        val = _outcome_value(obs.get("outcome"))
        if val is None:
            continue                                     # unresolved / unknown → excluded
        b = buckets.setdefault((ct, str(ck)), {"n": 0, "sum": 0.0})
        b["n"] += 1
        b["sum"] += val

    lessons: List[Dict[str, Any]] = []
    for (ct, ck), b in buckets.items():
        n = int(b["n"])
        hit_rate = (b["sum"] / n) if n else 0.0
        stage = stage_for(n)
        sig = _signal(n, hit_rate)
        conf = _confidence(n, hit_rate)
        txt = _lesson_text(ct, ck, sig, n, hit_rate)
        lessons.append({
            "lessonId": _lesson_id(ct, ck),
            "cohortKey": ck,
            "cohortType": ct,
            "sampleSize": n,
            "hitRate": round(hit_rate, 3),
            "stage": stage,
            "signal": sig,
            "confidence": conf,
            "lessonJa": txt["lessonJa"],
            "howToUseJa": txt["howToUseJa"],
            "doNotOveruseJa": txt["doNotOveruseJa"],
            "lastUpdatedAt": now_iso,
        })
    lessons.sort(key=lambda L: (L["cohortType"], L["cohortKey"]))
    return lessons[:120]


def _caps_and_hints(lessons: List[Dict[str, Any]], context: Dict[str, Any]) -> Dict[str, Any]:
    caps: List[Dict[str, Any]] = []
    prompt_hints: List[str] = []
    vis_hints: List[str] = []
    src_hints: List[str] = []
    dv_hints: List[str] = []
    for L in lessons:
        strong_enough = L["stage"] in ("usable", "mature") and L["confidence"] >= 0.3
        # a confidence CAP is only ever created by a NEGATIVE or MIXED usable+ lesson
        if strong_enough and L["signal"] in ("negative", "mixed"):
            cap = {"negative": 0.6, "mixed": 0.65}[L["signal"]]
            if L["stage"] == "mature" and L["signal"] == "negative":
                cap = 0.55
            caps.append({
                "cohortType": L["cohortType"], "cohortKey": L["cohortKey"],
                "cap": cap, "stage": L["stage"], "signal": L["signal"],
                "reasonJa": L["lessonJa"],
            })
        # prompt hints: the clearest usable+ lessons (positive or negative)
        if strong_enough and L["signal"] in ("positive", "negative"):
            prompt_hints.append(L["lessonJa"])
        if L["cohortType"] == "visibilityReason" and L["stage"] != "burn_in":
            vis_hints.append(L["lessonJa"])
        if L["cohortType"] in ("sourceFamily", "sourceTier") and L["stage"] != "burn_in":
            src_hints.append(f"{L['cohortKey']}: {L['signal']}(n={L['sampleSize']})")

    dv = context.get("decisionValue") or {}
    if dv.get("sampleStage") in ("burn_in", "none", None):
        dv_hints.append("Decision Valueはサンプル不足段階 — 期待値の主張はしない。")
    elif dv.get("sampleStage"):
        dv_hints.append(f"Decision Valueは{dv.get('sampleStage')}段階(記録{dv.get('totalRecords', 0)}件)。")

    caps.sort(key=lambda c: (c["cohortType"], c["cohortKey"]))
    return {
        "confidenceCaps": caps[:20],
        "promptHints": sorted(set(prompt_hints))[:8],
        "visibilityHints": sorted(set(vis_hints))[:6],
        "sourceReliabilityHints": sorted(set(src_hints))[:8],
        "decisionValueHints": dv_hints[:4],
    }


def build_memory(observations: List[Dict[str, Any]], *, context: Optional[Dict[str, Any]] = None,
                 now_iso: str) -> Dict[str, Any]:
    """Aggregate public-safe observations + context into the auditable memory doc.
    Pure + deterministic: same inputs → byte-identical output."""
    context = context or {}
    lessons = _aggregate(observations, now_iso)
    total_scored = sum(L["sampleSize"] for L in lessons)
    sample_stage = stage_for(total_scored)

    cohorts = {ct: sorted({L["cohortKey"] for L in lessons if L["cohortType"] == ct})
               for ct in COHORT_TYPES}
    usable = [L for L in lessons if L["stage"] in ("usable", "mature")]
    caps_hints = _caps_and_hints(lessons, context)

    # per-source scored sample counts (for the status endpoint)
    src_counts = context.get("sampleCounts") or {}

    limitations = [
        "Learning MemoryはARGUS自身の履歴の集計であり、モデルの重みは更新していません。",
        "参考情報として次回判断に戻すだけで、BUY/SELLを単独で作りません。",
        "現在の公式証拠・市場確認は履歴パターンより常に優先します。",
    ]
    if sample_stage in ("none", "burn_in"):
        limitations.insert(0, "サンプルが少ないため、傾向は未確定(参考情報)。判断を強制しません。")

    if sample_stage == "none":
        summary = "採点済みの履歴がまだありません(Learning Memoryは空・none段階)。"
    else:
        pos = sum(1 for L in usable if L["signal"] == "positive")
        neg = sum(1 for L in usable if L["signal"] == "negative")
        summary = (f"採点済み{total_scored}件から{len(lessons)}コホートを集計({sample_stage})。"
                   f"usable以上の教訓{len(usable)}件(良好{pos}/不振{neg})。"
                   "確信度の上限・注意喚起として次回判断に反映します。")

    return {
        "schemaVersion": SCHEMA_VERSION,
        "asOf": now_iso,
        "sampleStage": sample_stage,
        "summaryJa": summary,
        "cohorts": cohorts,
        "lessons": lessons,
        "capsAndHints": caps_hints,
        "counts": {
            "lessons": len(lessons),
            "usableLessons": len(usable),
            "burnInLessons": sum(1 for L in lessons if L["stage"] == "burn_in"),
            "totalScoredSamples": total_scored,
            "officialEventSamples": int(src_counts.get("officialEvents", 0)),
            "macroEventSamples": int(src_counts.get("macroEvents", 0)),
            "moverCauseSamples": int(src_counts.get("moverCauses", 0)),
            "decisionValueSamples": int(src_counts.get("decisionValue", 0)),
            "calibrationSamples": int(src_counts.get("calibration", 0)),
        },
        "limitationsJa": limitations,
    }


# ── consumer projections ─────────────────────────────────────────────────────
def _relevant(lesson: Dict[str, Any], *, symbol: Optional[str], market: Optional[str],
              cause_categories, macro_codes, source_families) -> bool:
    ct, ck = lesson["cohortType"], str(lesson["cohortKey"])
    if ct == "symbol" and symbol and ck.upper() == str(symbol).upper():
        return True
    if ct == "market" and market and ck.upper() == str(market).upper():
        return True
    if ct == "causeCategory" and ck in (cause_categories or set()):
        return True
    if ct == "macroEventCode" and ck in (macro_codes or set()):
        return True
    if ct in ("sourceFamily", "sourceTier") and ck in (source_families or set()):
        return True
    if ct == "visibilityReason":
        return True
    return False


def compact_for_evidence(memory: Dict[str, Any], *, symbol: Optional[str] = None,
                         market: Optional[str] = None, cause_categories=None,
                         macro_codes=None, source_families=None,
                         max_lessons: int = 4) -> Dict[str, Any]:
    """Compact, symbol/context-relevant slice for the Evidence Pack. Caution-only:
    never grounds a judgment, never confirms a cause, never forces a decision."""
    mem = memory or {}
    stage = mem.get("sampleStage") or "none"
    cause_categories = set(cause_categories or [])
    macro_codes = set(macro_codes or [])
    source_families = set(source_families or [])
    rel = [L for L in (mem.get("lessons") or [])
           if _relevant(L, symbol=symbol, market=market, cause_categories=cause_categories,
                        macro_codes=macro_codes, source_families=source_families)]
    # prefer the strongest (usable/mature, higher confidence) — burn_in only as filler
    rel.sort(key=lambda L: (-_STAGE_ORDER.get(L["stage"], 0), -L["confidence"],
                            L["cohortType"], L["cohortKey"]))
    top = [{"lessonId": L["lessonId"], "cohortType": L["cohortType"], "cohortKey": L["cohortKey"],
            "stage": L["stage"], "signal": L["signal"], "confidence": L["confidence"],
            "lessonJa": L["lessonJa"]} for L in rel[:max_lessons]]
    rel_keys = {(L["cohortType"], str(L["cohortKey"])) for L in rel}
    caps = [c for c in ((mem.get("capsAndHints") or {}).get("confidenceCaps") or [])
            if (c["cohortType"], str(c["cohortKey"])) in rel_keys]

    limitations = ["Learning Memoryは参考情報 — 現在の公式証拠・市場確認を上書きしません。",
                   "モデルの重みは更新していません(判断の教科書としての集計のみ)。"]
    if stage in ("none", "burn_in"):
        limitations.insert(0, "サンプル不足のため参考情報。判断を強制しません。")

    return {
        "schemaVersion": COMPACT_SCHEMA_VERSION,
        "sampleStage": stage,
        "lessons": top,
        "confidenceCaps": caps[:5],
        "promptHints": [L["lessonJa"] for L in top
                        if L["stage"] in ("usable", "mature") and L["signal"] in ("positive", "negative")][:4],
        "cautionOnly": True,                 # can NEVER ground/confirm/force a decision
        "limitationsJa": limitations,
    }


def compact_for_ai(compact: Dict[str, Any], max_chars: int = 700) -> str:
    """One-block prompt injection of the compact memory (pure). Frames memory as
    caution/context, explicitly subordinate to current official evidence."""
    c = compact or {}
    stage = c.get("sampleStage") or "none"
    L: List[str] = [f"■ Learning Memory[{stage}] (参考・現在の公式証拠が優先/売買指示ではない)"]
    if stage in ("none", "burn_in"):
        L.append("  サンプル不足 — 傾向は未確定。確信度を過大にしない。")
    for lesson in (c.get("lessons") or [])[:4]:
        L.append(f"  ・{lesson.get('lessonJa')}")
    for cap in (c.get("confidenceCaps") or [])[:3]:
        L.append(f"  ⚠ 確信度上限{cap.get('cap')}: {cap.get('reasonJa')}")
    return "\n".join(L)[:max_chars]


def applies_as_caution_only() -> bool:
    """Invariant marker used by consumers/tests: Learning Memory is caution-only.
    It can cap confidence or add caution; it can never create BUY/SELL or confirm
    a cause, and current official evidence always beats a historical lesson."""
    return True
