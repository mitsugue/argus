"""Tests for §14 Institutional Positioning aggregator (argus_positioning.py).

Asserts the key safety/correctness properties: probabilities always sum to 1.0
(including the bad-input → unknown=1 path), no named trader without an official
disclosure, the short-volume-vs-interest guard, and a high `unknown` on weak
evidence. No network, stdlib-only."""
import argus_positioning as P
import argus_research_mesh as M


def _sum(out):
    return round(sum(out["probabilities"].values()), 4)


# ── probabilities always sum to 1.0 ──────────────────────────────────────────
def test_probabilities_sum_to_one_rich_signal():
    out = P.aggregate_positioning({"changePct": -4.0, "volRatio": 1.6,
                                   "shortVolumeRatio": 0.55, "flowRatio": -0.3,
                                   "priorFlowRatio": 0.1})
    assert _sum(out) == 1.0
    assert set(out["probabilities"]) == set(P.POSITIONING_OUTCOMES)
    assert out["calibrationStatus"] == "uncalibrated"


def test_probabilities_sum_to_one_up_move():
    out = P.aggregate_positioning({"changePct": 3.0, "flowRatio": 0.4, "volRatio": 1.5})
    assert _sum(out) == 1.0


def test_bad_input_unknown_is_one_and_sums_to_one():
    for bad in (None, {}, [], "x", 0, {"foo": "bar"}):
        out = P.aggregate_positioning(bad)
        assert out["probabilities"]["unknown"] == 1.0
        assert _sum(out) == 1.0
        assert out["identifiedTrader"] is None
        assert out["calibrationStatus"] == "uncalibrated"


def test_no_numeric_signals_is_unknown_one():
    # keys present but no usable numbers → honest all-unknown
    out = P.aggregate_positioning({"relativeWeakness": True})
    assert out["probabilities"]["unknown"] == 1.0
    assert _sum(out) == 1.0


# ── weak evidence keeps unknown high ─────────────────────────────────────────
def test_weak_signal_keeps_unknown_high():
    out = P.aggregate_positioning({"changePct": -0.3})   # one weak signal
    assert out["probabilities"]["unknown"] >= 0.4
    assert _sum(out) == 1.0


def test_heavy_short_volume_down_tilts_but_unknown_material():
    # heavy short-sale VOLUME + price down → newShortBuildup/distribution tilt,
    # but VOLUME≠INTEREST so unknown stays MATERIAL (no confident short-interest build)
    out = P.aggregate_positioning({"changePct": -3.0, "shortVolumeRatio": 0.6,
                                   "volRatio": 1.4, "relativeWeakness": True})
    probs = out["probabilities"]
    assert probs["newShortBuildup"] > 0 or probs["distribution"] > 0
    assert probs["unknown"] >= 0.2          # still material — volume is not interest
    assert _sum(out) == 1.0


def test_short_covering_bounce():
    out = P.aggregate_positioning({"changePct": 2.5, "priorShortInterestHigh": True,
                                   "flowRatio": -0.1})
    probs = out["probabilities"]
    assert probs["shortCovering"] == max(probs.values()) or probs["shortCovering"] > 0.2
    assert _sum(out) == 1.0


# ── name_trader: only with official disclosure ───────────────────────────────
def test_name_trader_none_without_official():
    assert P.name_trader(None) is None
    assert P.name_trader({}) is None
    assert P.name_trader({"name": "Goldman Sachs"}) is None              # no official flag
    assert P.name_trader({"official": False, "name": "Goldman Sachs"}) is None
    assert P.name_trader({"official": True}) is None                     # official but no name


def test_name_trader_with_official_disclosure():
    assert P.name_trader({"official": True, "name": "Elliott Management"}) == "Elliott Management"
    # institutionId resolves to the canonical watchlist name
    assert P.name_trader({"official": True, "institutionId": "blackrock"}) == "BlackRock"


def test_aggregate_never_names_trader_from_flow():
    out = P.aggregate_positioning({"changePct": -5.0, "shortVolumeRatio": 0.7, "volRatio": 2.0})
    assert out["identifiedTrader"] is None       # never from flow alone


def test_aggregate_uses_official_disclosure_for_identity():
    out = P.aggregate_positioning({"changePct": -2.0, "flowRatio": -0.2,
                                   "disclosure": {"official": True, "institutionId": "blackrock"}})
    assert out["identifiedTrader"] == "BlackRock"


# ── short-sale VOLUME != short INTEREST guard ────────────────────────────────
def test_short_volume_guard_mentions_volume_and_interest():
    g = P.short_volume_guard("FINRA")
    assert "volume" in g.lower() and "interest" in g.lower()
    assert "出来高" in g and "残高" in g
    # also surfaced in the aggregate notes
    out = P.aggregate_positioning({"changePct": -1.0, "shortVolumeRatio": 0.5})
    joined = " ".join(out["notesJa"])
    assert "volume" in joined.lower() and "interest" in joined.lower()


# ── source descriptors carry honest §14 fields ───────────────────────────────
def test_describe_slow_and_fast_fields_present():
    fields = ("asOf", "publicationDelay", "coverage", "threshold",
              "identityAvailable", "positionOrVolume", "freshness")
    si = P.describe_source("finra_short_interest", {})
    sv = P.describe_source("finra_daily_short_volume", {})
    for f in fields:
        assert f in si and f in sv
    assert si["positionOrVolume"] == "position" and si["tier"] == "slow"
    assert sv["positionOrVolume"] == "volume" and sv["tier"] == "fast"
    # the daily short VOLUME source must carry the volume-vs-interest warning
    assert sv["volumeVsInterestNote"] and "interest" in sv["volumeVsInterestNote"].lower()


def test_describe_unknown_source_is_honest():
    d = P.describe_source("totally_made_up", {})
    assert d["tier"] == "unknown"
    assert d["identityAvailable"] is False
    assert d["freshness"] == "unknown"
    assert d["accessClass"] == "UNAVAILABLE"     # via research-mesh rights registry


def test_describe_payload_overlays_asof():
    d = P.describe_source("jpx_disclosed_short", {"asOf": "2026-06-25T00:00:00Z"})
    assert d["asOf"] == "2026-06-25T00:00:00Z"
    assert d["identityAvailable"] is True        # JPX disclosed shorts identify filer


def test_slow_sources_are_positions_fast_have_volume():
    for sid, s in P.SLOW_SOURCES.items():
        assert s["positionOrVolume"] == "position"
        assert s["freshness"] == "delayed"
    # at least the canonical volume sources are flagged as volume
    assert P.FAST_SOURCES["finra_daily_short_volume"]["positionOrVolume"] == "volume"


# ── safety: no trade surface, calibration honestly labelled ──────────────────
def test_no_order_surface():
    for bad in ("place_order", "execute", "submit_order", "buy", "sell", "broker"):
        assert not hasattr(P, bad)


def test_calibration_status_always_uncalibrated():
    assert P.CALIB == "uncalibrated"
    out = P.aggregate_positioning({"changePct": -2.0, "volRatio": 1.5, "flowRatio": -0.2})
    assert out["calibrationStatus"] == "uncalibrated"
