import copy
from unittest import mock

import argus_decision_ledger
import argus_market_data_truth
import scanner
from scripts import run_prediction_ledger


DECISION_AT = "2026-08-14T06:40:00Z"
GENERATED_AT = "2026-08-14T06:40:01Z"
BUILD_SHA = "a" * 40


def _legacy_prediction():
    return {
        "symbol": "7203", "market": "JP", "price": 2800.0,
        "action": "buy_dip",
        "scenarios": [
            {"label": "downside_continuation", "p": 20},
            {"label": "sideways_stabilization", "p": 50},
            {"label": "rebound_attempt", "p": 30},
        ],
    }


def _jquants_row(**changes):
    row = {
        "symbol": "7203", "price": 2800.0, "changePct": 1.0,
        "volume": 1000, "open": 2770.0, "high": 2820.0,
        "low": 2750.0, "close": 2800.0,
        "date": "2026-08-14", "sourceTimestamp": "2026-08-14",
        "receivedAt": DECISION_AT, "source": "jquants",
        "status": "live",
    }
    row.update(changes)
    return row


def _projection(*, legacy_rows=None, quote_rows=None,
                decision_at=DECISION_AT, generated_at=GENERATED_AT):
    with mock.patch.object(scanner, "_backend_exact_sha",
                           return_value=BUILD_SHA):
        return scanner._canonical_prediction_ledger_projection(
            legacy_rows=(legacy_rows if legacy_rows is not None else
                         [("tactical_rule", _legacy_prediction())]),
            quote_rows=(quote_rows if quote_rows is not None else
                        [("JP", "jquants", _jquants_row())]),
            decision_at=decision_at, generated_at=generated_at,
            engine_version="fixture-v1")


def _epoch_iso(value):
    return scanner.datetime.fromtimestamp(
        value, scanner.pytz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_one_source_age_contract_never_promotes_missing_old_or_future():
    now = 1_800_000_000.0
    missing = scanner._canonical_quote_source_age(None, now_epoch=now)
    old = scanner._canonical_quote_source_age(
        _epoch_iso(now - 3600), now_epoch=now)
    future = scanner._canonical_quote_source_age(
        _epoch_iso(now + 1), now_epoch=now)
    fresh = scanner._canonical_quote_source_age(
        _epoch_iso(now - 60), now_epoch=now)

    assert [missing["status"], old["status"], future["status"]] == [
        "delayed", "delayed", "delayed"]
    assert missing["ageSec"] is None
    assert future["ageSec"] is None and future["timestampInversion"] is True
    assert fresh["status"] == "live" and fresh["ageSec"] == 60


def test_cached_provider_status_is_reaged_and_cannot_remain_live(monkeypatch):
    now = 1_800_000_000.0
    monkeypatch.setattr(scanner.time, "time", lambda: now)
    cached = {
        "status": "live", "provider": "twelvedata",
        "stocks": [{"symbol": "AAPL", "status": "live",
                    "sourceTimestamp": _epoch_iso(now - 3600)}],
    }
    reaged = scanner._canonical_quote_snapshot_age(cached, "stocks")
    assert cached["status"] == "live"  # cache provenance is not rewritten
    assert reaged["status"] == "delayed"
    assert reaged["stocks"][0]["status"] == "delayed"
    assert reaged["stocks"][0]["ageSec"] == 3600


def test_twelve_data_finnhub_coingecko_and_coinbase_use_source_age(
        monkeypatch):
    now = 1_800_000_000.0
    monkeypatch.setattr(scanner.time, "time", lambda: now)
    fresh_iso = _epoch_iso(now - 60)
    old_iso = _epoch_iso(now - 3600)
    future_iso = _epoch_iso(now + 1)
    meta = {"symbol": "AAPL", "name": "Apple"}
    quote = {"close": "100", "change": "1", "percent_change": "1"}
    assert scanner._td_parse_row(
        meta, {**quote, "datetime": fresh_iso})["status"] == "live"
    assert scanner._td_parse_row(
        meta, {**quote, "datetime": old_iso})["status"] == "delayed"
    td_future = scanner._td_parse_row(
        meta, {**quote, "datetime": future_iso})
    assert td_future["status"] == "delayed"
    assert td_future["timestampInversion"] is True

    class FinnhubResponse:
        ok = True

        def json(self):
            return {"c": 100.0, "d": 1.0, "dp": 1.0}

    monkeypatch.setattr(scanner, "FINNHUB_API_KEY", "fixture")
    scanner._FINNHUB_QUOTE_CACHE.clear()
    monkeypatch.setattr(scanner.requests, "get",
                        lambda *_args, **_kwargs: FinnhubResponse())
    finnhub = scanner._finnhub_quote_row("AAPL")
    assert finnhub["status"] == "delayed"
    assert finnhub["sourceTimestamp"] is None
    assert finnhub["realtimeEvidence"] is False

    class CryptoResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"bitcoin": {
                "usd": 100.0, "usd_24h_change": 1.0,
                "usd_24h_vol": 1000.0,
                "last_updated_at": int(now - 3600),
            }}

    scanner._CRYPTO_CACHE.clear()
    monkeypatch.setattr(scanner.requests, "get",
                        lambda *_args, **_kwargs: CryptoResponse())
    coingecko = scanner.get_crypto_watchlist_snapshot(["bitcoin"])
    assert coingecko["status"] == "delayed"
    assert coingecko["quotes"][0]["status"] == "delayed"
    assert coingecko["quotes"][0]["ageSec"] == 3600

    class CoinbaseResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"last": "100", "open": "99", "volume": "10"}

    monkeypatch.setattr(scanner.requests, "get",
                        lambda *_args, **_kwargs: CoinbaseResponse())
    coinbase = scanner._crypto_coinbase_fallback(["bitcoin"])[0]
    assert coinbase["status"] == "delayed"
    assert coinbase["sourceTimestamp"] is None
    assert coinbase["ageSec"] is None


def test_scanner_projection_binds_truth_distribution_mode_and_session():
    projection = _projection()

    assert projection["status"] == "COMPLETE"
    assert projection["mode"] == "forward_live"
    assert projection["authority"] == "PREDICTION_EVIDENCE_ONLY"
    assert projection["finalDecisionAuthorityActive"] is False
    assert argus_market_data_truth.verify_decision_snapshot(
        projection["marketTruthSnapshot"])[0]
    assert projection["marketTruthSnapshot"]["buildIdentity"] == BUILD_SHA
    assert len(projection["issuedDecisions"]) == 3
    assert projection["candidateCount"] == 3
    assert projection["issuedCount"] == 3
    assert projection["omittedCandidateCount"] == 0
    assert projection["truthQualityComplete"] is True
    for issued in projection["issuedDecisions"]:
        assert argus_decision_ledger.verify_prediction_record_v2(issued)
        assert issued["mode"] == "forward_live"
        assert issued["candidateAction"] == ""
        assert issued["engine"]["buildSha"] == BUILD_SHA
        assert issued["forecastDistribution"]["classLabels"] == list(
            scanner.argus_calibration.CLASSES)
        # The selected canonical quote change (+1%) produces 30/50/20; the
        # contradictory legacy scenarios (20/50/30) are not an input.
        assert issued["forecastDistribution"]["probabilities"] == [
            0.3, 0.5, 0.2]
        assert issued["maturity"]["targetSessionId"].startswith(
            "JPX_TSE:cal-2026.2:")
        assert issued["targetLadder"][0]["comparator"] == "<"
        assert issued["targetLadder"][1]["comparator"] == ">"
        assert [row["targetId"] for row in issued["targetLadder"]] == [
            "scenario.downside_boundary", "scenario.rebound_boundary"]
        assert [row["value"] for row in issued["targetLadder"]] == [-2.0, 2.0]
        assert all(row["unit"] == "%" for row in issued["targetLadder"])
        assert len(issued["evaluationPolicy"]["parametersHash"]) == 64
    assert {row["forecastHorizon"] for row in
            projection["issuedDecisions"]} == {"1d", "3d", "5d"}
    assert projection["outcomeTruthObservations"]
    assert projection["outcomeTruthObservations"][0]["factType"] == "OHLCV_BAR"


def test_future_quote_timestamp_is_excluded_not_rounded_to_fresh():
    future = _jquants_row(
        sourceTimestamp="2026-08-14T07:00:00Z", date="2026-08-14")
    projection = _projection(
        quote_rows=[("JP", "jquants", future)])
    assert projection["status"] == "INCOMPLETE"
    assert projection["issuedDecisions"] == []


def test_provider_candidates_and_disagreement_survive_scanner_adapter():
    row = _jquants_row(
        selectionPolicyId="jp-moomoo-jquants-v1",
        providerCandidates=[
            {"value": 2810.0, "source": "moomoo-rt",
             "sourceTimestamp": "2026-08-14T06:39:00Z",
             "receivedAt": DECISION_AT, "status": "live", "selected": True},
            {"value": 2800.0, "source": "jquants",
             "sourceTimestamp": "2026-08-14", "receivedAt": DECISION_AT,
             "status": "delayed", "selected": False},
        ])
    projection = _projection(
        quote_rows=[("JP", "moomoo-bridge", row)])
    selection = projection["marketTruthSnapshot"]["selections"][0]
    assert selection["selected"]["observation"]["source"][
        "providerKey"] == "moomoo"
    assert selection["alternates"][0]["observation"]["source"][
        "providerKey"] == "jquants"
    assert selection["disagreement"]["status"] == "PRESENT"
    assert all(item["dissent"] == ["provider_disagreement:PRESENT"]
               for item in projection["issuedDecisions"])


def test_official_close_is_explicit_delayed_and_runner_eligible_at_1605_jst():
    decision_at = "2026-08-14T07:05:00Z"  # 16:05 JST, 35m after close
    projection = _projection(
        quote_rows=[("JP", "jquants", _jquants_row(
            # Cached just after close; freshness must still be evaluated at the
            # later decision cutoff rather than frozen at receipt.
            receivedAt="2026-08-14T06:31:00Z"))],
        decision_at=decision_at, generated_at="2026-08-14T07:05:01Z")

    assert projection["status"] == "COMPLETE"
    assert projection["truthQualityComplete"] is True
    selection = projection["marketTruthSnapshot"]["selections"][0]
    assert selection["freshness"] == argus_market_data_truth.DELAYED
    assert selection["completeness"] == argus_market_data_truth.COMPLETE
    assert len(projection["issuedDecisions"]) == 3
    assert all(row["missingEvidence"] == []
               for row in projection["issuedDecisions"])
    context = run_prediction_ledger._validate_input(
        {"asOf": decision_at, "generatedAt": "2026-08-14T07:05:01Z",
         "canonicalPredictionLedger": projection},
        expected_mode="forward_live", runner_build_sha="b" * 40)
    assert len(context["decisions"]) == 3


def test_stale_quote_is_never_admitted_to_canonical_predictions():
    decision_at = "2026-08-16T19:00:00Z"
    projection = _projection(
        quote_rows=[("JP", "jquants", _jquants_row(
            receivedAt=decision_at))],
        decision_at=decision_at, generated_at="2026-08-16T19:00:01Z")
    assert projection["status"] == "INCOMPLETE"
    assert projection["truthQualityComplete"] is False
    assert projection["issuedDecisions"] == []


def test_mock_provider_alternate_never_enters_truth_or_dissent():
    row = _jquants_row(
        source="moomoo-rt",
        sourceTimestamp="2026-08-14T06:39:00Z",
        providerCandidates=[
            {"value": 2810.0, "source": "moomoo-rt",
             "sourceTimestamp": "2026-08-14T06:39:00Z",
             "receivedAt": DECISION_AT, "status": "live", "selected": True},
            # Display-only fallback: no independent source timestamp or receipt.
            {"value": 9999.0, "source": "jquants", "status": "mock",
             "selected": False},
        ])
    projection = _projection(
        quote_rows=[("JP", "moomoo-bridge", row)])
    selection = projection["marketTruthSnapshot"]["selections"][0]
    assert projection["status"] == "COMPLETE"
    assert selection["alternates"] == []
    assert selection["candidateCount"] == 1
    assert selection["disagreement"]["status"] == "NONE"
    assert all(item["dissent"] == []
               for item in projection["issuedDecisions"])


def test_unavailable_or_unclassified_alternate_cannot_borrow_parent_truth():
    row = _jquants_row(
        source="moomoo-rt", sourceTimestamp="2026-08-14T06:39:00Z",
        providerCandidates=[
            {"value": 2810.0, "source": "moomoo-rt",
             "sourceTimestamp": "2026-08-14T06:39:00Z",
             "receivedAt": DECISION_AT, "status": "live", "selected": True},
            {"value": 2800.0, "source": "jquants",
             "sourceTimestamp": "2026-08-14", "receivedAt": DECISION_AT,
             "status": "unavailable", "selected": False},
            {"value": 2790.0, "source": "twelvedata",
             "sourceTimestamp": "2026-08-14T06:38:00Z",
             "receivedAt": DECISION_AT, "selected": False},
            # A nominally-live alternate cannot borrow the parent row's source
            # timestamp, receipt instant, or provider identity.
            {"value": 2780.0, "source": "finnhub", "status": "live",
             "selected": False},
            {"value": 2770.0, "sourceTimestamp": "2026-08-14T06:37:00Z",
             "receivedAt": DECISION_AT, "status": "live", "selected": False},
        ])
    projection = _projection(quote_rows=[("JP", "moomoo-bridge", row)])
    selection = projection["marketTruthSnapshot"]["selections"][0]
    assert projection["status"] == "COMPLETE"
    assert selection["candidateCount"] == 1
    assert selection["alternates"] == []
    assert selection["disagreement"]["status"] == "NONE"


def test_legacy_action_cannot_change_canonical_prediction_identity():
    wait = _legacy_prediction()
    wait["action"] = "WAIT"
    buy = _legacy_prediction()
    buy["action"] = "BUY"
    left = _projection(legacy_rows=[("tactical_rule", wait)])
    right = _projection(legacy_rows=[("tactical_rule", buy)])

    assert left["status"] == right["status"] == "COMPLETE"
    assert [row["id"] for row in left["issuedDecisions"]] == [
        row["id"] for row in right["issuedDecisions"]]
    assert [row["integrityHash"] for row in left["issuedDecisions"]] == [
        row["integrityHash"] for row in right["issuedDecisions"]]
    assert all(row["candidateAction"] == ""
               for row in left["issuedDecisions"] + right["issuedDecisions"])


def test_cached_history_keeps_actual_cache_knowledge_time_and_partial_ohlc():
    previous = copy.deepcopy(scanner._JQ_HISTORY_CACHE)
    try:
        acquired = 1_776_000_000.0
        scanner._JQ_HISTORY_CACHE.clear()
        scanner._JQ_HISTORY_CACHE["7203"] = {
            "expires": acquired + scanner._JQ_HISTORY_TTL,
            "data": {
                "dates": ["2026-04-12"], "opens": [100.0],
                "highs": [None], "lows": [98.0], "closes": [101.0],
                "volumes": [1000],
            },
        }
        rows = scanner._canonical_history_observations(
            [("JP", "7203")], DECISION_AT)
        assert len(rows) == 1
        assert rows[0]["completeness"] == "PARTIAL"
        assert rows[0]["missingFields"] == ["high"]
        assert rows[0]["knownAt"] != DECISION_AT
    finally:
        scanner._JQ_HISTORY_CACHE.clear()
        scanner._JQ_HISTORY_CACHE.update(previous)


def test_chart_cache_import_is_bound_to_acquisition_not_backdated_bar_date():
    previous = copy.deepcopy(scanner._JQ_HISTORY_CACHE)
    try:
        acquired = scanner.time.time() - 10.0
        scanner._JQ_HISTORY_CACHE.clear()
        scanner._JQ_HISTORY_CACHE["7203"] = {
            "expires": acquired + scanner._JQ_HISTORY_TTL,
            "data": {
                "dates": ["2026-04-12"], "opens": [100.0],
                "highs": [102.0], "lows": [98.0], "closes": [101.0],
                "volumes": [1000], "adjusted": [True],
            },
        }
        rows = scanner._chart_history_cached("7203", "JP")
        assert len(rows) == 1
        expected_known = scanner._canonical_truth_iso(acquired, "JP")
        assert rows[0]["knownAt"] == expected_known
        assert rows[0]["knownAt"] != rows[0]["date"]
        assert rows[0]["datasetId"].startswith("jquants:7203:")
        before = scanner._canonical_truth_iso(acquired - 1, "JP")
        after = scanner._canonical_truth_iso(acquired + 1, "JP")
        assert argus_market_data_truth.point_in_time_rows(rows, before)[0] == []
        admitted, proof = argus_market_data_truth.point_in_time_rows(rows, after)
        assert len(admitted) == 1
        assert argus_market_data_truth.verify_point_in_time_proof(proof)[0]
    finally:
        scanner._JQ_HISTORY_CACHE.clear()
        scanner._JQ_HISTORY_CACHE.update(previous)


def test_optional_projection_failure_has_no_legacy_route_side_effect():
    with mock.patch.object(
            scanner.argus_market_data_truth, "build_decision_snapshot",
            side_effect=ValueError("fixture")):
        projection = _projection()
    assert projection["status"] == "INCOMPLETE"
    assert projection["issuedDecisions"] == []


def test_missing_exact_build_identity_issues_no_forward_live_record():
    with mock.patch.object(scanner, "_backend_exact_sha", return_value=None):
        projection = scanner._canonical_prediction_ledger_projection(
            legacy_rows=[("tactical_rule", _legacy_prediction())],
            quote_rows=[("JP", "jquants", _jquants_row())],
            decision_at=DECISION_AT, generated_at=GENERATED_AT,
            engine_version="fixture-v1")
    assert projection["status"] == "INCOMPLETE"
    assert projection["reason"] == "build_identity_unavailable"
    assert projection["marketTruthSnapshot"] is None
    assert projection["issuedDecisions"] == []


def test_snapshot_request_overflow_is_bounded_visible_and_incomplete():
    legacy_rows = []
    quote_rows = []
    for index in range(argus_market_data_truth.MAX_SNAPSHOT_REQUESTS + 1):
        symbol = str(1000 + index)
        legacy_rows.append(("tactical_rule", {
            **_legacy_prediction(), "symbol": symbol, "price": 100.0,
        }))
        quote_rows.append(("JP", "jquants", _jquants_row(
            symbol=symbol, price=100.0, close=100.0, open=99.0,
            high=101.0, low=98.0)))
    projection = _projection(legacy_rows=legacy_rows, quote_rows=quote_rows)
    assert projection["status"] == "INCOMPLETE"
    assert projection["marketTruthSnapshotVerified"] is True
    assert len(projection["marketTruthSnapshot"]["selections"]) == \
        argus_market_data_truth.MAX_SNAPSHOT_REQUESTS
    assert projection["sourceCandidateCount"] == 65
    assert projection["candidateCount"] == 195
    assert projection["issuedCount"] == 192
    assert projection["omittedCandidateCount"] == 1
    assert len(projection["omittedCandidateIds"]) == 1
    assert projection["omittedCandidateIdsTruncated"] is False


def test_duplicate_source_candidates_are_deterministically_bounded():
    legacy_rows = [("tactical_rule", _legacy_prediction())
                   for _ in range(100)]
    projection = _projection(legacy_rows=legacy_rows)
    assert projection["status"] == "INCOMPLETE"
    assert projection["sourceCandidateCount"] == 100
    assert projection["candidateCount"] == 300
    assert projection["issuedCount"] == 192
    assert len(projection["issuedDecisions"]) == 192
    assert projection["omittedCandidateCount"] == 36
    assert len(projection["omittedCandidateIds"]) == 36
