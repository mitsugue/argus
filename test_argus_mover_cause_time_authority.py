"""Hostile timestamp tests for the common current-cause authority gate."""
import pytest

import argus_mover_cause as MC


NOW = "2026-07-02T05:00:00Z"
MOVE_START = "2026-07-02T00:05:00Z"
COVER_ALL = {k: True for k in (
    "tdnetChecked", "officialEventsChecked", "edinetSecChecked", "companyNewsChecked",
    "jpNewsChecked", "caosChecked", "sectorPeerChecked", "macroChecked",
    "flowChecked", "technicalChecked")}


def _mover():
    return {"symbol": "5801", "market": "JP", "changePct": -6.0,
            "direction": "down", "name": "テスト銘柄", "asOf": NOW,
            "moveStartedAt": MOVE_START}


def _evidence(source_family, timestamp):
    base = {"coverage": COVER_ALL}
    if source_family == "tdnet":
        base["tdnetItems"] = [{"title": "業績予想の下方修正", "categoryJa": "業績修正",
                               "disclosedAt": timestamp, "material": True,
                               "sentiment": "negative", "official": True,
                               "provider": "jquants-tdnet"}]
    elif source_family == "official_lifecycle":
        base["officialEvents"] = [{"title": "業績予想の下方修正", "categoryJa": "業績修正",
                                   "disclosedAt": timestamp, "material": True,
                                   "sentiment": "negative", "provider": "jquants-tdnet"}]
    elif source_family == "filing":
        base["filings"] = [{"form": "8-K", "docDescription": "Material event",
                            "submitDateTime": timestamp, "source": "SEC"}]
    elif source_family == "direct_news":
        base["companyNews"] = [{"headline": "業績予想の下方修正を発表",
                                "publishedAt": timestamp, "publisher": "WireA",
                                "tier": "wire", "sentiment": "negative"}]
    elif source_family == "caos":
        base["caosLead"] = {"titleJa": "関連企業の業績悪化", "via": "entity",
                            "corroboration": "single", "publishedAt": timestamp}
    return base


HOSTILE_TIMESTAMPS = [
    None,
    "not-a-timestamp",
    "2026-07-02",           # date-only cannot establish causal ordering
    "2026-07-02T05:00:01Z",  # future by one second
    "2026-07-03T05:00:00Z",  # future by one day
    "2026-07-01T00:00:00Z",  # stale (>24h)
    "2026-06-28T00:00:00Z",  # old (>72h)
]


@pytest.mark.parametrize("source_family", [
    "tdnet", "official_lifecycle", "filing", "direct_news", "caos",
])
@pytest.mark.parametrize("timestamp", HOSTILE_TIMESTAMPS)
def test_untrusted_time_is_background_and_never_earns_ladder_or_best_lead(
        source_family, timestamp):
    rec = MC.resolve(_mover(), _evidence(source_family, timestamp), NOW)
    assert rec["causeStatus"] == "no_lead_yet"
    assert rec["bestLeadJa"] == "最新材料は未確認"
    candidate = rec["causeCandidates"][0]
    assert candidate["role"] == "background_only"
    assert candidate["marketConfirmed"] is False
    assert candidate["timeAuthority"]["eligibleAsPrimaryLead"] is False


@pytest.mark.parametrize("source_family", [
    "tdnet", "official_lifecycle", "filing", "direct_news", "caos",
])
def test_valid_fresh_time_preserves_source_family_candidate(source_family):
    rec = MC.resolve(_mover(), _evidence(source_family, "2026-07-01T23:30:00Z"), NOW)
    assert rec["causeStatus"] in {
        "confirmed_cause", "probable_catalyst", "candidate_catalyst",
    }
    candidate = rec["causeCandidates"][0]
    assert candidate["role"] != "background_only"
    assert candidate["timeAuthority"]["eligibleAsPrimaryLead"] is True


def test_status_resolver_never_promotes_background_official_category():
    candidate = MC._mk(
        "official_disclosure", "background official", role="background_only",
        source_tier="official", corroboration="official", timing="before_move",
        market_confirmed=True, confidence=1.0)
    assert MC._status_from([candidate]) == ("no_lead_yet", None)


def test_timing_relation_rejects_future_by_one_second():
    assert MC.timing_relation(
        "2026-07-02T05:00:01Z", MOVE_START, NOW) == "unknown"


def test_timing_relation_rejects_date_only_causal_ordering():
    assert MC.timing_relation("2026-07-02", MOVE_START, NOW) == "unknown"
    assert MC.timing_relation("2026-07-01T23:30:00Z", "2026-07-02", NOW) == "unknown"


def test_sec_filing_date_only_is_background_not_probable():
    evidence = {"coverage": COVER_ALL,
                "filings": [{"form": "8-K", "filingDate": "2026-07-02",
                             "source": "SEC"}]}
    rec = MC.resolve(_mover(), evidence, NOW)
    assert rec["causeStatus"] == "no_lead_yet"
    filing = rec["causeCandidates"][0]
    assert filing["role"] == "background_only"
    assert filing["timingRelation"] == "unknown"
    assert filing["timeAuthority"]["freshness"] == "date_only"


def test_record_freshness_future_refresh_is_stale_not_age_zero():
    record = {
        "causeStatus": "candidate_catalyst",
        "asOf": "2026-07-02T05:00:01Z",
        "freshness": {"lastEvidenceRefreshAt": "2026-07-02T05:00:01Z"},
        "refreshPolicy": {"priority": "normal"},
    }
    result = MC.annotate_freshness(record, NOW)
    assert result["freshness"]["evidenceAgeSec"] is None
    assert result["freshness"]["isStale"] is True
    assert "未来" in result["freshness"]["staleReasonJa"]
