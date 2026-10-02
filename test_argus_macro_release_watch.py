from datetime import datetime, timedelta, timezone

import argus_macro_release_watch as watch

NFP = {"id": "us-nfp-2026-10-02", "eventTimeUtc": "2026-10-02T12:30:00Z"}
AT = datetime(2026, 10, 2, 12, 30, tzinfo=timezone.utc)


def test_refresh_runs_inside_the_release_window_only():
    assert watch.due_event([NFP], AT + timedelta(minutes=1), None) is None          # too early
    assert watch.due_event([NFP], AT + timedelta(minutes=2), None) == NFP["id"]
    assert watch.due_event([NFP], AT + timedelta(minutes=44), None) == NFP["id"]
    assert watch.due_event([NFP], AT + timedelta(minutes=46), None) is None         # window over
    assert watch.due_event([{"id": "no-time", "eventTimeUtc": None}], AT, None) is None


def test_refresh_is_spaced_and_failures_stay_visible(monkeypatch):
    monkeypatch.setattr(watch, "_state", {"thread": None, "lastRefreshAt": None, "lastEventId": None,
                                          "lastError": None, "refreshCount": 0})
    calls = []
    assert watch.tick(lambda: [NFP], lambda: calls.append(1), now=AT + timedelta(minutes=3)) == NFP["id"]
    assert watch.tick(lambda: [NFP], lambda: calls.append(1), now=AT + timedelta(minutes=4)) is None   # spaced
    assert watch.tick(lambda: [NFP], lambda: calls.append(1), now=AT + timedelta(minutes=7)) == NFP["id"]
    assert len(calls) == 2 and watch.status()["refreshCount"] == 2

    def broken():
        raise TimeoutError("provider")
    assert watch.tick(lambda: [NFP], broken, now=AT + timedelta(minutes=11)) is None
    assert watch.status()["lastError"] == "TimeoutError"
