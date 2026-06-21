"""Unit tests for the 24/7 event backbone pure foundation (argus_events.py).
Hermetic — no network, no clock dependency (datetimes are passed in)."""
from datetime import datetime, timedelta, timezone

import pytest

import argus_events as ev

JST = timezone(timedelta(hours=9))


def _jst(h, m, wd_monday=True):
    # 2026-06-22 is a Monday; 2026-06-20 is a Saturday.
    day = 22 if wd_monday else 20
    return datetime(2026, 6, day, h, m, tzinfo=JST)


# ── TSE price-limit table + S高/S安 ──────────────────────────────────────────
def test_tse_price_limit_bands():
    assert ev.tse_price_limit(80) == 30
    assert ev.tse_price_limit(1200) == 300       # 1000–1500 band
    assert ev.tse_price_limit(2776) == 500       # 2000–3000 (Toyota-ish)
    assert ev.tse_price_limit(0) is None
    assert ev.tse_price_limit(None) is None


def test_special_quote_proximity_limit_up():
    # prev 1000 → limit ±300 → up=1300. Price at 1300 = S高.
    sq = ev.special_quote_proximity(1300, 1000)
    assert sq["atLimitUp"] and sq["proximity"] == 1.0 and sq["limitYen"] == 300
    near = ev.special_quote_proximity(1240, 1000)   # 80% toward up
    assert not near["atLimitUp"] and near["proximity"] == 0.8


def test_detect_limit_up_event():
    q = {"market": "JP", "symbol": "9999", "price": 1300, "changePct": 30.0}
    trigs = ev.detect_anomalies(q, "JP_MORNING", prev_close=1000)
    types = {t["type"] for t in trigs}
    assert "LIMIT_UP" in types
    assert any(t["severity"] == 5 for t in trigs if t["type"] == "LIMIT_UP")


def test_detect_limit_proximity_approaching():
    # 80% toward the upper limit → LIMIT_UP_PROXIMITY (NOT mislabeled 特別気配).
    q = {"market": "JP", "symbol": "9999", "price": 1240, "changePct": 24.0}
    trigs = ev.detect_anomalies(q, "JP_MORNING", prev_close=1000)
    assert any(t["type"] == "LIMIT_UP_PROXIMITY" for t in trigs)
    assert not any("SPECIAL_QUOTE" in t["type"] for t in trigs)
    # afternoon session now correctly runs to 15:25 (closing auction 15:25–15:30)
    from datetime import datetime, timezone, timedelta
    jst = timezone(timedelta(hours=9))
    assert ev.session_label(datetime(2026, 6, 22, 15, 20, tzinfo=jst)) == "JP_AFTERNOON"
    assert ev.session_label(datetime(2026, 6, 22, 15, 27, tzinfo=jst)) == "JP_PRE_CLOSE"


# ── Session-aware anomaly thresholds ─────────────────────────────────────────
def test_spike_is_session_aware():
    q = {"market": "JP", "symbol": "7203", "changePct": 6.0}
    # 6% trips the regular-session 5% wire...
    assert any(t["type"] == "PRICE_SPIKE" for t in ev.detect_anomalies(q, "JP_MORNING"))
    # ...but NOT the thin-liquidity overnight 8% wire.
    assert not any(t["type"] == "PRICE_SPIKE" for t in ev.detect_anomalies(q, "OVERNIGHT_GLOBAL"))


def test_crash_and_volume_and_flow():
    q = {"market": "JP", "symbol": "7203", "changePct": -7.0, "volRatio": 3.0, "flowRatio": -0.30}
    types = {t["type"] for t in ev.detect_anomalies(q, "JP_AFTERNOON")}
    assert {"PRICE_CRASH", "VOLUME_ANOMALY", "FLOW_ANOMALY"} <= types


def test_quiet_quote_produces_nothing():
    q = {"market": "JP", "symbol": "7203", "changePct": 0.4, "volRatio": 1.1, "flowRatio": 0.02}
    assert ev.detect_anomalies(q, "JP_MORNING") == []


# ── Crypto 24/7 shock (no session gating) ────────────────────────────────────
def test_crypto_shock_detection():
    assert ev.detect_crypto_anomaly("BTC", 2.0) == []                 # quiet → nothing
    big = ev.detect_crypto_anomaly("BTC", -8.3)
    assert big and big[0]["type"] == "CRYPTO_SHOCK" and big[0]["severity"] == 4
    sev = ev.detect_crypto_anomaly("ETH", 12.5)
    assert sev[0]["severity"] == 5 and "急騰" in sev[0]["reasonJa"]
    assert ev.detect_crypto_anomaly("BTC", None) == []                # bad input safe


# ── Session labels ───────────────────────────────────────────────────────────
def test_session_labels():
    assert ev.session_label(_jst(10, 0)) == "JP_MORNING"
    assert ev.session_label(_jst(12, 0)) == "JP_LUNCH"
    assert ev.session_label(_jst(14, 30)) == "JP_AFTERNOON"
    assert ev.session_label(_jst(2, 0)) == "OVERNIGHT_GLOBAL"
    assert ev.session_label(_jst(10, 0, wd_monday=False)) == "WEEKEND"


# ── EventEnvelope normalization (event time vs ingest time) ───────────────────
def test_make_envelope_separates_times_and_dedups():
    now = _jst(10, 1)
    pub = _jst(10, 0)
    trig = ev._trig("PRICE_SPIKE", 4, 0.8, "急騰 +6%")
    e = ev.make_envelope(event_type="PRICE_SPIKE", symbol="7203", market="JP",
                         source="moomoo-bridge", trigger=trig, now=now,
                         published_at=pub, next_open=_jst(15, 30))
    assert e["schemaVersion"] == "event-v1"
    assert e["lifecycleState"] == "DETECTED" and e["currentGear"] == 0
    assert e["detectedAt"] != e["publishedAt"]          # times kept separate
    assert e["ingestAt"] is None                        # stamped later by the store
    assert e["session"] == "JP_MORNING" and e["severity"] == 4
    assert e["deduplicationKey"].startswith("JP:7203:PRICE_SPIKE:")


def test_capability_gated_pts_rejected():
    with pytest.raises(ValueError):
        ev.make_envelope(event_type="PTS_ANOMALY", symbol="7203", market="JP",
                         source="x", trigger=ev._trig("PTS_ANOMALY", 3, 0.5, "x"), now=_jst(20, 0))


# ── State machine + revisions ────────────────────────────────────────────────
def test_legal_and_illegal_transitions():
    assert ev.can_transition("DETECTED", "VERIFYING")
    assert ev.can_transition("VERIFIED", "HIGH_ALERT")
    assert not ev.can_transition("DETECTED", "CRITICAL")       # must pass through
    assert not ev.can_transition("RESOLVED", "HIGH_ALERT")     # terminal is final


def test_apply_transition_makes_new_revision():
    now = _jst(10, 1)
    e = ev.make_envelope(event_type="PRICE_SPIKE", symbol="7203", market="JP",
                         source="bridge", trigger=ev._trig("PRICE_SPIKE", 4, 0.8, "x"), now=now)
    v2 = ev.apply_transition(e, "VERIFYING", _jst(10, 2), reason="source ok")
    assert v2["eventVersion"] == 2 and v2["lifecycleState"] == "VERIFYING"
    assert v2["prevLifecycleState"] == "DETECTED"
    assert e["lifecycleState"] == "DETECTED"               # original NOT mutated
    with pytest.raises(ValueError):
        ev.apply_transition(e, "CRITICAL", now)            # illegal


# ── Dedup / idempotency / priority / notification dedup ──────────────────────
def test_dedup_key_buckets_same_anomaly():
    a = ev.dedup_key("JP", "7203", "PRICE_SPIKE", now=_jst(10, 1))
    b = ev.dedup_key("JP", "7203", "PRICE_SPIKE", now=_jst(10, 20))   # same 30m bucket
    c = ev.dedup_key("JP", "7203", "PRICE_SPIKE", now=_jst(11, 5))    # next bucket
    assert a == b and a != c


def test_priority_orders_by_severity_and_urgency():
    hi = {"severity": 5, "triggerScore": 0.9, "timeToNextOpenMin": 0}
    lo = {"severity": 2, "triggerScore": 0.3, "timeToNextOpenMin": 600}
    assert ev.priority_score(hi) > ev.priority_score(lo)


def test_notification_transition_dedup():
    base = {"lifecycleState": "VERIFIED", "severity": 3, "recommendedPosture": "WATCH"}
    assert ev.should_notify(None, base)[0]                                 # initial
    assert not ev.should_notify(base, dict(base))[0]                       # no change
    assert ev.should_notify(base, {**base, "lifecycleState": "HIGH_ALERT"})[0]
    assert ev.should_notify(base, {**base, "severity": 4})[0]              # +1 severity
    assert not ev.should_notify(base, {**base, "severity": 3})[0]
