"""2026-10-27 (owner): compare the sum of J-Quants daily per-stock margin rows
with the JPX two-market weekly totals before using it as a backup."""
import scanner


def test_reconcile_sums_jquants_rows_for_the_jpx_weeks(monkeypatch):
    ledger = {"observations": [
        {"seriesId": "credit.long_balance", "periodEnd": "2026-10-16", "value": 6664007000000, "knownAt": "2026-10-20T06:00:00Z"},
        {"seriesId": "credit.short_balance", "periodEnd": "2026-10-16", "value": 667054000000, "knownAt": "2026-10-20T06:00:00Z"},
        {"seriesId": "credit.long_balance", "periodEnd": "2026-09-19", "value": 1, "knownAt": "2026-09-24T06:00:00Z"},
        {"seriesId": "flow.foreign", "periodEnd": "2026-10-16", "value": 5}]}
    monkeypatch.setattr(scanner, "_MARKET_LEDGER", ledger)
    asked = []
    def pages(path, params, max_pages=40):
        asked.append((path, params))
        return [{"Date": params["date"], "Code": "72030", "LongVol": 100, "ShrtVol": 10, "LongVal": 3.0e12},
                {"Date": params["date"], "Code": "67580", "LongVol": 50, "ShrtVol": 5, "LongVal": 3.5e12, "Note": "x"}]
    monkeypatch.setattr(scanner, "_jquants_paginated", pages)
    result = scanner._margin_reconcile()
    assert asked == [("/markets/margin-interest", {"date": "2026-10-16"})]       # only weeks with daily rows
    [week] = result["weeks"]
    assert week["jpx"] == {"long": 6664007000000.0, "short": 667054000000.0}
    assert week["jquantsTotals"]["LongVal"] == 6.5e12 and week["jquantsTotals"]["LongVol"] == 150
    assert week["jquantsCodes"] == 2 and "Note" in week["jquantsFields"]


def test_route_is_admin_only(monkeypatch):
    client = scanner.app.test_client()
    assert client.get("/api/argus/admin/margin-reconcile").status_code in (401, 403, 503)
