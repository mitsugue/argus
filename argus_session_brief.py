"""ARGUS V11.13.0 — Morning / Session Brief Engine (pure, deterministic).

Action Priority が「見る順番」なら、この層は「今日の作戦」を1枚の日本語ブリーフ
にする — 攻める日か、待つ日か、確認の日か。売買指示では絶対にない。

HARD RULES:
  - P0 があれば見出しに必ず載せる。無ければ「最優先なし」を明言する。
  - 重要イベント待ちがあれば ownerMode は attack にしない(wait/monitor)。
  - 保有リスクは監視銘柄の機会より必ず先に述べる。
  - シグナルが矛盾したら「判断保留/要確認」と言う(決め打ちしない)。
  - 休場中(weekend/holiday)はザラ場風の文を絶対に出さない — レビュー体裁。
  - ブリーフは既存レイヤーの要約であり、新しい事実を捏造しない。
"""
from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Optional

SCHEMA_VERSION = "session-brief-v1"

SESSION_TYPES = ("morning", "pre_market", "intraday", "close", "after_close",
                 "weekend", "unknown")
MARKET_STATUSES = ("jp_open", "us_open", "both_closed", "pre_market", "after_hours",
                   "weekend", "holiday", "unknown")
OWNER_MODES = ("attack", "wait", "protect", "monitor", "review", "no_action", "unknown")
MODE_JA = {"attack": "攻める日", "wait": "待つ日", "protect": "守る日",
           "monitor": "監視の日", "review": "反省/記録の日",
           "no_action": "対応不要の日", "unknown": "判定保留"}
COMPLIANCE = "今日の作戦メモであり売買指示ではない。"


def resolve_session(now_jst_hour: int, weekday: int,
                    jp_open: bool, us_open: bool) -> Dict[str, str]:
    """Deterministic session/market status from clock inputs (caller supplies
    real values — this module never reads the clock itself)."""
    if weekday >= 5:
        return {"sessionType": "weekend", "marketStatus": "weekend"}
    if jp_open or us_open:
        return {"sessionType": "intraday",
                "marketStatus": "jp_open" if jp_open else "us_open"}
    if 5 <= now_jst_hour < 9:
        return {"sessionType": "morning", "marketStatus": "pre_market"}
    if 15 <= now_jst_hour < 22:
        return {"sessionType": "after_close", "marketStatus": "after_hours"}
    if 22 <= now_jst_hour or now_jst_hour < 5:
        return {"sessionType": "pre_market", "marketStatus": "pre_market"}
    return {"sessionType": "close", "marketStatus": "both_closed"}


def build_brief(inputs: Dict[str, Any], now_iso: str) -> Dict[str, Any]:
    """inputs (all optional, from existing layers — nothing fabricated):
      sessionType, marketStatus, priorityItems[] (ActionPriorityItem-shaped),
      eventNames[], regimeLabel, regimeRiskOff, sdHighlights[] (compact dicts),
      flowHighlights[], instHighlights[], exposureNoteJa, dqNoteJa,
      missingDataJa[], conflictingSignals(bool), isPrivate(bool)
    """
    st = inputs.get("sessionType") or "unknown"
    ms = inputs.get("marketStatus") or "unknown"
    items = list(inputs.get("priorityItems") or [])
    events = [e for e in (inputs.get("eventNames") or []) if e]
    risk_off = bool(inputs.get("regimeRiskOff"))
    missing = list(inputs.get("missingDataJa") or [])
    conflicting = bool(inputs.get("conflictingSignals"))

    p0 = [i for i in items if i.get("priorityRank") == "P0"]
    p1 = [i for i in items if i.get("priorityRank") == "P1"]
    held_risks = [i for i in items
                  if i.get("category") in ("held_risk", "flow_watch", "supply_demand_watch")
                  and i.get("isHeld") is True]
    avoid = [i for i in items if i.get("category") == "avoid_chase"]
    adds = [i for i in items if i.get("category") in ("add_candidate", "add_only_on_pullback")]
    event_wait = [i for i in items if i.get("blockingReason") == "event_pending"]
    data_missing = [i for i in items if i.get("category") == "data_missing"]

    # ── ownerMode ladder (worst wins; attack requires a genuinely clear day) ──
    if st == "weekend":
        mode = "review"
    elif p0:
        mode = "protect"
    elif conflicting:
        mode = "monitor"
    elif events or event_wait:
        mode = "wait"
    elif held_risks:
        mode = "protect" if any(i.get("priorityRank") == "P1" for i in held_risks) else "monitor"
    elif risk_off:
        mode = "monitor"
    elif adds and not avoid:
        mode = "attack" if any(i.get("category") == "add_candidate" for i in adds) else "monitor"
    elif items:
        mode = "monitor"
    else:
        mode = "no_action"

    def name_of(i):
        """JP=コード+社名並記(恒久ルール)。US等はティッカー(それ自体が読める)。"""
        n = i.get("assetName") or ""
        sym = str(i.get("symbol") or "")
        if sym[:1].isdigit() and n and n != sym:
            return f"{sym} {n[:8]}"
        return sym or n

    # ── headline ─────────────────────────────────────────────────────────────
    if st == "weekend":
        headline = "週末レビュー：市場は休場です。新規判断より記録と確認の日。"
    elif p0:
        headline = f"最優先確認あり：{name_of(p0[0])} — {p0[0].get('ownerReadableWhyJa', '')[:40]}"
    elif events:
        headline = f"今日は{MODE_JA[mode]}。{ '/'.join(events[:2]) }の結果を見てから動く日です。"
    else:
        headline = f"今日は{MODE_JA[mode]}。P0(最優先)はありません。"

    # ── summary(3-5文) — 保有リスク→イベント→機会 の順を強制 ────────────────
    parts: List[str] = []
    if st == "weekend":
        parts.append("市場は休場です。今日は新規判断より、保有数量・取得単価・スナップショット同期の確認が優先です。")
        if data_missing:
            parts.append(f"データ未入力の保有銘柄が{len(data_missing)}件あります。")
    else:
        parts.append("P0はありません。" if not p0 else
                     f"P0が{len(p0)}件 — まず{name_of(p0[0])}の確認から。")
        for i in held_risks[:2]:
            parts.append(f"{name_of(i)}は{i.get('ownerReadableWhyJa', '')[:44]}")
        if events:
            parts.append(f"{'/'.join(events[:2])}の発表前のため、関連銘柄の積極判断は結果と初動反応の確認後です。")
        for i in avoid[:1]:
            parts.append(f"{name_of(i)}は追いかけ買い注意(高値掴み/買い戻し主導の可能性)。")
        for i in adds[:1]:
            lbl = "押し目限定" if i.get("category") == "add_only_on_pullback" else "小さく分けて"
            parts.append(f"買い増し候補は{name_of(i)}({lbl})。")
        if conflicting:
            parts.append("強弱シグナルが混在しているため、決め打ちせず判断保留/要確認です。")
        if missing:
            parts.append(f"データ不足: {missing[0]}。")
    summary = " ".join(parts[:5])

    # ── what NOT to do / next checks / after-close review ───────────────────
    what_not: List[str] = []
    if avoid:
        what_not.append(f"急伸中の{name_of(avoid[0])}を追いかけて買わない")
    if events or event_wait:
        what_not.append("イベント結果を見る前に買い増ししない")
    if p0 or held_risks:
        what_not.append("原因未確認のまま保有銘柄をナンピンしない")
    if st == "weekend":
        what_not.append("休場中の値動き予想で新規判断をしない")
    if not what_not:
        what_not.append("一度に大きく買わない(分割が基本)")

    checks: List[str] = []
    for i in (p0 + p1)[:3]:
        if i.get("checkNextJa"):
            checks.append(f"{name_of(i)}: {i['checkNextJa'][:44]}")
    if events and not checks:
        checks.append(f"{events[0]}の結果と直後の金利・指数反応")
    if st == "weekend":
        checks = ["保有数量・取得単価の入力状態", "バックアップ/スナップショットの最終日時",
                  "答え合わせ待ちの判断記録"] if not checks else checks
    if not checks:
        checks.append("需給・フローの翌営業日更新")

    after_close: List[str] = []
    if st in ("close", "after_close", "intraday"):
        after_close.append("今日動いた保有銘柄の理由を記録(Decision Qualityに自動記録)")
        if avoid:
            after_close.append(f"{name_of(avoid[0])}の終値位置(失速したか)を確認")
        after_close.append("需給の公表更新(貸借残は日次・信用残は週次)を待って再判定")

    conf = 0.6
    if missing or data_missing:
        conf -= 0.1
    if conflicting:
        conf -= 0.1
    if not items:
        conf -= 0.1

    def compact(i):
        return {"symbol": i.get("symbol"), "assetName": i.get("assetName"),
                "rank": i.get("priorityRank"), "titleJa": i.get("ownerReadableTitleJa"),
                "actionLabelJa": i.get("actionLabelJa")}

    return {
        "schemaVersion": SCHEMA_VERSION,
        "id": "sb-" + hashlib.md5(f"{now_iso[:13]}:{st}".encode()).hexdigest()[:10],
        "asOf": now_iso,
        "sessionType": st, "marketStatus": ms,
        "ownerMode": mode, "ownerModeJa": MODE_JA[mode],
        "headlineJa": headline[:120],
        "summaryJa": summary[:400],
        "topPriorities": [compact(i) for i in (p0 + p1)[:5]],
        "eventWatch": events[:4],
        "heldRiskWatch": [compact(i) for i in held_risks[:4]],
        "addCandidates": [compact(i) for i in adds[:4]],
        "avoidChaseList": [compact(i) for i in avoid[:4]],
        "supplyDemandHighlights": list(inputs.get("sdHighlights") or [])[:4],
        "flowHighlights": list(inputs.get("flowHighlights") or [])[:4],
        "institutionalHighlights": list(inputs.get("instHighlights") or [])[:3],
        "marketRegimeNote": inputs.get("regimeLabel"),
        "positionExposureNote": inputs.get("exposureNoteJa"),
        "decisionQualityNote": inputs.get("dqNoteJa"),
        "missingDataNote": (" / ".join(missing[:3]) or None),
        "nextChecksJa": checks[:4],
        "whatNotToDoJa": what_not[:3],
        "afterCloseReviewJa": after_close[:3],
        "confidence": round(max(0.2, conf), 2),
        "privacyLevel": ("private_local" if inputs.get("isPrivate") else "public_safe"),
        "sourceLimitNote": "既存レイヤーの要約であり新しい市場データではない。休場中はレビュー体裁。",
        "complianceNote": COMPLIANCE,
    }


def status_doc(brief: Dict[str, Any], *, now_iso: str,
               sources: Dict[str, bool]) -> Dict[str, Any]:
    return {
        "schemaVersion": "session-brief-status-v1", "asOf": now_iso,
        "featureEnabled": True, "lastGeneratedAt": brief.get("asOf"),
        "sessionType": brief.get("sessionType"), "marketStatus": brief.get("marketStatus"),
        "ownerMode": brief.get("ownerMode"),
        "briefItemsCount": len(brief.get("topPriorities") or [])
                           + len(brief.get("heldRiskWatch") or [])
                           + len(brief.get("avoidChaseList") or []),
        "privateComposition": "public_redacted",   # server side never sees holdings
        "sourceAvailability": sources,
        "publicLeakSafe": True,
        "missingDataCount": 1 if brief.get("missingDataNote") else 0,
        "noteJa": "公開側はウォッチリスト水準の要約のみ(実保有はアプリ内でローカル合成)。"
                  "JPリアルタイム無効は意図的で欠陥ではない。",
        "complianceNote": COMPLIANCE,
    }


def handoff_section(brief: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "title": "Session Brief",
        "modeJa": brief.get("ownerModeJa"),
        "headlineJa": brief.get("headlineJa"),
        "summaryJa": brief.get("summaryJa"),
        "nextChecks": brief.get("nextChecksJa") or [],
        "whatNotToDo": brief.get("whatNotToDoJa") or [],
        "caveatJa": "要約レイヤーであり、判断の根拠は各レイヤー(需給/フロー/イベント)を参照。",
        "disclaimerJa": COMPLIANCE,
    }


def snapshot_summary(brief: Dict[str, Any]) -> Dict[str, Any]:
    """Compact block for the daily snapshot — future Decision Quality can ask
    「朝のブリーフは正しいリスクを指していたか」."""
    return {
        "headlineJa": brief.get("headlineJa"),
        "ownerMode": brief.get("ownerMode"),
        "sessionType": brief.get("sessionType"),
        "nextChecksJa": (brief.get("nextChecksJa") or [])[:3],
        "whatNotToDoJa": (brief.get("whatNotToDoJa") or [])[:2],
        "topPrioritySymbols": [p.get("symbol") for p in (brief.get("topPriorities") or [])[:5]],
    }
