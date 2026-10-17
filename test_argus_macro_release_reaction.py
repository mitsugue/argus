"""Pre-release baseline, post-release windows and the deterministic reading."""
from copy import deepcopy

import pytest
from datetime import datetime, timedelta, timezone

import argus_macro_release_reaction as rr

T = datetime(2026, 10, 2, 12, 30, tzinfo=timezone.utc)
E = lambda minutes: (T + timedelta(minutes=minutes)).timestamp()      # epoch relative to the release


def _payload(price, traded=1790945400):
    return {"chart": {"result": [{"meta": {"regularMarketPrice": price, "regularMarketTime": traded}}]}}


def _capture(prices, epoch):
    class Response:
        status_code = 200
        def __init__(self, symbol): self.symbol = symbol
        def json(self): return _payload(prices[self.symbol], traded=epoch) if self.symbol in prices else {"chart": {"result": []}}
    return rr.capture(lambda url, **k: Response(url.rsplit("/", 1)[1]), received_epoch=epoch, clock=lambda: epoch)


BEFORE = {"ZQ=F": 96.05, "ZT=F": 101.82, "ZN=F": 104.61, "NQ=F": 26800.0, "ES=F": 7650.0,
          "NKD=F": 68500.0, "JPY=X": 157.5, "^VIX": 16.0}
AFTER = {"ZQ=F": 96.075, "ZT=F": 101.95, "ZN=F": 105.02, "NQ=F": 27030.0, "ES=F": 7690.0,
         "NKD=F": 69300.0, "JPY=X": 157.9, "^VIX": 15.3}


def test_quote_parse_rejects_missing_price_or_time():
    assert rr.parse_quote(_payload(96.05), received_epoch=1790945400)["price"] == 96.05
    assert rr.parse_quote(_payload(None), received_epoch=1) is None
    assert rr.parse_quote(_payload(96.05, traded=None), received_epoch=1) is None
    assert rr.parse_quote({"chart": {"result": []}}, received_epoch=1) is None


def test_capture_lists_failures_instead_of_inventing_values():
    partial = dict(BEFORE); partial.pop("NKD=F")
    base = _capture(partial, E(-15))
    assert set(base["values"]) == set(partial) and base["missing"] == ["NKD=F"]
    assert base["capturedAt"] == "2026-10-02T12:15:00Z" and base["source"].startswith("Yahoo")


def test_windows_open_only_at_their_minute_and_once():
    assert not rr.baseline_due(T, T - timedelta(minutes=16))
    assert rr.baseline_due(T, T - timedelta(minutes=15))
    assert rr.baseline_due(T, T - timedelta(minutes=2))
    assert not rr.baseline_due(T, T - timedelta(minutes=1))
    assert rr.window_due(T, T + timedelta(minutes=4), {}) is None
    assert rr.window_due(T, T + timedelta(minutes=5), {}) == "+5m"
    assert rr.window_due(T, T + timedelta(minutes=9), {}) == "+5m"
    assert rr.window_due(T, T + timedelta(minutes=10), {}) is None       # grace over, not captured
    assert rr.window_due(T, T + timedelta(minutes=31), {"+5m": 1}) == "+30m"
    assert rr.window_due(T, T + timedelta(minutes=31), {"+5m": 1, "+30m": 1}) is None
    assert rr.window_due(T, T + timedelta(minutes=62), {"+30m": 1}) == "+60m"
    assert rr.window_due(T, T + timedelta(hours=8, minutes=20), {"+5m": 1, "+30m": 1, "+60m": 1}) == "+8h"
    assert rr.window_due(T, T + timedelta(hours=8, minutes=31), {}) is None


def test_moves_and_reading_follow_the_jobs_report_night():
    base = _capture(BEFORE, E(-15)); after = _capture(AFTER, E(30))
    move = rr.moves(base, after)
    assert move["ffImpliedRateMoveBp"] == -2.5
    assert move["ffImpliedRateBeforePct"] == 3.95 and move["ffImpliedRateAfterPct"] == 3.925
    assert abs(move["nasdaqFuturesMovePct"] - 0.86) < 0.01 and abs(move["vixMovePct"] + 4.37) < 0.02
    assert abs(move["nikkeiFuturesMovePct"] - 1.17) < 0.01
    assert abs(move["us10yFuturesMovePct"] - 0.39) < 0.01      # price up = yield down
    read = rr.reading(move)
    assert read["code"] == "RATE_RELIEF_RISK_ON" and "利上げ観測の後退" in read["labelJa"]


def test_reading_distinguishes_growth_scare_and_hawkish_cases():
    assert rr.reading({"ffImpliedRateMoveBp": -3.0, "nasdaqFuturesMovePct": -1.2})["code"] == "GROWTH_SCARE"
    assert rr.reading({"ffImpliedRateMoveBp": 4.0, "nasdaqFuturesMovePct": -0.8})["code"] == "HAWKISH_RISK_OFF"
    assert rr.reading({"ffImpliedRateMoveBp": 2.0, "spFuturesMovePct": 0.5})["code"] == "HAWKISH_RISK_ON"
    assert rr.reading({"ffImpliedRateMoveBp": 0.5, "nasdaqFuturesMovePct": 0.1})["code"] == "FLAT"
    assert rr.reading({"ffImpliedRateMoveBp": 4.0, "nasdaqFuturesMovePct": 0.27})["code"] == "HAWKISH_FLAT"   # CPI 2026-09-11
    assert rr.reading({"ffImpliedRateMoveBp": -4.0, "nasdaqFuturesMovePct": -0.19})["code"] == "DOVISH_FLAT"
    assert rr.reading({"ffImpliedRateMoveBp": None, "nasdaqFuturesMovePct": 0.6})["code"] == "EQUITY_UP_POLICY_UNMEASURED"
    assert rr.reading({})["code"] == "UNMEASURED"


def test_record_and_prompt_carry_only_measured_numbers():
    base = _capture(BEFORE, E(-15))
    w5 = _capture(AFTER, E(5))
    rec = rr.build("us-nfp-2026-10-02", "2026-10-02T12:30:00Z", base, {"+5m": w5})
    assert rec["basis"] == "PRE_RELEASE_BASELINE" and rec["actionAuthority"] is False
    assert rec["latestWindow"] == "+5m" and rec["readingJa"].startswith("利上げ観測の後退")
    assert "政策金利の予想-2.5bp(3.950%→3.925%)" in rec["summaryJa"]
    text = rr.prompt_text_ja(rec, next_fomc="2026-10-28")
    assert "発表前の織り込み: FF金利先物の示す政策金利の予想 3.950%(次回FOMC 2026-10-28)" in text
    assert "他の数字を作らない" in text and "景気の良し悪しを断定しない" in text
    assert rr.prompt_text_ja(None) == "" and rr.prompt_text_ja(rr.build("x", None, None, {})) == ""
    missing = rr.build("x", None, None, {"+5m": w5})
    assert missing["readingJa"] == "反応を測れていない" and "基準値が取れていない" in missing["limitationsJa"][0]


@pytest.mark.parametrize("change", [
    {"tradedAt": (T + timedelta(minutes=1)).isoformat()},
    {"tradedAt": (T - timedelta(days=1)).isoformat()},
    {"tradedAt": "2026-10-02T12:28:00"},
    {"receivedAt": (T + timedelta(minutes=1)).isoformat()},
    {"receivedAt": None},
    {"price": float("inf")},
])
def test_invalid_baseline_clock_never_becomes_a_measured_policy_change(change):
    base = _capture(BEFORE, E(-2)); after = _capture(AFTER, E(5))
    for quote in base["values"].values():
        quote.update(change)
    before_copy, after_copy = deepcopy(base), deepcopy(after)
    rec = rr.build("cpi-test", T.isoformat(), base, {"+5m": after})
    assert all(value is None for key, value in rec["windows"]["+5m"]["moves"].items()
               if "Move" in key)
    assert rec["windows"]["+5m"]["moves"]["ffImpliedRateBeforePct"] is None
    assert rec["readingJa"] == "反応を測れていない"
    assert "3.950%" not in rr.prompt_text_ja(rec)
    assert base == before_copy and after == after_copy
    assert rec["baseline"] == before_copy             # original evidence retained
    assert rec["baselineTimeRejections"]


@pytest.mark.parametrize("minute", [-1440, 1, 4, 10])
def test_source_quote_must_belong_to_five_minute_window_not_just_be_downloaded_then(minute):
    base = _capture(BEFORE, E(-2)); after = _capture(AFTER, E(5))
    for quote in after["values"].values():
        quote["tradedAt"] = (T + timedelta(minutes=minute)).isoformat()
    rec = rr.build("cpi-test", T.isoformat(), base, {"+5m": after})
    assert rec["windows"]["+5m"]["reading"]["code"] == "UNMEASURED"
    assert rec["windows"]["+5m"]["timeRejections"]
    assert rec["windows"]["+5m"]["values"] == after["values"]
    assert "政策金利の予想-2.5bp" not in rr.prompt_text_ja(rec)


def test_one_stale_asset_does_not_poison_valid_assets_or_invent_its_move():
    base = _capture(BEFORE, E(-2)); after = _capture(AFTER, E(5))
    after["values"]["ZQ=F"]["tradedAt"] = (T - timedelta(minutes=1)).isoformat()
    rec = rr.build("cpi-test", T.isoformat(), base, {"+5m": after})
    window = rec["windows"]["+5m"]
    assert window["moves"]["ffImpliedRateMoveBp"] is None
    assert window["moves"]["nasdaqFuturesMovePct"] == 0.86
    assert window["reading"]["code"] == "EQUITY_UP_POLICY_UNMEASURED"
    assert "利上げ観測は動かず" not in rr.prompt_text_ja(rec)
    assert "政策金利の変化は未取得" in rr.prompt_text_ja(rec)
    assert rec["actionAuthority"] is False


@pytest.mark.parametrize("name,minute", [("+5m", 5), ("+30m", 30), ("+60m", 60), ("+8h", 480)])
def test_correct_source_clocks_preserve_every_existing_window_and_formula(name, minute):
    base = _capture(BEFORE, E(-2)); after = _capture(AFTER, E(minute))
    rec = rr.build("cpi-test", T.isoformat(), base, {name: after})
    assert rec["windows"][name]["moves"]["ffImpliedRateMoveBp"] == -2.5
    assert rec["windows"][name]["reading"]["code"] == "RATE_RELIEF_RISK_ON"
    assert rec["windows"][name]["timeRejections"] == {}
    assert rec["baselineTimeRejections"] == {}


def test_rebuilt_old_prompt_rechecks_clocks_without_overwriting_saved_evidence():
    base = _capture(BEFORE, E(-2)); after = _capture(AFTER, E(5))
    rec = rr.build("cpi-test", T.isoformat(), base, {"+5m": after})
    for quote in rec["windows"]["+5m"]["values"].values():
        quote["tradedAt"] = (T - timedelta(days=1)).isoformat()
    rec["windows"]["+5m"]["summaryJa"] = "政策金利の予想-99.9bp"
    saved = deepcopy(rec)
    text = rr.prompt_text_ja(rec)
    assert "-99.9bp" not in text and "-2.5bp" not in text
    assert "反応を測れていない" in text and rec == saved


def test_capture_records_response_completion_and_closes_all_responses():
    clocks = iter([E(-1), E(1), E(2)])
    responses = []
    class Response:
        status_code = 200
        closed = False
        def json(self):
            return _payload(100, traded=E(0))
        def close(self):
            self.closed = True
    def get(*args, **kwargs):
        response = Response(); responses.append(response); return response
    batch = rr.capture(get, received_epoch=E(-2), symbols={"ES=F": {}, "NQ=F": {}},
                       clock=lambda: next(clocks))
    assert batch["captureStartedAt"] == (T - timedelta(minutes=2)).isoformat().replace("+00:00", "Z")
    assert batch["capturedAt"] == (T + timedelta(minutes=2)).isoformat().replace("+00:00", "Z")
    assert "ES=F" in batch["missing"]              # source time later than actual receipt
    assert batch["values"]["NQ=F"]["receivedAt"] == (T + timedelta(minutes=1)).isoformat().replace("+00:00", "Z")
    assert all(response.closed for response in responses)
    usable, rejected = rr.comparison_quotes(batch, T)
    assert usable == {} and rejected             # batch crossed release: no baseline claim


@pytest.mark.parametrize("traded", [True, float("inf"), float("nan"), 1e300, E(6)])
def test_unusable_source_epochs_are_rejected_without_timestamp_exceptions(traded):
    assert rr.parse_quote(_payload(100, traded=traded), received_epoch=E(5)) is None



def test_different_provider_is_rejected_again_when_prompt_rebuilds_old_window():
    base = _capture(BEFORE, E(-2)); after = _capture(AFTER, E(5))
    after["source"] = "another-provider"
    rec = rr.build("cpi-test", T.isoformat(), base, {"+5m": after})
    assert rec["windows"]["+5m"]["reading"]["code"] == "UNMEASURED"
    assert "-2.5bp" not in rr.prompt_text_ja(rec)


def test_batch_start_and_each_quote_receipt_cannot_run_backwards():
    base = _capture(BEFORE, E(-2))
    base["captureStartedAt"] = (T - timedelta(minutes=1)).isoformat()
    assert rr.comparison_quotes(base, T)[0] == {}


@pytest.mark.parametrize("policy,equity,code,missing", [
    (None, 0.6, "EQUITY_UP_POLICY_UNMEASURED", "政策金利の変化は未取得"),
    (None, -0.6, "EQUITY_DOWN_POLICY_UNMEASURED", "政策金利の変化は未取得"),
    (None, 0.1, "EQUITY_FLAT_POLICY_UNMEASURED", "政策金利の変化は未取得"),
    (4, None, "POLICY_UP_EQUITY_UNMEASURED", "株価の反応は未取得"),
    (-4, None, "POLICY_DOWN_EQUITY_UNMEASURED", "株価の反応は未取得"),
    (0.5, None, "POLICY_FLAT_EQUITY_UNMEASURED", "株価の反応は未取得"),
])
def test_partial_reaction_does_not_describe_missing_measurement_as_flat(policy, equity, code, missing):
    actual = rr.reading({"ffImpliedRateMoveBp": policy, "nasdaqFuturesMovePct": equity})
    assert actual["code"] == code
    assert missing in actual["labelJa"]
    assert "測れていない" in actual["meaningJa"]
    assert "株はまだ反応していない" not in actual["meaningJa"]
    assert "政策金利の予想は変わらず" not in actual["meaningJa"]


@pytest.mark.parametrize("start", ["not-a-time", "2026-10-02T12:35:00", "2026-10-02T12:36:00Z"])
def test_saved_window_keeps_invalid_collection_start_through_rebuild_and_prompt(start):
    base = _capture(BEFORE, E(-2)); after = _capture(AFTER, E(5))
    after["captureStartedAt"] = start
    rec = rr.build("cpi-test", T.isoformat(), base, {"+5m": after})
    original = deepcopy(rec)
    assert rec["windows"]["+5m"]["captureStartedAt"] == start
    assert rr.stored_window_captures(rec)["+5m"]["captureStartedAt"] == start
    rebuilt = rr.revalidate(rec)
    assert rebuilt["windows"]["+5m"]["reading"]["code"] == "UNMEASURED"
    assert "政策金利の予想-2.5bp" not in rr.prompt_text_ja(rec)
    assert rec == original


def test_provider_evidence_missing_cannot_be_promoted_from_top_level_constant():
    base = _capture(BEFORE, E(-2)); after = _capture(AFTER, E(5))
    rec = rr.build("cpi-test", T.isoformat(), base, {"+5m": after})
    rec["windows"]["+5m"].pop("source")
    original = deepcopy(rec)
    assert rr.revalidate(rec)["windows"]["+5m"]["reading"]["code"] == "UNMEASURED"
    assert "政策金利の予想-2.5bp" not in rr.prompt_text_ja(rec)
    assert rec == original


def test_revalidated_valid_record_preserves_formula_reading_and_original_evidence():
    rec = rr.build("cpi-test", T.isoformat(), _capture(BEFORE, E(-2)),
                   {name: _capture(AFTER, E(minute)) for name, minute in
                    [("+5m",5),("+30m",30),("+60m",60),("+8h",480)]})
    original = deepcopy(rec)
    assert rr.revalidate(rec) == rec
    assert rec == original


def test_large_integer_price_is_invalid_instead_of_overflowing_revalidation():
    assert rr.parse_quote(_payload(10**1000, E(5)), received_epoch=E(5)) is None
