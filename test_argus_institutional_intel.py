"""ARGUS V11.6.0 — Institutional Intelligence layer (pure): registry / classification /
directness / headline-only limited confidence / dedupe / asset mapping / no trading."""
import json

import argus_institutional_intel as II

NOW = "2026-07-04T06:00:00Z"
OWNER = {"NVDA", "9984", "TSLA", "GLD"}


def _item(title, *, snippet="", inst=None, source="cnbc_public", assets=None,
          published="2026-07-04T04:00:00Z", lang="en"):
    return {"intelligenceId": f"ii-{abs(hash(title)) % 99999}", "title": title,
            "publicSnippet": snippet, "institutionId": inst, "sourceId": source,
            "linkedAssets": assets or [], "linkedThemes": [], "language": lang,
            "publishedAt": published, "fetchedAt": NOW, "canonicalUrl": "https://x/y",
            "sourceTier": "reputable"}


# ── source registry ──────────────────────────────────────────────────────────

def test_registry_contains_spec_banks_and_honest_statuses():
    reg = II.build_source_registry()
    names = {b["sourceName"] for b in reg["banks"]}
    for want in ("JPMorgan", "Goldman Sachs", "Morgan Stanley", "Bank of America",
                 "Citi", "UBS", "Nomura Securities", "Mizuho Securities",
                 "Daiwa Securities", "SMBC Nikko Securities",
                 "Mitsubishi UFJ Morgan Stanley Securities"):
        assert want in names, want
    media = {m["sourceName"]: m for m in reg["media"]}
    assert media["Financial Times"]["status"] == "metadata_only"      # paywall honesty
    assert media["Wall Street Journal"]["status"] == "metadata_only"
    assert media["Barron's"]["status"] == "disabled"
    assert media["Reuters"]["status"] == "live"
    official = {o["sourceName"]: o for o in reg["official"]}
    assert official["Federal Reserve"]["sourceType"] == "central_bank"
    assert official["SEC / EDGAR"]["status"] == "live"
    assert official["FSA Japan"]["status"] == "disabled"              # no fabricated feed


# ── classification ───────────────────────────────────────────────────────────

def test_stance_labels():
    assert II.classify_stance("goldman upgrades nvda, strong upside") == "bullish"
    assert II.classify_stance("jpmorgan warns of downside risk") == "bearish"
    assert II.classify_stance("upgrade but concern remains on risk") == "mixed"
    assert II.classify_stance("bullish if the fed cuts rates") == "conditional"
    assert II.classify_stance("bank of japan holds meeting") == "neutral"


def test_claim_types():
    assert II.classify_claim_type("morgan stanley upgrades tesla 格上げ") == "upgrade"
    assert II.classify_claim_type("citi downgrade on weak guidance") == "downgrade"
    assert II.classify_claim_type("ubs initiates coverage of ionq") == "initiation"
    assert II.classify_claim_type("goldman warns of ai bubble correction risk") == "risk_warning"
    assert II.classify_claim_type("what to expect ahead of friday's cpi") == "event_preview"
    assert II.classify_claim_type("stocks rally after the fomc decision を受けて") == "event_reaction"
    assert II.classify_claim_type("fed rate cut path and inflation 金利") == "macro_view"


def test_directness_mapping():
    up = _item("Goldman upgrades NVDA price target", inst="goldman_sachs", assets=["NVDA"])
    assert II.build_signal(up, owner_assets=OWNER, now_iso=NOW)["directness"] == "direct_cause"
    rel = _item("SoftBank mentioned in AI datacenter flows", assets=["9984"])
    assert II.build_signal(rel, owner_assets=OWNER, now_iso=NOW)["directness"] == "related_signal"
    bg = _item("JPMorgan macro view: fed rates path", inst="jpmorgan")
    assert II.build_signal(bg, owner_assets=OWNER, now_iso=NOW)["directness"] == "background"
    weak = _item("celebrity buys a house")
    assert II.build_signal(weak, owner_assets=OWNER, now_iso=NOW)["directness"] == "weak_context"


def test_headline_only_limited_confidence():
    s = II.build_signal(_item("Nikkei: BOJ policy shift view 金利", snippet=""),
                        owner_assets=OWNER, now_iso=NOW)
    assert s["headlineOnly"] is True
    assert s["confidence"] <= 0.4
    assert "headline-only" in s["complianceNote"]
    assert s["ownerReadableWhy"].startswith("(見出しベース")
    s2 = II.build_signal(_item("BOJ view", snippet="Full public summary text here 金利"),
                         owner_assets=OWNER, now_iso=NOW)
    assert s2["headlineOnly"] is False


def test_owner_asset_mapping_and_importance():
    hit = II.build_signal(_item("Morgan Stanley upgrades NVDA", inst="morgan_stanley",
                                assets=["NVDA", "AMD"]), owner_assets=OWNER, now_iso=NOW)
    miss = II.build_signal(_item("Morgan Stanley upgrades XYZ", inst="morgan_stanley",
                                 assets=["XYZ"]), owner_assets=OWNER, now_iso=NOW)
    assert hit["ownerAssetHit"] is True
    assert hit["affectedAssets"][0] == "NVDA"          # owner assets first
    assert hit["importance"] > miss["importance"]


def test_build_signals_dedupe_and_rank():
    items = [
        _item("Goldman upgrades NVDA price target to new high", inst="goldman_sachs",
              assets=["NVDA"]),
        _item("Goldman upgrades NVDA price target to new high!!", inst="goldman_sachs",
              assets=["NVDA"]),                                    # syndicated dup
        _item("random blog says stocks"),                          # not qualified
        _item("Fed statement on rates 金利", source="federal_reserve"),
    ]
    sigs = II.build_signals(items, owner_assets=OWNER, now_iso=NOW)
    heads = [s["headline"] for s in sigs]
    assert len([h for h in heads if "Goldman upgrades" in h]) == 1  # deduped
    assert any(s["sourceType"] == "central_bank" for s in sigs)
    assert all(sigs[i]["importance"] >= sigs[i + 1]["importance"] for i in range(len(sigs) - 1))


def test_old_news_excluded_from_current():
    sigs = II.build_signals([_item("Goldman upgrades NVDA", inst="goldman_sachs",
                                   assets=["NVDA"], published="2026-06-20T00:00:00Z")],
                            owner_assets=OWNER, now_iso=NOW)
    assert sigs == []                                   # 過去材料はcurrentに出ない


def test_action_implication_never_a_trade():
    for title, inst, assets, snippet in [
        ("Goldman upgrades NVDA", "goldman_sachs", ["NVDA"], ""),
        ("JPMorgan warns of ai bubble risk", "jpmorgan", [], ""),
        ("Citi preview ahead of CPI", "citi", [], ""),
    ]:
        s = II.build_signal(_item(title, inst=inst, assets=assets, snippet=snippet),
                            owner_assets=OWNER, now_iso=NOW)
        assert s["actionImplication"] in II.ACTIONS
        blob = json.dumps(s, ensure_ascii=False).lower()
        for forbidden in ("buy now", "sell now", '"order"', '"trade":', "自動売買", "全力買い"):
            assert forbidden not in blob, forbidden
    # risk warning => caution; direct bullish => investigate (verify-first, not buy)
    warn = II.build_signal(_item("JPMorgan warns of downside risk", inst="jpmorgan"),
                           owner_assets=OWNER, now_iso=NOW)
    assert warn["actionImplication"] == "caution"
    up = II.build_signal(_item("Goldman upgrades NVDA", inst="goldman_sachs", assets=["NVDA"]),
                         owner_assets=OWNER, now_iso=NOW)
    assert up["actionImplication"] == "investigate"


def test_owner_readable_why_japanese():
    s = II.build_signal(_item("Goldman warns of AI capex bubble risk", inst="goldman_sachs"),
                        owner_assets=OWNER, now_iso=NOW)
    assert "慎重" in s["ownerReadableWhy"] or "売られやすく" in s["ownerReadableWhy"]
    assert s["checkNextJa"]


def test_regime_themes_and_handoff():
    sigs = II.build_signals([
        _item("Goldman: rotate into value, risk-off positioning", inst="goldman_sachs",
              snippet="risk-off"),
        _item("JPMorgan sees fed rate cut in September 利下げ", inst="jpmorgan"),
        _item("Morgan Stanley on AI datacenter capex boom", inst="morgan_stanley",
              snippet="ai capex"),
        _item("UBS bullish on japan equities flows 日本株", inst="ubs"),
    ], owner_assets=OWNER, now_iso=NOW)
    th = II.regime_themes(sigs)
    assert th["rate_cut"]["count"] >= 1
    assert th["ai_capex"]["count"] >= 1
    assert th["jp_flow"]["count"] >= 1
    ho = II.handoff_summary(sigs)
    assert ho["title"] == "Institutional Intelligence Summary"
    assert "disclaimerJa" in ho and "自動売買の指示ではありません" in ho["disclaimerJa"]
    assert isinstance(ho["missingEvidence"], list)
