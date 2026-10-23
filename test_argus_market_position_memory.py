"""Market position memory: append-only theme entries from existing stores, no AI."""
import json

import argus_market_position_memory as mpm

NEWS = [
    {"eventId": "nie-1", "severity": "HIGH", "eventType": "FED", "headlineJa": "FRB高官、年内の追加利上げを示唆",
     "sourceReceivedAt": "2026-09-28T13:00:00Z", "sourceFamily": "FRB", "confirmationState": "MARKET_CONFIRMED"},
    {"eventId": "nie-2", "severity": "CRITICAL", "eventType": "WAR_ESCALATION", "headlineJa": "米軍、中東へ数千人を追加派遣",
     "sourceReceivedAt": "2026-10-01T02:00:00Z", "sourceFamily": "NIKKEI"},
    {"eventId": "nie-3", "severity": "WATCH", "eventType": "FED", "headlineJa": "小さな話", "sourceReceivedAt": "2026-10-01T03:00:00Z"},
    {"eventId": "nie-4", "severity": "HIGH", "eventType": "OTHER_MARKET_RELEVANT", "headlineJa": "決算", "sourceReceivedAt": "2026-10-01T03:00:00Z"},
    {"eventId": "nie-5", "severity": "HIGH", "eventType": "BOJ", "headlineJa": "翻訳処理中", "sourceReceivedAt": "2026-10-01T03:00:00Z"},
]
# Raw synthetic quote clocks, rather than an unverified precomputed reading.
import argus_macro_release_reaction as rr
def _release_capture(at, prices):
    return {"capturedAt":at,"captureStartedAt":at,"source":rr.PROVIDER,"missing":[],
            "values":{symbol:{"price":value,"tradedAt":at,"receivedAt":at} for symbol,value in prices.items()}}
RECORD = {"eventId":"nfp-test","eventCode":"NFP","title":"米雇用統計",
          "releaseReaction":rr.build("nfp-test","2026-10-02T12:30:00Z",
              _release_capture("2026-10-02T12:28:00Z",{"ZQ=F":96.05,"NQ=F":26800,"NKD=F":68500}),
              {"+5m":_release_capture("2026-10-02T12:35:00Z",{"ZQ=F":96.075,"NQ=F":27030,"NKD=F":69300})})}

CALENDAR = [{"eventCode": "FOMC", "title": "FOMC", "eventTimeUtc": "2026-10-28T18:00:00Z"},
            {"eventCode": "CPI", "title": "米CPI", "eventTimeUtc": "2026-10-14T12:30:00Z"},
            {"eventCode": "BOJ", "title": "日銀会合", "eventTimeUtc": "2026-10-30T03:00:00Z"},
            {"eventCode": "NFP", "title": "過去", "eventTimeUtc": "2026-10-02T12:30:00Z"}]


def test_news_entries_are_themed_filtered_and_appended_once():
    memory = mpm.empty()
    # 2026-10-15: themed WATCH reporting is remembered too; unclassified news
    # (no fixed or emerging theme) and a pending translation are left out.
    assert mpm.ingest_news(memory, NEWS) == 3
    assert mpm.ingest_news(memory, NEWS) == 0
    themes = {row["themeId"] for row in memory["entries"]}
    assert themes == {"US_POLICY_RATE", "MIDDLE_EAST"}
    assert {row["ref"]["eventId"] for row in memory["entries"]} == {"nie-1", "nie-2", "nie-3"}
    row = next(r for r in memory["entries"] if r["themeId"] == "MIDDLE_EAST")
    assert row["textJa"].startswith("NIKKEI: 米軍") and row["severity"] == "CRITICAL" and row["ref"]["eventId"] == "nie-2"


def test_news_points_travel_with_the_headline_and_an_event_is_remembered_once():
    memory = mpm.empty()
    story = {"eventId": "nie-cpi", "severity": "WATCH", "eventType": "INFLATION",
             "headlineJa": "米CPI、市場予想上回る", "sourceReceivedAt": "2026-10-14T13:00:00Z",
             "sourceFamily": "NIKKEI",
             "facts": ["ガソリン高が物価を押し上げたとの報道", "利上げ警戒から株安との報道", "三つ目"]}
    assert mpm.ingest_news(memory, [story]) == 1
    row = memory["entries"][0]
    assert row["themeId"] == "US_POLICY_RATE" and row["severity"] == "WATCH"
    assert "ガソリン高が物価を押し上げた" in row["textJa"] and "利上げ警戒から株安" in row["textJa"]
    assert "三つ目" not in row["textJa"] and len(row["textJa"]) <= mpm.NEWS_TEXT_LIMIT
    # A later translation or analysis of the same article is not appended again.
    assert mpm.ingest_news(memory, [{**story, "headlineJa": "改訂後の見出し", "facts": []}]) == 0
    assert mpm.ingest_news(memory, [{**story, "eventId": "nie-info", "severity": "INFO"}]) == 0


def test_release_reaction_and_pricing_become_measured_entries():
    memory = mpm.empty()
    assert mpm.ingest_release_reaction(memory, RECORD) == 2
    assert mpm.ingest_release_reaction(memory, RECORD) == 0
    kinds = sorted(r["kind"] for r in memory["entries"])
    assert kinds == ["PRICING", "RELEASE_REACTION"]
    reaction = next(r for r in memory["entries"] if r["kind"] == "RELEASE_REACTION")
    assert "利上げ観測の後退を安心材料に株高(政策金利の予想-2.5bp→3.925%)" in reaction["textJa"]
    assert reaction["measured"]["readingCode"] == "RATE_RELIEF_RISK_ON" and reaction["at"] == "2026-10-02T12:35:00Z"
    pricing = next(r for r in memory["entries"] if r["kind"] == "PRICING")
    assert pricing["measured"] == {"ffImpliedRatePct": 3.95}
    assert mpm.ingest_release_reaction(memory, {"eventCode": "AUCTION", "releaseReaction": {}}) == 0


def test_snapshot_and_facts_put_the_position_first_with_next_check():
    memory = mpm.empty(); mpm.ingest_news(memory, NEWS); mpm.ingest_release_reaction(memory, RECORD)
    view = mpm.snapshot(memory, now_iso="2026-10-03T02:00:00Z", scheduled_events=CALENDAR)
    by_id = {t["themeId"]: t for t in view["themes"]}
    us = by_id["US_POLICY_RATE"]
    assert us["status"] == "ACTIVE" and us["entryCount"] == 4 and us["pricing"] == {"ffImpliedRatePct": 3.95}
    assert us["lastReaction"]["readingCode"] == "RATE_RELIEF_RISK_ON"
    assert us["nextEvent"]["title"] == "米CPI" and us["recent"][0]["kind"] in ("RELEASE_REACTION", "PRICING")
    assert by_id["BOJ"]["status"] == "EMPTY" and by_id["BOJ"]["nextEvent"]["title"] == "日銀会合"
    assert by_id["MIDDLE_EAST"]["status"] == "ACTIVE" and by_id["MIDDLE_EAST"]["nextEvent"] is None
    quiet = mpm.snapshot(memory, now_iso="2026-11-03T02:00:00Z")["themes"]
    assert {t["status"] for t in quiet if t["entryCount"]} == {"QUIET"}
    facts = mpm.explanation_facts(view)
    assert [f["provenance"]["eventId"] for f in facts] == ["market-position-US_POLICY_RATE", "market-position-MIDDLE_EAST"]
    assert facts[0]["verification"] == "VERIFIED" and facts[1]["verification"] == "CORROBORATED"
    assert facts[0]["text"].startswith("現在位置・米国の利上げ・利下げ観測。米雇用統計の発表+5m: 利上げ観測の後退")
    assert "次: 米CPI（2026-10-14 12:30Z）" in facts[0]["text"] and len(facts[0]["text"]) <= 160
    assert all(f["priority"] == "P1" and f["source"] == "market_position" for f in facts)
    assert view["automaticAiCalls"] == 0 and view["actionAuthority"] is False


def test_load_accepts_only_this_schema_and_bounds_entries():
    memory = mpm.empty(); mpm.ingest_news(memory, NEWS)
    raw = json.loads(json.dumps(memory))
    assert mpm.load(raw) == memory
    assert mpm.load({"schemaVersion": "other", "entries": [1]}) == mpm.empty()
    assert mpm.load({"schemaVersion": mpm.SCHEMA, "entries": [{"entryId": "x", "themeId": "NOPE"}]})["entries"] == []
    big = mpm.empty()
    for n in range(mpm.MAX_ENTRIES + 5):
        mpm.append(big, mpm._entry("JPY", "NEWS", f"2026-01-01T00:{n % 60:02d}:00Z", f"n{n}", ref={"i": n}))
    assert len(big["entries"]) == mpm.MAX_ENTRIES


def test_public_headlines_and_radar_widen_the_memory_as_watch_entries():
    import argus_news_intelligence as ni
    memory = mpm.empty()
    items = [{"sourceId": "reuters_jp", "title": "イラン革命防衛隊、ホルムズ海峡で艦船を拿捕", "publishedAt": "2026-10-02T20:00:00Z", "canonicalUrl": "https://example.com/a"},
             {"sourceId": "nikkei", "title": "今週の読まれた記事ランキング", "publishedAt": "2026-10-02T20:00:00Z"},
             {"sourceId": "old", "title": "イラン、制裁に反発", "publishedAt": "2026-09-20T00:00:00Z"},
             {"sourceId": "bloomberg", "title": "FRB高官、追加利上げに慎重", "publishedAt": "2026-10-03T00:30:00Z", "canonicalUrl": "http://insecure"}]
    assert mpm.ingest_public_headlines(memory, items, ni.classify_event, now_iso="2026-10-03T02:00:00Z") == 2
    assert mpm.ingest_public_headlines(memory, items, ni.classify_event, now_iso="2026-10-03T02:00:00Z") == 0
    kinds = {(r["themeId"], r["kind"], r["severity"]) for r in memory["entries"]}
    assert kinds == {("MIDDLE_EAST", "PUBLIC_HEADLINE", "WATCH"), ("US_POLICY_RATE", "PUBLIC_HEADLINE", "WATCH")}
    assert next(r for r in memory["entries"] if r["themeId"] == "US_POLICY_RATE")["ref"]["url"] is None
    radar = {"status": "live", "asOf": "2026-10-03T01:40:00Z", "themes": [
        {"key": "energy_geopolitics", "labelJa": "エネルギー・地政学", "count": 7, "level": "elevated"},
        {"key": "rates_shock", "labelJa": "米長期金利ショック", "count": 0, "level": "none"},
        {"key": "disaster", "labelJa": "災害", "count": 3, "level": "elevated"}]}
    assert mpm.ingest_radar(memory, radar) == 1
    assert mpm.ingest_radar(memory, radar) == 0
    assert mpm.ingest_radar(memory, {**radar, "asOf": "2026-10-03T01:55:00Z"}) == 0     # same hour
    assert mpm.ingest_radar(memory, {**radar, "asOf": "2026-10-03T02:05:00Z"}) == 1
    assert mpm.ingest_radar(memory, {**radar, "status": "stale"}) == 0
    row = next(r for r in memory["entries"] if r["kind"] == "RADAR")
    assert row["measured"] == {"count": 7, "level": "elevated"} and row["at"] == "2026-10-03T01:00Z"


def test_policy_rate_quote_becomes_one_pricing_entry_per_day():
    memory = mpm.empty()
    quote = {"symbol": "ZQ=F", "price": 96.07, "impliedRatePct": 3.93, "tradedAt": "2026-10-02T20:59:00Z"}
    assert mpm.ingest_policy_rate_quote(memory, quote) == 1
    assert mpm.ingest_policy_rate_quote(memory, {**quote, "price": 96.08, "impliedRatePct": 3.92, "tradedAt": "2026-10-02T22:00:00Z"}) == 0
    assert mpm.ingest_policy_rate_quote(memory, {**quote, "tradedAt": "2026-10-05T12:00:00Z"}) == 1
    assert mpm.ingest_policy_rate_quote(memory, None) == 0 and mpm.ingest_policy_rate_quote(memory, {"impliedRatePct": "x", "tradedAt": "2026-10-05T12:00:00Z"}) == 0
    view = mpm.snapshot(memory, now_iso="2026-10-05T13:00:00Z")
    us = next(t for t in view["themes"] if t["themeId"] == "US_POLICY_RATE")
    assert us["pricing"] == {"ffImpliedRatePct": 3.93} and us["status"] == "ACTIVE"


def test_ai_views_are_validated_like_sections_and_appended_once():
    memory = mpm.empty(); mpm.ingest_news(memory, NEWS); mpm.ingest_release_reaction(memory, RECORD)
    view = mpm.snapshot(memory, now_iso="2026-10-03T02:00:00Z", scheduled_events=CALENDAR)
    facts = mpm.explanation_facts(view)
    context = {"contextId": "ctx-1", "facts": [{"evidenceId": "brief-fact-" + f["provenance"]["eventId"], **f} for f in facts]}
    ids = [r["evidenceId"] for r in context["facts"]]
    good = [{"themeId": "US_POLICY_RATE", "expectationJa": "弱い雇用で追加利上げは見送られるとの見方",
             "fearJa": "次のCPIが強ければ利上げ観測が戻る", "triggerJa": "次のCPIと次回FOMCの示唆",
             "evidenceIds": [ids[0]], "kind": "INFERENCE"},
            {"themeId": "JPY", "expectationJa": "x", "fearJa": "y", "triggerJa": "z", "evidenceIds": [], "kind": "UNKNOWN"}]
    diag = {}
    import argus_market_brief
    check = lambda value, active, **kw: argus_market_brief.validate_theme_views(
        value, context, theme_ids=mpm.THEMES, active_theme_ids=active, fields=mpm.VIEW_FIELDS,
        text_limit=mpm.VIEW_TEXT_LIMIT, **kw)
    out = check(good, ["US_POLICY_RATE", "MIDDLE_EAST"], diagnostic=diag)
    assert diag["status"] == "ACCEPTED" and [v["themeId"] for v in out] == ["US_POLICY_RATE"]   # quiet JPY dropped
    assert check(None, []) == []
    bad = lambda **patch: check([{**good[0], **patch}], ["US_POLICY_RATE"], diagnostic=(d := {})) is None and d["reason"]
    assert bad(kind="FACT") == "position_view_is_inference"
    assert bad(evidenceIds=["brief-fact-nope"]) == "unknown_evidence_reference"
    assert bad(evidenceIds=[]) == "evidence_reference_required"
    assert bad(expectationJa="上がる確率は高い") == "unsupported_authority_or_probability"
    assert bad(fearJa="政策金利は4.50%に上がる") == "unsupported_numeric_tokens"
    assert bad(expectationJa="x" * 161) == "position_field_invalid"
    assert check([{**good[0], "extra": 1}], ["US_POLICY_RATE"]) is None
    assert check(good + [good[0]], ["US_POLICY_RATE"]) is None
    assert mpm.ingest_views(memory, out, context_id="ctx-1", generated_at="2026-10-03T02:10:00Z") == 1
    assert mpm.ingest_views(memory, out, context_id="ctx-2", generated_at="2026-10-03T03:10:00Z") == 0   # unchanged view
    changed = [{**out[0], "fearJa": "中東情勢の急変"}]
    assert mpm.ingest_views(memory, changed, context_id="ctx-3", generated_at="2026-10-03T04:10:00Z") == 1
    later = mpm.snapshot(memory, now_iso="2026-10-03T05:00:00Z")
    us = next(t for t in later["themes"] if t["themeId"] == "US_POLICY_RATE")
    assert us["view"]["fearJa"] == "中東情勢の急変" and us["view"]["contextId"] == "ctx-3" and us["view"]["kind"] == "INFERENCE"
    # The AI view is context for display, never evidence text the AI could cite back.
    assert all("期待:" not in f["text"] for f in mpm.explanation_facts(later))



def test_reaction_memory_rechecks_invalid_source_and_never_invents_pricing():
    from copy import deepcopy
    record = deepcopy(RECORD)
    record["releaseReaction"]["baseline"]["source"] = "synthetic-other-provider"
    original = deepcopy(record)
    memory = mpm.empty()
    assert mpm.ingest_release_reaction(memory,record) == 1
    assert not any(r["kind"] == "PRICING" for r in memory["entries"])
    reaction = memory["entries"][0]
    assert reaction["measured"]["readingCode"] == "UNMEASURED"
    assert reaction["measured"]["ffImpliedRateMoveBp"] is None
    assert reaction["ref"]["hasComparableMoves"] is False
    facts = mpm.explanation_facts(mpm.snapshot(memory,now_iso="2026-10-03T02:00:00Z"))
    assert facts[0]["verification"] == "CORROBORATED"
    assert "3.950" not in facts[0]["text"] and "反応を測れていない" in facts[0]["text"]
    assert record == original


def test_old_unverified_derived_memory_is_preserved_but_not_cited_as_current_evidence():
    from copy import deepcopy
    memory = mpm.empty();mpm.ingest_release_reaction(memory,RECORD)
    for entry in memory["entries"]:
        entry["ref"].pop("sourceTimeValidation")
        entry["ref"].pop("hasComparableMoves", None)
        # A real legacy entry's identity was made from its legacy body.
        entry.update(mpm._entry(entry["themeId"],entry["kind"],entry["at"],entry["textJa"],
                               ref=entry["ref"],severity=entry["severity"],measured=entry["measured"]))
    original = deepcopy(memory)
    view = mpm.snapshot(memory,now_iso="2026-10-03T02:00:00Z")
    theme = next(t for t in view["themes"] if t["themeId"] == "US_POLICY_RATE")
    assert theme["lastReaction"] is None and theme["pricing"] is None
    assert theme["excludedUnverifiedReleaseEntries"] == 2
    assert mpm.explanation_facts(view) == []
    assert memory == original
    assert mpm.ingest_release_reaction(memory,RECORD) == 2
    assert memory["entries"][:2] == original["entries"]
    assert mpm.ingest_release_reaction(memory,RECORD) == 0
    restored = mpm.snapshot(memory,now_iso="2026-10-03T02:00:00Z")
    facts = mpm.explanation_facts(restored)
    assert facts[0]["verification"] == "VERIFIED"


# ── Emerging themes (owner 2026-10-23) ─────────────────────────────────────
def _cyber(eid, at, severity="HIGH", family="CYBER_SECURITY"):
    return {"eventId": eid, "severity": severity, "eventType": family,
            "headlineJa": f"ハッカー集団の攻撃 {eid}", "sourceReceivedAt": at, "sourceFamily": "NIKKEI"}


def _emerging(memory, now_iso):
    view = mpm.snapshot(memory, now_iso=now_iso)
    return [t for t in view["themes"] if t.get("emerging")], view


def test_emerging_theme_appears_with_repeated_important_news_and_leaves_when_quiet():
    memory = mpm.empty()
    assert mpm.ingest_news(memory, [_cyber("c1", "2026-10-22T12:45:00Z")]) == 1
    shown, view = _emerging(memory, "2026-10-23T00:00:00Z")
    assert shown == []                                   # one story is an event, not a theme
    assert [t["themeId"] for t in view["themes"]] == list(mpm.FIXED_THEMES)
    mpm.ingest_news(memory, [_cyber("c2", "2026-10-25T01:00:00Z")])
    shown, view = _emerging(memory, "2026-10-25T02:00:00Z")
    assert [t["themeId"] for t in shown] == ["EMERGING_CYBER_SECURITY"]
    theme = shown[0]
    assert theme["labelJa"] == "サイバー・システム障害" and theme["status"] == "ACTIVE"
    assert theme["recent"][0]["ref"]["eventId"] == "c2"
    # The fixed seven keep their order; the new theme follows them.
    assert [t["themeId"] for t in view["themes"]][:7] == list(mpm.FIXED_THEMES)
    fact = next(f for f in mpm.explanation_facts(view)
                if f["provenance"]["eventId"] == "market-position-EMERGING_CYBER_SECURITY")
    assert fact["text"].startswith("現在位置・サイバー・システム障害(新しい話題)")
    # Still shown within 14 days of the last article, gone after.
    assert _emerging(memory, "2026-11-07T01:00:00Z")[0]
    assert _emerging(memory, "2026-11-08T01:30:00Z")[0] == []
    # Saved and public forms keep the emerging theme.
    restored = mpm.load(json.loads(json.dumps(memory)))
    assert len(restored["entries"]) == 2
    public = mpm.public_snapshot(view)
    assert public["themes"][-1]["themeId"] == "EMERGING_CYBER_SECURITY" and public["themes"][-1]["emerging"] is True


def test_emerging_theme_needs_two_important_or_four_articles_in_seven_days():
    memory = mpm.empty()
    mpm.ingest_news(memory, [_cyber("c1", "2026-10-01T00:00:00Z"), _cyber("c2", "2026-10-08T00:00:01Z")])
    assert _emerging(memory, "2026-10-08T01:00:00Z")[0] == []          # 7 days apart
    memory = mpm.empty()
    watch = [_cyber(f"w{i}", f"2026-10-1{i}T00:00:00Z", severity="WATCH") for i in range(4)]
    mpm.ingest_news(memory, watch[:3])
    assert _emerging(memory, "2026-10-13T01:00:00Z")[0] == []          # three WATCH
    mpm.ingest_news(memory, watch[3:])
    assert _emerging(memory, "2026-10-13T01:00:00Z")[0][0]["themeId"] == "EMERGING_CYBER_SECURITY"
    # Fixed families never become emerging; unclassified news is not named.
    other = mpm.empty()
    mpm.ingest_news(other, [_cyber(f"o{i}", "2026-10-13T00:00:00Z", family=family)
                            for i, family in enumerate(["OTHER_MARKET_RELEVANT"] * 4 + ["FED"] * 4)])
    assert _emerging(other, "2026-10-13T01:00:00Z")[0] == []


def test_at_most_two_emerging_themes_busiest_first():
    memory = mpm.empty()
    for family, count in (("EARNINGS", 4), ("CYBER_SECURITY", 3), ("REGULATION", 2), ("COMMODITIES", 2)):
        mpm.ingest_news(memory, [_cyber(f"{family}-{i}", f"2026-10-2{i}T00:00:00Z", family=family)
                                 for i in range(count)])
    shown, _ = _emerging(memory, "2026-10-24T00:00:00Z")
    assert [t["themeId"] for t in shown] == ["EMERGING_EARNINGS", "EMERGING_CYBER_SECURITY"]


def test_reclassified_news_moves_to_its_new_theme_without_rewriting_history():
    memory = mpm.empty()
    war = _cyber("nie-58ec472f1b292c45", "2026-10-22T12:45:00Z", family="WAR_ESCALATION")
    assert mpm.ingest_news(memory, [war]) == 1
    view = mpm.snapshot(memory, now_iso="2026-10-23T00:00:00Z")
    assert next(t for t in view["themes"] if t["themeId"] == "MIDDLE_EAST")["entryCount"] == 1
    # The news store re-derived it (news-policy-v7); a second cyber story follows.
    fixed = dict(war, eventType="CYBER_SECURITY", severity="WATCH")
    assert mpm.ingest_news(memory, [fixed, _cyber("c2", "2026-10-23T01:00:00Z"),
                                    _cyber("c3", "2026-10-23T01:10:00Z")]) == 3
    assert mpm.ingest_news(memory, [fixed]) == 0
    assert len(memory["entries"]) == 4                          # the old row stays stored
    view = mpm.snapshot(memory, now_iso="2026-10-23T02:00:00Z")
    middle_east = next(t for t in view["themes"] if t["themeId"] == "MIDDLE_EAST")
    assert middle_east["status"] == "EMPTY" and middle_east["recent"] == []
    cyber = next(t for t in view["themes"] if t["themeId"] == "EMERGING_CYBER_SECURITY")
    moved = next(r for r in cyber["recent"] if r["ref"]["eventId"] == war["eventId"])
    assert moved["ref"]["reclassifiedFrom"] == "MIDDLE_EAST"
    # Re-derived to an unthemed family: withdrawn from its old theme.
    gone = dict(_cyber("c4", "2026-10-23T01:30:00Z", family="FED"))
    mpm.ingest_news(memory, [gone])
    mpm.ingest_news(memory, [dict(gone, eventType="OTHER_MARKET_RELEVANT")])
    view = mpm.snapshot(memory, now_iso="2026-10-23T02:00:00Z")
    us = next(t for t in view["themes"] if t["themeId"] == "US_POLICY_RATE")
    assert us["status"] == "EMPTY" and all(r["kind"] != "NEWS_WITHDRAWN" for r in us["recent"])


def test_ai_views_may_cover_a_shown_emerging_theme():
    import argus_market_brief
    memory = mpm.empty()
    mpm.ingest_news(memory, [_cyber("c1", "2026-10-22T12:45:00Z"), _cyber("c2", "2026-10-23T00:00:00Z")])
    view = mpm.snapshot(memory, now_iso="2026-10-23T01:00:00Z")
    facts = mpm.explanation_facts(view)
    context = {"contextId": "ctx", "facts": [{"evidenceId": "brief-fact-" + f["provenance"]["eventId"], **f} for f in facts]}
    active = [t["themeId"] for t in view["themes"] if t["status"] == "ACTIVE"]
    row = {"themeId": "EMERGING_CYBER_SECURITY", "expectationJa": "被害は限定的との見方",
           "fearJa": "被害企業の事業停止が広がること", "triggerJa": "被害企業の続報",
           "evidenceIds": [context["facts"][0]["evidenceId"]], "kind": "INFERENCE"}
    diag = {}
    out = argus_market_brief.validate_theme_views(
        [row], context, theme_ids=mpm.THEMES, active_theme_ids=active, fields=mpm.VIEW_FIELDS,
        text_limit=mpm.VIEW_TEXT_LIMIT, diagnostic=diag)
    assert diag["status"] == "ACCEPTED" and out[0]["themeId"] == "EMERGING_CYBER_SECURITY"
    assert mpm.ingest_views(memory, out, context_id="ctx", generated_at="2026-10-23T01:05:00Z") == 1
    shown = next(t for t in mpm.snapshot(memory, now_iso="2026-10-23T01:10:00Z")["themes"]
                 if t["themeId"] == "EMERGING_CYBER_SECURITY")
    assert shown["view"]["fearJa"] == "被害企業の事業停止が広がること"


# ── Owner 2026-10-23: a short market summary for the news analysis ─────────
def test_news_ai_context_names_active_themes_and_the_latest_fear():
    assert mpm.news_ai_context(mpm.snapshot(mpm.empty(), now_iso="2026-10-23T00:00:00Z")) is None
    assert mpm.news_ai_context(None) is None
    memory = mpm.empty()
    mpm.ingest_news(memory, [
        _cyber("s1", "2026-10-22T10:00:00Z", family="SEMICONDUCTORS"),
        _cyber("f1", "2026-10-22T11:00:00Z", family="FED"),
        _cyber("c1", "2026-10-22T12:00:00Z"), _cyber("c2", "2026-10-22T13:00:00Z")])
    mpm.ingest_views(memory, [{"themeId": "AI_SEMIS", "expectationJa": "AI投資の継続",
                               "fearJa": "AI投資の回収不安で半導体株が崩れること" * 3,
                               "triggerJa": "大手の設備投資計画", "evidenceIds": [], "kind": "INFERENCE"}],
                     context_id="ctx", generated_at="2026-10-22T14:00:00Z")
    text = mpm.news_ai_context(mpm.snapshot(memory, now_iso="2026-10-23T00:00:00Z"))
    assert text.startswith("動きのある主題: ")
    assert "AI・半導体相場" in text and "米国の利上げ・利下げ観測" in text
    assert "新しい話題: サイバー・システム障害" in text
    assert "恐れ AI投資の回収不安" in text and "期待 AI投資の継続" in text
    assert len(text) <= mpm.NEWS_AI_CONTEXT_LIMIT == 300
    assert "s1" not in text                                   # no ids, no article text


# ── Owner 2026-10-23: one critical breaking report is a new topic for 72 hours ──
def _breaking(eid, at, severity="CRITICAL", family="CYBER_SECURITY", marker="【速報】"):
    row = _cyber(eid, at, severity=severity, family=family)
    row["titleOriginal"] = marker + "大手クラウドで大規模障害 " + eid
    row["headlineJa"] = row["titleOriginal"]
    return row


def test_one_critical_breaking_report_is_shown_for_72_hours_without_follow_up():
    memory = mpm.empty()
    mpm.ingest_news(memory, [_breaking("b1", "2026-10-23T00:00:00Z")])
    assert memory["entries"][0]["ref"]["breaking"] is True
    shown, _ = _emerging(memory, "2026-10-23T01:00:00Z")
    assert [t["themeId"] for t in shown] == ["EMERGING_CYBER_SECURITY"]
    assert shown[0]["emergingBasis"] == "BREAKING"
    assert _emerging(memory, "2026-10-25T23:59:00Z")[0]                  # within 72h
    assert _emerging(memory, "2026-10-26T00:01:00Z")[0] == []            # gone after 72h
    # A follow-up article extends the hold by another 72 hours.
    mpm.ingest_news(memory, [_cyber("f1", "2026-10-25T00:00:00Z", severity="WATCH")])
    assert _emerging(memory, "2026-10-27T23:00:00Z")[0][0]["emergingBasis"] == "BREAKING"
    assert _emerging(memory, "2026-10-28T00:01:00Z")[0] == []
    public = mpm.public_snapshot(mpm.snapshot(memory, now_iso="2026-10-25T01:00:00Z"))
    assert public["themes"][-1]["emergingBasis"] == "BREAKING"


def test_breaking_reports_below_critical_or_without_a_marker_wait_for_the_running_bar():
    for row in (_breaking("h1", "2026-10-23T00:00:00Z", severity="HIGH"),
                _breaking("h2", "2026-10-23T00:00:00Z", marker="")):
        memory = mpm.empty()
        mpm.ingest_news(memory, [row])
        assert _emerging(memory, "2026-10-23T01:00:00Z")[0] == []
    # 【特報】 counts as a breaking report too.
    memory = mpm.empty()
    mpm.ingest_news(memory, [_breaking("t1", "2026-10-23T00:00:00Z", marker="【特報】")])
    assert _emerging(memory, "2026-10-23T01:00:00Z")[0]
    # A running theme that also had a breaking report keeps the 14-day rule.
    memory = mpm.empty()
    mpm.ingest_news(memory, [_breaking("b1", "2026-10-23T00:00:00Z"), _cyber("c2", "2026-10-23T02:00:00Z")])
    shown, _ = _emerging(memory, "2026-11-01T00:00:00Z")
    assert shown and shown[0]["emergingBasis"] == "RUNNING"


def test_a_new_critical_breaking_report_is_not_buried_by_busier_themes():
    memory = mpm.empty()
    for family, count in (("EARNINGS", 4), ("REGULATION", 4)):
        mpm.ingest_news(memory, [_cyber(f"{family}-{i}", f"2026-10-2{i}T00:00:00Z", family=family)
                                 for i in range(count)])
    mpm.ingest_news(memory, [_breaking("b1", "2026-10-23T12:00:00Z")])
    shown, _ = _emerging(memory, "2026-10-24T00:00:00Z")
    assert [t["themeId"] for t in shown] == ["EMERGING_CYBER_SECURITY", "EMERGING_EARNINGS"]
    assert len(shown) == mpm.EMERGING_LIMIT == 2
    # Once its hold ends, the busier running themes return.
    shown, _ = _emerging(memory, "2026-10-26T13:00:00Z")
    assert [t["themeId"] for t in shown] == ["EMERGING_EARNINGS", "EMERGING_REGULATION"]
