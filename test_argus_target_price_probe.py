import scanner


class R:
    def __init__(self, status, body): self.status_code, self._body = status, body
    def json(self): return self._body


def _rows(monkeypatch, replies):
    monkeypatch.setattr(scanner, "_TWELVEDATA_API_KEY", "k")
    monkeypatch.setattr(scanner, "FINNHUB_API_KEY", "k")
    def get(url, params=None, **kw):
        for key, reply in replies.items():
            if key in url:
                return R(*reply)
        return R(500, {})
    monkeypatch.setattr(scanner.requests, "get", get)
    monkeypatch.setattr(scanner, "_PROVIDER_DIAG_CACHE", {"data": None, "expires": 0})
    return {row["provider"]: row for row in scanner._provider_diagnostics()["items"]}


def test_target_price_probes_count_only_a_real_field(monkeypatch):
    rows = _rows(monkeypatch, {
        "finnhub.io/api/v1/stock/price-target": (403, {"error": "premium"}),
        "finnhub.io/api/v1/stock/recommendation": (200, [{"buy": 10}]),
    })
    assert rows["finnhub-price-target"]["ok"] is False
    assert rows["finnhub-recommendation"]["ok"] is True


def test_twelve_data_connection_probes_are_removed(monkeypatch):
    """2026-10-22 (owner): US data moved to moomoo; the admin Twelve Data probes
    (quote, time series, target price, recommendations) are gone so the
    diagnostics spend nothing there."""
    called = []
    monkeypatch.setattr(scanner, "_td_get", lambda *a, **k: called.append(a) or R(500, {}))
    rows = _rows(monkeypatch, {})
    assert not [name for name in rows if name.startswith("twelvedata")]
    assert called == []
    cached = scanner._provider_diagnostics_cached_only()
    assert not [item for item in cached["items"] if item["provider"].startswith("twelvedata")]
