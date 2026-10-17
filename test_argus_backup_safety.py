"""V11.16.0 Backup Safety — pure-module tests (calm wording, no fabrication)."""
import json

import argus_backup_safety as bs

NOW = "2026-07-06T09:00:00+09:00"


def _c(**kw):
    base = {"hasPrivateData": True, "vaultConfigured": True, "vaultSyncAgeDays": 0.5,
            "snapshotAgeDays": 0.5, "exportAgeDays": 5, "restoreVerified": True,
            "conflictStatus": "clean",
            "categoriesPresent": ["positions", "snapshots", "decisions"]}
    base.update(kw)
    return bs.classify(base, NOW)


# ── protection levels ───────────────────────────────────────────────────────
def test_protected():
    r = _c()
    assert r["protectionLevel"] == "protected"
    assert "保護済み" in r["ownerReadableStatusJa"]
    assert r["storageMode"] == "encrypted_vault_plus_export"
    assert r["riskFlags"] == []


def test_protected_via_drill_without_recent_export():
    r = _c(exportAgeDays=None, restoreVerified=True)
    assert r["protectionLevel"] == "protected"          # drill substitutes export
    assert "no_export_backup" in r["riskFlags"]         # still nudges export


def test_partially_protected_vault_but_no_export_or_drill():
    r = _c(exportAgeDays=None, restoreVerified=False)
    assert r["protectionLevel"] == "partially_protected"
    assert "一部保護" in r["ownerReadableStatusJa"]
    assert "restore_not_verified" in r["riskFlags"]


def test_partially_protected_export_only_no_vault():
    r = _c(vaultConfigured=False, exportAgeDays=3, restoreVerified=False)
    assert r["protectionLevel"] == "partially_protected"
    assert "暗号化バックアップ(端末間同期)が未設定" in r["ownerReadableStatusJa"]


def test_unprotected_local_only_private_data():
    r = _c(vaultConfigured=False, exportAgeDays=None, restoreVerified=False,
           vaultSyncAgeDays=None, snapshotAgeDays=None)
    assert r["protectionLevel"] == "unprotected"
    assert r["storageMode"] == "local_only"
    assert "local_only_with_private_data" in r["riskFlags"]
    assert "未保護" in r["ownerReadableStatusJa"]
    assert "端末紛失" in r["ownerReadableRiskJa"]
    # calm vocabulary only — no catastrophic words
    assert "全滅" not in r["ownerReadableRiskJa"] and "破滅" not in r["ownerReadableRiskJa"]


def test_no_private_data_is_honest_unknown():
    r = _c(hasPrivateData=False)
    assert r["protectionLevel"] == "unknown"
    assert "まだ端末にありません" in r["ownerReadableStatusJa"]


def test_stale_sync_and_missing_snapshot_flags():
    r = _c(vaultSyncAgeDays=7, snapshotAgeDays=10)
    assert "vault_sync_stale" in r["riskFlags"]
    assert "no_snapshot" in r["riskFlags"]
    assert r["protectionLevel"] == "partially_protected"


def test_conflict_blocks_protected():
    r = _c(conflictStatus="conflict")
    assert r["protectionLevel"] != "protected"
    assert "conflict_unresolved" in r["riskFlags"]


def test_unknown_sync_is_not_fabricated():
    r = _c(vaultSyncAgeDays=None)
    assert "vault_sync_stale" in r["riskFlags"]         # unknown treated as stale
    assert r["vaultSyncAgeDays"] is None                # never invented


# ── recovery drill ──────────────────────────────────────────────────────────
def test_drill_pass_and_fail():
    ok = bs.evaluate_drill({"positions": 5, "snapshots": 3}, {"positions": 5, "snapshots": 3}, NOW)
    assert ok["status"] == "passed" and ok["restorePreviewOnly"] is True
    assert ok["destructiveRestorePerformed"] is False
    assert "既存データは変更していません" in ok["resultJa"]
    valid, errs = bs.validate_drill(ok)
    assert valid, errs
    bad = bs.evaluate_drill({"positions": 5}, {"positions": 3}, NOW)
    assert bad["status"] == "failed" and "positions" in bad["resultJa"]


def test_drill_never_destructive():
    d = bs.evaluate_drill({"positions": 1}, {"positions": 1}, NOW)
    d["destructiveRestorePerformed"] = True
    valid, errs = bs.validate_drill(d)
    assert not valid and any("non-destructive" in e for e in errs)


# ── privacy ─────────────────────────────────────────────────────────────────
def test_outputs_never_contain_secret_substrings():
    blob = json.dumps([_c(), _c(vaultConfigured=False),
                       bs.evaluate_drill({"positions": 1}, {"positions": 1}, NOW),
                       bs.public_status(now_iso=NOW)], ensure_ascii=False)
    for banned in bs.FORBIDDEN_SUBSTRINGS:
        assert banned not in blob, banned
    for banned in ("quantity", "averageCost", "ownerActionNote"):
        assert banned not in blob, banned


def test_public_status_architecture_only():
    st = bs.public_status(now_iso=NOW)
    assert st["architecture"]["serverKnowsDeviceProtectionState"] is False
    assert st["architecture"]["vaultPayloadVisibleToServer"] is False
    assert st["storageMode"] == "redacted"
    assert "パスフレーズの有無" in st["noteJa"]


def test_pure_no_network():
    src = open("argus_backup_safety.py", encoding="utf-8").read()
    for banned_import in ("import requests", "import urllib", "import socket"):
        assert banned_import not in src, banned_import
