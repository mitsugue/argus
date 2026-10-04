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
    scanner._future_map_refresh()                                     # same sha: nothing rewritten
    assert scanner._FUTURE_MAP["lastChangedAt"] == changed
    assert json.loads((tmp_path / "future_map.json").read_text())["remoteSha"] == "sha-1"
    before = len(calls)
    body = scanner.app.test_client().get("/api/argus/future-map").get_json()
    assert body["availability"] == "AVAILABLE" and "remoteSha" not in body and len(calls) == before
    assert body["status"]["position"] == "天井圏" and body["status"]["nextAlert"]["label"] == "米CPI"
    assert "src_a" not in json.dumps(body)
