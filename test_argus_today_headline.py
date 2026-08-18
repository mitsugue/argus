"""Today headline view: derivation truth, explicit states, size discipline."""
import copy
import json

import argus_today_headline as headline
import argus_verified_snapshot


def _bar(index):
    return {
        "date": f"2026-07-{index + 1:02d}", "open": 100.0 + index,
        "high": 102.0 + index, "low": 99.0 + index, "close": 101.0 + index,
        "volume": 1000 + index, "atr14": 2.5, "availableFrom": f"2026-07-{index + 1:02d}",
        "ma": {"25": 100.5}, "rsi14": 51.2, "macd": {"line": 0.1},
        "bollinger": {"upper": 105.0}, "ichimoku": {"base": 100.0},
        "sar": 99.0, "volumeRatio20": 1.1, "observedAt": "x", "knownAt": "x",
        "datasetId": "d", "sourceId": "s", "revision": 1, "adjusted": False,
    }


def _snapshot(symbol="1321"):
    calibration_horizon = {
        "horizon": 5,
        "referenceDirectionProbabilities": {"UP": 41, "RANGE": 26, "DOWN": 33},
        "directionProbabilities": None,
        "probabilities": None,
        "returnDistribution": {"q10": -0.03, "q25": -0.018, "q75": 0.022,
                               "q90": 0.042, "median": 0.002},
        "probabilityEligibility": {"eligible": False, "reasonCodes": ["x"]},
        "probabilityTruthEvidence": {"contractVersion": "v1"},
        "effectiveSampleCount": 120, "episodeCount": 40,
        "modelBrier": 0.66, "baselineBrier": 0.65, "brierSkill": -0.02,
        "calibrationIntegrity": "PASS", "calibrationVersion": "beta-v2",
        "calibrationDatasetHash": "h" * 16, "calibrationStatus": "calibrated",
        "expectedValue": 0.001, "signalFamily": "baseline",
        # heavy fields that must NOT survive into the headline
        "walkForward": {"folds": list(range(500))},
        "unroundedProbabilities": {"UP": 40.61},
        "baseRates": {"UP": 0.4},
    }
    payload = {
        "symbol": symbol, "market": "JP", "displayNameJa": "日経225 ETF",
        "status": "complete", "periodEnd": "2026-08-18", "quoteState": "CLOSE",
        "instrumentMetadata": {"symbol": symbol, "market": "JP",
                               "instrumentId": f"JP:{symbol}:ETF",
                               "assetType": "ETF"},
        "marketCalendar": {"market": "JP_EQUITY", "isTradingDay": True,
                           "session": "AFTER_CLOSE"},
        "indicators": {"status": "complete",
                       "bars": [_bar(i) for i in range(60)]},
        "zones": [
            {"status": "active", "lower": 98.0, "upper": 99.5, "center": 98.7},
            {"status": "expired", "lower": 90.0, "upper": 91.0, "center": 90.5},
        ],
        "turningPoints": [
            {"id": f"tp{i}", "status": "confirmed" if i % 2 else "rejected",
             "direction": "up", "effectiveFrom": "2026-08-01",
             "facts": ["f"]} for i in range(10)
        ],
        "eventMarkers": [{"id": f"e{i}", "date": "2026-08-10"} for i in range(20)],
        "todayIntelligence": {
            "calibration": {"schemaVersion": "cal-v1",
                            "calibrationVersion": "beta-v2",
                            "methodVersion": "m", "historyStart": "2021-01-01",
                            "historyEnd": "2026-08-18", "historyCount": 1340,
                            "horizons": {"1": dict(calibration_horizon),
                                         "5": dict(calibration_horizon),
                                         "20": dict(calibration_horizon)}},
            "shortSelling": {"latest": {"previousDayDifference": -1.0}},
            "failedRally": None,
            "historyCoverage": {"start": "2021-01-01", "end": "2026-08-18"},
        },
        # heavy fields that must NOT survive into the headline
        "marketReplay": {"contexts": {"5": {"big": "x" * 100000}}},
        "relativeStrength": {"huge": "y" * 100000},
        "ledgerTurningPoints": [{"big": True}] * 200,
    }
    return {
        "schemaVersion": "argus-verified-view-snapshot-v1",
        "snapshotId": "vs-" + "a" * 32, "kind": "market-chart",
        "instrument": symbol, "horizon": "5D", "datasetHash": "d" * 16,
        "payloadHash": "p" * 16, "methodVersion": "method-x",
        "asOf": "2026-08-18T15:00:00Z", "generatedAt": "2026-08-18T15:00:01Z",
        "verifiedAt": "2026-08-18T15:00:02Z", "quality": "live",
        "sourceStatus": {"chart": "complete"},
        "verificationStatus": "verified", "payload": payload,
    }


def test_headline_derives_only_from_verified_snapshot_fields():
    snapshot = _snapshot()
    entry = headline.build_instrument_headline(snapshot, "1321")
    assert entry["status"] == "ready"
    assert entry["parentSnapshotId"] == snapshot["snapshotId"]
    assert entry["parentPayloadHash"] == snapshot["payloadHash"]
    assert entry["verificationStatus"] == "verified"
    assert len(entry["bars"]) == headline.HEADLINE_BAR_COUNT
    assert entry["bars"][-1]["close"] == snapshot[
        "payload"]["indicators"]["bars"][-1]["close"]
    assert entry["bars"][-1]["atr14"] == 2.5
    # canonical probabilities are copied verbatim, never recomputed
    five = entry["calibration"]["horizons"]["5"]
    assert five["referenceDirectionProbabilities"] == {
        "UP": 41, "RANGE": 26, "DOWN": 33}
    # only active/reclaimed zones and confirmed/candidate turning points
    assert all(zone["status"] in ("active", "reclaimed")
               for zone in entry["zones"])
    assert len(entry["turningPoints"]) == 3
    assert all(point["status"] in ("confirmed", "candidate")
               for point in entry["turningPoints"])


def test_headline_excludes_heavy_payload_sections():
    entry = headline.build_instrument_headline(_snapshot(), "1321")
    text = json.dumps(entry)
    assert "marketReplay" not in text
    assert '"relativeStrength"' not in text
    assert entry["relativeStrengthSummary"] is None  # fixture has no summary number
    assert "ledgerTurningPoints" not in text
    assert "walkForward" not in text
    assert "unroundedProbabilities" not in text
    # size discipline: a headline entry stays orders of magnitude below the
    # multi-megabyte verified snapshot
    assert len(text) < 200_000


def test_headline_reports_unavailable_truthfully():
    entry = headline.build_instrument_headline(None, "SPY")
    assert entry == {"status": "unavailable", "instrument": "SPY",
                     "reason": "verified_snapshot_missing"}
    unverified = _snapshot("SPY")
    unverified["verificationStatus"] = "pending"
    assert headline.build_instrument_headline(
        unverified, "SPY")["status"] == "unavailable"


def test_headline_document_covers_all_instruments_and_is_stable():
    snapshots = {"1321": _snapshot("1321"), "1306": _snapshot("1306")}
    document = headline.build_today_headline(
        snapshots, now_iso="2026-08-18T15:10:00Z")
    assert document["schemaVersion"] == headline.HEADLINE_SCHEMA
    assert set(document["instruments"]) == set(headline.HEADLINE_INSTRUMENTS)
    assert document["readyCount"] == 2
    assert document["instruments"]["SPY"]["status"] == "unavailable"
    assert document["automaticAiCalls"] == 0
    again = headline.build_today_headline(
        snapshots, now_iso="2026-08-18T15:10:00Z")
    assert again["headlineSetId"] == document["headlineSetId"]
    assert again["instruments"]["1321"]["headlineHash"] == \
        document["instruments"]["1321"]["headlineHash"]


def test_headline_does_not_mutate_source_snapshots():
    snapshot = _snapshot()
    pristine = copy.deepcopy(snapshot)
    headline.build_instrument_headline(snapshot, "1321")
    assert snapshot == pristine


def test_headline_from_real_snapshot_builder_round_trip():
    """The headline derives cleanly from a snapshot built by the real
    argus_verified_snapshot builder, proving field-name agreement."""
    base = _snapshot()
    built = argus_verified_snapshot.build_snapshot(
        payload=base["payload"], kind="market-chart", instrument="1321",
        horizon="5D", dataset_hash="d" * 16, method_version="method-x",
        as_of="2026-08-18T15:00:00Z", generated_at="2026-08-18T15:00:01Z",
        quality="live", source_status={"chart": "complete"})
    entry = headline.build_instrument_headline(built, "1321")
    assert entry["status"] == "ready"
    assert entry["parentSnapshotId"] == built["snapshotId"]
    assert len(entry["bars"]) == headline.HEADLINE_BAR_COUNT
