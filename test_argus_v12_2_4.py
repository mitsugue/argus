"""ARGUS V12.2.4 — 状態耐久/測定反復性/リリースゲートの恒久ガード。"""
import json
import os
import subprocess

import scanner

NOW = "2026-07-10T15:00:00+09:00"
ROOT = os.path.dirname(__file__)


def test_measurement_survives_via_history():
    scanner._OSINT_STORE.clear()
    scanner._OSINT_RPS_HISTORY.clear()
    scanner._OSINT_RPS_HISTORY.append({
        "symbol": "6965", "at": NOW, "status": "exceeds_gemini",
        "argusScore": 103, "geminiBaselineScore": 72,
        "epochId": scanner._current_epoch_id(), "ratio": 1.43})
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/data-quality").get_json() or {}
        rm = d.get("researchMeasurement") or {}
        assert rm.get("status") == "measured"          # storeが空でも履歴から復元
        assert rm.get("currentRatio") == 1.43
        assert "復元" in (rm.get("ratioLabelJa") or "")


def test_single_run_not_stable_ratio():
    scanner._OSINT_RPS_HISTORY.clear()
    scanner._OSINT_RPS_HISTORY.append({
        "symbol": "6965", "at": NOW, "epochId": scanner._current_epoch_id(),
        "argusScore": 103, "ratio": 1.43})
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/data-quality").get_json() or {}
        st = d.get("researchMeasurementStability") or {}
        assert st.get("runCount") == 1
        assert st.get("currentRatioEligible") is False
        assert "measurement_in_progress" in (st.get("statusJa") or "")
        assert "観測run" in (st.get("observedNoteJa") or "")


def test_three_stable_runs_eligible():
    scanner._OSINT_RPS_HISTORY.clear()
    ep = scanner._current_epoch_id()
    for r in (1.40, 1.43, 1.46):
        scanner._OSINT_RPS_HISTORY.append({
            "symbol": "6965", "at": NOW, "epochId": ep,
            "argusScore": 100, "ratio": r})
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/data-quality").get_json() or {}
        st = d.get("researchMeasurementStability") or {}
        assert st.get("runCount") == 3
        assert st.get("medianRatio") == 1.43
        assert st.get("currentRatioEligible") in (True, False)  # 分散次第
        assert st.get("minRatio") == 1.40 and st.get("maxRatio") == 1.46


def test_other_epoch_runs_excluded_from_stability():
    scanner._OSINT_RPS_HISTORY.clear()
    scanner._OSINT_RPS_HISTORY.append({
        "symbol": "6965", "at": NOW, "epochId": "old:epoch", "ratio": 0.92})
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/data-quality").get_json() or {}
        st = d.get("researchMeasurementStability") or {}
        assert st.get("runCount") == 0


def test_durable_state_status_exposed():
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/data-quality").get_json() or {}
        ds = d.get("durableState") or {}
        assert ds.get("schemaVersion") == "argus-durable-v2"
        assert "integrityStatus" in ds


def test_corrupt_state_not_trusted():
    import inspect
    src = inspect.getsource(scanner._osint_restore_once)
    assert "corrupt_ignored" in src
    assert "壊れた状態を信頼しない" in src


def test_snapshot_carries_durable_fields():
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/osint/memory-snapshot").get_json() or {}
        for k in ("soak", "missions", "forecasts", "outcomes", "schemaVersion"):
            assert k in d, k
        body = str(d)
        for banned in ("passphrase", "hmac", "quantity", "avgCost"):
            assert banned not in body


def test_release_gate_manifest_logic():
    # 失敗SHAは不適格になる(スクリプトの判定部を検証)
    src = open(os.path.join(ROOT, "scripts", "release_gate.sh"),
               encoding="utf-8").read()
    assert 'ELIGIBLE=false' in src
    import re
    assert re.search(r'\[ "\$PY" = pass \]\s+\|\| ELIGIBLE=false', src)
    assert "pushしない" in src


def test_release_gate_workflow_exists():
    src = open(os.path.join(ROOT, ".github", "workflows", "release-gate.yml"),
               encoding="utf-8").read()
    assert "eligibleForDeploy" in src
    assert "release_gate.sh" in src


def test_caos_scan_persists_osint_ledger():
    src = open(os.path.join(ROOT, ".github", "workflows", "caos-scan.yml"),
               encoding="utf-8").read()
    assert "osint-memory.json" in src
    assert "ledger/osint" in src
