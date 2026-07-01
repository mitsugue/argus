"""Institutional Intelligence / Research Mesh core (argus_research_mesh, v1)."""
import argus_research_mesh as M


# ── source rights enforcement (§4/§30) ──
def test_rights_metadata_only_strips_fulltext():
    rec = M.enforce_storage("marketwatch_public", {"title": "x", "fullText": "BODY", "publicSnippet": "snip"})
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
    items = [M.normalize_item({"sourceId": "marketwatch_public", "title": "JPMorgan flags Micron earnings risk", "linkedAssets": ["MU"], "firstDetectedAt": "2026-06-25T14:02:00Z"}),
             M.normalize_item({"sourceId": "cnbc_public", "title": "JPMorgan flags Micron earnings risk", "linkedAssets": ["MU"], "firstDetectedAt": "2026-06-25T14:05:00Z"})]
    clusters = M.cluster_items(items)
    assert len(clusters) == 1 and clusters[0]["count"] == 2 and clusters[0]["syndicationCount"] == 1


# ── causal integrity (§2/§11/§30) ──
def test_report_after_move_not_trigger():
    item = M.normalize_item({"sourceId": "bloomberg_public", "title": "JPMorgan note on Micron", "linkedAssets": ["MU"], "publishedAt": "2026-06-25T15:00:00Z"})
    link = M.link_to_event(item, {"eventId": "e1", "linkedAssets": ["MU"], "moveStartedAt": "2026-06-25T14:00:00Z"})
    assert link["causalRole"] != "IMMEDIATE_TRIGGER" and link["causalRole"] == "AMPLIFIER"

def test_named_view_is_not_named_trade():
    item = M.normalize_item({"sourceId": "marketwatch_public", "title": "JPMorgan cautious on Micron", "linkedAssets": ["MU"], "publishedAt": "2026-06-25T13:50:00Z"})
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
    a = M.normalize_item({"sourceId": "marketwatch_public", "title": "Snowflake surges 36% for best day ever"})
    b = M.normalize_item({"sourceId": "cnbc_public",    "title": "Snowflake surges 36% for best day ever"})
    cl = M.cluster_items([a, b])
    assert len(cl) == 1 and cl[0]["syndicationCount"] == 1


# ── corroboration (§9, v10.170): source-FAMILY aware, official-priority ──
def test_source_family_collapses_wire_to_one():
    # Dow Jones stable (MarketWatch / WSJ / Barron's) is ONE family, not three.
    assert M.source_family("marketwatch_public") == "dowjones"
    assert M.source_family("Wall Street Journal") == "dowjones"
    assert M.source_family("CNBC") == "cnbc"
    assert M.is_official_source("federal_reserve") and M.is_official_source("sec_press")

def test_corroboration_single_when_same_family():
    # two Dow Jones outlets = one origin family = NOT independent corroboration
    assert M.corroboration_level(["marketwatch_public", "Wall Street Journal"]) == "single"

def test_corroboration_corroborated_two_independent_families():
    assert M.corroboration_level(["cnbc_public", "bloomberg_public"]) == "corroborated"

def test_corroboration_official_outranks_count():
    assert M.corroboration_level(["federal_reserve"]) == "official"

def test_corroboration_aggregators_are_not_independent():
    # yahoo + nasdaq are portals that re-syndicate → never counted as independent
    assert M.corroboration_level(["yahoo_finance_public", "nasdaq_public"]) == "single"

def test_cluster_emits_corroboration_level():
    items = [M.normalize_item({"sourceId": "cnbc_public", "title": "Fed signals rate cut path", "linkedAssets": ["_"]}),
             M.normalize_item({"sourceId": "bloomberg_public", "title": "Fed signals rate cut path", "linkedAssets": ["_"]})]
    cl = M.cluster_items(items)
    assert len(cl) == 1 and cl[0]["corroborationLevel"] == "corroborated"


# ── entity+event+time corroboration (§9b, v10.172) — adversarial set from the design workflow ──
from datetime import datetime, timedelta, timezone

_CORROB_BASE = datetime(2026, 6, 26, 18, 0, 0, tzinfo=timezone.utc)

def _mk_news(title, source, asset, hours_ago):
    fd = None if (hours_ago is None or hours_ago < 0) else (_CORROB_BASE - timedelta(hours=hours_ago)).isoformat()
    return M.normalize_item({"sourceId": source, "title": title,
                             "linkedAssets": [asset] if asset else [], "firstDetectedAt": fd})

# (name, aTitle, aSrc, aAsset, aHrs, bTitle, bSrc, bAsset, bHrs, shouldCorroborate)
_CORROB_CASES = [
    ("fed_ratecut", "Fed signals rate cut path as inflation cools", "reuters", "SPY", 2,
     "Powell hints at September easing after price data", "bloomberg", "SPY", 1.5, True),
    ("micron_earnings", "Micron earnings beat on AI memory demand", "reuters", "MU", 5,
     "Micron tops Wall Street estimates, lifted by HBM boom", "cnbc", "MU", 4, True),
    ("nvidia_launch", "Nvidia unveils next-gen Blackwell chips at GTC", "bloomberg", "NVDA", 3,
     "Jensen Huang debuts new AI accelerators at developer event", "marketwatch_public", "NVDA", 2.5, True),
    ("boeing_ceo", "Boeing CEO Calhoun to step down amid safety crisis", "reuters", "BA", 6,
     "Boeing chief exits as 737 Max troubles deepen", "bloomberg", "BA", 5.5, True),
    ("toyota_guidance_en_jp", "Toyota raises full-year profit forecast on weak yen", "cnbc", "7203.T", 8,
     "トヨタ、通期利益見通しを上方修正 円安追い風", "nikkei_web", "7203.T", 7, True),
    ("payrolls", "US adds 250,000 jobs in May, beating expectations", "reuters", "SPY", 4,
     "Hiring surges as payrolls top forecasts last month", "bloomberg", "SPY", 3.5, True),
    ("disney_proxy", "Disney board defeats Peltz in proxy fight", "reuters", "DIS", 10,
     "Iger prevails over activist Trian in shareholder vote", "bloomberg", "DIS", 9, True),
    ("window_inside", "Fed signals rate-cut path as inflation cools", "reuters", "SPY", 0,
     "Powell hints at September easing, markets cheer", "bloomberg_public", "SPY", 5.5, True),
    ("official_single", "Federal Reserve issues FOMC statement, holds rates at 4.25%", "federal_reserve", "SPY", 1,
     "Federal Reserve issues FOMC statement, holds rates at 4.25%", "federal_reserve", "SPY", 1, True),
    ("window_outside", "Nvidia tops Q1 estimates on surging data-center demand", "reuters", "NVDA", 0,
     "Nvidia beats forecasts as AI chip orders accelerate", "cnbc_public", "NVDA", 96, False),
    ("nvidia_pt_polarity", "Nvidia price target raised to 200 at Morgan Stanley", "bloomberg_public", "NVDA", 6,
     "Nvidia price target lowered to 120 at HSBC", "reuters", "NVDA", 5, False),
    ("micron_earnings_vs_lawsuit", "Micron earnings beat as HBM demand surges", "reuters", "MU", 0,
     "Micron sued by investor over alleged disclosure lapse", "bloomberg_public", "MU", 2, False),
    ("visa_earnings_vs_antitrust", "Visa profit rises on resilient consumer spending", "reuters", "V", 8,
     "Visa hit with antitrust suit over debit card fees", "bloomberg_public", "V", 7, False),
    ("boeing_grounding_vs_order", "Boeing 737 Max grounded after door panel blows out mid-flight", "reuters", "BA", 30,
     "Boeing wins record order from Emirates at Dubai Airshow", "cnbc_public", "BA", 3, False),
    ("meta_earnings_vs_launch", "Meta shares slump as Reality Labs losses widen", "marketwatch_public", "META", 10,
     "Meta unveils new Llama model at developer conference", "bloomberg_public", "META", 9, False),
    ("tesla_deliveries_vs_recall", "Tesla deliveries miss estimates in second quarter", "reuters", "TSLA", 72,
     "Tesla recalls Cybertruck over accelerator pedal issue", "cnbc_public", "TSLA", 2, False),
    ("intel_dividend_vs_grant", "Intel cuts dividend to fund foundry buildout", "bloomberg_public", "INTC", 5,
     "Intel awarded 8.5 billion in CHIPS Act grants", "reuters", "INTC", 5, False),
    ("republic_name_collision", "First Republic Bank seized by regulators, sold to JPMorgan", "cnbc_public", "FRC", 4,
     "Republic Services raises full-year guidance on pricing", "marketwatch_public", "RSG", 4, False),
    ("aggregator_only", "Tesla deliveries miss as China demand softens", "yahoo_finance_public", "TSLA", 0.5,
     "Tesla Q2 deliveries fall short on weak China sales", "nasdaq_public", "TSLA", 2, False),
    ("same_wire_syndication", "Apple unveils M5 chip with on-device AI, shares rise", "reuters", "AAPL", 0,
     "Apple unveils M5 chip with on-device AI, shares rise", "yahoo_finance_public", "AAPL", 0.3, False),
    ("two_outlets_one_family", "Boeing wins $10B order from Emirates for 777X jets", "marketwatch_public", "BA", 0,
     "Emirates places $10 billion Boeing 777X order", "barrons", "BA", 1.5, False),
    ("missing_timestamp", "Intel cuts 2026 capex guidance amid foundry losses", "reuters", "INTC", 0,
     "Intel slashes capital spending plan as foundry bleeds cash", "cnbc_public", "INTC", -1, False),
]

def test_corroboration_entity_event_time_clustering():
    failures = []
    for name, at, asrc, aa, ah, bt, bsrc, ba, bh, expect in _CORROB_CASES:
        a = _mk_news(at, asrc, aa, ah)
        b = _mk_news(bt, bsrc, ba, bh)
        cl = M.cluster_items([a, b])
        same = a["storyClusterId"] == b["storyClusterId"]
        level = next((c["corroborationLevel"] for c in cl if c["storyClusterId"] == a["storyClusterId"]), "single")
        corroborated = same and level in ("corroborated", "official")
        if corroborated != expect:
            failures.append(f"{name}: corroborated={corroborated} (same={same} level={level}) expected={expect}")
    assert not failures, "CORROBORATION FAILURES:\n" + "\n".join(failures)


# ── §5 category separation + §11 trigger gating (Phase B, v10.197) ────────────
def test_map_category_separates_action_disclosure_view():
    assert M.map_category("ANALYST_DOWNGRADE", "goldman_sachs", "sell_side") == "ANALYST_ACTION"
    assert M.map_category("PRICE_TARGET_CHANGE", "jpmorgan", "sell_side") == "ANALYST_ACTION"
    assert M.map_category("REGULATORY_FILING", "blackrock", "asset_manager") == "DISCLOSED_POSITION"
    assert M.map_category("STRATEGY_OUTLOOK", "goldman_sachs", "sell_side") == "INSTITUTIONAL_RESEARCH_VIEW"
    assert M.map_category("MARKET_NEWS", None, None) == "MARKET_NEWS"

def test_analyst_action_on_buyside_is_not_disclosed_position():
    # a rating-action content type maps to ANALYST_ACTION regardless of institution type
    assert M.map_category("ANALYST_UPGRADE", "blackrock", "asset_manager") == "ANALYST_ACTION"

def test_immediate_trigger_only_for_hard_news_not_named_view():
    # hard news (a downgrade), no named VIEW, asset-matched, published BEFORE the move → IMMEDIATE_TRIGGER
    hard = M.normalize_item({"sourceId": "marketwatch_public", "title": "Micron downgraded to sell",
                             "linkedAssets": ["MU"], "publishedAt": "2026-06-25T13:50:00Z"})
    link_hard = M.link_to_event(hard, {"eventId": "e1", "linkedAssets": ["MU"], "moveStartedAt": "2026-06-25T14:00:00Z"})
    assert link_hard["causalRole"] == "IMMEDIATE_TRIGGER"
    # a NAMED institutional VIEW with identical perfect timing is NEVER a trigger
    view = M.normalize_item({"sourceId": "marketwatch_public", "title": "JPMorgan cautious on Micron",
                             "linkedAssets": ["MU"], "publishedAt": "2026-06-25T13:50:00Z"})
    link_view = M.link_to_event(view, {"eventId": "e1", "linkedAssets": ["MU"], "moveStartedAt": "2026-06-25T14:00:00Z"})
    assert link_view["isNamedView"] is True
    assert link_view["causalRole"] != "IMMEDIATE_TRIGGER"

def test_new_institution_aliases_resolve():
    assert M.resolve_institution("RBC Capital Markets lifts target") == "rbc_capital_markets"
    assert M.resolve_institution("Two Sigma builds stake") == "two_sigma"
    assert M.resolve_institution("東海東京証券のレポート") == "tokai"
    # a bare unrelated word must NOT false-match an institution
    assert M.resolve_institution("the weather today is fine") is None


# ── §22 missed-intelligence replay (Phase E, v10.198) ────────────────────────
def test_diagnose_miss_unknown_institution():
    d = M.diagnose_miss(title="SomeBoutique cuts Toyota target", institution="SomeBoutique Advisors", symbol="7203",
                        known_symbol_names={"7203": "Toyota"})
    assert d["likelyCause"] == "institution_alias"
    assert d["suggestedFix"]["type"] == "add_institution_alias"

def test_diagnose_miss_asset_not_named():
    d = M.diagnose_miss(title="Goldman turns cautious on chip demand", institution="Goldman Sachs", symbol="5803",
                        known_symbol_names={"5803": "Fujikura"})
    assert d["likelyCause"] == "asset_link"

def test_diagnose_miss_passes_when_resolvable():
    d = M.diagnose_miss(title="Goldman Sachs downgrades Toyota", institution="Goldman Sachs", symbol="7203",
                        known_symbol_names={"7203": "Toyota"})
    assert d["likelyCause"] == "passed_gates"
    assert d["institutionResolved"] == "goldman_sachs"
