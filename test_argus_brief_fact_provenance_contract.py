"""Every brief fact's provenance must pass the page's check (web/src/lib/marketBrief.ts
`provenance`): one failing fact makes the page reject the whole brief, and the
integrated explanation card disappears (2026-10-04: the market-position facts
from 10/3 and the macro-frequency facts had no `scope` and no time fields)."""
import re
from datetime import datetime

import argus_macro_frequency
import argus_market_position_memory as position


def page_accepts(p):
    if not isinstance(p, dict) or p.get("scope") != "published_metadata_snapshot":
        return False
    if not (p.get("eventId") is None or (isinstance(p.get("eventId"), str)
                                        and re.fullmatch(r"[a-zA-Z0-9_.:-]{1,160}", p["eventId"]))):
        return False
    if not (p.get("revision") is None or (isinstance(p.get("revision"), int) and p["revision"] >= 0)):
        return False
    if not (p.get("sourceLabel") is None or (isinstance(p.get("sourceLabel"), str) and len(p["sourceLabel"]) <= 160)):
        return False
    for key in ("publishedAt", "receivedAt", "observedAt"):
        if key not in p:
            return False                      # undefined fails the page's check
        value = p[key]
        if value is not None:
            try:
                datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            except ValueError:
                return False
    for key in ("sourceResponseSha256", "sourceRowSha256"):
        if key in p and not (isinstance(p[key], str) and re.fullmatch(r"[a-f0-9]{64}", p[key])):
            return False
    return p.get("url", None) is None or str(p["url"]).startswith("https://")


def test_the_page_contract_itself_is_mirrored():
    source = open("web/src/lib/marketBrief.ts", encoding="utf-8").read()
    assert "value.scope !== 'published_metadata_snapshot'" in source
    assert "['publishedAt', 'receivedAt', 'observedAt'].every(key => value[key] === null || instant(value[key]))" in source


def test_macro_frequency_facts_pass_the_page_check():
    cpi = {"month": "2026-08", "yoyPct": 3.7, "yoyThreeMonthsEarlierPct": 4.3, "rising": False, "knownFrom": "2026-09-20"}
    facts = argus_macro_frequency.explanation_facts(cpi, 27.0)
    assert len(facts) == 2 and all(page_accepts(f["provenance"]) for f in facts)


def test_market_position_facts_pass_the_page_check():
    memory = position.load(None)
    position.ingest_news(memory, [
        {"eventId": "nie-1", "severity": "HIGH", "eventType": "FED", "headlineJa": "FRB、追加利上げを示唆",
         "sourceReceivedAt": "2026-10-01T03:00:00Z"}])
    view = position.snapshot(memory, now_iso="2026-10-01T05:00:00Z")
    facts = position.explanation_facts(view)
    assert facts and all(page_accepts(f["provenance"]) for f in facts)


def test_facts_carried_over_from_an_older_stored_brief_are_reshaped_for_the_page():
    """2026-10-04 evening: a brief stored before the producers were fixed became
    the 'previous' brief; its old-shape facts made the page reject the new one."""
    import argus_market_brief
    old_shape = {"eventId": "market-position-us-rates", "asOf": "2026-10-03T21:00:00Z",
                 "sourceLabelJa": "ARGUSの市場の現在位置メモ", "sourceRowSha256": "a" * 64}
    broken = {"eventId": "bad id with spaces", "receivedAt": "not-a-time", "url": "http://plain.example",
              "sourceResponseSha256": "XYZ", "revision": -1}
    good = {"scope": "published_metadata_snapshot", "eventId": "n225-1", "revision": 2, "sourceLabel": "J-Quants",
            "publishedAt": "2026-10-03T06:00:00Z", "receivedAt": "2026-10-03T07:00:00Z", "observedAt": None,
            "url": "https://example.com/a"}
    fact = lambda p, t: {"text": t, "source": "market_position", "priority": "P1", "verification": "CORROBORATED",
                         "provenance": p}
    previous = {"generatedAt": "2026-10-03T22:00:00Z", "facts": [fact(old_shape, "前回A"), fact(broken, "前回B")]}
    current = {"generatedAt": "2026-10-04T12:00:00Z", "facts": [fact(good, "今回")]}
    context = argus_market_brief.unified_context(current, previous)
    rows = context["facts"] + context["previousFacts"]
    assert len(rows) == 3 and all(page_accepts(r["provenance"]) for r in rows)
    assert context["facts"][0]["provenance"] == good                          # a valid shape is kept as is
    carried = context["previousFacts"][0]["provenance"]
    assert carried["eventId"] == "market-position-us-rates" and carried["sourceLabel"] == "ARGUSの市場の現在位置メモ"
    assert carried["receivedAt"] is None and carried["sourceRowSha256"] == "a" * 64   # nothing invented
    fixed = context["previousFacts"][1]["provenance"]
    assert fixed["eventId"] is None and fixed["url"] is None and "sourceResponseSha256" not in fixed
