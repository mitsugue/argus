"""Source-authority gates for macro market-reaction inputs.

The macro reaction engine may only compare values whose provider/source time is
still decision-usable.  Transport receipt, cache residence, and a real numeric
value are deliberately insufficient on their own.
"""

from __future__ import annotations

from datetime import datetime, timezone
import time

import pytest

import argus_market_data_truth as truth
import scanner


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


def _isolate_other_snapshot_sources(monkeypatch) -> None:
    monkeypatch.setattr(scanner, "_quote_cached_only", lambda *_args: None)
    monkeypatch.setattr(scanner, "_CRYPTO_CACHE", {})


def _rate_row(*, value=4.25, observed_at, freshness=truth.FRESH,
              completeness=truth.COMPLETE):
    return {
        "latestValue": value,
        "observedAt": observed_at,
        "sourceTimestamp": observed_at,
        "freshness": freshness,
        "completeness": completeness,
    }


def _cached_rate_values(monkeypatch, data, *, expires_in=60.0):
    _isolate_other_snapshot_sources(monkeypatch)
    monkeypatch.setattr(
        scanner,
        "_RATES_CACHE",
        {"data": data, "expires": time.time() + expires_in},
    )
    return scanner._market_snapshot_values(cached_only=True)


def test_market_snapshot_accepts_exact_fresh_and_bounded_delayed_complete_rates(
        monkeypatch):
    now = time.time()
    delayed_date = datetime.fromtimestamp(
        now - 2 * 24 * 3600, timezone.utc).strftime("%Y-%m-%d")
    values = _cached_rate_values(monkeypatch, {
        "us10y": _rate_row(value=4.31, observed_at=_iso(now - 30)),
        "vix": _rate_row(value=18.2, observed_at=_iso(now - 45)),
        "usdJpy": _rate_row(
            value=147.6,
            observed_at=delayed_date,
            freshness=truth.DELAYED,
        ),
    })

    assert values == {"us10y": 4.31, "usdJpy": 147.6, "vix": 18.2}


@pytest.mark.parametrize(
    ("mutation", "label"),
    [
        ({"freshness": truth.STALE}, "canonical stale"),
        ({"freshness": truth.DELAYED,
          "observedAt": "OLD", "sourceTimestamp": "OLD"},
         "delayed beyond bound"),
        ({"observedAt": "FUTURE", "sourceTimestamp": "FUTURE"},
         "future source time"),
        ({"observedAt": "not-a-timestamp",
          "sourceTimestamp": "not-a-timestamp"}, "malformed source time"),
        ({"observedAt": None, "sourceTimestamp": None}, "missing source time"),
        ({"completeness": truth.PARTIAL}, "incomplete"),
        ({"completeness": truth.MISSING}, "missing"),
        ({"latestValue": True}, "boolean value"),
        ({"latestValue": "4.25"}, "coerced string value"),
        ({"latestValue": float("nan")}, "non-finite value"),
    ],
    ids=lambda value: value if isinstance(value, str) else None,
)
def test_market_snapshot_rejects_non_authoritative_rate_rows(
        monkeypatch, mutation, label):
    del label
    now = time.time()
    mutation = {
        key: (_iso(now - 8 * 24 * 3600) if value == "OLD" else
              _iso(now + 60) if value == "FUTURE" else value)
        for key, value in mutation.items()
    }
    row = _rate_row(value=4.25, observed_at=_iso(now - 30))
    row.update(mutation)

    assert "us10y" not in _cached_rate_values(
        monkeypatch, {"us10y": row})


def test_market_snapshot_rejects_valid_rate_from_expired_cache(monkeypatch):
    now = time.time()
    values = _cached_rate_values(
        monkeypatch,
        {"us10y": _rate_row(value=4.25, observed_at=_iso(now - 30))},
        expires_in=-1.0,
    )

    assert "us10y" not in values


def _crypto_row(*, source="coingecko", price=65_000.0, source_timestamp,
                status="live", realtime_evidence=True):
    return {
        "id": "bitcoin",
        "priceUsd": price,
        "source": source,
        "sourceTimestamp": source_timestamp,
        "status": status,
        "freshness": "fresh" if status == "live" else "delayed",
        "delayClass": "LIVE" if status == "live" else "UNKNOWN",
        "realtimeEvidence": realtime_evidence,
    }


def _cached_crypto_values(monkeypatch, row, *, expires_in=60.0):
    monkeypatch.setattr(scanner, "_quote_cached_only", lambda *_args: None)
    monkeypatch.setattr(
        scanner,
        "_RATES_CACHE",
        {"data": None, "expires": 0.0},
    )
    monkeypatch.setattr(scanner, "_CRYPTO_CACHE", {
        ("bitcoin",): {
            "data": {"status": row.get("status"), "quotes": [row]},
            "expires": time.time() + expires_in,
        },
    })
    return scanner._market_snapshot_values(cached_only=True)


def test_market_snapshot_accepts_only_current_exact_coingecko_btc(monkeypatch):
    row = _crypto_row(source_timestamp=_iso(time.time() - 30))

    assert _cached_crypto_values(monkeypatch, row)["btc"] == 65_000.0


@pytest.mark.parametrize(
    ("row_factory", "label"),
    [
        (lambda now: _crypto_row(
            source="coinbase", source_timestamp=None, status="delayed",
            realtime_evidence=False), "Coinbase missing source time"),
        (lambda now: _crypto_row(
            source_timestamp=_iso(
                now - scanner._DECISION_QUOTE_LIVE_MAX_AGE_SEC - 1)),
         "stale CoinGecko"),
        (lambda now: _crypto_row(source_timestamp=_iso(now + 60)),
         "future CoinGecko"),
        (lambda now: _crypto_row(source_timestamp="not-a-timestamp"),
         "malformed CoinGecko timestamp"),
        (lambda now: _crypto_row(
            source_timestamp=None, status="mock", realtime_evidence=False),
         "mock crypto"),
        (lambda now: _crypto_row(
            price="65000", source_timestamp=_iso(now - 30)),
         "malformed crypto price"),
    ],
    ids=lambda value: value if isinstance(value, str) else None,
)
def test_market_snapshot_rejects_non_authoritative_crypto_rows(
        monkeypatch, row_factory, label):
    del label
    row = row_factory(time.time())

    assert "btc" not in _cached_crypto_values(monkeypatch, row)


def test_market_snapshot_rejects_current_crypto_from_expired_cache(monkeypatch):
    row = _crypto_row(source_timestamp=_iso(time.time() - 30))

    assert "btc" not in _cached_crypto_values(
        monkeypatch, row, expires_in=-1.0)


class _CoinbaseStatsResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {"last": "65000", "open": "64000", "volume": "123.5"}


def test_reachable_coinbase_fallback_cannot_create_btc_reaction_confirmation(
        monkeypatch):
    calls = []

    def fake_get(url, **_kwargs):
        calls.append(url)
        if url == scanner._COINGECKO_PRICE:
            raise RuntimeError("CoinGecko unavailable")
        assert url == scanner._COINBASE_STATS.format("BTC")
        return _CoinbaseStatsResponse()

    monkeypatch.setattr(scanner.requests, "get", fake_get)
    monkeypatch.setattr(scanner, "_CRYPTO_CACHE", {})
    monkeypatch.setattr(scanner, "get_rates_snapshot", lambda: {
        "us10y": _rate_row(
            value=4.10, observed_at=_iso(time.time() - 30)),
    })
    monkeypatch.setattr(scanner, "_quote_cached_only", lambda *_args: None)

    after = scanner._market_snapshot_values(cached_only=False)
    cached = scanner._CRYPTO_CACHE[("bitcoin",)]["data"]
    quote = cached["quotes"][0]

    assert calls == [
        scanner._COINGECKO_PRICE,
        scanner._COINBASE_STATS.format("BTC"),
    ]
    assert cached["provider"] == "coinbase"
    assert cached["status"] == "delayed"
    assert quote["sourceTimeStatus"] == "MISSING"
    assert quote["sourceTimestamp"] is None
    assert quote["realtimeEvidence"] is False
    assert "btc" not in after
    assert after["us10y"] == 4.10

    window = scanner.argus_macro_market_reaction.build_window(
        "same_day",
        {"btc": 64_000.0, "us10y": 4.00},
        after,
        _iso(time.time()),
    )
    assert window["btcMovePct"] is None
    assert window["us10yMoveBp"] == 10.0
    # One authoritative rates move remains below the two-signal confirmation
    # threshold; the source-time-less Coinbase number cannot become signal #2.
    assert window["marketConfirmed"] is False
    assert window["riskTone"] == "rates_up"
