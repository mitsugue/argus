"""ARGUS V11.16.0 — Backup Safety / Vault Guard + Recovery Drill (pure).

保有・判断記録・通知・学習履歴が端末に貯まるほど「消えたら困る」が重くなる。
この層は既存の暗号化vault設計を置き換えず、**保護状態を見える化**し、安全な
復元ドリル(非破壊)で「戻せること」を確認済みにする。

HARD RULES:
  - 穏当な語彙のみ: 保護済み/一部保護/未保護/復元未確認(破滅的表現禁止)。
  - 分からないものは unknown と言う(同期状態を捏造しない)。
  - パスフレーズ・暗号ペイロード・トークン類は絶対に出力に含めない。
  - 復元ドリルは既定で非破壊(preview照合のみ)。破壊的restoreは行わない。
  - サーバーは端末の保護状態を知らない — 公開statusはアーキテクチャ事実のみ。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

SCHEMA_VERSION = "backup-safety-v1"

STORAGE_MODES = ("local_only", "encrypted_vault", "encrypted_vault_plus_export",
                 "unprotected", "unknown")
PROTECTION_LEVELS = ("protected", "partially_protected", "unprotected",
                     "needs_attention", "unknown")
CONFLICTS = ("clean", "local_newer", "vault_newer", "conflict", "unknown")
DRILL_STATUSES = ("not_started", "in_progress", "passed", "failed", "skipped")
DRILL_TYPES = ("export_import_validation", "vault_restore_validation",
               "backup_file_validation", "unknown")
DATA_CATEGORIES = ("positions", "snapshots", "decisions", "notifications",
                   "learning", "ownerAnnotations")
RISK_FLAGS = ("passphrase_not_set", "vault_not_configured", "vault_sync_stale",
              "no_export_backup", "no_snapshot", "restore_not_verified",
              "conflict_unresolved", "private_browsing_possible",
              "local_only_with_private_data", "unknown")

LEVEL_JA = {"protected": "保護済み", "partially_protected": "一部保護",
            "unprotected": "未保護", "needs_attention": "要確認",
            "unknown": "判定保留"}

# forbidden anywhere in outputs (belt & braces — tests scan for these)
# NOTE: the spec-mandated risk flag "passphrase_not_set" is a STATE NAME, not
# a secret — so we ban value-bearing patterns, not the word itself.
FORBIDDEN_SUBSTRINGS = ("vaultPass", "argus.vaultPass", "ct\":", "HMAC", "login_pwd",
                        "X-ARGUS-ADMIN-TOKEN", "passphrase=", "passphrase\":")


def classify(inputs: Dict[str, Any], now_iso: str) -> Dict[str, Any]:
    """inputs (device-local facts, caller-supplied; None=unknown, never guessed):
      hasPrivateData(bool), vaultConfigured(bool), vaultSyncAgeDays(float|None),
      snapshotAgeDays, exportAgeDays, importAgeDays, restoreVerified(bool),
      lastDrillAt(iso|None), conflictStatus(str|None), deviceLabel,
      categoriesPresent[list], categoriesInVault(bool|None)
    """
    has_data = bool(inputs.get("hasPrivateData"))
    vault = bool(inputs.get("vaultConfigured"))
    sync_age = inputs.get("vaultSyncAgeDays")
    snap_age = inputs.get("snapshotAgeDays")
    exp_age = inputs.get("exportAgeDays")
    verified = bool(inputs.get("restoreVerified"))
    conflict = inputs.get("conflictStatus") or "unknown"

    risks: List[str] = []
    if not vault:
        risks += ["vault_not_configured", "passphrase_not_set"]
    if vault and (sync_age is None or sync_age > 2):
        risks.append("vault_sync_stale")
    if exp_age is None or exp_age > 30:
        risks.append("no_export_backup")
    if has_data and (snap_age is None or snap_age > 3):
        risks.append("no_snapshot")
    if not verified:
        risks.append("restore_not_verified")
    if conflict == "conflict":
        risks.append("conflict_unresolved")
    if has_data and not vault:
        risks.append("local_only_with_private_data")

    if not has_data:
        level = "unknown"
        status_ja = "保護対象の個人データはまだ端末にありません(保有数量を入力すると保護状態を判定します)。"
    elif vault and (sync_age is not None and sync_age <= 2) \
            and (snap_age is not None and snap_age <= 3) \
            and conflict != "conflict" \
            and ((exp_age is not None and exp_age <= 30) or verified):
        level = "protected"
        status_ja = "バックアップ保護済み：暗号化バックアップが最近同期され、スナップショットも最新です。"
    elif vault:
        level = "partially_protected"
        missing = ("復元確認またはJSONエクスポート" if "no_export_backup" in risks and not verified
                   else "スナップショット" if "no_snapshot" in risks
                   else "同期の更新")
        status_ja = f"一部保護：暗号化バックアップは有効ですが、{missing}がまだです。"
    elif exp_age is not None and exp_age <= 30:
        level = "partially_protected"
        status_ja = "一部保護：JSONエクスポートはありますが、暗号化バックアップ(端末間同期)が未設定です。"
    else:
        level = "unprotected"
        status_ja = "バックアップ未保護：保有データはこの端末内にのみあります。暗号化バックアップを有効化してください。"

    storage = ("unknown" if not has_data else
               "encrypted_vault_plus_export" if vault and exp_age is not None and exp_age <= 30 else
               "encrypted_vault" if vault else
               "local_only")

    risk_ja = ("保有・判断記録・通知・学習履歴がこの端末だけにあり、サイトデータ削除・"
               "ブラウザリセット・PWA削除・端末紛失で失われます。"
               if level == "unprotected" else
               "復元できることを一度も確認していません。復元ドリル(非破壊)の実行を推奨します。"
               if verified is False and level != "unknown" else "")
    next_ja = ("Guideの「バックアップと同期」でパスフレーズを設定(暗号化バックアップ有効化)"
               if not vault and has_data else
               "「復元ドリルを実行」で戻せることを確認(非破壊)" if not verified and has_data else
               "バックアップJSONを書き出してiCloud Drive等に保管" if "no_export_backup" in risks and has_data else
               "現状維持でOK(週1回のエクスポート保管を推奨)")
    lost_ja = ("サイトデータ消去/ブラウザ初期化/PWA削除/プライベートブラウズ/端末変更・紛失で、"
               "端末内のデータ(保有数量・取得単価・判断記録・通知・学習履歴)が消える可能性があります。"
               "アプリを閉じるだけでは通常消えません。")

    return {
        "schemaVersion": SCHEMA_VERSION,
        "id": f"bs-{now_iso[:13]}",
        "asOf": now_iso,
        "storageMode": storage,
        "protectionLevel": level, "protectionLevelJa": LEVEL_JA[level],
        "localDataDetected": has_data,
        "vaultConfigured": vault,
        "vaultSyncAgeDays": sync_age,
        "snapshotAgeDays": snap_age,
        "exportAgeDays": exp_age,
        "restoreVerified": verified,
        "lastRecoveryDrillAt": inputs.get("lastDrillAt"),
        "deviceLabel": inputs.get("deviceLabel"),
        "conflictStatus": conflict if conflict in CONFLICTS else "unknown",
        "dataCategoriesProtected": (list(inputs.get("categoriesPresent") or [])
                                    if vault else []),
        "dataCategoriesMissing": ([] if vault else
                                  list(inputs.get("categoriesPresent") or [])),
        "riskFlags": risks[:8],
        "ownerReadableStatusJa": status_ja,
        "ownerReadableRiskJa": risk_ja,
        "nextStepJa": next_ja,
        "whatCanBeLostJa": lost_ja,
        "privacyNoteJa": "この判定は端末内で行われ、保護状態の詳細・パスフレーズ・"
                         "暗号ペイロードがサーバーへ送られることはない。",
    }


def validate_drill(d: Dict[str, Any]) -> Tuple[bool, List[str]]:
    errs: List[str] = []
    if d.get("status") not in DRILL_STATUSES:
        errs.append("status invalid")
    if d.get("drillType") not in DRILL_TYPES:
        errs.append("drillType invalid")
    if d.get("destructiveRestorePerformed"):
        errs.append("drill must be non-destructive")   # hard rule
    if d.get("status") == "passed" and not d.get("restorePreviewOnly"):
        errs.append("passed drill must be preview-only")
    return (not errs), errs


def evaluate_drill(expected: Dict[str, int], previewed: Dict[str, int],
                   now_iso: str) -> Dict[str, Any]:
    """Compare category counts (export vs re-import preview). Non-destructive."""
    mismatches = [k for k in expected
                  if previewed.get(k, -1) != expected.get(k, -2)]
    ok = not mismatches
    return {
        "schemaVersion": "recovery-drill-v1",
        "id": f"rd-{now_iso[:16]}",
        "createdAt": now_iso, "completedAt": now_iso,
        "status": "passed" if ok else "failed",
        "drillType": "export_import_validation",
        "backupFileMetadata": {"categories": sorted(expected.keys())},
        "validatedCategories": [k for k in expected if k not in mismatches],
        "restorePreviewOnly": True,
        "destructiveRestorePerformed": False,
        "resultJa": ("復元ドリル成功：書き出したバックアップを読み戻し、全カテゴリの件数が"
                     "一致しました(既存データは変更していません)。" if ok else
                     f"復元ドリル不一致：{'/'.join(mismatches)} の件数が一致しません。"
                     "エクスポートを取り直して再実行してください。"),
        "nextStepJa": ("バックアップJSONをiCloud Drive等の安全な場所に保管" if ok else
                       "再エクスポート後にもう一度ドリルを実行"),
    }


def public_status(*, now_iso: str) -> Dict[str, Any]:
    """PUBLIC — architecture facts ONLY. The server does not know (and must not
    know) the device's protection state, passphrase presence, or payloads."""
    return {
        "schemaVersion": "backup-safety-status-v1", "asOf": now_iso,
        "featureEnabled": True,
        "architecture": {
            "privateData": "device_local_plus_client_encrypted_vault",
            "vaultPayloadVisibleToServer": False,
            "serverKnowsDeviceProtectionState": False,
            "recoveryDrill": "non_destructive_preview_only",
        },
        "storageMode": "redacted",              # device-side detail stays on device
        "publicLeakSafe": True,
        "lastCheckedAt": now_iso,
        "noteJa": "保護状態の判定・復元ドリルは端末内で完結する。サーバーは"
                  "パスフレーズの有無・保護状態・バックアップ内容を一切知らない。",
    }
