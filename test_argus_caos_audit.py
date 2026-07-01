"""ARGUS Pro — CAOS association audit trail (Phase 7)."""
import argus_caos_audit as CA
import scanner


def setup_function(_):
    CA.clear()


def test_build_entry_carries_caveat_and_why():
    e = CA.build_entry(symbol="nvda", event_id="e1", link_type="theme",
                       matched_terms=["AI", "GPU"], source_family="reputable:reuters",
                       corroboration_level="single_source", why_ja="AIテーマで連想")
    assert e["symbol"] == "NVDA"
    assert e["nonCausalityCaveatJa"]                     # always present
    assert e["whyJa"] == "AIテーマで連想"
    assert e["schemaVersion"] == "caos-link-v1"


def test_single_source_theme_is_candidate_or_background_never_confirmed():
    e = CA.build_entry(symbol="X", event_id="e", link_type="theme",
                       corroboration_level="single_source")
    assert e["triggerRole"] in ("candidate_catalyst", "background_theme")
    assert e["triggerRole"] != "confirmed_cause"


def test_post_move_association_is_background():
    e = CA.build_entry(symbol="X", event_id="e", link_type="direct_mention",
                       corroboration_level="official", event_after_move=True)
    assert e["triggerRole"] == "background_theme"


def test_direct_official_can_be_probable():
    e = CA.build_entry(symbol="X", event_id="e", link_type="direct_mention",
                       corroboration_level="official")
    assert e["triggerRole"] == "probable_catalyst"


def test_why_is_truncated_never_full_text():
    e = CA.build_entry(symbol="X", event_id="e", link_type="theme",
                       why_ja="x" * 5000)
    assert len(e["whyJa"]) <= 280                        # metadata only, no full article body


def test_record_and_snapshot_roundtrip():
    CA.record_association(symbol="AAPL", event_id="e1", link_type="direct_mention",
                          corroboration_level="corroborated", why_ja="決算")
    snap = CA.snapshot(symbol="AAPL")
    assert snap["count"] == 1 and snap["items"][0]["symbol"] == "AAPL"


def test_ring_buffer_caps():
    for i in range(CA._MAX + 50):
        CA.record_association(symbol=f"S{i}", event_id=str(i), link_type="theme")
    assert len(CA._TRAIL) <= CA._MAX


def test_snapshot_filters_by_symbol():
    CA.record_association(symbol="AAA", event_id="1", link_type="theme")
    CA.record_association(symbol="BBB", event_id="2", link_type="theme")
    assert CA.snapshot(symbol="AAA")["count"] == 1


def test_caos_audit_endpoint_shape():
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/caos/audit").get_json()
    assert d["schemaVersion"] == "caos-link-v1" and "items" in d
