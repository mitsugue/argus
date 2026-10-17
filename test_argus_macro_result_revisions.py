from copy import deepcopy
import json
import pytest
import argus_macro_event_store as store
import argus_macro_event_analysis as analysis

A = "2026-09-11T12:35:00Z"
B = "2026-09-11T18:35:00Z"

def record(value, at):
    return {"eventId": "cpi-20260911", "eventCode": "CPI", "phase": "post_result",
            "eventDate": "2026-09-11", "eventTimeUtc": "2026-09-11T12:30:00Z",
            "updatedAt": at, "actual": {"available": True, "source": "BLS", "receivedAt": at,
            "releasedAt": None, "metrics": {"headlineCpiMoM": value, "referenceMonth": "2026-08"}},
            "pre": {"generatedAt": "2026-09-11T12:00:00Z", "argusScenarioJa": "条件付き見通し"}}

def test_old_result_and_explanation_survive_revision_roundtrip_without_mutation():
    first = record(0.3, A)
    first["post"] = {"generatedAt": A, "verdict": "miss", "answerCheckJa": "当初の見立ては外れ",
                     "actualRevisionId": store.actual_revision_id(first["actual"])}
    original = deepcopy(first)
    saved = store.merge_record(None, first, now_iso=A)
    revised = store.merge_record(saved, record(0.4, B), now_iso=B)
    assert first == original
    assert revised["actual"]["metrics"]["headlineCpiMoM"] == 0.4
    assert len(revised["resultRevisions"]) == 2
    assert revised["post"]["verdict"] == "not_scoreable"
    assert any(r["analysis"].get("verdict") == "miss" for r in revised["analysisRevisions"])
    back = store.restore_from_snapshot(json.loads(json.dumps(store.serialize_snapshot([revised], as_of=B))))
    assert back[revised["eventId"]] == revised
    assert saved["resultRevisions"][0] in revised["resultRevisions"]

def test_repeated_receipt_does_not_rewrite_original_or_duplicate_revision():
    saved = store.merge_record(None, record(0.3, A), now_iso=A)
    after = store.merge_record(saved, record(0.3, B), now_iso=B)
    assert after["resultRevisions"] == saved["resultRevisions"]
    assert after["actual"]["receivedAt"] == B

def test_restoring_an_older_available_snapshot_cannot_replace_new_result():
    current = store.merge_record(None, record(0.4, B), now_iso=B)
    restored = store.merge_record(current, record(0.3, A), now_iso=B)
    assert restored["actual"]["metrics"]["headlineCpiMoM"] == 0.4
    assert len(restored["resultRevisions"]) == 2

def test_legacy_result_keeps_unknown_receipt_status():
    legacy = record(0.3, A)
    del legacy["actual"]["receivedAt"]
    legacy["actual"]["releasedAt"] = A
    migrated = store.merge_record(None, legacy, now_iso=B)
    revision = migrated["resultRevisions"][0]
    assert revision["receiptStatus"] == "LEGACY_UNVERIFIED"
    assert revision["firstObservedAt"] is None
    assert revision["actual"] == legacy["actual"]

def test_corrupt_revision_is_detected_instead_of_silently_discarded():
    saved = store.merge_record(None, record(0.3, A), now_iso=A)
    saved["resultRevisions"][0]["actual"]["metrics"]["headlineCpiMoM"] = 99
    with pytest.raises(ValueError, match="revision_integrity"):
        store.merge_record(saved, record(0.4, B), now_iso=B)

def test_post_prompt_receives_definition_receipt_and_previous_values():
    actual = {"available": True, "metrics": {"headlineCpiYoY": 3.4},
              "metricDefinitions": {"headlineCpiYoY": {"seasonalAdjustment": "NSA"}},
              "previousMetrics": {"headlineCpiYoY": 3.3}, "receivedAt": A, "releasedAt": None}
    prompt = analysis.build_post_prompt({}, {}, actual)
    assert '"seasonalAdjustment": "NSA"' in prompt and A in prompt
    assert '"previousMetrics"' in prompt
    assert "単一の原因を断定しない" in prompt

def test_collector_revision_preserves_previous_runtime_record(monkeypatch, tmp_path):
    import scanner
    old = record(0.3, A)
    old = store.merge_record(None, old, now_iso=A)
    old["lastResultAttemptAt"] = A
    monkeypatch.setattr(scanner, "_MACRO_ANALYSIS", {old["eventId"]: deepcopy(old)})
    monkeypatch.setattr(scanner, "_macro_analysis_restore_once", lambda: None)
    monkeypatch.setattr(scanner, "_MACRO_ANALYSIS_FILE", str(tmp_path / "macro.json"))
    monkeypatch.setattr(scanner, "_ai_now_iso", lambda: B)
    monkeypatch.setattr(scanner, "_macro_important_events", lambda limit: [old])
    calls = []
    def fetch(event):
        calls.append(event["eventId"])
        return record(0.4, B)["actual"]
    monkeypatch.setattr(scanner, "_macro_result_fetch", fetch)
    assert scanner._refresh_macro_results()["resultsFetched"] == 1
    saved = scanner._MACRO_ANALYSIS[old["eventId"]]
    assert len(saved["resultRevisions"]) == 2
    assert old["resultRevisions"][0] in saved["resultRevisions"]
    disk = json.loads((tmp_path / "macro.json").read_text())
    assert disk["items"][old["eventId"]] == saved
    assert (tmp_path / "macro.json").stat().st_mode & 0o777 == 0o600
    scanner._refresh_macro_results()
    assert len(calls) == 1


def test_concurrent_result_updates_keep_every_observed_revision(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    import scanner
    monkeypatch.setattr(scanner, "_MACRO_ANALYSIS", {})
    records = [record(i / 100, f"2026-09-11T13:{i:02d}:00Z") for i in range(20)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda rec: scanner._macro_merge_record(rec["eventId"], rec, rec["updatedAt"]), records))
    result = scanner._MACRO_ANALYSIS[records[0]["eventId"]]
    assert len(result["resultRevisions"]) == 20
    assert result["actual"]["metrics"]["headlineCpiMoM"] == .19


def test_failed_local_write_preserves_previous_file_and_reports_failure(monkeypatch, tmp_path):
    import scanner
    path = tmp_path / "macro.json"
    path.write_text('{"preserved":true}')
    monkeypatch.setattr(scanner, "_MACRO_ANALYSIS_FILE", str(path))
    monkeypatch.setattr(scanner, "_MACRO_ANALYSIS_STATE", {})
    def fail(*a, **k):
        raise OSError("test_disk_failure")
    monkeypatch.setattr(scanner.argus_persistent_storage, "atomic_write_json", fail)
    assert scanner._macro_analysis_persist() is None
    assert path.read_text() == '{"preserved":true}'
    assert scanner._MACRO_ANALYSIS_STATE["localPersistence"]["status"] == "failed"
