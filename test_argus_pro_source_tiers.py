"""ARGUS Pro — source tiers + coverage (Phase 6).

Weak sources cannot ground judgment or confirm cause; only official tiers confirm
cause; two copies of one wire are one family (handled by cluster_items elsewhere).
"""
import argus_research_mesh as M
import scanner


def test_official_regulatory_can_confirm_cause():
    assert M.source_tier("sec_press_release") == "official_regulatory"
    g = M.tier_grounding("official_regulatory")
    assert g["canGroundJudgment"] and g["canConfirmCause"] and not g["weakSignal"]


def test_central_bank_tier():
    assert M.source_tier("federal_reserve") == "central_bank_or_government"
    assert M.source_tier("boj_release") == "central_bank_or_government"


def test_exchange_venue_tier_raw_form():
    assert M.source_tier("tdnet") == "exchange_or_listing_venue"
    assert M.source_tier("edinet") == "exchange_or_listing_venue"


def test_reputable_media_grounds_but_cannot_confirm_cause():
    assert M.source_tier("reuters_public") == "reputable_financial_media"
    g = M.tier_grounding("reputable_financial_media")
    assert g["canGroundJudgment"] and not g["canConfirmCause"]


def test_aggregator_is_weak_and_cannot_ground():
    assert M.source_tier("yahoo_finance") == "aggregator"
    g = M.tier_grounding("aggregator")
    assert not g["canGroundJudgment"] and not g["canConfirmCause"] and g["weakSignal"]


def test_unknown_source_is_weak():
    assert M.source_tier("some_random_blog_xyz") == "unknown"
    assert M.tier_grounding("unknown")["weakSignal"] is True


def test_normalize_item_carries_tier_and_grounding():
    item = M.normalize_item({"sourceId": "reuters_public", "title": "NVDA rises",
                             "canonicalUrl": "https://reuters.test/a", "linkedAssets": ["NVDA"]})
    assert item["sourceTier"] == "reputable_financial_media"
    assert item["canGroundJudgment"] is True
    assert item["canConfirmCause"] is False


def test_source_coverage_endpoint_shape():
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/source-coverage").get_json()
    assert d["schemaVersion"] == "source-coverage-v1"
    assert "tiers" in d and "summary" in d
    assert set(d["summary"]) >= {"totalItems", "canGroundJudgmentItems", "weakSignalItems"}
