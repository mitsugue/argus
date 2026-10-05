import copy
import json

import pytest

import argus_future_map as f
import scanner

DOC = {"schema": "future_map.v1", "updatedAt": "2026-10-04T21:00:00+09:00",
       "status": {"position": "天井圏", "nextAlert": {"date": "2026-10-14", "label": "米CPI"},
                  "nextBottom": {"date": "2026-10-30", "label": "10/30ごろ"}},
       "rows": [
           {"id": "a", "periodLabel": "10/1〜10/10", "start": "2026-10-01", "end": "2026-10-10",
            "view": "天井。上がっても7万円前後まで", "reason": None, "alt": None,
            "level": {"low": 69700, "high": 72000}, "tag": "売り時", "agree": 2, "sources": ["src_a", "src_b"],
            "emphasis": False, "changed": None, "result": None},
           {"id": "b", "periodLabel": "12/25前後", "start": "2026-12-21", "end": "2026-12-28",
            "view": "クリスマスが底", "reason": None, "alt": "年末に向けて上がる", "level": None, "tag": "大底",
            "agree": 1, "sources": ["src_a"], "emphasis": True, "changed": None, "result": None},
           {"id": "c", "periodLabel": "9/1〜9/5", "start": "2026-09-01", "end": "2026-09-05",
            "view": "古い行", "reason": None, "alt": None, "level": None, "tag": "―", "agree": 0,
            "sources": [], "emphasis": False, "changed": None, "result": "missed"}],
       "record": {"scored": 1, "reached": 0}}


def test_public_form_drops_the_sources_and_keeps_the_seven_tags():
    public = f.validate(DOC)
    assert "src_a" not in json.dumps(public) and "sources" not in public["rows"][0]
    assert [r["tone"] for r in public["rows"]] == ["grey", "red", "green"]
    assert public["argusValidated"] is False and public["actionAuthority"] is False
    for bad in ({"tag": "買い"}, {"view": "x" * 41}, {"start": "2026-10-11"}, {"agree": -1}, {"result": "maybe"}):
        doc = copy.deepcopy(DOC); doc["rows"][0].update(bad)
        with pytest.raises(f.FutureMapError):
            f.validate(doc)


def test_display_marks_the_current_row_and_drops_rows_two_weeks_past():
    view = f.for_display(f.validate(DOC), "2026-10-04")
    assert [r["id"] for r in view["rows"]] == ["a", "b"]           # 9/5 is more than 14 days past
    assert [r["isNow"] for r in view["rows"]] == [True, False]
    later = f.for_display(f.validate(DOC), "2026-10-20")              # between rows: the next one is "now"
    assert [r["isNow"] for r in later["rows"]] == [False, True] and later["rows"][0]["past"] is True


def test_refresh_reads_the_private_store_once_per_change_and_the_route_never_fetches(monkeypatch, tmp_path):
    calls = []

    class Remote:
        def get(self, path):
            calls.append(path)
            return json.dumps(DOC).encode(), "sha-1"

    monkeypatch.setattr(scanner, "_level_map_remote", lambda: Remote())
    monkeypatch.setattr(scanner, "_future_map_path", lambda: str(tmp_path / "future_map.json"))
    monkeypatch.setattr(scanner, "_FUTURE_MAP", {"loaded": False, "public": None, "sha": None, "lastAttemptAt": None,
                                                 "lastError": None, "lastChangedAt": None})
    scanner._future_map_refresh()
    assert scanner._FUTURE_MAP["public"]["status"]["position"] == "天井圏"
    changed = scanner._FUTURE_MAP["lastChangedAt"]
    scanner._future_map_refresh()                                     # same sha: content-change clock stays fixed
    assert scanner._FUTURE_MAP["lastChangedAt"] == changed
    assert json.loads((tmp_path / "future_map.json").read_text())["remoteSha"] == "sha-1"
    before = len(calls)
    body = scanner.app.test_client().get("/api/argus/future-map").get_json()
    assert body["availability"] == "AVAILABLE" and "remoteSha" not in body and len(calls) == before
    assert body["status"]["position"] == "天井圏" and body["status"]["nextAlert"]["label"] == "米CPI"
    assert "src_a" not in json.dumps(body)


def _fresh_state(monkeypatch, tmp_path, version):
    class Remote:
        def get(self, path):
            assert path == f.REMOTE_PATH
            version["reads"] = version.get("reads", 0) + 1
            return json.dumps(version["doc"]).encode(), version["sha"]

    monkeypatch.setattr(scanner, "_level_map_remote", lambda: Remote())
    monkeypatch.setattr(scanner, "_future_map_path", lambda: str(tmp_path / "future_map.json"))
    monkeypatch.setattr(scanner, "_FUTURE_MAP", {"loaded": False, "public": None, "sha": None, "lastAttemptAt": None,
                                                 "lastError": None, "lastChangedAt": None, "lastReadOkAt": None, "lastTrigger": None})
    monkeypatch.setattr(scanner, "_FUTURE_MAP_FALLBACK", {"lastDay": None, "lastDecision": None, "emptyRetryAt": None})


def test_notification_reads_once_through_the_existing_collection_route(monkeypatch, tmp_path):
    version = {"sha": "sha-1", "doc": DOC}
    _fresh_state(monkeypatch, tmp_path, version)
    monkeypatch.setattr(scanner, "_ARGUS_ADMIN_TOKEN", "tok")
    heavy = []
    monkeypatch.setattr(scanner, "_collect_institutional_intel_and_warm", lambda: heavy.append(1) or {})
    monkeypatch.setattr(scanner, "_intel_collect_tracked", lambda *a, **k: (heavy.append(1) or {}, 200))
    client = scanner.app.test_client()
    url = "/api/argus/institutional-intelligence/collect"
    denied = client.post(url, json={"only": "future_map"})
    assert denied.status_code in (401, 403) and version.get("reads", 0) == 0
    response = client.post(url, json={"only": "future_map"}, headers={"X-ARGUS-ADMIN-TOKEN": "tok"})
    body = response.get_json()
    assert response.status_code == 200 and body["ok"] is True and body["only"] == "future_map"
    assert body["availability"] == "AVAILABLE" and body["sha"] == "sha-1" and body["lastError"] is None
    assert body["lastTrigger"] == "notification" and body["lastReadOkAt"] and body["lastChangedAt"]
    assert version["reads"] == 1 and body["rows"] == 3 and heavy == []         # nothing else of the collection ran
    # The writer stores a new version and notifies again (query form): shown at once.
    version.update(sha="sha-2", doc={**DOC, "status": {**DOC["status"], "position": "下落局面"}})
    body = client.post(url + "?only=future_map", headers={"X-ARGUS-ADMIN-TOKEN": "tok"}).get_json()
    assert body["sha"] == "sha-2" and version["reads"] == 2 and heavy == []
    shown = client.get("/api/argus/future-map").get_json()
    assert shown["status"]["position"] == "下落局面" and version["reads"] == 2   # the public read never fetches
    assert "src_a" not in json.dumps(body) + json.dumps(shown)


def test_a_failed_notification_read_is_reported_as_a_failure(monkeypatch, tmp_path):
    version = {"sha": "sha-1", "doc": {**DOC, "schema": "wrong"}}
    _fresh_state(monkeypatch, tmp_path, version)
    monkeypatch.setattr(scanner, "_ARGUS_ADMIN_TOKEN", "tok")
    response = scanner.app.test_client().post("/api/argus/institutional-intelligence/collect",
                                              json={"only": "future_map"}, headers={"X-ARGUS-ADMIN-TOKEN": "tok"})
    assert response.status_code == 502 and response.get_json()["ok"] is False


def test_fallback_reads_once_at_six_only_when_nothing_was_read_since_midnight(monkeypatch, tmp_path):
    from datetime import datetime
    version = {"sha": "sha-1", "doc": DOC}
    _fresh_state(monkeypatch, tmp_path, version)
    jst = scanner.TZ_JST
    scanner._future_map_refresh()                                    # a version exists (read the day before)
    version["reads"] = 0
    monkeypatch.setattr(scanner, "_ai_now_iso", lambda: "2026-10-05T15:01:00Z")   # 10/6 00:01 JST: notified
    scanner._future_map_refresh()
    assert version["reads"] == 1
    assert scanner._future_map_fallback_tick(jst.localize(datetime(2026, 10, 6, 5, 59))) is None
    assert scanner._future_map_fallback_tick(jst.localize(datetime(2026, 10, 6, 6, 0))) == "skipped_already_read"
    assert version["reads"] == 1
    assert scanner._future_map_fallback_tick(jst.localize(datetime(2026, 10, 6, 6, 30))) is None   # once a day
    # Next day: no notification arrived since 00:00 JST, so the fallback reads once.
    assert scanner._future_map_fallback_tick(jst.localize(datetime(2026, 10, 7, 6, 0))) == "read"
    assert version["reads"] == 2
    assert scanner._future_map_fallback_tick(jst.localize(datetime(2026, 10, 7, 9, 0))) is None and version["reads"] == 2


def test_collection_warms_no_longer_read_the_store_and_the_scheduler_runs_the_fallback():
    import inspect
    source = inspect.getsource(scanner)
    warm = source[source.index("        _level_map_warm(nikkei_rows)\n"):][:400]
    assert "_future_map_refresh" not in warm
    assert "_future_map_fallback_tick" in inspect.getsource(scanner.run_scheduler)
    assert "_future_map_refresh" not in inspect.getsource(scanner.run_scheduler)


def test_the_existing_collection_workflow_carries_the_notification():
    src = open(".github/workflows/caos-scan.yml", encoding="utf-8").read()
    job = src.split("\n  future-map:\n", 1)[1].split("\n  result:\n", 1)[0]
    assert "if: github.event_name == 'workflow_dispatch' && inputs.only == 'future_map'" in job
    assert "/api/argus/institutional-intelligence/collect" in job and '{"only":"future_map"}' in job
    assert 'd.get("ok") is True' in job and "exit 1" in job                  # a failed read fails the run
    assert "secrets.ARGUS_ADMIN_TOKEN" in job and "echo \"$ARGUS_ADMIN_TOKEN" not in job
    import os
    assert not os.path.exists(".github/workflows/future-map-refresh.yml")
