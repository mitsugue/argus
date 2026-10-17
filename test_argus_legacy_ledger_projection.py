import json

import argus_ledger as ledger


def _setup(monkeypatch, tmp_path, now_ms=1_800_000_000_000):
    monkeypatch.setattr(ledger, "LEDGER_PATH", tmp_path / "predictions.jsonl")
    monkeypatch.setattr(ledger, "_now_ms", lambda: now_ms)


def test_legacy_facade_appends_issued_and_unscorable_outcome(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    issued = ledger.log_prediction(
        code="AAPL", direction="up", probability=0.7, horizon="10m",
        price_at_prediction=100.0)
    before = ledger.LEDGER_PATH.read_bytes()
    monkeypatch.setattr(ledger, "_now_ms",
                        lambda: issued["resolvesAt"] + 1)
    assert ledger.resolve_outcomes(lambda _code, _target: 110.0) == 0
    after = ledger.LEDGER_PATH.read_bytes()
    assert after.startswith(before)
    rows = [json.loads(line) for line in after.decode().splitlines()]
    assert [row["recordType"] for row in rows] == [
        "issued_projection", "outcome_projection"]
    assert rows[1]["status"] == "unscorable"
    assert rows[1]["movePct"] is None
    assert rows[1]["mode"] == "unknown_legacy"
    recent = ledger.list_recent(1)[0]
    assert recent["outcome"] == "unscorable"
    assert recent["targetTruthBound"] is False


def test_legacy_facade_accepts_only_exact_target_bound_truth(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    issued = ledger.log_prediction(
        code="AAPL", direction="up", probability=0.7, horizon="10m",
        price_at_prediction=100.0)
    monkeypatch.setattr(ledger, "_now_ms",
                        lambda: issued["resolvesAt"] + 1)

    def exact(_code, target):
        return {"price": 110.0, "asOfMs": target,
                "knownAtMs": target + 1,
                "targetSessionId": "XNYS:target:regular",
                "truthObservationId": "truth-aapl-target"}

    assert ledger.resolve_outcomes(exact) == 1
    recent = ledger.list_recent(1)[0]
    assert recent["outcome"] == "hit"
    assert recent["movePct"] == 10.0
    assert recent["targetTruthBound"] is True
    stats = ledger.aggregate_stats(window_days=30)
    assert stats["mode"] == "unknown_legacy"
    assert stats["calibrationEligible"] is False
    assert stats["resolvedCount"] == 1


def test_historical_mutable_row_is_read_only_unknown_legacy(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    historical = {
        "id": "pred-old", "predictedAt": 1_799_999_000_000,
        "resolvesAt": 1_799_999_600_000, "code": "AAPL",
        "direction": "up", "probability": 0.7,
        "priceAtPrediction": 100.0, "outcome": "hit",
        "priceAtResolution": 101.0, "movePct": 1.0,
    }
    ledger.LEDGER_PATH.write_text(json.dumps(historical) + "\n")
    before = ledger.LEDGER_PATH.read_bytes()
    assert ledger.resolve_outcomes(lambda *_args: 999.0) == 0
    assert ledger.LEDGER_PATH.read_bytes() == before
    assert ledger.list_recent(1)[0] == historical
