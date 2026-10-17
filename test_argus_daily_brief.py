"""§21 Owner-only Daily Institutional Brief (argus_daily_brief, v1).

Safety/correctness properties: action vs report routing, watchlist relevance,
theme counting, licensed-feed visibility, UNCONFIRMED labelling, caps, no trade
surface. No network, no LLM.
"""
import argus_daily_brief as B
import argus_research_mesh as M


def _item(**kw):
    """Build a normalized IntelligenceItem via the mesh (matches production shape)."""
    raw = {"sourceId": kw.pop("sourceId", "marketwatch_public")}
    raw.update(kw)
    it = M.normalize_item(raw)
    # allow tests to force a content-type / stance the heuristic wouldn't pick
    if "_contentType" in kw:
        it["contentType"] = kw["_contentType"]
    if "_stance" in kw:
        it["stance"] = kw["_stance"]
    if "_institutionId" in kw:
        it["institutionId"] = kw["_institutionId"]
    if "_linkedThemes" in kw:
        it["linkedThemes"] = kw["_linkedThemes"]
    return it


# ── A. analyst ACTION routing (not a report) ──
def test_upgrade_is_action_not_report():
    up = _item(title="JPMorgan upgrade of Micron to overweight",
               author="JPMorgan", linkedAssets=["MU"],
               firstDetectedAt="2026-06-25T13:00:00Z")
    assert up["contentType"] == "ANALYST_UPGRADE"
    brief = B.build_daily_brief([up], ["MU"])
    action_ids = {i["intelligenceId"] for i in brief["newAnalystActions"]}
    report_ids = {i["intelligenceId"] for i in brief["newInstitutionalReports"]}
    assert up["intelligenceId"] in action_ids
    assert up["intelligenceId"] not in report_ids


# ── B. named-institution research note → reports + watchlistRelevance ──
def test_jpmorgan_note_in_reports_and_watchlist():
    note = _item(title="JPMorgan strategy note: AI capex outlook for semiconductors",
                 author="JPMorgan", linkedAssets=["NVDA"],
                 _contentType="STRATEGY_OUTLOOK",
                 firstDetectedAt="2026-06-25T12:00:00Z")
    assert note["institutionId"] == "jpmorgan"
    brief = B.build_daily_brief([note], ["NVDA"])
    rep_ids = {i["intelligenceId"] for i in brief["newInstitutionalReports"]}
    rel_ids = {i["intelligenceId"] for i in brief["watchlistRelevance"]}
    assert note["intelligenceId"] in rep_ids
    assert note["intelligenceId"] in rel_ids


def test_watchlist_relevance_filters_non_watchlist():
    on = _item(title="JPMorgan research note on Micron", author="JPMorgan",
               linkedAssets=["MU"], _contentType="RESEARCH_NOTE")
    off = _item(title="Goldman research note on Tesla", author="Goldman",
                linkedAssets=["TSLA"], _contentType="RESEARCH_NOTE")
    brief = B.build_daily_brief([on, off], ["MU"])
    rel_ids = {i["intelligenceId"] for i in brief["watchlistRelevance"]}
    assert on["intelligenceId"] in rel_ids
    assert off["intelligenceId"] not in rel_ids


# ── C. theme counting ──
def test_major_strategy_themes_counts():
    a = _item(title="JPMorgan outlook", author="JPMorgan", _contentType="STRATEGY_OUTLOOK",
              _linkedThemes=["AI_CAPEX", "RATES"])
    b = _item(title="Goldman outlook", author="Goldman", _contentType="STRATEGY_OUTLOOK",
              _linkedThemes=["AI_CAPEX"])
    c = _item(title="Morgan Stanley outlook", author="Morgan Stanley",
              _contentType="STRATEGY_OUTLOOK", _linkedThemes=["AI_CAPEX", "RATES"])
    brief = B.build_daily_brief([a, b, c], [])
    themes = {t["theme"]: t["count"] for t in brief["majorStrategyThemes"]}
    assert themes["AI_CAPEX"] == 3
    assert themes["RATES"] == 2
    # most-cited first
    assert brief["majorStrategyThemes"][0]["theme"] == "AI_CAPEX"


# ── D. active event links ──
def test_active_event_links_match_assets():
    it = _item(title="JPMorgan note on Micron", author="JPMorgan",
               linkedAssets=["MU"], _contentType="RESEARCH_NOTE")
    other = _item(title="Goldman note on Apple", author="Goldman",
                  linkedAssets=["AAPL"], _contentType="RESEARCH_NOTE")
    brief = B.build_daily_brief([it, other], ["MU"],
                                active_events=[{"eventId": "e1", "linkedAssets": ["MU"]}])
    assert len(brief["activeEventLinks"]) == 1
    link = brief["activeEventLinks"][0]
    assert link["eventId"] == "e1"
    ids = {i["intelligenceId"] for i in link["items"]}
    assert it["intelligenceId"] in ids
    assert other["intelligenceId"] not in ids


# ── E. licensed feeds always reported unavailable ──
def test_licensed_feeds_in_sources_unavailable():
    brief = B.build_daily_brief([], [])
    sids = {s["sourceId"] for s in brief["sourcesUnavailable"]}
    for licensed in ("bloomberg_feed", "lseg_mrn", "factiva_ai", "ravenpack"):
        assert licensed in sids
    licensed_rows = [s for s in brief["sourcesUnavailable"]
                     if s["sourceId"] == "bloomberg_feed"]
    assert licensed_rows and licensed_rows[0]["accessClass"] == "UNAVAILABLE"
    assert licensed_rows[0]["reason"] == "LICENSED_NOT_CONFIGURED"


def test_zero_item_rss_feed_reported_unavailable():
    # one rss source produced an item; another known rss source is silent.
    it = _item(sourceId="cnbc_public", title="Some market headline")
    brief = B.build_daily_brief([it], [], rss_item_counts={"cnbc_public": 1})
    rss_silent = {s["sourceId"] for s in brief["sourcesUnavailable"]
                  if s["reason"] == "RSS_ZERO_ITEMS"}
    assert "cnbc_public" not in rss_silent          # produced an item → not silent
    assert "marketwatch_public" in rss_silent       # known rss, zero items this run


# ── F. UNCONFIRMED labelling: directional view with no official corroboration ──
def test_directional_view_without_official_is_unconfirmed():
    cautious = _item(title="JPMorgan cautious: Micron downside risk on demand weakness",
                     author="JPMorgan", linkedAssets=["MU"], _contentType="RESEARCH_NOTE")
    assert cautious["institutionId"] == "jpmorgan"
    assert cautious["stance"] == "cautious"
    brief = B.build_daily_brief([cautious], ["MU"])
    unresolved = brief["unresolvedClaims"]
    assert any(u["intelligenceId"] == cautious["intelligenceId"] for u in unresolved)
    row = next(u for u in unresolved if u["intelligenceId"] == cautious["intelligenceId"])
    assert row["status"] == "UNCONFIRMED"


def test_official_corroboration_removes_from_unresolved():
    # same cluster: a directional JPMorgan view + an item from an OFFICIAL source
    # (sec_press, kind='official') on the same story → corroborated, so the view is
    # NOT an unresolved claim. They share a cluster because their norm-key inputs
    # (institution, content-type, asset, title fingerprint) match.
    headline = "JPMorgan cautious: Micron downside risk on demand weakness"
    view = _item(sourceId="marketwatch_public", title=headline, author="JPMorgan",
                 linkedAssets=["MU"], _contentType="RESEARCH_NOTE")
    official = _item(sourceId="sec_press", title=headline, author="JPMorgan",
                     linkedAssets=["MU"], _contentType="RESEARCH_NOTE")
    assert M.source_rights("sec_press")["kind"] == "official"
    view["institutionId"] = "jpmorgan"
    official["institutionId"] = "jpmorgan"
    # sanity: they really do land in ONE cluster
    assert M._norm_key(view) == M._norm_key(official)
    brief = B.build_daily_brief([view, official], ["MU"])
    unresolved_ids = {u["intelligenceId"] for u in brief["unresolvedClaims"]}
    assert view["intelligenceId"] not in unresolved_ids


# ── caps: every list is short ──
def test_lists_are_capped():
    many = []
    for i in range(30):
        many.append(_item(title=f"JPMorgan upgrade number {i} of Stock{i}",
                          author="JPMorgan", linkedAssets=[f"SYM{i}"],
                          _contentType="ANALYST_UPGRADE",
                          firstDetectedAt=f"2026-06-25T12:{i:02d}:00Z"))
    watch = [f"SYM{i}" for i in range(30)]
    brief = B.build_daily_brief(many, watch)
    assert len(brief["newAnalystActions"]) <= 8
    assert len(brief["watchlistRelevance"]) <= 8
    # counts reflect the true (uncapped) totals
    assert brief["counts"]["analystActions"] == 30


def test_custom_cap_respected():
    items = [_item(title=f"JPMorgan upgrade of S{i}", author="JPMorgan",
                   linkedAssets=[f"S{i}"], _contentType="ANALYST_UPGRADE")
             for i in range(10)]
    brief = B.build_daily_brief(items, [f"S{i}" for i in range(10)], cap=3)
    assert len(brief["newAnalystActions"]) <= 3


# ── purity / safety ──
def test_no_trade_surface():
    for bad in ("place_order", "execute_trade", "buy", "sell", "broker", "size_position"):
        assert not hasattr(B, bad)


def test_owner_only_and_boundary_flags():
    brief = B.build_daily_brief([], [])
    assert brief["ownerOnly"] is True
    assert brief["calibration"] == "uncalibrated_heuristic_v1"
    assert "売買指示ではない" in brief["boundaryNote"]


def test_empty_inputs_are_safe():
    brief = B.build_daily_brief([], [])
    assert brief["counts"]["totalItems"] == 0
    assert brief["newAnalystActions"] == []
    assert brief["asOf"] is None
    # licensed feeds still surface even with no items
    assert brief["counts"]["sourcesUnavailable"] >= 4


def test_named_view_flag_present():
    note = _item(title="JPMorgan research note on Micron", author="JPMorgan",
                 linkedAssets=["MU"], _contentType="RESEARCH_NOTE")
    brief = B.build_daily_brief([note], ["MU"])
    rel = brief["watchlistRelevance"][0]
    assert rel["isNamedView"] is True
    assert rel["institutionName"] == "JPMorgan"
