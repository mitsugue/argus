"""ARGUS V11.22.0 — Admin / Data Quality Console (pure, deterministic).

「今の判断は最新データに基づいているか」に運用者目線で答える層。
ソース健全性・データ鮮度・エンジン健全性を1画面に集約し、総合ステータス
(ok/degraded/warning/critical)を決定論で判定する。取引機能ではない。

HARD RULES:
  - ステータス・鮮度を捏造しない(不明はunknown・年齢が測れなければ測れないと言う)。
  - **意図的な無効(JPリアルタイム/逆日歩/銘柄別空売り比率)は絶対にcriticalに
    しない** — expected_disabledとして「意図的に無効」表示。
  - 失敗理由はredacted(例外文字列にトークン等が乗る事故を防ぐためクラス名のみ)。
  - 秘密(パスフレーズ/vault/HMAC/トークン/OpenD・moomoo資格情報)は出力ゼロ。
  - 私的データ(保有/投信/記録)は「端末内で判定」とだけ言う(サーバーは知らない)。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

SCHEMA_VERSION = "data-quality-v1"

OVERALL = ("ok", "degraded", "partial", "warning", "critical", "unknown")
SOURCE_TYPES = ("market_data", "macro", "event", "supply_demand", "flow",
                "institutional", "portfolio_local", "backup", "bridge",
                "frontend", "backend", "unknown")
SOURCE_STATUSES = ("ok", "stale", "degraded", "disabled_expected",
                   "disabled_problem", "failed", "unknown")
ENGINE_STATUSES = ("ok", "degraded", "stale_input", "disabled", "failed", "unknown")
CADENCES = ("realtime", "intraday", "daily", "weekly", "manual", "event_based", "unknown")
BUCKETS = ("fresh", "recent", "stale", "very_stale", "unknown")

BUCKET_JA = {"fresh": "新鮮", "recent": "最近", "stale": "古い",
             "very_stale": "かなり古い", "unknown": "不明"}
OVERALL_JA = {"ok": "正常", "degraded": "一部劣化", "partial": "部分的",
              "warning": "警告", "critical": "重大", "unknown": "判定保留"}

COMPLIANCE = "運用ステータスの可視化であり、売買判断・売買指示ではない。秘密情報は含まれない。"

# 期待どおりの無効(criticalにしない・「意図的」表示) — 恒久の3件
EXPECTED_DISABLED = (
    {"sourceName": "moomoo JPリアルタイム", "reasonJa": "moomoo側の日本株APIメンテナンス(サポート確認済み)のため意図的に無効(エラーではない)。JPは常時フォールバック(J-Quants/Yahoo)"},
    {"sourceName": "逆日歩(品貸料)", "reasonJa": "未取込(日証金の品貸料CSVは別系統・捏造せず未取得表示)"},
    {"sourceName": "銘柄別空売り比率", "reasonJa": "J-Quants Standardは業種別のみ(銘柄別は未提供)"},
)

# cadence → (fresh上限, recent上限, stale上限) 秒。超えたらvery_stale。
_THRESH = {
    "realtime": (120, 900, 3600),
    "intraday": (3600, 4 * 3600, 24 * 3600),
    "daily": (26 * 3600, 2 * 86400, 4 * 86400),
    "weekly": (8 * 86400, 10 * 86400, 15 * 86400),
    "manual": (8 * 86400, 15 * 86400, 31 * 86400),
    "event_based": (2 * 86400, 5 * 86400, 10 * 86400),
}


def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        t = str(s).replace("Z", "+00:00")
        d = datetime.fromisoformat(t[:32] if "+" in t or "-" in t[10:] else t)
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d
    except Exception:
        return None


def freshness_bucket(age_seconds: Optional[float], cadence: str) -> str:
    """年齢が測れない=unknown(捏造しない)。"""
    if age_seconds is None:
        return "unknown"
    f, r, s = _THRESH.get(cadence, _THRESH["daily"])
    if age_seconds <= f:
        return "fresh"
    if age_seconds <= r:
        return "recent"
    if age_seconds <= s:
        return "stale"
    return "very_stale"


def build_source(raw: Dict[str, Any], now_iso: str) -> Dict[str, Any]:
    """raw: sourceName, sourceType, cadence, lastSuccessAt|None,
    lastAttemptAt|None, expectedDisabled(bool), failureClass|None,
    fallbackActive(bool), impactJa, nextStepJa"""
    now = _parse_iso(now_iso)
    last = _parse_iso(raw.get("lastSuccessAt"))
    age = (now - last).total_seconds() if now and last else None
    cadence = raw.get("cadence") if raw.get("cadence") in CADENCES else "unknown"
    bucket = freshness_bucket(age, cadence)

    if raw.get("expectedDisabled"):
        status = "disabled_expected"
        status_ja = "意図的に無効(エラーではない)"
    elif raw.get("failureClass"):
        status = "failed"
        status_ja = "取得失敗(詳細はredacted)"
    elif bucket in ("fresh", "recent"):
        status = "ok"
        status_ja = f"正常({BUCKET_JA[bucket]})"
    elif bucket in ("stale", "very_stale"):
        status = "stale"
        status_ja = f"データが{BUCKET_JA[bucket]}(最終成功: {str(raw.get('lastSuccessAt'))[:16]})"
    else:
        status = "unknown"
        status_ja = "鮮度不明(タイムスタンプ未取得 — 捏造しません)"

    if status == "stale" and raw.get("fallbackActive"):
        status = "degraded"
        status_ja += " — フォールバック稼働中"

    return {
        "sourceName": raw.get("sourceName") or "unknown",
        "sourceType": raw.get("sourceType") if raw.get("sourceType") in SOURCE_TYPES else "unknown",
        "status": status,
        "lastSuccessAt": raw.get("lastSuccessAt"),
        "lastAttemptAt": raw.get("lastAttemptAt"),
        "freshnessAgeSec": round(age) if age is not None else None,
        "freshnessBucket": bucket if not raw.get("expectedDisabled") else "unknown",
        "ownerReadableStatusJa": status_ja,
        "ownerReadableImpactJa": raw.get("impactJa") or "",
        "nextStepJa": raw.get("nextStepJa") or "",
        # クラス名のみ(例外メッセージにトークンが乗る事故を構造的に防ぐ)
        "failureReasonRedacted": (str(raw.get("failureClass"))[:40]
                                  if raw.get("failureClass") else None),
        "isExpectedDisabled": bool(raw.get("expectedDisabled")),
        "privacyLevel": "public_safe",
    }


def build_engine(raw: Dict[str, Any]) -> Dict[str, Any]:
    status = raw.get("status") if raw.get("status") in ENGINE_STATUSES else "unknown"
    return {
        "engineName": raw.get("engineName") or "unknown",
        "status": status,
        "lastRunAt": raw.get("lastRunAt"),
        "outputCount": raw.get("outputCount"),
        "staleInputCount": raw.get("staleInputCount"),
        "missingEvidenceCount": raw.get("missingEvidenceCount"),
        "ownerReadableImpactJa": raw.get("impactJa") or "",
        "nextStepJa": raw.get("nextStepJa") or "",
    }


def score_overall(sources: List[Dict[str, Any]], engines: List[Dict[str, Any]],
                  bridge: Dict[str, Any], *, public_leak_safe: bool,
                  backup_unsafe_with_data: bool = False,
                  event_near: bool = False) -> str:
    """§5の決定論スコア。expected_disabledは一切数えない。"""
    live = [s for s in sources if not s["isExpectedDisabled"]]
    failed = [s for s in live if s["status"] == "failed"]
    stale = [s for s in live if s["status"] in ("stale",)]
    degraded = [s for s in live if s["status"] == "degraded"]
    major = [s for s in live if s.get("sourceType") in ("market_data", "bridge", "backend")]
    major_bad = [s for s in major if s["status"] in ("failed", "stale")]
    engine_failed = [e for e in engines if e["status"] == "failed"]
    engine_stale = [e for e in engines if e["status"] == "stale_input"]

    us_down = str(bridge.get("usRealtimeStatus") or "") in ("failed", "down", "error")
    bridge_down = str(bridge.get("bridgeProcess") or "") in ("down", "failed")

    if not public_leak_safe:
        return "critical"
    if us_down or bridge_down or engine_failed:
        return "critical"
    if major_bad or backup_unsafe_with_data \
            or (event_near and any(s["sourceType"] == "event" for s in stale)) \
            or len(stale) >= 3:
        return "warning"
    if stale or degraded or failed or engine_stale:
        return "degraded"
    if not live and not engines:
        return "unknown"
    return "ok"


def build_console(inputs: Dict[str, Any], now_iso: str,
                  app_version: str = "") -> Dict[str, Any]:
    """inputs: sources[](build_source raw), engines[](build_engine raw),
    bridge{bridgeProcess,openDStatus,usRealtimeStatus,jpRealtimeStatus,
    jpFallbackActive,heartbeatAgeSec,acceptedCount,diskUsagePct},
    cron[] {name, lastRunAt, cadence}, publicLeakSafe(bool),
    backupUnsafeWithData(bool|None), eventNear(bool)"""
    sources = [build_source(s, now_iso) for s in (inputs.get("sources") or [])]
    engines = [build_engine(e) for e in (inputs.get("engines") or [])]
    bridge = dict(inputs.get("bridge") or {})
    leak_safe = inputs.get("publicLeakSafe", True) is True

    overall = score_overall(sources, engines, bridge,
                            public_leak_safe=leak_safe,
                            backup_unsafe_with_data=bool(inputs.get("backupUnsafeWithData")),
                            event_near=bool(inputs.get("eventNear")))

    live = [s for s in sources if not s["isExpectedDisabled"]]
    issues = [i for i in (
        "公開エンドポイントの漏洩ガードに異常(即時確認)" if not leak_safe else None,
        "USリアルタイム(bridge)が停止" if overall == "critical"
        and str(bridge.get("usRealtimeStatus") or "") in ("failed", "down", "error") else None,
        *[f"{s['sourceName']}: {s['ownerReadableStatusJa']}" for s in live
          if s["status"] in ("failed", "stale", "degraded")][:4],
        *[f"エンジン{e['engineName']}: 入力が古い" for e in engines
          if e["status"] == "stale_input"][:2],
    ) if i][:6]

    summary = (
        "全ソース正常 — 今日の判断は新しいデータに基づいています。" if overall == "ok" else
        f"一部のデータが古い/劣化しています({len(issues)}件)。該当レイヤーの確度は割り引いて読んでください。" if overall == "degraded" else
        "重要ソースに問題があります。関連する判断の確度を下げ、下の対応手順を確認してください。" if overall in ("warning", "partial") else
        "重大: 基盤(bridge/公開ガード/主要エンジン)に問題があります。判断より先に復旧確認を。" if overall == "critical" else
        "ステータスを判定できるデータが不足しています。")

    return {
        "schemaVersion": SCHEMA_VERSION, "asOf": now_iso, "appVersion": app_version,
        "overallStatus": overall, "overallStatusJa": OVERALL_JA[overall],
        "ownerReadableSummaryJa": summary,
        "topIssuesJa": issues,
        "nextChecksJa": [c for c in (
            "bridge/scripts/check_bridge_status.sh で実プロセス確認" if overall in ("warning", "critical") else None,
            "collect cron(30分毎)の次回実行後に再確認" if any(s["status"] == "stale" for s in live) else None,
            "このページを再読込(キャッシュ更新)",
        ) if c][:3],
        "sourceHealth": sources,
        "engineHealth": engines,
        "freshness": [{
            "dataKind": s["sourceName"], "latestFetchedAt": s["lastSuccessAt"],
            "expectedCadence": next((r.get("cadence") for r in (inputs.get("sources") or [])
                                     if r.get("sourceName") == s["sourceName"]), "unknown"),
            "freshnessStatus": s["freshnessBucket"],
            "staleReasonJa": s["ownerReadableStatusJa"] if s["status"] in ("stale", "degraded") else None,
            "impactJa": s["ownerReadableImpactJa"],
        } for s in sources],
        "cronHealth": list(inputs.get("cron") or []),
        "bridgeHealth": {
            "bridgeProcess": bridge.get("bridgeProcess"),
            "openDStatus": bridge.get("openDStatus"),
            "bridgeMode": bridge.get("bridgeMode"),
            "usRealtimeStatus": bridge.get("usRealtimeStatus"),
            "jpRealtimeStatus": bridge.get("jpRealtimeStatus"),
            "jpRealtimeNoteJa": "意図的に無効(moomoo側メンテナンス確認済み) — エラーではない"
            if str(bridge.get("jpRealtimeStatus")) == "disabled" else None,
            "jpFallbackActive": bridge.get("jpFallbackActive"),
            "heartbeatAgeSec": bridge.get("heartbeatAgeSec"),
            "acceptedCount": bridge.get("acceptedCount"),
            "diskUsagePct": bridge.get("diskUsagePct"),
        },
        # v12.0.2: JP復帰準備 + 再起動安全(heartbeat実測のみ・捏造なし)
        "jpReadiness": build_jp_readiness(bridge, inputs.get("jpApiContext")),
        "rebootSafety": build_reboot_safety(bridge, inputs.get("heartbeatRaw")),
        "backupHealth": {"evaluatedOnDevice": True,
                         "noteJa": "保護状態・復元確認は端末内で判定(Backupページ参照)。サーバーは知らない。"},
        "privacyHealth": {"publicLeakSafe": leak_safe,
                          "redactedEndpoints": True,
                          "noteJa": "公開系は保有・投信・記録・秘密を構造的に含まない(3層テスト+smoke検査)。"},
        "expectedDisabled": [dict(x) for x in EXPECTED_DISABLED],
        "publicLeakSafe": leak_safe,
        "sourceLimitNote": "鮮度はサーバーが実測できたタイムスタンプのみから判定(不明はunknown)。",
        "complianceNote": COMPLIANCE,
    }


# ── V12.0.2 — JP Realtime Activation Readiness / Reboot Safety ──────────────
# JPリアルタイムはmoomoo側の権限次第 — アプリコードでは直せない事実を明示し、
# US-only解除の手順は「準備OKが実測できた時だけ」表示する(誤操作ガード)。

JP_PERMISSION = ("no_permission", "maintenance_or_no_permission",
                 "maintenance_confirmed", "ready", "unknown")
JP_MAINTENANCE_JA = ("日本株リアルタイムAPIは現在利用できません。moomoo側の日本株API"
                     "相場情報サービスがメンテナンス/権限未反映の可能性があります。")
JP_FULLBOARD_JA = ("日本株フル板契約済みでも、OpenD API側ではまだJP snapshot / "
                   "ORDER_BOOKが ret=-1 のため復帰不可です。")
# v12.0.5: moomooサポートがメンテナンス影響を正式確認(「疑い」→「確認済み」へ昇格)
JP_MAINT_CONFIRMED_JA = ("moomooサポート確認済み：日本株API相場情報サービスの"
                         "メンテナンスがOpenD APIのJP snapshot / ORDER_BOOKに影響しています。")
JP_RECOVERY_WAIT_JA = ("復旧待ち：moomoo側の日本株API相場情報サービスがメンテナンス中です。"
                       "フル板契約は済んでいますが、復旧完了まではOpenD APIでsnapshot / "
                       "ORDER_BOOKを取得できません。復旧後はOpenDの再起動・再ログイン後に"
                       "ret=0確認が必要です。")
JP_GUARD_MAINT_JA = ("まだUS-onlyを外さないでください。復旧後にOpenD再起動・再ログインし、"
                     "JP snapshot ret=0を確認してから解除します。")
JP_ACTIVATION_FULL_JA = ("①moomooメンテナンス完了 ②OpenD再起動・再ログイン "
                         "③JP.5803 / JP.8058 / JP.9984 のsnapshotが ret=0 "
                         "④板情報を使う場合は JP.5803 のORDER_BOOKも ret=0。")
ACTIVATION_TEST_JA = "JP.5803 / JP.8058 / JP.9984 のsnapshot testが ret=0 になったら復帰可能。"


def build_jp_readiness(bridge: Dict[str, Any],
                       context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """bridge: jpRealtimeStatus, jpLastErrorClass, lastJPQuotePushAt,
    jpFallbackActive, bridgeMode, bridgeProcess, openDStatus.
    権限状態はheartbeatの実測からのみ導出(捏造しない・不明はunknown)。"""
    jp = str(bridge.get("jpRealtimeStatus") or "unknown")
    err = str(bridge.get("jpLastErrorClass") or "").lower()
    mode = str(bridge.get("bridgeMode") or "")
    us_only = mode == "us_only" or jp == "disabled"
    bridge_ok = str(bridge.get("bridgeProcess") or "") in ("ok", "ok_legacy")
    opend_ok = str(bridge.get("openDStatus") or "") == "connected"
    ctx = dict(context or {})
    maintenance_note = bool(ctx.get("supportMaintenanceNote"))
    maintenance_confirmed = bool(ctx.get("supportMaintenanceConfirmed"))

    if jp == "ok":
        perm = "ready"            # 実測ret=0は古いcontextに常に勝つ
    elif jp == "entitlement_unavailable" or "permission" in err or "entitlement" in err \
            or ctx.get("manualProbeNoPermission"):
        if maintenance_confirmed:
            perm = "maintenance_confirmed"
        elif maintenance_note:
            perm = "maintenance_or_no_permission"
        else:
            perm = "no_permission"
    else:
        perm = "unknown"          # 権限テスト未実施(disabledだけでは権限は断定できない)

    order_book = ctx.get("orderBookReady")
    if order_book is None:
        order_book = False if ctx.get("manualProbeNoPermission") else "unknown"
    full_board = ctx.get("fullBoardAppSubscription")
    full_board = bool(full_board) if isinstance(full_board, bool) else "unknown"
    add_sub = ctx.get("additionalSubscriptionRequired")
    add_sub = bool(add_sub) if isinstance(add_sub, bool) else "unknown"

    if perm == "maintenance_confirmed":
        activation = False
        status_ja = JP_RECOVERY_WAIT_JA
        next_ja = ("moomooのメンテナンス完了告知/サポート確認を待つ → 市場時間外に"
                   "OpenDを再起動・再ログイン(SMS/図形認証の可能性あり・認証コードや"
                   "パスワードはチャット等に貼らない) → JP.5803/8058/9984のsnapshotと"
                   "JP.5803のORDER_BOOKが ret=0 になるまでUS-onlyを維持。"
                   "詳細は bridge/README.md の復旧ランブック(v12.0.5)。"
                   "アプリ側のコード変更では直りません。")
    elif perm == "maintenance_or_no_permission":
        activation = False
        status_ja = "復帰不可：" + JP_MAINTENANCE_JA
        next_ja = ("moomoo側のAPIメンテナンス完了を待ち、後日JP snapshot / ORDER_BOOKを"
                   "再テスト(安全手順参照)。ret=0になるまでUS-onlyを維持。"
                   "アプリ側のコード変更では直りません。")
    elif perm == "no_permission":
        activation = False
        status_ja = "復帰不可：moomoo側の日本株クォート権限がありません。"
        next_ja = ("moomooアプリ/サポートでJPN Stocksクォート権限を取得後、EC2で権限テスト"
                   "(下の安全手順)を実行。アプリ側のコード変更では直りません。")
    elif perm == "ready" and us_only:
        activation = True
        status_ja = "復帰準備OK：US-only解除前に安全手順を実行してください。"
        next_ja = "Data Qualityの復帰手順(表示中)に従いUS-onlyを解除 → 復帰後にJP push実測を確認。"
    elif perm == "ready" and not us_only and bridge_ok and opend_ok:
        activation = True
        status_ja = "JPリアルタイム稼働中。"
        next_ja = "対応不要(JP pushの鮮度をこのページで監視)。"
    else:
        activation = "unknown"
        status_ja = "権限テスト未実施。US-only modeで運用中。日本株は代替データで判定しています。"
        next_ja = f"必要ならEC2で権限テストを実行(安全手順参照)。{ACTIVATION_TEST_JA}"

    return {
        "jpRealtimeStatus": jp,
        "jpPermissionStatus": perm,
        "lastJPQuotePushAt": bridge.get("lastJPQuotePushAt"),
        "jpFallbackActive": bool(bridge.get("jpFallbackActive")),
        "usOnlyOverrideActive": us_only,
        "activationReady": activation,
        "showActivationSteps": activation is True and us_only,   # ガード: 準備OK時のみ
        "jpApiMaintenanceSuspected": (True if perm in ("maintenance_or_no_permission",
                                                       "maintenance_confirmed")
                                      else False if perm in ("ready", "no_permission")
                                      else "unknown"),
        # v12.0.5: サポートがメンテナンス影響を正式確認(疑いとは別フィールド)
        "jpApiMaintenanceConfirmed": (True if perm == "maintenance_confirmed"
                                      else False if perm in ("ready", "no_permission")
                                      else "unknown"),
        "jpFullBoardAppSubscriptionKnown": full_board,
        "jpOpenDOrderBookReady": order_book,
        "additionalSubscriptionRequired": add_sub,
        "additionalSubscriptionNoteJa": ("追加申込は現時点で不要(moomooサポート回答)"
                                         if add_sub is False else None),
        "recoveryEtaJa": ("未定(moomoo側の告知待ち)"
                          if perm == "maintenance_confirmed" else None),
        "postRecoveryActionJa": ("OpenDの再起動・再ログイン後、JP snapshot / ORDER_BOOKの"
                                 "ret=0確認が必要"
                                 if perm == "maintenance_confirmed" else None),
        "fullBoardNoteJa": (JP_FULLBOARD_JA if full_board is True and order_book is not True
                            else None),
        "contextAsOf": ctx.get("asOf"),
        "reasonJa": ("moomooのJPN Stocksクォート権限がないため、日本株リアルタイムは利用できません。"
                     if perm == "no_permission"
                     else JP_MAINT_CONFIRMED_JA if perm == "maintenance_confirmed"
                     else JP_MAINTENANCE_JA if perm == "maintenance_or_no_permission"
                     else None),
        "safeModeJa": "US-only modeで運用中。日本株は代替データで判定しています。" if us_only else None,
        "activationConditionJa": (JP_ACTIVATION_FULL_JA
                                  if perm in ("maintenance_confirmed",
                                              "maintenance_or_no_permission")
                                  else ACTIVATION_TEST_JA),
        "ownerReadableStatusJa": status_ja,
        "nextStepJa": next_ja,
        "guardJa": (None if activation is True
                    else JP_GUARD_MAINT_JA if perm == "maintenance_confirmed"
                    else "まだUS-onlyを外さないでください。"),
    }


def build_reboot_safety(bridge: Dict[str, Any],
                        hb: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """EC2再起動の安全性 — サーバーが実測できない項目はunknown(捏造しない)。
    OpenD autostartは提案のみ・未検証のため、確認まで再起動は非推奨。"""
    hb = hb or {}
    opend_auto = hb.get("opendAutostart")
    bridge_auto = hb.get("bridgeAutostart")
    opend_auto = bool(opend_auto) if isinstance(opend_auto, bool) else "unknown"
    bridge_auto = bool(bridge_auto) if isinstance(bridge_auto, bool) else "unknown"
    safe = True if opend_auto is True and bridge_auto is True else \
        ("unknown" if "unknown" in (opend_auto, bridge_auto) else False)
    return {
        "systemRestartRequired": hb.get("systemRestartRequired")
        if isinstance(hb.get("systemRestartRequired"), bool) else "unknown",
        "opendAutostartConfigured": opend_auto,
        "bridgeAutostartConfigured": bridge_auto,
        "rebootSafe": safe,
        "ownerReadableRiskJa": (
            "再起動可(自動復旧が両方確認済み)。念のため再起動後チェックリストを実施。"
            if safe is True else
            "EC2再起動はまだ推奨しません。OpenD自動復旧を確認してから実施してください"
            "(OpenDのsystemd化は提案のみで未検証。再起動するとOpenDが手動ログイン待ちになり、"
            "USリアルタイムが停止する可能性があります)。"),
        "nextStepJa": ("bridge/README.md の再起動ランブック(v12.0.2)に従い、"
                       "①OpenD自動起動+自動ログインの検証 ②検証後に計画再起動 ③再起動後チェック。"),
    }


def public_status(console: Dict[str, Any], *, now_iso: str) -> Dict[str, Any]:
    """PUBLIC redacted summary — counts/buckets only."""
    by = lambda arr, key: {v: sum(1 for x in arr if x[key] == v)
                           for v in sorted({x[key] for x in arr})}
    hb = console.get("bridgeHealth", {}).get("heartbeatAgeSec")
    return {
        "schemaVersion": "data-quality-status-v1", "asOf": now_iso,
        "featureEnabled": True,
        "overallStatus": console["overallStatus"],
        "sourceCountByStatus": by(console["sourceHealth"], "status") if console["sourceHealth"] else {},
        "engineCountByStatus": by(console["engineHealth"], "status") if console["engineHealth"] else {},
        "heartbeatBucket": freshness_bucket(hb, "realtime") if hb is not None else "unknown",
        "expectedDisabledCount": len(console.get("expectedDisabled") or []),
        "storageMode": "public_redacted",
        "publicLeakSafe": console["publicLeakSafe"],
        "noteJa": "件数とバケットのみ。詳細はData Qualityページ(それでも秘密・保有は含まれない)。",
        "complianceNote": COMPLIANCE,
    }
