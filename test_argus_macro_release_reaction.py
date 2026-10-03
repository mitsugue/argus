"""Pre-release baseline, post-release windows and the deterministic reading."""
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
        def json(self): return _payload(prices[self.symbol]) if self.symbol in prices else {"chart": {"result": []}}
    return rr.capture(lambda url, **k: Response(url.rsplit("/", 1)[1]), received_epoch=epoch)


BEFORE = {"ZQ=F": 96.05, "ZT=F": 101.82, "ZN=F": 104.61, "NQ=F": 26800.0, "ES=F": 7650.0,
          "NKD=F": 68500.0, "JPY=X": 157.5, "^VIX": 16.0}
AFTER = {"ZQ=F": 96.075, "ZT=F": 101.95, "ZN=F": 105.02, "NQ=F": 27030.0, "ES=F": 7690.0,
         "NKD=F": 69300.0, "JPY=X": 157.9, "^VIX": 15.3}


def test_quote_parse_rejects_missing_price_or_time():
    assert rr.parse_quote(_payload(96.05), received_epoch=1790945000)["price"] == 96.05
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
    assert rr.reading({"ffImpliedRateMoveBp": None, "nasdaqFuturesMovePct": 0.6})["code"] == "RISK_ON"
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
