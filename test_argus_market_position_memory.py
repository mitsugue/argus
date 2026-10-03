"""Market position memory: append-only theme entries from existing stores, no AI."""
import json

import argus_market_position_memory as mpm

NEWS = [
    {"eventId": "nie-1", "severity": "HIGH", "eventType": "FED", "headlineJa": "FRB高官、年内の追加利上げを示唆",
     "sourceReceivedAt": "2026-09-28T13:00:00Z", "sourceFamily": "FRB", "confirmationState": "MARKET_CONFIRMED"},
    {"eventId": "nie-2", "severity": "CRITICAL", "eventType": "WAR_ESCALATION", "headlineJa": "米軍、中東へ数千人を追加派遣",
     "sourceReceivedAt": "2026-10-01T02:00:00Z", "sourceFamily": "NIKKEI"},
    {"eventId": "nie-3", "severity": "WATCH", "eventType": "FED", "headlineJa": "小さな話", "sourceReceivedAt": "2026-10-01T03:00:00Z"},
    {"eventId": "nie-4", "severity": "HIGH", "eventType": "EARNINGS", "headlineJa": "決算", "sourceReceivedAt": "2026-10-01T03:00:00Z"},
    {"eventId": "nie-5", "severity": "HIGH", "eventType": "BOJ", "headlineJa": "翻訳処理中", "sourceReceivedAt": "2026-10-01T03:00:00Z"},
]
RECORD = {"eventId": "ev-nfp-20261002", "eventCode": "NFP", "title": "米雇用統計",
          "releaseReaction": {"basis": "PRE_RELEASE_BASELINE", "eventTimeUtc": "2026-10-02T12:30:00Z",
                              "baseline": {"capturedAt": "2026-10-02T12:29:00Z", "values": {"ZQ=F": {"price": 96.05}}},
                              "windows": {"+5m": {"observedAt": "2026-10-02T12:35:00Z",
                                                  "moves": {"ffImpliedRateMoveBp": -2.5, "ffImpliedRateAfterPct": 3.925,
                                                            "nasdaqFuturesMovePct": 0.86, "nikkeiFuturesMovePct": 1.17},
                                                  "reading": {"code": "RATE_RELIEF_RISK_ON", "labelJa": "利上げ観測の後退を安心材料に株高"}}}}}
CALENDAR = [{"eventCode": "FOMC", "title": "FOMC", "eventTimeUtc": "2026-10-28T18:00:00Z"},
            {"eventCode": "CPI", "title": "米CPI", "eventTimeUtc": "2026-10-14T12:30:00Z"},
            {"eventCode": "BOJ", "title": "日銀会合", "eventTimeUtc": "2026-10-30T03:00:00Z"},
            {"eventCode": "NFP", "title": "過去", "eventTimeUtc": "2026-10-02T12:30:00Z"}]


def test_news_entries_are_themed_filtered_and_appended_once():
    memory = mpm.empty()
    assert mpm.ingest_news(memory, NEWS) == 2             # WATCH, EARNINGS and pending translation are left out
    assert mpm.ingest_news(memory, NEWS) == 0
    themes = {row["themeId"] for row in memory["entries"]}
    assert themes == {"US_POLICY_RATE", "MIDDLE_EAST"}
    row = next(r for r in memory["entries"] if r["themeId"] == "MIDDLE_EAST")
    assert row["textJa"].startswith("NIKKEI: 米軍") and row["severity"] == "CRITICAL" and row["ref"]["eventId"] == "nie-2"


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
    assert us["status"] == "ACTIVE" and us["entryCount"] == 3 and us["pricing"] == {"ffImpliedRatePct": 3.95}
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
