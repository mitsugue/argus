"""ARGUS V12.0.8 — Primary Stance Resolver (pure, deterministic).

同じ銘柄に Session Brief=リスク / Position Plan=リスク確認が先 / Action Priority=
対応不要 が同時に出る矛盾(オーナー報告)を根治する「銘柄ごとの単一の構え」解決器。
全カードはこの出力を表示し、下位セクションは詳細を説明できるが矛盾してはならない。

HARD RULES(テストで固定):
  - 保有 × P0/P1リスク → 絶対に「対応不要」にしない(リスク確認が先)
  - PlanがリスクレビューならAPの「対応不要」を上書き
  - イベント待ちは買い増し系ラベルをブロック
  - improving_but_heavy / squeeze系 は強気・追いかけ化しない
  - 部分データは確度を0.55で上限し、強気は判定保留へ落とす

売買指示ではない(構えの分類)。TS側 web/src/domain/primaryStance.ts と完全同期。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

SCHEMA_VERSION = "primary-stance-v1"

STANCES = ("risk_review", "trim_consideration", "wait_event", "avoid_chase",
           "add_only_on_pullback", "small_add_allowed", "deferred_today",
           "hold", "no_action", "unknown")

STANCE_JA = {
    "risk_review": "リスク確認が先",
    "trim_consideration": "一部利確を検討する局面",
    "wait_event": "イベント待ち",
    "avoid_chase": "追いかけ買い注意",
    "add_only_on_pullback": "買うなら押し目限定",
    "small_add_allowed": "小さく買い増し可",
    # v12.0.8追補: 総合コマンドが買い増し禁止の日は、買い系を主表示にしない
    "deferred_today": "候補だが今日は保留",
    "hold": "保有継続",
    "no_action": "対応不要",
    "unknown": "判定保留",
}

PARTIAL_CONF_CAP = 0.55

_RISKY_PLAN = ("risk_review",)
_TRIM_PLAN = ("trim_consideration",)
_EVENT_PLAN = ("wait",)
_ADD_LABELS = ("SMALL_ADD_ALLOWED",)
_PULLBACK_LABELS = ("ADD_ONLY_ON_PULLBACK",)
_HEAVY_SD = ("improving_but_heavy", "credit_overhang", "heavy")
_SQUEEZE_SD = ("squeeze_prone", "squeeze_fade")
_BAD_FLOW = ("panic_selling", "distribution")


def resolve(i: Dict[str, Any]) -> Dict[str, Any]:
    """inputs: isHeld, apRank('P0'..'Ignore'), apLabel(ActionLabel), planStance,
    scenarioDominant, sdCondition, sdLevel, flowClass, eventWait(bool),
    riskLevel('low'..'critical'), dataPartial(bool), baseConfidence(0..1)。
    欠落はunknown扱い(好条件に倒さない)。"""
    held = bool(i.get("isHeld"))
    ap_rank = str(i.get("apRank") or "Unknown")
    ap_label = str(i.get("apLabel") or "UNKNOWN")
    plan = str(i.get("planStance") or "unknown")
    dom = str(i.get("scenarioDominant") or "unknown")
    sd_cond = str(i.get("sdCondition") or "unknown")
    sd_level = str(i.get("sdLevel") or "unknown")
    flow = str(i.get("flowClass") or "unknown")
    risk = str(i.get("riskLevel") or "unknown")
    partial = bool(i.get("dataPartial"))
    global_add_prohibited = bool(i.get("globalAddProhibited"))
    event_wait = bool(i.get("eventWait")) or plan in _EVENT_PLAN \
        or ap_label == "WAIT_EVENT" or dom == "wait_event"
    conf = float(i.get("baseConfidence") or 0.6)
    reasons: List[str] = []

    risky = held and (
        ap_rank in ("P0", "P1")
        or plan in _RISKY_PLAN
        or dom == "bearish"
        or risk in ("high", "critical")
        or flow in _BAD_FLOW
    )

    stance: str
    if risky:
        # 保有×リスクは最優先 — 「対応不要」への降格は構造的に不可能
        if plan in _TRIM_PLAN:
            stance = "trim_consideration"
            reasons.append("計画が一部利確検討(保有×リスク側)")
        else:
            stance = "risk_review"
            if ap_rank in ("P0", "P1"):
                reasons.append(f"優先度{ap_rank}(保有×複合シグナル)")
            if plan in _RISKY_PLAN:
                reasons.append("計画がリスクレビュー")
            if dom == "bearish":
                reasons.append("シナリオ優勢が弱気")
            if risk in ("high", "critical"):
                reasons.append(f"保有リスク{risk}")
            if flow in _BAD_FLOW:
                reasons.append("フローが売り圧推定")
    elif held and plan in _TRIM_PLAN:
        stance = "trim_consideration"
        reasons.append("計画が一部利確検討")
    elif event_wait:
        stance = "wait_event"
        reasons.append("重要イベント接近 — 買い増し系は通過後に再評価")
    elif sd_cond in _SQUEEZE_SD or ap_label == "AVOID_CHASE" or plan == "avoid_chase":
        # 踏み上げ/急伸は絶対に追いかけ化しない
        stance = "avoid_chase"
        reasons.append("踏み上げ/急伸圏 — 追いかけは構造的に不可")
    elif sd_cond in _HEAVY_SD or sd_level in ("heavy", "very_heavy"):
        stance = "add_only_on_pullback"
        reasons.append("需給が重い(改善中でも上値吸収まで強気化しない)")
    elif plan == "add_only_on_pullback" or ap_label in _PULLBACK_LABELS:
        stance = "add_only_on_pullback"
        reasons.append("計画/優先度が押し目限定")
    elif ap_label in _ADD_LABELS and plan in ("small_add_allowed", "monitor", "unknown", "no_action"):
        stance = "small_add_allowed"
        reasons.append("ブロック要因なし(小分け前提)")
    elif held:
        stance = "hold"
        reasons.append("保有継続(明確な悪化シグナルなし)")
    elif ap_label in ("NO_ACTION", "IGNORE_TODAY") and plan in ("no_action", "unknown"):
        stance = "no_action"
        reasons.append("非保有×シグナルなし")
    elif ap_label == "UNKNOWN" and plan == "unknown" and dom == "unknown":
        stance = "unknown"
        reasons.append("判定材料不足")
    else:
        stance = "hold" if held else "no_action"

    cap_notes: List[str] = []
    if partial:
        conf = min(conf, PARTIAL_CONF_CAP)
        cap_notes.append("部分データのため確度に上限(0.55)")
        # 部分データ下では強気スタンスを出さない(判定保留へ)
        if stance == "small_add_allowed":
            stance = "unknown"
            cap_notes.append("部分データ下の買い増し可は判定保留へ降格")
    # イベント待ち中は買い系が残っていれば強制変換(二重の安全)
    if event_wait and stance in ("small_add_allowed", "add_only_on_pullback") :
        stance = "wait_event"
        cap_notes.append("イベント通過まで買い増し系は保留")
    # v12.0.8追補: 総合コマンドが買い増し禁止の日は、買い系を主表示にしない
    # (「小さく買い増し可」がヒーローの「買い増し: 禁止」と並ぶ矛盾の根治)
    if global_add_prohibited and stance in ("small_add_allowed", "add_only_on_pullback"):
        cap_notes.append(f"通常なら{STANCE_JA[stance]}。ただし今日は総合コマンドが買い増し禁止のため保留")
        stance = "deferred_today"
    # v12.0.8追補: P0/P1は「対応不要」を構造的に禁止(スクショの P1 対応不要 矛盾)
    if ap_rank in ("P0", "P1") and stance in ("no_action",):
        stance = "risk_review" if held else "unknown"
        cap_notes.append(f"優先度{ap_rank}のため対応不要にはしない")

    return {
        "schemaVersion": SCHEMA_VERSION,
        "primaryStance": stance,
        "stanceJa": STANCE_JA[stance],
        "confidence": round(min(max(conf, 0.0), 1.0), 2),
        "reasonsJa": reasons[:4],
        "capNotesJa": cap_notes,
        "complianceNote": "構えの分類であり売買指示ではない。",
    }
