"""Counts-only AI usage report (owner request 2026-10-16): no money reaches a public log."""
import json
import pathlib
import sqlite3
import sys

import argus_analysis_history as history

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "scripts"))
import ai_usage_report  # noqa: E402


def _view(conn, day, attempts, corrections=None):
    diag = {"outcome": "ok", "attempts": attempts, "estUsd": 0.123456, "totalEstUsd": 0.987654}
    if corrections is not None:
        diag["callReduction"] = {"attemptCount": len(attempts), "correctionCalls": corrections}
    body = json.dumps({"brief": {"aiDiagnostics": diag}, "recordedAt": f"{day}T01:00:00Z"})
    conn.execute("INSERT INTO views(record_id,recorded_at,body) VALUES(?,?,?)",
                 (f"r-{day}-{conn.total_changes}", f"{day}T01:00:00Z", body))


def _attempt(reason=None, inp=1000, out=200, cached=100):
    return {"provider": {"inputTokens": inp, "outputTokens": out, "cachedInputTokens": cached, "estUsd": 0.05},
            "validation": {"status": "REJECTED" if reason else "ACCEPTED", "reason": reason}}


def test_call_report_counts_views_corrections_reasons_and_tokens(tmp_path):
    path = tmp_path / "market_analysis_history.sqlite3"
    history.initialize(path)
    conn = sqlite3.connect(path, isolation_level=None)
    _view(conn, "2026-10-09", [_attempt("unsupported_numeric_tokens"), _attempt()], corrections=1)
    _view(conn, "2026-10-09", [_attempt("unsupported_numeric_tokens"), _attempt()])     # old record: no callReduction
    _view(conn, "2026-10-12", [_attempt()], corrections=0)
    _view(conn, "2026-10-12", [], corrections=None)                                    # deterministic only
    _view(conn, "2026-09-01", [_attempt("x"), _attempt()], corrections=1)              # before the window
    conn.close()
    report = history.call_report(path, since_day="2026-10-01")
    days = {row["dayUtc"]: row for row in report["days"]}
    assert set(days) == {"2026-10-09", "2026-10-12"}
    first = days["2026-10-09"]
    assert first["views"] == 2 and first["viewsWithAi"] == 2 and first["viewsWithCorrection"] == 2
    assert first["aiCalls"] == 4 and first["correctionCalls"] == 2
    assert first["firstRejectionReasons"] == {"unsupported_numeric_tokens": 2}
    assert first["inputTokens"] == 4000 and first["outputTokens"] == 800 and first["cachedInputTokens"] == 400
    second = days["2026-10-12"]
    assert second["views"] == 2 and second["viewsWithAi"] == 1 and second["correctionCalls"] == 0
    assert "Usd" not in json.dumps(report) and report["coverage"] == "saved_views_only"
    assert report["rowsRead"] == 4 and report["truncated"] is False


def test_the_printed_report_carries_counts_and_never_money(tmp_path):
    path = tmp_path / "market_analysis_history.sqlite3"
    history.initialize(path)
    conn = sqlite3.connect(path, isolation_level=None)
    _view(conn, "2026-10-09", [_attempt("unsupported_numeric_tokens"), _attempt()], corrections=1)
    _view(conn, "2026-10-13", [_attempt()], corrections=0)
    conn.close()
    document = {
        "daySpentUsd": 1.2345, "monthSpentUsd": 45.6789, "dailyBudgetUsd": 9.87,
        "featureUsage": {"readStatus": "AVAILABLE", "summary": {"groups": [
            {"dayUtc": "2026-10-09", "feature": "market_brief", "providerCalls": 2, "inputTokens": 2000,
             "outputTokens": 400, "cachedInputTokens": 200, "knownEstimatedCostUsd": 3.21}]}},
        "briefCallReport": {"readStatus": "AVAILABLE", **history.call_report(path, since_day="2026-10-01")},
    }
    text = ai_usage_report.report(document)
    for money in ("1.2345", "45.6789", "9.87", "3.21", "0.123456", "0.987654", "Usd", "$"):
        assert money not in text, money
    assert "| 2026-10-09 | market_brief | 2 | 2000 | 400 | 200 |" in text
    assert "unsupported_numeric_tokens:1" in text
    assert "13.8.91 より前：1日" in text and "13.8.91 以降：1日" in text
    assert ai_usage_report.strip_money(document).keys() == {"featureUsage", "briefCallReport"}


def test_the_workflow_prints_only_the_filtered_report():
    text = (ROOT / ".github/workflows/ai-usage-report.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch" in text and "- cron:" not in text
    assert "upload-artifact" not in text and "cat \"$DOC\"" not in text
    assert "scripts/ai_usage_report.py \"$DOC\"" in text and "rm -f \"$DOC\"" in text
    assert "${{ secrets.ARGUS_ADMIN_TOKEN }}" in text


def test_reads_in_short_pages_and_counts_only_true_integers(tmp_path, monkeypatch):
    path = tmp_path / "market_analysis_history.sqlite3"
    history.initialize(path)
    conn = sqlite3.connect(path, isolation_level=None)
    for i in range(7):
        _view(conn, "2026-10-14", [_attempt()], corrections=0)
    _view(conn, "2026-10-14", [_attempt(inp=True, out="200"), _attempt(inp=-5)], corrections=True)
    conn.close()
    monkeypatch.setattr(history, "CALL_REPORT_PAGE_ROWS", 3)
    report = history.call_report(path, since_day="2026-10-01")
    day = report["days"][0]
    assert report["rowsRead"] == 8 and day["views"] == 8
    assert day["unknownTokenAttempts"] == 2 and day["inputTokens"] == 7000
    assert day["correctionCalls"] == 1                    # a bool is not a count: attempts - 1
    monkeypatch.setattr(history, "CALL_REPORT_MAX_ROWS", 4)
    assert history.call_report(path, since_day="2026-10-01")["truncated"] is True


def test_a_money_value_reaching_the_text_by_any_path_stops_the_report(monkeypatch):
    document = {"daySpentUsd": 1.2345, "featureUsage": {"summary": {"groups": [
        {"dayUtc": "2026-10-09", "feature": "1.2345", "providerCalls": 1}]}}}
    try:
        ai_usage_report.report(document)
    except SystemExit as stop:
        assert str(stop).startswith("money_value_in_report")
    else:
        raise AssertionError("a money value in the printed text must stop the report")
    assert ai_usage_report.money_leaks({}, "合計 $3") == 1


def test_the_cost_route_reads_the_saved_views_only_when_asked(monkeypatch):
    import scanner
    calls = []
    monkeypatch.setattr(scanner, "_saved_view_call_report", lambda: calls.append(1) or {"readStatus": "AVAILABLE"})
    source = open(scanner.__file__, encoding="utf-8").read()
    assert 'if str(request.args.get("calls") or "") == "1":' in source
    workflow = (ROOT / ".github/workflows/ai-usage-report.yml").read_text(encoding="utf-8")
    assert "/api/argus/ai-cost?calls=1" in workflow


def test_the_report_counts_conclusion_changes_and_why_editions_were_written(tmp_path):
    """2026-10-17 (owner): how often the written conclusion moves, and why each edition was written."""
    path = tmp_path / "market_analysis_history.sqlite3"
    history.initialize(path)
    conn = sqlite3.connect(path, isolation_level=None)
    for i, (now, trigger) in enumerate([("様子見", None), ("様子見", None), ("警戒", None),
                                        ("警戒", {"kind": "SCHEDULED", "changedFactGroups": ["official_sensor"]}),
                                        ("警戒", {"kind": "EVENT", "changedFactGroups": ["official_macro_result", "official_sensor"]})]):
        body = {"brief": {"aiDiagnostics": {"attempts": [_attempt()]}, "aiText": {"nowJa": now}},
                "recordedAt": "2026-10-18T01:00:00Z"}
        if trigger:
            body["brief"]["generationTrigger"] = trigger
        conn.execute("INSERT INTO views(record_id,recorded_at,body) VALUES(?,?,?)",
                     (f"t-{i}", "2026-10-18T01:00:00Z", json.dumps(body)))
    conn.close()
    day = history.call_report(path, since_day="2026-10-01")["days"][0]
    assert day["views"] == 5 and day["conclusionChanged"] == 1
    assert day["triggers"] == {"NOT_RECORDED": 3, "SCHEDULED": 1, "EVENT": 1}
    assert day["changedFactGroups"] == {"official_sensor": 2, "official_macro_result": 1}
    text = ai_usage_report.report({"briefCallReport": {"readStatus": "AVAILABLE",
                                   **history.call_report(path, since_day="2026-10-01")}})
    assert "| 2026-10-18 | 5 | 1 | 記録前:3, 定時:1, 発表直後:1 |" in text
