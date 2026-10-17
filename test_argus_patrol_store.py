"""ARGUS V11.5.5 — patrol ledger (pure): record/prune/merge/summarize/health."""
import argus_caos_patrol_store as PL

NOW = "2026-07-03T12:00:00Z"
OLD = "2026-07-02T10:00:00Z"     # 26h ago — outside the 24h window


def _ledger_with_run(**kw):
    lg = PL.new_ledger(NOW)
    args = dict(now_iso=NOW, ok=True, deep_sweeps=1, baseline_checked=True,
                fresh_items=3, new_items=10, source_success=20, source_errors=1,
                active_movers=2)
    args.update(kw)
    return PL.record_run(lg, **args)


def test_record_and_prune_window():
    lg = PL.new_ledger(OLD)
    PL.record_run(lg, now_iso=OLD, ok=True, baseline_checked=True)
    PL.record_run(lg, now_iso=NOW, ok=True, baseline_checked=True)
    assert len(lg["runs"]) == 1                    # 26h-old run pruned
    assert lg["runs"][0]["at"] == NOW


def test_summarize_counts():
    lg = _ledger_with_run()
    PL.record_sweep(lg, now_iso=NOW, symbol="5803", market="JP", kind="deep",
                    status="completed", fresh=2)
    PL.record_sweep(lg, now_iso=NOW, symbol="9984", market="JP", kind="investigate",
                    status="completed", fresh=5)
    s = PL.summarize(lg, NOW)
    assert s["runs24h"] == 1 and s["successfulRuns24h"] == 1
    assert s["deepSweeps24h"] == 2
    assert s["baselineSweeps24h"] == 1
    assert s["freshItems24h"] == 3 + 5             # run fresh + investigate fresh
    assert s["emptyDeepSweepRuns24h"] == 0


def test_empty_deep_sweep_with_movers_counts():
    lg = _ledger_with_run(deep_sweeps=0, active_movers=3)
    s = PL.summarize(lg, NOW)
    assert s["emptyDeepSweepRuns24h"] == 1


def test_merge_restores_without_wiping():
    runtime = _ledger_with_run()
    snapshot = PL.new_ledger("2026-07-03T08:00:00Z")
    PL.record_run(snapshot, now_iso="2026-07-03T08:00:00Z", ok=True,
                  baseline_checked=True, new_items=50)
    PL.update_source(snapshot, "nhk_business", now_iso="2026-07-03T08:00:00Z",
                     ok=True, newest_published_at="2026-07-03T07:30:00Z")
    merged = PL.merge(runtime, snapshot, NOW)
    assert len(merged["runs"]) == 2                # union, not replacement
    assert "nhk_business" in merged["sources"]
    # duplicate-at merge stays single
    again = PL.merge(merged, snapshot, NOW)
    assert len(again["runs"]) == 2


def test_source_health_no_success_today_not_live():
    lg = PL.new_ledger(NOW)
    PL.update_source(lg, "reuters_jp", now_iso=OLD, ok=True)   # last success 26h ago
    lg["sources"]["reuters_jp"]["lastSuccessAt"] = OLD
    sh = PL.source_health(lg, NOW)
    assert sh[0]["status"] == "stale"


def test_source_health_live_and_partial():
    lg = PL.new_ledger(NOW)
    PL.update_source(lg, "nhk_business", now_iso=NOW, ok=True,
                     newest_published_at="2026-07-03T11:30:00Z")
    PL.update_source(lg, "coindesk", now_iso=NOW, ok=True)
    PL.update_source(lg, "coindesk", now_iso=NOW, ok=False)
    sh = {s["sourceId"]: s for s in PL.source_health(lg, NOW)}
    assert sh["nhk_business"]["status"] == "live"
    assert sh["nhk_business"]["newestAgeHours"] == 0.5
    assert sh["coindesk"]["status"] == "partial"


def test_derive_status_rules():
    # healthy
    lg = _ledger_with_run()
    s = PL.summarize(lg, NOW)
    st, alerts = PL.derive_status(now_iso=NOW, last_patrol_at=NOW, summary=s,
                                  is_weekday=True, has_runs=True)
    assert st == "healthy" and alerts == []
    # stale: last patrol 45 min ago on a weekday
    st, alerts = PL.derive_status(now_iso=NOW, last_patrol_at="2026-07-03T11:10:00Z",
                                  summary=s, is_weekday=True, has_runs=True)
    assert st == "stale" and any("遅延" in a["messageJa"] for a in alerts)
    # weekend tolerance: 45 min ago is fine hourly
    st, _ = PL.derive_status(now_iso=NOW, last_patrol_at="2026-07-03T11:10:00Z",
                             summary=s, is_weekday=False, has_runs=True)
    assert st == "healthy"
    # degraded: movers existed but zero deep sweeps in 24h
    lg2 = _ledger_with_run(deep_sweeps=0, active_movers=3)
    s2 = PL.summarize(lg2, NOW)
    st, alerts = PL.derive_status(now_iso=NOW, last_patrol_at=NOW, summary=s2,
                                  is_weekday=True, has_runs=True)
    assert st == "degraded"
    # degraded: no baseline sweeps
    lg3 = _ledger_with_run(baseline_checked=False)
    s3 = PL.summarize(lg3, NOW)
    st, _ = PL.derive_status(now_iso=NOW, last_patrol_at=NOW, summary=s3,
                             is_weekday=True, has_runs=True)
    assert st == "degraded"
    # error: old-news-as-primary violation
    st, alerts = PL.derive_status(now_iso=NOW, last_patrol_at=NOW,
                                  summary={**s, "oldPrimaryViolations": 1},
                                  is_weekday=True, has_runs=True)
    assert st == "error"
    # not_ready: no runs yet
    st, _ = PL.derive_status(now_iso=NOW, last_patrol_at=None, summary=s,
                             is_weekday=True, has_runs=False)
    assert st == "not_ready"
