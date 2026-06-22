"""ARGUS 24/7 Gear-Shift Event Backbone — pure foundation (v10.39, Phase 1).

Leaf-pure, stdlib-only domain layer for the event backbone: the EventEnvelope
schema, deterministic Gear-0/1 anomaly detection (price spike/crash, S高/S安
limit proximity via the TSE 制限値幅 table, volume surge, flow imbalance),
session labelling + session-aware thresholds, the lifecycle state machine,
dedup / novelty / priority, and notification-transition dedup.

NO Flask, NO network, NO LLM, NO module-level mutable state — so it is safe to
import anywhere and is exhaustively unit-tested (test_events.py). The Render
ingest/read endpoints (Phase 2) and the EC2 bridge detector (Phase 3) call
THESE functions; the brain lives here, deterministic and cheap, exactly as the
gear design requires (Gear 0/1 never touch an LLM).
"""
from datetime import datetime, timedelta, timezone

SCHEMA_VERSION = "event-v1"
TZ_JST = timezone(timedelta(hours=9))
TZ_ET = timezone(timedelta(hours=-4))   # ET (DST-approx; precise DST handled upstream)

# ── Event taxonomy (extensible) ──────────────────────────────────────────────
EVENT_TYPES = {
    "PRICE_SPIKE", "PRICE_CRASH", "LIMIT_UP_PROXIMITY", "LIMIT_DOWN_PROXIMITY",
    "LIMIT_UP", "LIMIT_DOWN",
    "VOLUME_ANOMALY", "FLOW_ANOMALY", "SHORT_COVERING_RISK", "DISTRIBUTION_RISK",
    "TRADING_HALT", "CORPORATE_DISCLOSURE", "EARNINGS", "GUIDANCE_REVISION",
    "NEWS_BREAK", "NEWS_REVISION", "FX_SHOCK", "RATE_SHOCK", "CREDIT_SHOCK",
    "COMMODITY_SHOCK", "CRYPTO_SHOCK", "CROSS_MARKET_ANOMALY", "PRE_MARKET_ANOMALY",
    "AFTER_HOURS_ANOMALY", "PTS_ANOMALY", "DATA_QUALITY_ALERT", "SOURCE_HEARTBEAT_FAILURE",
    "MOMENTUM_ACCELERATION", "FLOW_REVERSAL", "VOLUME_ACCELERATION",
    "MARKET_MOVER",   # market-WIDE gainer/loser (beyond the watchlist), v10.62
}


def detect_market_mover(symbol, change_pct, price, *, min_price=1.0,
                        gainer_pct=10.0, severe_pct=20.0):
    """Pure: a MARKET_MOVER trigger from a WHOLE-MARKET scan row (e.g. Alpha
    Vantage top gainers/losers). Filters penny-stock noise via min_price.
    severity 4 at gainer_pct, 5 at severe_pct. [] when below threshold/invalid."""
    if not isinstance(change_pct, (int, float)) or isinstance(change_pct, bool):
        return []
    if not isinstance(price, (int, float)) or isinstance(price, bool) or price < min_price:
        return []
    a = abs(change_pct)
    if a < gainer_pct:
        return []
    sev = 5 if a >= severe_pct else 4
    direction = "急騰" if change_pct > 0 else "急落"
    return [_trig("MARKET_MOVER", sev, min(1.0, a / severe_pct),
                  f"{symbol} 全市場{direction} {change_pct:+.1f}%(${price})")]


# Capability-gated: never emitted until a real provider is verified upstream.
CAPABILITY_GATED_TYPES = {"PTS_ANOMALY"}

# ── Lifecycle state machine ──────────────────────────────────────────────────
LIFECYCLE_STATES = {
    "DETECTED", "OBSERVING", "VERIFYING", "VERIFIED", "DEEP_SCAN_QUEUED",
    "DEEP_SCAN_RUNNING", "HIGH_ALERT", "CRITICAL", "PRE_MARKET_PLAN",
    "SESSION_REVIEW", "RESOLVED", "INVALIDATED", "EXPIRED", "FAILED",
}
_TERMINAL = {"RESOLVED", "INVALIDATED", "EXPIRED", "FAILED"}
ALLOWED_TRANSITIONS = {
    "DETECTED": {"OBSERVING", "VERIFYING", "INVALIDATED", "EXPIRED", "FAILED"},
    "OBSERVING": {"VERIFYING", "INVALIDATED", "EXPIRED", "FAILED"},
    "VERIFYING": {"VERIFIED", "OBSERVING", "INVALIDATED", "FAILED"},
    "VERIFIED": {"DEEP_SCAN_QUEUED", "HIGH_ALERT", "PRE_MARKET_PLAN", "SESSION_REVIEW",
                 "RESOLVED", "INVALIDATED", "EXPIRED"},
    "DEEP_SCAN_QUEUED": {"DEEP_SCAN_RUNNING", "INVALIDATED", "EXPIRED", "FAILED"},
    "DEEP_SCAN_RUNNING": {"HIGH_ALERT", "VERIFIED", "INVALIDATED", "RESOLVED", "FAILED"},
    "HIGH_ALERT": {"CRITICAL", "PRE_MARKET_PLAN", "SESSION_REVIEW", "RESOLVED", "INVALIDATED"},
    "CRITICAL": {"PRE_MARKET_PLAN", "SESSION_REVIEW", "RESOLVED", "INVALIDATED"},
    "PRE_MARKET_PLAN": {"SESSION_REVIEW", "RESOLVED", "INVALIDATED", "EXPIRED"},
    "SESSION_REVIEW": {"RESOLVED", "INVALIDATED", "HIGH_ALERT", "EXPIRED"},
}

GEARS = {0: "AMBIENT_WATCH", 1: "DETERMINISTIC_VERIFY", 2: "DYNAMIC_DEEP_SCAN", 3: "CRITICAL_INVESTIGATION"}


def can_transition(frm, to):
    """Pure: is frm→to a legal, auditable lifecycle transition?"""
    if frm in _TERMINAL:
        return False
    if to not in LIFECYCLE_STATES:
        return False
    return to in ALLOWED_TRANSITIONS.get(frm, set())


# ── TSE daily price-limit table (制限値幅) — the key to S高/S安 detection ──────
# (upper_bound_yen, limit_yen): a previous close < upper_bound has this daily
# limit. Standard TSE table; deterministic, public, no LLM. Extend upward as
# needed. The limit is symmetric (±limit) from the previous close.
_TSE_LIMIT_TABLE = [
    (100, 30), (200, 50), (500, 80), (700, 100), (1000, 150), (1500, 300),
    (2000, 400), (3000, 500), (5000, 700), (7000, 1000), (10000, 1500),
    (15000, 3000), (20000, 4000), (30000, 5000), (50000, 7000), (70000, 10000),
    (100000, 15000), (150000, 30000), (200000, 40000), (300000, 50000),
    (500000, 70000), (700000, 100000), (1000000, 150000), (1500000, 300000),
    (2000000, 400000), (3000000, 500000), (5000000, 700000), (10000000, 1000000),
]


def tse_price_limit(prev_close):
    """Pure: the TSE daily price limit (±yen) for a given previous close.
    None if prev_close is not a positive number."""
    if not isinstance(prev_close, (int, float)) or prev_close <= 0:
        return None
    for upper, limit in _TSE_LIMIT_TABLE:
        if prev_close < upper:
            return limit
    return _TSE_LIMIT_TABLE[-1][1]


def special_quote_proximity(price, prev_close):
    """Pure: how close a JP quote is to its limit-up (S高) / limit-down (S安).
    Returns None on bad input, else a dict with the limit band and a signed
    proximity in [-1, 1] (+1 = at limit-up, -1 = at limit-down)."""
    limit = tse_price_limit(prev_close)
    if limit is None or not isinstance(price, (int, float)) or price <= 0:
        return None
    up, down = prev_close + limit, prev_close - limit
    move = price - prev_close
    prox = max(-1.0, min(1.0, move / limit)) if limit else 0.0
    return {
        "limitUp": round(up, 2), "limitDown": round(down, 2), "limitYen": limit,
        "proximity": round(prox, 3),
        "atLimitUp": price >= up - 1e-9,
        "atLimitDown": price <= down + 1e-9,
        "towardLimit": ("up" if prox > 0 else "down" if prox < 0 else "flat"),
    }


# ── Session labelling ────────────────────────────────────────────────────────
def session_label(now_jst):
    """Pure: the market session for a JST datetime (weekend/JP-cash-session
    aware). US/overnight refinement is left to callers that pass ET context."""
    if now_jst.weekday() >= 5:
        return "WEEKEND"
    hm = now_jst.hour * 60 + now_jst.minute
    if hm < 8 * 60:
        return "OVERNIGHT_GLOBAL"
    if hm < 9 * 60:
        return "JP_PRE_MARKET"
    if hm < 11 * 60 + 30:
        return "JP_MORNING"
    if hm < 12 * 60 + 30:
        return "JP_LUNCH"
    if hm < 15 * 60 + 25:          # TSE afternoon runs to 15:25 (closing auction 15:25–15:30)
        return "JP_AFTERNOON"
    if hm < 15 * 60 + 30:
        return "JP_PRE_CLOSE"
    if hm < 16 * 60:
        return "JP_POST_CLOSE"
    if hm < 22 * 60 + 30:
        return "OVERNIGHT_GLOBAL"     # US pre-market window (UTC overlap)
    return "OVERNIGHT_GLOBAL"


# Session-aware thresholds: a thin after-hours print must not trip the same
# wire as a regular-session move. (changePct = abs %, volRatio = vs 20d avg.)
_SESSION_THRESHOLDS = {
    "JP_MORNING":    {"spikePct": 5.0, "crashPct": 5.0, "volRatio": 2.5, "flowAbs": 0.25},
    "JP_AFTERNOON":  {"spikePct": 5.0, "crashPct": 5.0, "volRatio": 2.5, "flowAbs": 0.25},
    "JP_PRE_CLOSE":  {"spikePct": 4.0, "crashPct": 4.0, "volRatio": 2.0, "flowAbs": 0.20},
    "JP_LUNCH":      {"spikePct": 7.0, "crashPct": 7.0, "volRatio": 3.0, "flowAbs": 0.30},
    "JP_PRE_MARKET": {"spikePct": 7.0, "crashPct": 7.0, "volRatio": 3.0, "flowAbs": 0.35},
    "JP_POST_CLOSE": {"spikePct": 6.0, "crashPct": 6.0, "volRatio": 3.0, "flowAbs": 0.30},
    "OVERNIGHT_GLOBAL": {"spikePct": 8.0, "crashPct": 8.0, "volRatio": 4.0, "flowAbs": 0.40},
    "WEEKEND":       {"spikePct": 10.0, "crashPct": 10.0, "volRatio": 5.0, "flowAbs": 0.50},
}
_DEFAULT_THRESHOLDS = {"spikePct": 6.0, "crashPct": 6.0, "volRatio": 3.0, "flowAbs": 0.30}


def session_thresholds(session):
    return dict(_SESSION_THRESHOLDS.get(session, _DEFAULT_THRESHOLDS))


# ── Gear 0 — deterministic anomaly detection (NO LLM) ────────────────────────
def detect_anomalies(quote, session, prev_close=None):
    """Pure: given a single quote snapshot + session, return a list of candidate
    triggers (each a dict: type, severity 1-5, triggerScore 0-1, reasonJa). This
    is Gear 0 — cheap, deterministic, source-confirmed inputs only. S高/S安 from
    the real TSE limit table; spike/crash/volume/flow from session thresholds.

    quote: {market, symbol, changePct, price, volRatio, flowRatio, status, ...}
    Returns [] when nothing is anomalous (the common case)."""
    out = []
    if not isinstance(quote, dict):
        return out
    th = session_thresholds(session)
    chg = quote.get("changePct")
    vr = quote.get("volRatio")
    flow = quote.get("flowRatio")
    market = quote.get("market")
    price = quote.get("price")

    # S高 / S安 (JP only) — proximity to the official daily limit.
    if market == "JP" and prev_close:
        sq = special_quote_proximity(price, prev_close)
        if sq:
            p = sq["proximity"]
            if sq["atLimitUp"]:
                out.append(_trig("LIMIT_UP", 5, 1.0, f"ストップ高(S高)に到達 — 制限値幅±{sq['limitYen']}円"))
            elif sq["atLimitDown"]:
                out.append(_trig("LIMIT_DOWN", 5, 1.0, f"ストップ安(S安)に到達 — 制限値幅±{sq['limitYen']}円"))
            elif p >= 0.7:
                # PROXIMITY to the price limit — NOT the exchange 特別気配 state
                # (that needs a verified exchange-status field we don't have).
                out.append(_trig("LIMIT_UP_PROXIMITY", 4, round(p, 2),
                                 f"値幅上限まで{int(p*100)}%(あと{round(sq['limitUp']-price,1)}円)"))
            elif p <= -0.7:
                out.append(_trig("LIMIT_DOWN_PROXIMITY", 4, round(-p, 2),
                                 f"値幅下限まで{int(-p*100)}%(あと{round(price-sq['limitDown'],1)}円)"))

    # Price spike / crash (session-aware).
    if isinstance(chg, (int, float)):
        if chg >= th["spikePct"]:
            out.append(_trig("PRICE_SPIKE", _sev(chg, th["spikePct"]), _score(chg, th["spikePct"]),
                             f"急騰 +{round(chg,2)}%({session}閾値{th['spikePct']}%)"))
        elif chg <= -th["crashPct"]:
            out.append(_trig("PRICE_CRASH", _sev(-chg, th["crashPct"]), _score(-chg, th["crashPct"]),
                             f"急落 {round(chg,2)}%({session}閾値{th['crashPct']}%)"))

    # Volume surge.
    if isinstance(vr, (int, float)) and vr >= th["volRatio"]:
        out.append(_trig("VOLUME_ANOMALY", _sev(vr, th["volRatio"]), _score(vr, th["volRatio"]),
                         f"出来高が平常の{round(vr,1)}倍(閾値{th['volRatio']}倍)"))

    # Big-money flow imbalance.
    if isinstance(flow, (int, float)) and abs(flow) >= th["flowAbs"]:
        d = "純流入" if flow > 0 else "純流出"
        out.append(_trig("FLOW_ANOMALY", 3, min(1.0, abs(flow)),
                         f"大口資金が{d} {round(flow*100)}%(閾値{int(th['flowAbs']*100)}%)"))
    return out


def _trig(t, sev, score, reason):
    return {"type": t, "severity": int(sev), "triggerScore": float(score), "reasonJa": reason}


def _sev(val, threshold):
    """1-5 severity: at threshold=3, escalating with how far past it the move is."""
    r = abs(val) / threshold if threshold else 1.0
    return max(1, min(5, int(2 + r)))


def _score(val, threshold):
    return round(max(0.0, min(1.0, (abs(val) / threshold - 1.0) * 0.5 + 0.5)), 3)


# ── Crypto 24/7 shock detection (no session gating — crypto always trades) ────
def detect_crypto_anomaly(symbol, change_pct_24h, shock_pct=5.0, severe_pct=10.0):
    """Pure: a CRYPTO_SHOCK trigger from the 24h move. Runs 24/7 (incl. nights/
    weekends) — this is what makes the '24h監視' honest for an asset class that
    actually trades around the clock. Wider thresholds than equities (crypto is
    intrinsically more volatile)."""
    if not isinstance(change_pct_24h, (int, float)) or isinstance(change_pct_24h, bool):
        return []
    a = abs(change_pct_24h)
    if a < shock_pct:
        return []
    sev = 5 if a >= severe_pct else 4
    direction = "急騰" if change_pct_24h > 0 else "急落"
    return [_trig("CRYPTO_SHOCK", sev, min(1.0, a / severe_pct),
                  f"{symbol} 24時間で{change_pct_24h:+.1f}%({direction})")]


# ── Rolling short-window EARLY-warning detection (the "moment it starts" layer) ─
def detect_acceleration(samples, session, now=None):
    """Pure: short-window early-warning detection from a rolling buffer of recent
    quote samples for ONE symbol. Fires BEFORE the cumulative day-change thresholds
    in detect_anomalies do — it measures the *rate* of change over the last ~1 min
    rather than the full-day move, so a fast build catches earlier.

    samples: list of {"ts": epoch_sec, "price", "volRatio", "flowRatio"} (any order).
    Returns [] on insufficient history or when nothing is accelerating (common case)."""
    out = []
    if not isinstance(samples, list):
        return out
    pts = sorted((s for s in samples
                  if isinstance(s, dict) and isinstance(s.get("ts"), (int, float))
                  and not isinstance(s.get("ts"), bool)),
                 key=lambda s: s["ts"])
    if len(pts) < 3:
        return out
    newest = pts[-1]
    th = session_thresholds(session)
    if newest["ts"] - pts[0]["ts"] < 30:        # need ≥30s of real history
        return out

    # ── Momentum acceleration: signed %-move per minute over the last ~1 min ────
    ref = None
    for s in pts[:-1]:
        if newest["ts"] - s["ts"] >= 45:        # ref ≥45s back; closest-to-newest wins
            ref = s
    rp, np_ = (ref or {}).get("price"), newest.get("price")
    if ref and isinstance(rp, (int, float)) and rp > 0 and isinstance(np_, (int, float)):
        elapsed_min = (newest["ts"] - ref["ts"]) / 60.0
        if elapsed_min > 0:
            rate = ((np_ - rp) / rp * 100.0) / elapsed_min      # %/min, signed
            accel_th = max(1.0, th["spikePct"] * 0.5)           # half-a-spike per minute
            if abs(rate) >= accel_th:
                up = rate > 0
                out.append(_trig(
                    "MOMENTUM_ACCELERATION", _sev(abs(rate), accel_th), _score(abs(rate), accel_th),
                    f"{'急加速上昇' if up else '急加速下落'} {rate:+.1f}%/分"
                    f"(直近{round(elapsed_min*60)}秒・閾値{accel_th:.1f}%/分)"))

    # ── Flow reversal: big-money flow flipped sign across the buffer ────────────
    flows = [s["flowRatio"] for s in pts
             if isinstance(s.get("flowRatio"), (int, float)) and not isinstance(s.get("flowRatio"), bool)]
    if len(flows) >= 3:
        first_f, last_f = flows[0], flows[-1]
        mag = th["flowAbs"] * 0.6
        if first_f <= -mag and last_f >= mag:
            out.append(_trig("FLOW_REVERSAL", 4, min(1.0, abs(last_f - first_f)),
                             f"大口資金が流出→流入に反転({round(first_f*100)}%→{round(last_f*100)}%)"))
        elif first_f >= mag and last_f <= -mag:
            out.append(_trig("FLOW_REVERSAL", 4, min(1.0, abs(last_f - first_f)),
                             f"大口資金が流入→流出に反転({round(first_f*100)}%→{round(last_f*100)}%)"))

    # ── Volume acceleration: volume rate climbing sharply but still UNDER the
    # absolute VOLUME_ANOMALY threshold (an earlier, distinct signal). ──────────
    vols = [s["volRatio"] for s in pts
            if isinstance(s.get("volRatio"), (int, float)) and not isinstance(s.get("volRatio"), bool)]
    if len(vols) >= 3:
        first_v, last_v = vols[0], vols[-1]
        if first_v > 0 and last_v >= first_v * 2.0 and (th["volRatio"] * 0.6) <= last_v < th["volRatio"]:
            out.append(_trig("VOLUME_ACCELERATION", 3, _score(last_v, th["volRatio"] * 0.6),
                             f"出来高が急加速中 {round(first_v,1)}倍→{round(last_v,1)}倍"
                             f"(本格閾値{th['volRatio']}倍の手前)"))
    return out


# ── Dedup / novelty / priority ───────────────────────────────────────────────
def dedup_key(market, symbol, event_type, bucket_minutes=30, now=None):
    """Pure: a stable key so the same anomaly on the same symbol within a time
    bucket merges into one root event instead of spamming. now is a datetime."""
    n = now or datetime(2000, 1, 1)
    bucket = int((n.hour * 60 + n.minute) // bucket_minutes)
    daystr = n.strftime("%Y-%m-%d")
    return f"{market}:{symbol}:{event_type}:{daystr}:{bucket}"


def priority_score(envelope):
    """Pure: rank an event for the bounded deep-scan queue. Higher = sooner.
    Weighs severity, trigger strength, novelty, reliability, completeness, and
    urgency to the next market open."""
    sev = (envelope.get("severity") or 1) / 5.0
    trig = envelope.get("triggerScore") or 0.0
    nov = envelope.get("noveltyScore", 0.5)
    rel = envelope.get("reliabilityScore", 0.5)
    comp = envelope.get("dataCompleteness", 0.5)
    ttl_open = envelope.get("timeToNextOpenMin")
    urgency = 0.5
    if isinstance(ttl_open, (int, float)):
        urgency = 1.0 if ttl_open <= 0 else max(0.1, min(1.0, 240.0 / (ttl_open + 60)))
    return round(0.34*sev + 0.22*trig + 0.14*nov + 0.12*rel + 0.08*comp + 0.10*urgency, 4)


# ── Notification-transition dedup ────────────────────────────────────────────
def should_notify(prev, new):
    """Pure: notify only on a MEANINGFUL change. prev/new are dicts with
    lifecycleState / severity / recommendedPosture. No prev → notify (initial)."""
    if prev is None:
        return True, "initial"
    if new.get("lifecycleState") != prev.get("lifecycleState"):
        if new.get("lifecycleState") in ("HIGH_ALERT", "CRITICAL", "INVALIDATED",
                                         "RESOLVED", "PRE_MARKET_PLAN"):
            return True, "state_change"
    if (new.get("severity") or 0) - (prev.get("severity") or 0) >= 1:
        return True, "severity_up"
    if new.get("recommendedPosture") != prev.get("recommendedPosture"):
        return True, "posture_change"
    return False, "no_material_change"


# ── EventEnvelope normalization ──────────────────────────────────────────────
def make_envelope(*, event_type, symbol, market, source, trigger, now,
                  next_open=None, reliability=0.6, completeness=0.6, novelty=0.5,
                  evidence_ids=None, linked_assets=None, recommended_posture="WATCH",
                  gear=0, observed_at=None, published_at=None, fetched_at=None):
    """Pure: normalize a detected trigger into the canonical EventEnvelope.
    Keeps EVENT time and INGEST time separate (the GPT spec's core requirement).
    `now` and the *_at args are datetimes; serialized to ISO-Z."""
    if event_type not in EVENT_TYPES:
        raise ValueError(f"unknown event_type {event_type}")
    if event_type in CAPABILITY_GATED_TYPES:
        raise ValueError(f"{event_type} is capability-gated and must not be emitted yet")
    sev = int(trigger.get("severity", 1))
    ts = lambda d: (d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if d else None)
    sess = session_label(now.astimezone(TZ_JST))
    tto = None
    if next_open:
        tto = max(0, int((next_open - now).total_seconds() / 60))
    eid = f"{dedup_key(market, symbol, event_type, now=now.astimezone(TZ_JST))}#{ts(now)}"
    return {
        "schemaVersion": SCHEMA_VERSION, "eventId": eid, "eventType": event_type,
        "eventVersion": 1, "rootEventId": None,
        "symbol": symbol, "market": market, "linkedAssets": linked_assets or [],
        "source": source,
        "detectedAt": ts(now), "observedAt": ts(observed_at or now),
        "publishedAt": ts(published_at), "fetchedAt": ts(fetched_at or now),
        "ingestAt": None,                       # stamped by the store on persist
        "session": sess, "severity": sev, "triggerScore": float(trigger.get("triggerScore", 0.0)),
        "noveltyScore": novelty, "reliabilityScore": reliability, "dataCompleteness": completeness,
        "currentGear": gear, "lifecycleState": "DETECTED",
        "nextOpenAt": ts(next_open), "timeToNextOpenMin": tto,
        "deduplicationKey": dedup_key(market, symbol, event_type, now=now.astimezone(TZ_JST)),
        "evidenceIds": evidence_ids or [], "invalidationConditions": [],
        "recommendedPosture": recommended_posture, "reasonJa": trigger.get("reasonJa"),
        "status": "active",
    }


def apply_transition(envelope, to_state, now, reason=None, severity=None, posture=None):
    """Pure: return a NEW revision (never mutates) when frm→to is legal, else
    raise. Bumps eventVersion, records the prior state, stamps the time."""
    frm = envelope.get("lifecycleState")
    if not can_transition(frm, to_state):
        raise ValueError(f"illegal transition {frm} -> {to_state}")
    rev = dict(envelope)
    rev["eventVersion"] = (envelope.get("eventVersion") or 1) + 1
    rev["prevLifecycleState"] = frm
    rev["lifecycleState"] = to_state
    rev["revisedAt"] = now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if reason is not None:
        rev["transitionReasonJa"] = reason
    if severity is not None:
        rev["severity"] = int(severity)
    if posture is not None:
        rev["recommendedPosture"] = posture
    if to_state in _TERMINAL:
        rev["status"] = "closed"
    return rev
