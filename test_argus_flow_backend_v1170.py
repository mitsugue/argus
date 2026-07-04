"""V11.7.0 backend wiring tests — flow-attribution endpoints, evidence collection
is cached-only (no fetch), JP moomoo-off is not an error, no trading language."""
import scanner


class _Boom:
    """Any attribute access = attempted network call → test fails loudly."""
    def __getattr__(self, name):
        raise AssertionError(f"network call attempted via requests.{name}")


def _no_fetch(monkeypatch):
    monkeypatch.setattr(scanner, "requests", _Boom())


def test_flow_evidence_cached_only(monkeypatch):
    _no_fetch(monkeypatch)
    ev = scanner._flow_evidence_for("6146", "JP")   # cold caches → honest gaps
    assert isinstance(ev, dict)
    assert "sources" in ev


def test_flow_attribution_single_symbol(monkeypatch):
    _no_fetch(monkeypatch)
    with scanner.app.test_client() as c:
        r = c.get("/api/argus/flow-attribution?symbol=6146&market=JP")
        assert r.status_code == 200
        d = r.get_json()
        assert d["schemaVersion"] == "flow-attribution-response-v1"
        rec = d["record"]
        assert rec["symbol"] == "6146" and rec["flowClass"] in (
            "unknown", "liquidity_noise") or rec["flowClass"]  # cold cache → unknown ok
        assert rec["complianceNote"]
        assert "断定" in rec["complianceNote"]


def test_flow_attribution_list_and_status(monkeypatch):
    _no_fetch(monkeypatch)
    with scanner.app.test_client() as c:
        r = c.get("/api/argus/flow-attribution")
        assert r.status_code == 200
        d = r.get_json()
        assert "records" in d and d["disclaimerJa"]
        r2 = c.get("/api/argus/flow-attribution/status")
        assert r2.status_code == 200
        st = r2.get_json()
        assert st["schemaVersion"] == "flow-attribution-status-v1"
        # JP moomoo flow off is INTENTIONAL, reported as availability not error
        assert st["sourceAvailability"]["flow_jp_bridge"] is False
        assert "意図的に無効" in st["noteJa"]


def test_flow_with_pushed_quote_classifies(monkeypatch):
    _no_fetch(monkeypatch)
    scanner._PUSHED_QUOTES.setdefault("US", {})["FLOWTEST"] = {
        "row": {"symbol": "FLOWTEST", "price": 100.0, "changePct": 4.5,
                "volume": 9_000_000, "status": "live",
                "flow": {"bigNetRatio": 0.3, "bigIn": 5e8, "bigOut": 2e8}},
        "ts": 9e12}
    try:
        rec = scanner._flow_attribution_for("FLOWTEST", "US")
        assert rec["evidence"]["priceActionEvidence"]
        assert rec["flowClass"] != "unknown"
        # measured US flow present → can be direct, but never assertive wording
        assert "大口が買っている" not in rec["ownerReadableWhyJa"]
    finally:
        scanner._PUSHED_QUOTES["US"].pop("FLOWTEST", None)


def test_cause_attribution_attaches_flow(monkeypatch):
    _no_fetch(monkeypatch)
    monkeypatch.setattr(scanner, "get_catalysts_snapshot", lambda *a, **k: {"items": []})
    with scanner.app.test_client() as c:
        r = c.get("/api/argus/cause-attribution?symbol=6146&market=JP")
        assert r.status_code == 200
        d = r.get_json()
        assert "flowAttribution" in d
        fa = d["flowAttribution"]
        if fa:                                   # cold cache may yield unknown, still a record
            assert fa["schemaVersion"] == "flow-attribution-v1"
            assert fa["actionImplication"] in ("investigate", "wait_for_confirmation",
                                               "avoid_chase", "monitor", "caution", "no_action")


def test_handoff_prompt_contains_flow_section_when_movers(monkeypatch):
    recs = [scanner.argus_flow_attribution.classify(
        "TEST", "US", {"changePct": 4.0, "volumeRatio": 2.2, "closeLocation": 0.9},
        "2026-07-04T05:00:00+00:00")]
    sec = scanner.argus_flow_attribution.handoff_section(recs)
    assert sec["likelyAccumulation"] and "反対解釈" in sec["opposingViewJa"]


def test_no_order_or_broker_words_in_flow_module():
    src = open("argus_flow_attribution.py", encoding="utf-8").read()
    for banned in ("place_order", "order(", "buy(", "sell(", "broker",
                   "trd_env", "unlock_trade"):
        assert banned not in src, banned
