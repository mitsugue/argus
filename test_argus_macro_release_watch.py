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


def _fresh(monkeypatch):
    monkeypatch.setattr(watch, "_state", {"thread": None, "lastRefreshAt": None, "lastEventId": None,
                                          "lastError": None, "refreshCount": 0,
                                          "baselines": {}, "windows": {}, "posted": {}, "reactionError": None})


def test_reaction_baseline_windows_and_post_run_once_each_in_order(monkeypatch):
    _fresh(monkeypatch)
    log = []; result_ready = [False]
    cb = dict(baseline=lambda e: log.append(("baseline", e["id"])),
              window=lambda e, n: log.append((n, e["id"])),
              post=lambda e, ask: (log.append(("post" + ask, e["id"])), result_ready[0])[1])
    minutes = [-20, -14, -8, -2, 0, 3, 5, 6, 12, 30, 35, 60, 61, 90, 480, 490, 540]
    for m in minutes:
        if m == 35:
            result_ready[0] = True
        watch.tick(lambda: [NFP], lambda: None, now=AT + timedelta(minutes=m), **cb)
    assert [x for x in log if x[0] == "baseline"] == [("baseline", NFP["id"])] * 3   # -14, -8, -2
    assert [x[0] for x in log if x[0].startswith("+")] == ["+5m", "+30m", "+60m", "+8h"]
    # asked at +5, +6, +12, +30 (result missing), succeeded at +35; again once at +60 and once at +8h
    assert [x[0] for x in log if x[0].startswith("post")] == ["post+5m"] * 5 + ["post+60m", "post+8h"]
    st = watch.status()["reaction"]
    assert st["windows"] == {NFP["id"]: ["+30m", "+5m", "+60m", "+8h"]} and st["posted"] == {NFP["id"]: ["+5m", "+60m", "+8h"]}
    assert st["lastError"] is None


def test_reaction_failures_never_block_the_result_refresh(monkeypatch):
    _fresh(monkeypatch)
    calls = []
    def broken(*a):
        raise OSError("provider")
    assert watch.tick(lambda: [NFP], lambda: calls.append(1), now=AT + timedelta(minutes=5),
                      baseline=broken, window=broken, post=None) == NFP["id"]
    assert calls == [1] and watch.status()["reaction"]["lastError"] == "OSError"
    # The failed window is retried inside its grace period.
    log = []
    watch.tick(lambda: [NFP], lambda: None, now=AT + timedelta(minutes=7), window=lambda e, n: log.append(n))
    assert log == ["+5m"]



def test_delayed_source_price_retries_inside_window_instead_of_claiming_capture_success(monkeypatch):
    _fresh(monkeypatch)
    import argus_macro_release_reaction as reaction
    def capture(event, name):
        return {"schemaVersion": reaction.SCHEMA, "windows": {name: {"comparisonValues": {}}}}
    watch.tick(lambda: [NFP], lambda: None, now=AT + timedelta(minutes=5), window=capture)
    assert NFP["id"] not in watch.status()["reaction"]["windows"]
    assert watch.status()["reaction"]["lastError"] == "ValueError"
    calls = []
    def arrived(event, name):
        calls.append(name)
        return {"schemaVersion": reaction.SCHEMA, "windows": {name: {"comparisonValues": {"ES=F": {"price": 100}}}}}
    watch.tick(lambda: [NFP], lambda: None, now=AT + timedelta(minutes=8), window=arrived)
    watch.tick(lambda: [NFP], lambda: None, now=AT + timedelta(minutes=9), window=arrived)
    assert calls == ["+5m"]
    assert watch.status()["reaction"]["windows"] == {NFP["id"]: ["+5m"]}



def test_unusable_baseline_is_not_counted_as_a_successful_measurement(monkeypatch):
    _fresh(monkeypatch)
    import argus_macro_release_reaction as reaction
    watch.tick(lambda: [NFP], lambda: None, now=AT - timedelta(minutes=2),
               baseline=lambda event: {"schemaVersion": reaction.SCHEMA, "baselineComparisonValues": {}})
    assert watch.status()["reaction"]["baselines"] == 0
    assert watch.status()["reaction"]["lastError"] == "ValueError"
