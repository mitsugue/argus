"""Future lines (2026-10-19): pre-recorded paths and scores from the private store."""
import copy
import json
from datetime import datetime

import pytest

import argus_future_lines as f
import scanner

LINE = {"rec": "2026-10-16", "recordedAt": "2026-10-19T11:03:57+09:00", "eps": 3826.848,
        "points": [{"kind": "L", "date": "2026-10-30", "price": 61230}, {"kind": "H", "date": "2026-11-10", "price": 65056.4}]}
MEASURE = {"hit": 1, "n": 3, "pending": 2, "randomMean": 0.8}
RECORD = {"records": 1, "strict": MEASURE, "standard": MEASURE, "loose": MEASURE, "timing": MEASURE,
          "reach": {"reach": 1, "stop": 0, "expire": 0, "pending": 0, "n/a": 0}}
DOC = {"schema": "future_lines.v1", "updatedAt": "2026-10-24T09:40:00+09:00", "dataEnd": "2026-10-23",
       "lines": {"commentator": LINE, "machine": LINE, "machine2": LINE},
       "history": {"commentator": [LINE]},
       "wave": {"pub": "2026-10-22", "recordedAt": "2026-10-24T09:40:00+09:00", "dir": "up", "target": 71540,
                "stop": 64946, "result": "pending", "settledBeforeRecord": False},
       "record": {"commentator": RECORD, "machine": RECORD, "wave": {"records": 1, "reach": 0, "n": 0, "pending": 1}},
       "retroRecord": {"commentator": RECORD}}


def test_public_form_keeps_only_numbers_and_dates():
    public = f.validate(DOC)
    assert public["schemaVersion"] == f.PUBLIC_SCHEMA and public["actionAuthority"] is False
    assert public["lines"]["commentator"]["points"][0] == {"kind": "L", "date": "2026-10-30", "price": 61230.0}
    assert public["record"]["machine"]["loose"]["randomMean"] == 0.8


@pytest.mark.parametrize("mutate", [
    lambda d: d.update(note="名前入りの文章"),                                     # 自由な文章の欄は受け付けない
    lambda d: d["lines"].update(other=LINE),                                        # 決まった線だけ
    lambda d: d["lines"]["machine"]["points"][0].update(kind="X"),
    lambda d: d["lines"]["machine"]["points"].reverse(),                             # 日付は先へ進む順
    lambda d: d["lines"]["machine"]["points"][0].update(date="2026-10-16"),          # 収録日より後だけ
    lambda d: d["wave"].update(target=60000),                                        # 上向きなら目標>崩れ
    lambda d: d["record"]["machine"]["loose"].update(hit=4),                          # 当たり<=判定できた数
])
def test_rejects_malformed_documents(mutate):
    doc = copy.deepcopy(DOC)
    mutate(doc)
    with pytest.raises(f.FutureLinesError):
        f.validate(doc)


def _state(monkeypatch, tmp_path, raw=None):
    calls = []

    class Remote:
        def get(self, path):
            calls.append(path)
            return (json.dumps(DOC).encode() if raw is None else raw), "sha-1"

    monkeypatch.setattr(scanner, "_level_map_remote", lambda: Remote())
    monkeypatch.setattr(scanner, "_future_lines_path", lambda: str(tmp_path / "future_lines.json"))
    monkeypatch.setattr(scanner, "_FUTURE_LINES", {"loaded": False, "public": None, "sha": None, "lastAttemptAt": None,
                                                   "lastError": None, "lastReadOkAt": None, "lastDay": None, "retryAt": None})
    return calls


def test_refresh_reads_once_and_the_route_never_fetches(monkeypatch, tmp_path):
    calls = _state(monkeypatch, tmp_path)
    monkeypatch.setattr(scanner, "_nikkei_chart_rows", lambda: [{"date": "2026-10-23", "close": 65000.0}])
    monkeypatch.setattr(scanner, "_level_map_completed_bars", lambda rows, now: rows)
    assert scanner._future_lines_refresh(trigger="test") is True
    assert calls == [f.REMOTE_PATH]
    assert json.loads((tmp_path / "future_lines.json").read_text())["sha"] == "sha-1"
    body = scanner.app.test_client().get("/api/argus/future-lines").get_json()
    assert body["availability"] == "AVAILABLE" and len(calls) == 1
    assert body["lines"]["machine"]["points"][1]["price"] == 65056.4 and body["closes"] == [{"date": "2026-10-23", "close": 65000.0}]


def test_invalid_document_is_reported_and_not_served(monkeypatch, tmp_path):
    _state(monkeypatch, tmp_path, raw=json.dumps({**DOC, "note": "x"}).encode())
    assert scanner._future_lines_refresh() is False
    assert scanner._FUTURE_LINES["lastError"] == "FutureLinesError"
    body = scanner.app.test_client().get("/api/argus/future-lines").get_json()
    assert body["availability"] == "UNAVAILABLE"


def test_daily_tick_reads_once_after_ten_and_retries_hourly(monkeypatch, tmp_path):
    _state(monkeypatch, tmp_path)
    seen = []
    monkeypatch.setattr(scanner, "_future_lines_refresh", lambda trigger="": seen.append(trigger) or False)
    jst = scanner.TZ_JST
    assert scanner._future_lines_tick(datetime(2026, 10, 24, 9, 59, tzinfo=jst)) is None
    assert scanner._future_lines_tick(datetime(2026, 10, 24, 10, 0, tzinfo=jst)) is False
    assert scanner._future_lines_tick(datetime(2026, 10, 24, 10, 30, tzinfo=jst)) is None    # 1時間待つ
    assert scanner._future_lines_tick(datetime(2026, 10, 24, 11, 1, tzinfo=jst)) is False
    assert seen == ["daily", "daily"]
    scanner._FUTURE_LINES.update(lastDay="2026-10-24", retryAt=None)
    assert scanner._future_lines_tick(datetime(2026, 10, 24, 15, 0, tzinfo=jst)) is None      # その日は済み


def test_notification_reads_only_the_future_lines(monkeypatch, tmp_path):
    _state(monkeypatch, tmp_path)
    monkeypatch.setattr(scanner, "_ARGUS_ADMIN_TOKEN", "tok")
    heavy = []
    monkeypatch.setattr(scanner, "_collect_institutional_intel_and_warm", lambda: heavy.append(1) or {})
    r = scanner.app.test_client().post("/api/argus/institutional-intelligence/collect", json={"only": "future_lines"},
                                       headers={"X-ARGUS-ADMIN-TOKEN": "tok"})
    assert r.status_code == 200 and r.get_json()["ok"] is True and not heavy


def test_scheduler_starts_the_daily_read_and_the_route_is_catalogued():
    import argus_route_catalog as cat
    source = open("scanner.py", encoding="utf-8").read()
    assert 'target=_future_lines_tick, daemon=True, name="future-lines-daily"' in source
    assert any(e.route == "/api/argus/future-lines" for e in cat.ROUTE_CATALOG)
