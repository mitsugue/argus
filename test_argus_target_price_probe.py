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
        "twelvedata.com/price_target": (200, {"status": "error", "code": 403, "message": "plan"}),
        "twelvedata.com/recommendations": (200, {"trends": {"current_month": {}}}),
        "finnhub.io/api/v1/stock/price-target": (403, {"error": "premium"}),
        "finnhub.io/api/v1/stock/recommendation": (200, [{"buy": 10}]),
    })
    assert rows["twelvedata-price-target"]["ok"] is False and rows["twelvedata-price-target"]["httpStatus"] == 403
    assert rows["twelvedata-recommendations"]["ok"] is True
    assert rows["finnhub-price-target"]["ok"] is False
    assert rows["finnhub-recommendation"]["ok"] is True
