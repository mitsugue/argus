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
