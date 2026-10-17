"""Important Events priority + novice explanations (argus_important_events, v10.138)."""
import argus_important_events as IE


def _ev(kind, impact, days, linked, eid=None, jst="21:30", date="2026-06-25"):
    return {"id": eid or f"us-{kind}-{date}", "kind": kind, "title": kind.upper(),
            "impact": impact, "daysUntil": days, "escalation": ("D-1" if days == 1 else "D" if days == 0 else "D-7"),
            "linkedAssets": linked, "eventDate": date, "localTimeJst": jst,
            "rationaleJa": "x", "source": "BEA", "status": "live"}


def test_pce_explained_not_just_named():
    out = IE.build_important_events([_ev("pce", "high", 1, ["USDJPY", "US10Y", "QQQ"])])
    assert len(out) == 1
    e = out[0]
    assert e["eventCode"] == "PCE"
    assert "インフレ" in e["noviceJa"] and "FRB" in e["noviceJa"]
    assert "inflation" in e["noviceEn"].lower()
    # explanation is much longer than the name
    assert len(e["noviceEn"]) > 40 and len(e["noviceJa"]) > 20


def test_direction_neutral_no_bull_bear():
    for k in IE.NOVICE:
        for loc in ("en", "ja"):
            t = IE.NOVICE[k][loc].lower()
            assert "bullish" not in t and "bearish" not in t
            assert "上昇する" not in t and "下落する" not in t  # no asserted direction


def test_no_consensus_fabrication():
    e = IE.build_important_events([_ev("cpi", "high", 1, ["US10Y"])])[0]
    assert e["forecast"] == "UNAVAILABLE" and e["previous"] == "UNAVAILABLE"
    assert e["actual"] is None and e["releasedAt"] is None


def test_visibility_rules():
    evs = [_ev("pce", "critical", 1, ["USDJPY"]),
           _ev("ppi", "medium", 2, ["US10Y"]),          # medium, not owner-linked → hidden
           _ev("jolts", "low", 3, ["US10Y"])]            # low → hidden
    out = IE.build_important_events(evs)
    codes = {e["eventCode"] for e in out}
    assert "PCE" in codes and "PPI" not in codes and "JOLTS" not in codes


def test_owner_relevance_promotes_medium():
    # medium impact, but linked to a HELD asset and within a day → shown + promoted
    out = IE.build_important_events([_ev("ppi", "medium", 1, ["8058"])],
                                    owner_symbols={"8058"}, held_symbols={"8058"})
    assert len(out) == 1
    assert out[0]["ownerRelevance"] == "critical"
    assert out[0]["displayImpact"] in ("high", "critical")   # promoted above medium


def test_sort_by_impact_then_priority():
    evs = [_ev("jolts", "high", 5, ["US10Y"]),
           _ev("fomc", "critical", 0, ["USDJPY", "QQQ"])]
    out = IE.build_important_events(evs)
    assert out[0]["eventCode"] == "FOMC"           # critical before high


def test_lifecycle_states():
    assert IE.lifecycle_state(1) == "UPCOMING"
    assert IE.lifecycle_state(0) == "IMMINENT"
    assert IE.lifecycle_state(-1) == "RELEASED"


def test_action_until_blocks_on_high_critical():
    e = IE.build_important_events([_ev("pce", "critical", 1, ["USDJPY"])])[0]
    assert "BLOCKED" in e["actionUntilEn"] and "禁止" in e["actionUntilJa"]


def test_imminent_high_under_event_wait_becomes_critical():
    e = IE.build_important_events([_ev("pce", "high", 1, ["USDJPY", "QQQ"])],
                                  ctx={"regime": "EVENT_WAIT"})[0]
    assert e["displayImpact"] == "critical"   # PCE pops as CRITICAL when it drives the regime


def test_high_stays_high_in_calm_regime():
    e = IE.build_important_events([_ev("pce", "high", 1, ["USDJPY", "QQQ"])],
                                  ctx={"regime": "RISK_ON"})[0]
    assert e["displayImpact"] == "high"        # no false escalation when regime is calm
