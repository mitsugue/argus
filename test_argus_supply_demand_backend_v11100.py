"""V11.10.0 backend wiring — supply-demand endpoints cached-only, Flow
integration (structure hints shift the flow read), no leakage, regressions."""
import json

import scanner
import argus_flow_attribution as fa


class _Boom:
    def __getattr__(self, name):
        raise AssertionError(f"network call attempted via requests.{name}")


def _no_fetch(monkeypatch):
    monkeypatch.setattr(scanner, "requests", _Boom())


def test_supply_demand_single_and_list(monkeypatch):
    _no_fetch(monkeypatch)
    with scanner.app.test_client() as c:
        r = c.get("/api/argus/supply-demand?symbol=6146")
        assert r.status_code == 200
        d = r.get_json()
        sig = d["signal"]
        assert sig["schemaVersion"] == "supply-demand-v1"
        assert sig["supplyDemandRank"] in ("S", "A", "B", "C", "D", "E", "Unknown")
        assert sig["readabilityLabelJa"].startswith("需給ランク")
        assert "売買指示ではない" in d["disclaimerJa"]
        r2 = c.get("/api/argus/supply-demand")
        assert r2.status_code == 200
        d2 = r2.get_json()
        assert "signals" in d2


def test_supply_demand_status_honest_sources(monkeypatch):
    _no_fetch(monkeypatch)
    with scanner.app.test_client() as c:
        r = c.get("/api/argus/supply-demand/status")
        assert r.status_code == 200
        d = r.get_json()
        assert d["schemaVersion"] == "supply-demand-status-v1"
        disabled = {x["source"] for x in d["sourcesDisabledWithReason"]}
        assert "逆日歩(品貸料)" in disabled            # never pretended available
        assert any("moomoo" in x for x in disabled)   # JP realtime = intentional
        assert "意図的" in d["noteJa"]
        # public payload carries no private-position fields
        assert scanner.argus_portfolio_sync.contains_sensitive(d) == []


def test_cold_cache_yields_unknown_not_fabricated(monkeypatch):
    _no_fetch(monkeypatch)
    sig = scanner._supply_demand_signal_for("9999")   # no caches for this code
    assert sig["supplyDemandRank"] == "Unknown"
    assert sig["evidence"]["marginBuyingBalance"] is None
    assert sig["evidence"]["reverseStockLendingFee"] is None
    assert "暫定" in sig["sourceLimitNote"]


def test_flow_integration_squeeze_shifts_read():
    NOW = "2026-07-04T12:00:00+00:00"
    base = {"changePct": 6.0, "volumeRatio": 2.5, "priorRunupPct": -2,
            "marginShortHeavy": True, "closeLocation": 0.6}
    plain = fa.classify("5803", "JP", base, NOW)
    hinted = fa.classify("5803", "JP", dict(base, squeezeProne=True), NOW)
    assert hinted["flowClass"] == "short_covering"
    assert "SD_SQUEEZE_SUPPORT" in hinted["reasonCodes"]
    # squeeze support must not decrease covering confidence vs plain
    if plain["flowClass"] == "short_covering":
        assert hinted["confidence"] >= plain["confidence"]


def test_flow_integration_overhang_weakens_accumulation():
    NOW = "2026-07-04T12:00:00+00:00"
    base = {"changePct": 4.0, "volumeRatio": 2.2, "closeLocation": 0.9,
            "shortRatio": 0.3, "shortRatioAvg": 0.3, "marginShortHeavy": False}
    plain = fa.classify("9984", "JP", base, NOW)
    hinted = fa.classify("9984", "JP", dict(base, creditOverhang=True), NOW)
    assert plain["flowClass"] == "institutional_accumulation"
    assert "SD_CREDIT_OVERHANG" in hinted["reasonCodes"]
    assert hinted["confidence"] <= plain["confidence"]


def test_flow_record_carries_sd_support_note(monkeypatch):
    _no_fetch(monkeypatch)
    rec = scanner._flow_attribution_for("6146", "JP")
    assert "supplyDemand" in rec
    sdc = rec["supplyDemand"]
    assert sdc["rank"] in ("S", "A", "B", "C", "D", "E", "Unknown")
    assert sdc["supportNoteJa"]


def test_handoff_prompt_gains_sd_section(monkeypatch):
    sh = scanner.argus_supply_demand.handoff_section(
        [scanner._supply_demand_signal_for("6146")])
    assert sh["title"].startswith("Supply / Demand")
    assert "断定しない" in sh["sourceLimitJa"]


def test_regressions_all_layers(monkeypatch):
    _no_fetch(monkeypatch)
    with scanner.app.test_client() as c:
        for path, schema in (("/api/argus/bridge/status", "bridge-status-v1"),
                             ("/api/argus/institutional-intel/status", "institutional-intel-status-v1"),
                             ("/api/argus/flow-attribution/status", "flow-attribution-status-v1"),
                             ("/api/argus/position-exposure/status", "position-exposure-status-v1"),
                             ("/api/argus/portfolio-sync/status", "portfolio-sync-status-v1")):
            r = c.get(path)
            assert r.status_code == 200, path
            assert r.get_json()["schemaVersion"] == schema
