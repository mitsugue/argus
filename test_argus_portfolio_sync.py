"""V11.9.0 Portfolio Sync / Snapshot Foundation — pure-module tests."""
import argus_portfolio_sync as ps

NOW = "2026-07-04T12:00:00+00:00"


def _sync_rec(**kw):
    base = {"schemaVersion": ps.SYNC_SCHEMA_VERSION, "portfolioId": "default",
            "positions": [{"symbol": "5803", "market": "JP", "quantity": 100,
                           "averageCost": 5000, "currency": "JPY"}],
            "updatedAt": NOW, "updatedByDevice": "dev-abc", "deviceLabel": "Mac",
            "syncVersion": 1, "localRevision": 3, "cloudRevision": 3,
            "conflictStatus": "clean", "encryptionStatus": "client_encrypted",
            "source": "localStorage"}
    base.update(kw)
    return base


# ── model validation ────────────────────────────────────────────────────────
def test_sync_record_valid():
    ok, errs = ps.validate_sync_record(_sync_rec())
    assert ok, errs


def test_sync_record_rejects_bad_enum_and_shape():
    ok, errs = ps.validate_sync_record(_sync_rec(conflictStatus="whatever"))
    assert not ok and any("conflictStatus" in e for e in errs)
    ok2, errs2 = ps.validate_sync_record(_sync_rec(positions=[{"noSymbol": 1}]))
    assert not ok2 and any("symbol" in e for e in errs2)
    ok3, _ = ps.validate_sync_record(_sync_rec(schemaVersion="v0"))
    assert not ok3


def test_snapshot_validation():
    snap = {"schemaVersion": ps.SNAPSHOT_SCHEMA_VERSION, "snapshotId": "snap-1",
            "asOf": NOW, "createdAt": NOW, "appVersion": "11.9.0",
            "privacyLevel": "local_only"}
    ok, errs = ps.validate_snapshot(snap)
    assert ok, errs
    bad = dict(snap, privacyLevel="public")
    ok2, errs2 = ps.validate_snapshot(bad)
    assert not ok2 and any("privacyLevel" in e for e in errs2)


def test_audit_record_requires_future_placeholders():
    rec = {"schemaVersion": ps.AUDIT_SCHEMA_VERSION, "symbol": "TSLA",
           "decisionContext": "avoid_chase", "ownerAction": None,
           "futureReturn1d": None, "futureReturn3d": None,
           "futureReturn5d": None, "futureReturn20d": None}
    ok, errs = ps.validate_audit_record(rec)
    assert ok, errs
    rec2 = {k: v for k, v in rec.items() if k != "futureReturn20d"}
    ok2, errs2 = ps.validate_audit_record(rec2)
    assert not ok2 and any("futureReturn20d" in e for e in errs2)
    rec3 = dict(rec, decisionContext="buy_now")     # trading verbs are not contexts
    ok3, _ = ps.validate_audit_record(rec3)
    assert not ok3


# ── conflict model — never silently overwrite ──────────────────────────────
def test_conflict_states():
    assert ps.detect_conflict(3, 3, NOW, NOW, cloud_enabled=True) == "clean"
    assert ps.detect_conflict(4, 3, "2026-07-04T12:05:00Z", NOW, cloud_enabled=True) == "local_newer"
    assert ps.detect_conflict(3, 5, NOW, "2026-07-04T12:05:00Z", cloud_enabled=True) == "cloud_newer"
    # both advanced with contradictory timestamps → conflict (manual resolve)
    assert ps.detect_conflict(4, 5, "2026-07-04T12:10:00Z",
                              "2026-07-04T12:00:00Z", cloud_enabled=True) == "conflict"
    # cloud not configured → disabled, regardless of revisions
    assert ps.detect_conflict(9, 0, NOW, None, cloud_enabled=False) == "disabled"


# ── privacy tripwire ────────────────────────────────────────────────────────
def test_contains_sensitive_finds_nested_fields():
    doc = {"a": {"positions": [{"symbol": "X", "quantity": 5}]},
           "b": [{"totalMarketValue": 1}]}
    found = ps.contains_sensitive(doc)
    assert "quantity" in found and "positions" in found and "totalMarketValue" in found


def test_public_sync_status_is_structurally_leak_free():
    doc = ps.public_sync_status(server_sync_enabled=False, now_iso=NOW)
    assert ps.contains_sensitive(doc) == []
    assert doc["storageLayers"]["privateCloud"]["serverPlaintextSync"] == "disabled"
    assert "暗号文のみ" in doc["privacyNoteJa"]


def test_export_manifest_forbids_secrets():
    m = ps.export_manifest("11.9.0", NOW)
    assert "secrets" in m["forbidden"] and "opendCredentials" in m["forbidden"]
    assert "個人投資情報" in m["warningJa"]
    assert ps.contains_sensitive(m) == []       # manifest itself carries no values


def test_no_broker_or_trading_in_module():
    src = open("argus_portfolio_sync.py", encoding="utf-8").read()
    for banned in ("place_order", "order(", "broker_login", "unlock_trade", "trd_env"):
        assert banned not in src, banned
    for banned_import in ("import requests", "import urllib", "import socket"):
        assert banned_import not in src, banned_import
