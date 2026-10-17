"""Restart, failed writes and concurrent delivery use synthetic forecasts only."""
import copy
from datetime import datetime
import json
import threading

import pytest

import argus_future_map as forecast
import argus_future_map_cache as cache
import scanner
from test_argus_future_map import DOC, _fresh_state


@pytest.fixture
def reader(monkeypatch, tmp_path):
    version = {"sha": "synthetic-1", "doc": copy.deepcopy(DOC)}
    clock = {"now": "2026-10-05T15:01:00Z"}
    monkeypatch.setattr(scanner, "_FUTURE_MAP_LOCK", threading.RLock())
    monkeypatch.setattr(scanner, "_ai_now_iso", lambda: clock["now"])
    monkeypatch.setattr(scanner, "_ARGUS_ADMIN_TOKEN", "synthetic-test-token")
    _fresh_state(monkeypatch, tmp_path, version)

    def restart():
        _fresh_state(monkeypatch, tmp_path, version)
        scanner._future_map_load_saved()

    def tick(stamp):
        clock["now"] = stamp
        return scanner._future_map_fallback_tick(datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(scanner.TZ_JST))

    return version, clock, restart, tick, tmp_path / "future_map.json"


def test_notification_survives_restart_and_suppresses_only_same_day_fallback(reader):
    version, clock, restart, tick, path = reader
    assert scanner._future_map_refresh(trigger="notification") is True
    restart()
    assert tick("2026-10-05T21:00:00Z") == "skipped_already_read"
    assert version["reads"] == 1
    restart()
    assert tick("2026-10-05T21:30:00Z") is None
    assert version["reads"] == 1
    # The same receipt cannot suppress tomorrow's read.
    assert tick("2026-10-06T21:00:00Z") == "read"
    assert version["reads"] == 2
    restart()
    assert tick("2026-10-06T22:00:00Z") is None
    shown = scanner.app.test_client().get("/api/argus/future-map").get_json()
    assert cache.RECEIPT_KEY not in json.dumps(shown)
    assert shown["fallback"] == {"day": "2026-10-07", "decision": "read"}
    assert shown["lastReadOkAt"] == clock["now"].replace("22:00", "21:00")
    assert path.stat().st_mode & 0o777 == 0o600


def test_unchanged_forecast_advances_read_clock_but_not_change_clock(reader):
    version, clock, restart, tick, path = reader
    assert scanner._future_map_refresh(trigger="notification")
    changed = scanner._FUTURE_MAP["lastChangedAt"]
    assert tick("2026-10-05T21:00:00Z") == "skipped_already_read"
    clock["now"] = "2026-10-06T15:01:00Z"
    assert scanner._future_map_refresh(trigger="notification")
    restart()  # The previous day's skip is valid alongside the newer read.
    assert scanner._FUTURE_MAP["lastReadOkAt"] == clock["now"]
    assert scanner._FUTURE_MAP["lastChangedAt"] == changed
    assert tick("2026-10-06T21:00:00Z") == "skipped_already_read"
    assert version["reads"] == 2


def test_read_crossing_midnight_records_completion_not_start(reader, monkeypatch):
    version, clock, restart, tick, path = reader
    clock["now"] = "2026-10-05T14:59:59Z"

    class Remote:
        def get(self, path):
            clock["now"] = "2026-10-05T15:00:01Z"
            return json.dumps(DOC).encode(), "synthetic-1"

    monkeypatch.setattr(scanner, "_level_map_remote", lambda: Remote())
    assert scanner._future_map_refresh(trigger="notification")
    assert scanner._FUTURE_MAP["lastAttemptAt"] == "2026-10-05T14:59:59Z"
    restart()
    assert scanner._FUTURE_MAP["lastReadOkAt"] == "2026-10-05T15:00:01Z"
    assert tick("2026-10-05T21:00:00Z") == "skipped_already_read"


def test_legacy_cache_keeps_forecast_without_inventing_a_read(reader):
    version, clock, restart, tick, path = reader
    public = forecast.validate(DOC)
    public["remoteSha"] = version["sha"]
    path.write_text(json.dumps(public))
    restart()
    assert scanner._FUTURE_MAP["public"] == public
    assert scanner._FUTURE_MAP["lastReadOkAt"] is None
    assert tick("2026-10-05T21:00:00Z") == "read"
    assert version["reads"] == 1


@pytest.mark.parametrize("damage", ["naive", "future", "wrong_document", "bad_day"])
def test_invalid_receipt_preserves_forecast_without_suppressing_read(reader, damage):
    version, clock, restart, tick, path = reader
    assert scanner._future_map_refresh(trigger="notification")
    saved = json.loads(path.read_text())
    receipt = saved[cache.RECEIPT_KEY]
    if damage == "naive":
        receipt["lastReadOkAt"] = "2026-10-06T00:01:00"
    elif damage == "future":
        receipt["lastReadOkAt"] = "2026-10-07T00:01:00+09:00"
    elif damage == "wrong_document":
        saved["status"]["position"] = "下落局面"
    else:
        receipt["fallback"] = {"day": "2026-10-07", "decision": "skipped_already_read"}
    path.write_text(json.dumps(saved))
    restart()
    assert scanner._FUTURE_MAP["public"]["rows"]
    assert scanner._FUTURE_MAP["lastReadOkAt"] is None
    assert tick("2026-10-05T21:00:00Z") == "read"
    assert version["reads"] == 2


def test_failed_save_and_bad_remote_keep_last_good_forecast_and_receipt(reader, monkeypatch):
    version, clock, restart, tick, path = reader
    assert scanner._future_map_refresh(trigger="notification")
    original = path.read_bytes()
    old_public = copy.deepcopy(scanner._FUTURE_MAP["public"])
    old_read = scanner._FUTURE_MAP["lastReadOkAt"]
    version.update(sha="synthetic-2", doc={**DOC, "status": {**DOC["status"], "position": "下落局面"}})
    clock["now"] = "2026-10-05T15:02:00Z"

    def fail(*args, **kwargs):
        raise OSError("synthetic-private-message")

    monkeypatch.setattr(cache.os, "replace", fail)
    client = scanner.app.test_client()
    response = client.post("/api/argus/institutional-intelligence/collect", json={"only": "future_map"},
                           headers={"X-ARGUS-ADMIN-TOKEN": "synthetic-test-token"})
    assert response.status_code == 502 and response.get_json()["ok"] is False
    assert scanner._FUTURE_MAP["public"] == old_public
    assert scanner._FUTURE_MAP["lastReadOkAt"] == old_read
    assert path.read_bytes() == original and not list(path.parent.glob(".future-map-*"))
    assert "synthetic-private-message" not in response.get_data(as_text=True)
    version.update(sha="bad-remote", doc={**DOC, "schema": "invalid"})
    assert scanner._future_map_refresh() is False
    assert scanner._FUTURE_MAP["public"] == old_public and path.read_bytes() == original


def test_busy_reader_never_acknowledges_cached_forecast(reader, monkeypatch):
    version, clock, restart, tick, path = reader
    assert scanner._future_map_refresh(trigger="notification")
    before = path.read_bytes()

    class Busy:
        def acquire(self, **kwargs):
            return False

        def release(self):
            pytest.fail("unacquired lock released")

    monkeypatch.setattr(scanner, "_FUTURE_MAP_LOCK", Busy())
    response = scanner.app.test_client().post("/api/argus/institutional-intelligence/collect",
        json={"only": "future_map"}, headers={"X-ARGUS-ADMIN-TOKEN": "synthetic-test-token"})
    assert response.status_code == 502 and response.get_json()["ok"] is False
    assert tick("2026-10-05T21:00:00Z") is None
    assert version["reads"] == 1 and path.read_bytes() == before


@pytest.mark.parametrize("stamp", ["2026-10-06T22:00:00Z", "2026-10-06T00:01:00"])
def test_bad_in_memory_clock_cannot_skip_fallback(reader, stamp):
    version, clock, restart, tick, path = reader
    assert scanner._future_map_refresh()
    scanner._FUTURE_MAP["lastReadOkAt"] = stamp
    assert tick("2026-10-05T21:00:00Z") == "read"
    assert version["reads"] == 2


def test_local_cache_limits_and_atomic_replacement_preserve_existing_file(tmp_path, monkeypatch):
    path = tmp_path / "future_map.json"
    public = forecast.validate(DOC)
    kwargs = dict(last_read_ok_at="2026-10-05T15:01:00Z", last_changed_at="2026-10-05T15:01:00Z",
                  last_trigger="notification", fallback=None)
    cache.store(path, public, **kwargs)
    original = path.read_bytes()
    with pytest.raises(ValueError):
        cache.store(path, {**public, "extra": "x" * cache.MAX_BYTES}, **kwargs)
    assert path.read_bytes() == original
    link = tmp_path / "link.json"
    link.symlink_to(path)
    with pytest.raises(ValueError):
        cache.store(link, public, **kwargs)
    with pytest.raises(ValueError):
        cache.load(link, now_iso="2026-10-05T15:02:00Z")
    with pytest.raises(ValueError):
        cache.store(path, {**public, cache.RECEIPT_KEY: {}}, **kwargs)
    path.write_bytes(b"x" * (cache.MAX_BYTES + 1))
    with pytest.raises(ValueError):
        cache.load(path, now_iso="2026-10-05T15:02:00Z")


def test_notification_workflow_never_prints_authenticated_response():
    from pathlib import Path
    source = Path(".github/workflows/caos-scan.yml").read_text()
    job = source.split("\n  future-map:\n", 1)[1].split("\n  result:\n", 1)[0]
    assert 'echo "future-map attempt=${attempt}"' in job
    assert '${body}' not in job and 'echo "$body"' not in job


def test_concurrent_read_does_not_overwrite_or_duplicate_receipt(reader, monkeypatch):
    version, clock, restart, tick, path = reader
    assert scanner._future_map_refresh(trigger="notification")
    entered, finish = threading.Event(), threading.Event()
    result = []

    class SlowRemote:
        def get(self, path):
            version["reads"] += 1
            entered.set()
            assert finish.wait(2)
            return json.dumps(DOC).encode(), version["sha"]

    monkeypatch.setattr(scanner, "_level_map_remote", lambda: SlowRemote())
    clock["now"] = "2026-10-05T21:00:00Z"
    worker = threading.Thread(target=lambda: result.append(scanner._future_map_refresh(trigger="notification")))
    worker.start()
    try:
        assert entered.wait(2)
        assert scanner._future_map_refresh(wait_seconds=0.01, trigger="notification") is False
        assert scanner._future_map_fallback_tick(datetime.fromisoformat("2026-10-06T06:00:00+09:00")) is None
        assert scanner._FUTURE_MAP_FALLBACK["lastDay"] is None
    finally:
        finish.set()
        worker.join(2)
    assert result == [True] and version["reads"] == 2
    restart()
    assert tick("2026-10-05T21:01:00Z") == "skipped_already_read"
    assert version["reads"] == 2
