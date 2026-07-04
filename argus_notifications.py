"""ARGUS V11.14.0 — Notification / Alert Delivery Engine (pure, deterministic).

「本当に注意が必要な時だけ、静かに知らせる」。既存の高品質レイヤー(Brief/AP/
イベント/保有/フロー/需給/DQ/Sync)の**変化**だけを通知にする — ポーリングの
たびに鳴らない。売買指示では絶対にない。

HARD RULES (noise control is the product):
  - Diff-based: a notification fires on CHANGE (new P0, rank entering D/E,
    flow turning distribution), never on steady state re-polls.
  - dedupeKey + per-rule cooldown + daily caps + quiet hours(JST23-6は
    critical以外沈黙) + weekend calm(review/backup系以外はhigh未満沈黙).
  - Ignore/低確度Watch からは通知しない。
  - 需給の「改善」通知: levelがheavy/very_heavyの間は「改善方向だがまだ重い」
    と表現し、絶対に「需給良好」と言わない(v11.14 Part B連動)。
  - Private notifications live device-local(+encrypted vault); the server
    stores none. Public status is redacted aggregate flags only.
  - External channels (push/email/webhook) are DISABLED adapters by design.
"""
from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Optional

SCHEMA_VERSION = "notification-v1"

EVENT_TYPES = ("p0_priority", "p1_held_priority", "event_before", "event_after",
               "held_risk_change", "flow_deterioration", "flow_improvement",
               "supply_demand_deterioration", "supply_demand_improvement",
               "squeeze_watch", "avoid_chase", "session_brief_ready",
               "snapshot_missing", "sync_backup_warning", "decision_quality_ready",
               "data_stale", "system_health", "unknown")
SEVERITIES = ("critical", "high", "medium", "low", "info")
DELIVERY_CHANNELS = ("in_app", "browser_push", "email", "webhook", "disabled")

# Conservative defaults — in_app only; external adapters exist but disabled.
DEFAULT_RULES: Dict[str, Dict[str, Any]] = {
    "p0_priority":        {"severity": "critical", "cooldownMinutes": 60,   "maxPerDay": 5,  "heldOnly": True},
    "p1_held_priority":   {"severity": "high",     "cooldownMinutes": 1440, "maxPerDay": 5,  "heldOnly": True},
    "event_before":       {"severity": "medium",   "cooldownMinutes": 720,  "maxPerDay": 4,  "heldOnly": False},
    "event_after":        {"severity": "medium",   "cooldownMinutes": 720,  "maxPerDay": 4,  "heldOnly": False},
    "held_risk_change":   {"severity": "high",     "cooldownMinutes": 720,  "maxPerDay": 5,  "heldOnly": True},
    "flow_deterioration": {"severity": "high",     "cooldownMinutes": 720,  "maxPerDay": 5,  "heldOnly": False},
    "supply_demand_deterioration": {"severity": "high", "cooldownMinutes": 1440, "maxPerDay": 4, "heldOnly": False},
    "supply_demand_improvement":   {"severity": "low",  "cooldownMinutes": 1440, "maxPerDay": 3, "heldOnly": False},
    "squeeze_watch":      {"severity": "medium",   "cooldownMinutes": 1440, "maxPerDay": 3,  "heldOnly": False},
    "avoid_chase":        {"severity": "medium",   "cooldownMinutes": 1440, "maxPerDay": 4,  "heldOnly": False},
    "session_brief_ready": {"severity": "info",    "cooldownMinutes": 240,  "maxPerDay": 3,  "heldOnly": False},
    "snapshot_missing":   {"severity": "low",      "cooldownMinutes": 1440, "maxPerDay": 1,  "heldOnly": False},
    "sync_backup_warning": {"severity": "low",     "cooldownMinutes": 4320, "maxPerDay": 1,  "heldOnly": False},
}
GLOBAL_MAX_PER_DAY = 12
QUIET_HOURS_JST = (23, 6)          # critical以外沈黙
COMPLIANCE = "注意喚起であり売買指示ではない。"
_SEV_ORDER = {s: i for i, s in enumerate(SEVERITIES)}


def _mk(event_type, severity, symbol, market, name, title, body, why, check,
        change, now_iso, dedupe, sources, held):
    return {
        "schemaVersion": SCHEMA_VERSION,
        "id": "nt-" + hashlib.md5(f"{dedupe}:{now_iso[:16]}".encode()).hexdigest()[:12],
        "asOf": now_iso, "createdAt": now_iso, "updatedAt": now_iso,
        "eventType": event_type, "severity": severity,
        "symbol": symbol, "market": market, "assetName": name,
        "titleJa": title[:90], "bodyJa": body[:200], "whyJa": why[:160],
        "checkNextJa": check[:120], "whatWouldChangeJa": change[:120],
        "relatedPriorityId": None, "relatedEventId": None,
        "relatedSnapshotId": None, "relatedDecisionId": None,
        "sourceModules": sources,
        "privacyLevel": ("private_local" if held else "public_safe"),
        "deliveryState": "new", "dedupeKey": dedupe,
        "ttl": 3 * 86400, "expiresAt": None,
        "throttleGroup": event_type,
        "sourceLimitNote": "既存レイヤーの変化検知であり新しい市場データではない。",
        "complianceNote": COMPLIANCE,
    }


def _disp(symbol, name):
    sym = str(symbol or "")
    n = str(name or "")
    return f"{sym} {n[:8]}" if sym[:1].isdigit() and n and n != sym else (sym or n)


def generate(prev: Dict[str, Any], cur: Dict[str, Any], now_iso: str) -> List[Dict[str, Any]]:
    """Diff prev→cur layer states into candidate notifications (noise control
    is applied separately by apply_noise_control). Inputs (all optional):
      apItems[] (ActionPriority-shaped), eventNames[], sdBySymbol{SYM:{rank,
      condition,level,name,isHeld}}, flowBySymbol{SYM:{flowClass,name,isHeld}},
      briefSession, snapshotAgeDays, vaultConfigured, hasHoldings
    """
    out: List[Dict[str, Any]] = []
    day = now_iso[:10]
    p_ap = {i["symbol"]: i for i in (prev.get("apItems") or [])}
    c_ap = {i["symbol"]: i for i in (cur.get("apItems") or [])}

    for sym, it in c_ap.items():
        if it.get("priorityRank") == "Ignore":
            continue                                   # never notify Ignore
        name = it.get("assetName")
        held = it.get("isHeld") is True
        was = p_ap.get(sym) or {}
        # P0 new/changed
        if it.get("priorityRank") == "P0" and was.get("priorityRank") != "P0":
            out.append(_mk("p0_priority", "critical", sym, it.get("market"), name,
                           f"最優先確認：{_disp(sym, name)}",
                           f"保有中の{_disp(sym, name)}に複数のリスク信号が重なっています。",
                           it.get("ownerReadableWhyJa") or "", it.get("checkNextJa") or "",
                           it.get("whatWouldChangeJa") or "", now_iso,
                           f"p0|{sym}|{day}", ["action_priority"], held))
        # P1 held entering
        elif held and it.get("priorityRank") == "P1" and was.get("priorityRank") not in ("P0", "P1"):
            out.append(_mk("p1_held_priority", "high", sym, it.get("market"), name,
                           f"保有銘柄の優先確認：{_disp(sym, name)}",
                           f"{_disp(sym, name)}は今日確認が必要です。",
                           it.get("ownerReadableWhyJa") or "", it.get("checkNextJa") or "",
                           it.get("whatWouldChangeJa") or "", now_iso,
                           f"p1|{sym}|{day}", ["action_priority"], held))
        # avoid-chase entering
        if it.get("category") == "avoid_chase" and was.get("category") != "avoid_chase":
            out.append(_mk("avoid_chase", "medium", sym, it.get("market"), name,
                           f"追いかけ注意：{_disp(sym, name)}",
                           "上昇していますが、買い戻し主導/過熱の可能性があります。",
                           it.get("ownerReadableWhyJa") or "", it.get("checkNextJa") or "",
                           it.get("whatWouldChangeJa") or "", now_iso,
                           f"chase|{sym}", ["action_priority", "supply_demand"], held))

    # events entering window
    prev_ev = set(prev.get("eventNames") or [])
    for ev in (cur.get("eventNames") or []):
        if ev and ev not in prev_ev:
            out.append(_mk("event_before", "medium", None, None, None,
                           f"イベント前：{ev}",
                           f"{ev}発表前のため、関連銘柄の買い増し判断は発表後の反応確認まで待機。",
                           "重要イベントは初動反応で判断が変わるため。",
                           f"{ev}の結果と直後の金利・指数反応を確認",
                           "イベント通過後、通常の優先度に戻ります", now_iso,
                           f"evb|{ev}|{day}", ["event_radar"], False))

    # flow deterioration (change into panic/distribution)
    p_fl = prev.get("flowBySymbol") or {}
    for sym, f in (cur.get("flowBySymbol") or {}).items():
        fc = (f or {}).get("flowClass")
        was_fc = (p_fl.get(sym) or {}).get("flowClass")
        if fc in ("panic_selling", "distribution") and was_fc not in ("panic_selling", "distribution"):
            held = bool((f or {}).get("isHeld"))
            out.append(_mk("flow_deterioration", "high" if held else "medium",
                           sym, None, (f or {}).get("name"),
                           f"Flow悪化：{_disp(sym, (f or {}).get('name'))}",
                           "大口流出/売り抜け/狼狽売りの可能性が出ています。",
                           "実測フロー/値動きの型が売り圧力側に変化。",
                           "翌営業日に戻りが売られるか、公式材料を確認",
                           "売り圧力の推定が消えれば解除", now_iso,
                           f"flow|{sym}|{fc}", ["flow_attribution"], held))

    # supply/demand transitions
    p_sd = prev.get("sdBySymbol") or {}
    for sym, sdd in (cur.get("sdBySymbol") or {}).items():
        rank = (sdd or {}).get("rank")
        cond = (sdd or {}).get("condition")
        level = (sdd or {}).get("level")
        name = (sdd or {}).get("name")
        held = bool((sdd or {}).get("isHeld"))
        was = p_sd.get(sym) or {}
        if rank in ("D", "E") and was.get("rank") not in ("D", "E"):
            out.append(_mk("supply_demand_deterioration", "high" if held else "medium",
                           sym, "JP", name,
                           f"需給悪化：{_disp(sym, name)}",
                           "信用買い残が重く、戻り売りに注意。",
                           "需給ランクがD/Eに移行。", "戻り局面で売りが出るかを確認",
                           "買い残の減少/投げ一巡で解除", now_iso,
                           f"sdD|{sym}|{rank}", ["supply_demand"], held))
        elif cond == "squeeze_prone" and was.get("condition") != "squeeze_prone":
            out.append(_mk("squeeze_watch", "medium", sym, "JP", name,
                           f"踏み上げ注意：{_disp(sym, name)}",
                           "売り長で踏み上げ余地。ただし買い戻し主導の可能性があり新規の大口買いとは未確定。",
                           "貸借倍率が売り長側。", "買い戻し一巡後に失速しないかを確認",
                           "上昇主体の入れ替わり確認で評価変更", now_iso,
                           f"sq|{sym}", ["supply_demand"], held))
        elif rank in ("S", "A", "B") and was.get("rank") in ("C", "D", "E", "Unknown"):
            # Part B discipline: improvement while HEAVY is phrased honestly and
            # stays low-key — never 「需給良好」.
            if level in ("heavy", "very_heavy") or cond == "improving_but_heavy":
                out.append(_mk("supply_demand_improvement", "low", sym, "JP", name,
                               f"需給改善方向：{_disp(sym, name)}",
                               "需給は改善方向ですが、信用買い残はまだ重いです。",
                               "買い残は減少中だが絶対量が大きい。",
                               "買い残が続けて減るか、上昇日に出来高を伴うかを確認",
                               "水準が普通まで軽くなれば評価上げ", now_iso,
                               f"sdUpH|{sym}|{day}", ["supply_demand"], held))
            else:
                out.append(_mk("supply_demand_improvement", "low", sym, "JP", name,
                               f"需給改善：{_disp(sym, name)}",
                               f"需給ランクが{rank}に改善しました。",
                               "買い残水準・売り圧力が軽い状態。",
                               "続伸時の出来高を確認", "需給悪化で解除", now_iso,
                               f"sdUp|{sym}|{day}", ["supply_demand"], held))

    # session brief ready (per session change)
    if cur.get("briefSession") and cur.get("briefSession") != prev.get("briefSession"):
        out.append(_mk("session_brief_ready", "info", None, None, None,
                       "今日の作戦が更新されました。",
                       "SESSION BRIEFで今日のモードと「やらないこと」を確認してください。",
                       "セッションが切り替わりました。", "SESSION BRIEFを確認",
                       "", now_iso, f"brief|{cur.get('briefSession')}|{day}",
                       ["session_brief"], False))

    # snapshot / backup warnings
    if cur.get("hasHoldings"):
        age = cur.get("snapshotAgeDays")
        if age is None or (isinstance(age, (int, float)) and age > 3):
            out.append(_mk("snapshot_missing", "low", None, None, None,
                           "バックアップ確認：スナップショット未作成",
                           "保有データのスナップショットが最近作成されていません。",
                           "履歴が残らないと後日の答え合わせができません。",
                           "Todayを開けば自動作成されます", "", now_iso,
                           f"snap|{day}", ["portfolio_sync"], True))
        if cur.get("vaultConfigured") is False:
            out.append(_mk("sync_backup_warning", "low", None, None, None,
                           "バックアップ未設定",
                           "暗号化バックアップ(パスフレーズ)が未設定です。端末故障で保有データが失われます。",
                           "保有・判断履歴は端末内のみ。", "Guideの「バックアップと同期」で設定",
                           "", now_iso, "vault", ["portfolio_sync"], True))
    return out


def apply_noise_control(candidates: List[Dict[str, Any]], state: Dict[str, Any],
                        now_iso: str, *, weekend: bool = False,
                        quiet_override: Optional[bool] = None) -> Dict[str, Any]:
    """state: {"lastByDedupe": {key: iso}, "sentToday": {"day":.., "total":n,
    "byType": {t:n}}} → {"deliver": [...], "suppressed": n, "state": updated}"""
    day = now_iso[:10]
    hour_jst = int(now_iso[11:13]) if len(now_iso) >= 13 else 12
    quiet = quiet_override if quiet_override is not None else (
        hour_jst >= QUIET_HOURS_JST[0] or hour_jst < QUIET_HOURS_JST[1])
    last = dict(state.get("lastByDedupe") or {})
    sent = state.get("sentToday") or {}
    if sent.get("day") != day:
        sent = {"day": day, "total": 0, "byType": {}}
    by_type = dict(sent.get("byType") or {})
    total = int(sent.get("total") or 0)
    deliver, suppressed = [], 0

    def minutes_since(iso):
        try:
            from_h = int(iso[11:13]) * 60 + int(iso[14:16])
            now_h = int(now_iso[11:13]) * 60 + int(now_iso[14:16])
            dd = (now_h - from_h) if iso[:10] == day else 24 * 60
            return dd if dd >= 0 else 24 * 60
        except Exception:
            return 24 * 60

    for ev in sorted(candidates, key=lambda e: _SEV_ORDER.get(e["severity"], 9)):
        rule = DEFAULT_RULES.get(ev["eventType"], {"severity": "info",
                                                   "cooldownMinutes": 1440, "maxPerDay": 2})
        # quiet hours: only critical passes
        if quiet and ev["severity"] != "critical":
            suppressed += 1
            continue
        # weekend calm: below high suppressed except backup/review types
        if weekend and _SEV_ORDER[ev["severity"]] > _SEV_ORDER["high"] \
                and ev["eventType"] not in ("snapshot_missing", "sync_backup_warning",
                                            "session_brief_ready"):
            suppressed += 1
            continue
        prev_iso = last.get(ev["dedupeKey"])
        if prev_iso and minutes_since(prev_iso) < rule["cooldownMinutes"]:
            suppressed += 1
            continue
        if by_type.get(ev["eventType"], 0) >= rule["maxPerDay"]:
            suppressed += 1
            continue
        if total >= GLOBAL_MAX_PER_DAY and ev["severity"] != "critical":
            suppressed += 1
            continue
        deliver.append(ev)
        last[ev["dedupeKey"]] = now_iso
        by_type[ev["eventType"]] = by_type.get(ev["eventType"], 0) + 1
        total += 1
    return {"deliver": deliver, "suppressed": suppressed,
            "state": {"lastByDedupe": last,
                      "sentToday": {"day": day, "total": total, "byType": by_type}}}


def digest(items: List[Dict[str, Any]], now_iso: str,
           suppressed: int = 0) -> Dict[str, Any]:
    unread = [i for i in items if i.get("deliveryState") == "new"]
    return {
        "schemaVersion": "notification-digest-v1", "asOf": now_iso,
        "unreadCount": len(unread),
        "criticalCount": sum(1 for i in unread if i["severity"] == "critical"),
        "highCount": sum(1 for i in unread if i["severity"] == "high"),
        "todayCount": sum(1 for i in items if i.get("createdAt", "")[:10] == now_iso[:10]),
        "suppressedCount": suppressed,
        "topNotifications": sorted(unread, key=lambda i: _SEV_ORDER.get(i["severity"], 9))[:5],
        "quietMode": False, "lastGeneratedAt": now_iso,
        "privacyLevel": "private_local",
    }


def public_status(*, now_iso: str, sources: Dict[str, bool]) -> Dict[str, Any]:
    """PUBLIC — feature/architecture flags only. The server stores ZERO
    notifications (they are device-local); nothing here can leak."""
    return {
        "schemaVersion": "notification-status-v1", "asOf": now_iso,
        "featureEnabled": True,
        "deliveryChannelsEnabled": ["in_app"],
        "deliveryChannelsDisabled": ["browser_push", "email", "webhook"],
        "quietHoursJst": f"{QUIET_HOURS_JST[0]}:00-{QUIET_HOURS_JST[1]}:00",
        "maxPerDay": GLOBAL_MAX_PER_DAY,
        "storageMode": "local_only+encrypted_vault",
        "serverStoresNotifications": False,
        "publicLeakSafe": True,
        "sourceAvailability": sources,
        "noteJa": "通知は端末内で生成・保存され、サーバーには一切保存されない。"
                  "外部push/メール/webhookは未設定のため無効。"
                  "JPリアルタイム無効は意図的で欠陥ではない。",
        "complianceNote": COMPLIANCE,
    }
