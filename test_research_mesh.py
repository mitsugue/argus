"""Institutional Intelligence / Research Mesh core (argus_research_mesh, v1)."""
import argus_research_mesh as M


# ── source rights enforcement (§4/§30) ──
def test_rights_metadata_only_strips_fulltext():
    rec = M.enforce_storage("reuters_public", {"title": "x", "fullText": "BODY", "publicSnippet": "snip"})
    assert "fullText" not in rec and rec["accessClass"] == "PUBLIC_METADATA"
    assert rec.get("publicSnippet") == "snip"           # excerpt allowed

def test_link_only_blocks_llm_and_excerpt():
    M.SOURCE_RIGHTS["tmp_linkonly"] = {"accessClass": "LINK_ONLY", "kind": "news", "licenceStatus": "public"}
    assert M.can_send_to_llm("tmp_linkonly") is False
    rec = M.enforce_storage("tmp_linkonly", {"title": "x", "publicSnippet": "s", "fullText": "b"})
    assert "fullText" not in rec and "publicSnippet" not in rec

def test_licensed_feeds_disabled_until_contract():
    for s in ("bloomberg_feed", "lseg_mrn", "factiva_ai", "ravenpack"):
        r = M.source_rights(s)
        assert r["accessClass"] == "UNAVAILABLE" and r["canSendToLLM"] is False and r["licenceStatus"] == "not_configured"


# ── institution / analyst identity (§6/§30) ──
def test_institution_alias_resolution():
    assert M.resolve_institution("JPMorgan sees Micron earnings risk") == "jpmorgan"
    assert M.resolve_institution("野村が半導体の見通しを発表") == "nomura"
    assert M.resolve_institution("some random blog post") is None        # not invented

def test_analyst_identity_not_invented():
    a = M.resolve_analyst("", "jpmorgan")
    assert a["analystId"] == "unknown" and a["name"] is None

def test_asset_manager_not_sellside():
    assert "blackrock" in M._BUY_SIDE and "jpmorgan" not in M._BUY_SIDE


# ── dedup / syndication (§9/§30) ──
def test_syndication_counts_as_one_origin():
    items = [M.normalize_item({"sourceId": "reuters_public", "title": "JPMorgan flags Micron earnings risk", "linkedAssets": ["MU"], "firstDetectedAt": "2026-06-25T14:02:00Z"}),
             M.normalize_item({"sourceId": "cnbc_public", "title": "JPMorgan flags Micron earnings risk", "linkedAssets": ["MU"], "firstDetectedAt": "2026-06-25T14:05:00Z"})]
    clusters = M.cluster_items(items)
    assert len(clusters) == 1 and clusters[0]["count"] == 2 and clusters[0]["syndicationCount"] == 1


# ── causal integrity (§2/§11/§30) ──
def test_report_after_move_not_trigger():
    item = M.normalize_item({"sourceId": "bloomberg_public", "title": "JPMorgan note on Micron", "linkedAssets": ["MU"], "publishedAt": "2026-06-25T15:00:00Z"})
    link = M.link_to_event(item, {"eventId": "e1", "linkedAssets": ["MU"], "moveStartedAt": "2026-06-25T14:00:00Z"})
    assert link["causalRole"] != "IMMEDIATE_TRIGGER" and link["causalRole"] == "AMPLIFIER"

def test_named_view_is_not_named_trade():
    item = M.normalize_item({"sourceId": "reuters_public", "title": "JPMorgan cautious on Micron", "linkedAssets": ["MU"], "publishedAt": "2026-06-25T13:50:00Z"})
    link = M.link_to_event(item, {"eventId": "e1", "linkedAssets": ["MU"], "moveStartedAt": "2026-06-25T14:00:00Z"})
    assert link["isNamedView"] is True
    assert "当該機関の建玉/売買の変化" in link["notConfirmed"]


# ── report intelligence preserves both sides (§10/§30) ──
def test_report_preserves_bull_and_bear():
    r = M.analyze_report("AI capex supports semiconductor earnings", "However ROI pressure creates catch-down risk if demand weakens")
    assert r["bullishClaims"] and r["bearishClaims"] and r["conditionalClaims"] and r["balanced"]


# ── narrative integrity gate (§16/§30) ──
def test_gate_rejects_forbidden_and_requires_sections():
    bad = M.gate_synthesis({"interpretation": "JPMorganが売った", "confidence": "HIGH"})
    assert bad["ok"] is False and bad["violations"]
    good = M.gate_synthesis({"confirmedFacts": "x", "reportedView": "y", "interpretation": "z",
                             "alternative": "a", "notConfirmed": "n", "confidence": "MODERATE"})
    assert good["ok"] is True and good["confidence"] == "MODERATE"


# ── safety: no trade surface ──
def test_no_order_surface():
    for bad in ("place_order", "execute_trade", "buy", "sell", "broker"):
        assert not hasattr(M, bad)


def test_distinct_generic_news_not_collapsed():
    # two UNRELATED institution-less market headlines must NOT cluster together
    a = M.normalize_item({"sourceId": "cnbc_public", "title": "Dell shares jump 39% on server sales"})
    b = M.normalize_item({"sourceId": "cnbc_public", "title": "Gap shares tumble 14% on weak guidance"})
    cl = M.cluster_items([a, b])
    assert len(cl) == 2                          # different stories stay separate

def test_same_headline_syndication_still_collapses():
    a = M.normalize_item({"sourceId": "reuters_public", "title": "Snowflake surges 36% for best day ever"})
    b = M.normalize_item({"sourceId": "cnbc_public",    "title": "Snowflake surges 36% for best day ever"})
    cl = M.cluster_items([a, b])
    assert len(cl) == 1 and cl[0]["syndicationCount"] == 1
