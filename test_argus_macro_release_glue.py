"""The in-server release reaction: baseline before, windows after, post analysis once the
result and the measured reaction exist (owner finding 2026-10-03, US jobs report)."""
import json

import scanner
import argus_macro_event_analysis as MA

EVENT = {"id": "ev-nfp-20261002", "eventCode": "NFP", "title": "US Employment Situation",
         "eventTimeUtc": "2026-10-02T12:30:00Z", "eventDate": "2026-10-02", "source": "BLS"}
PRICES = {"before": {"ZQ=F": 96.05, "ZT=F": 101.82, "ZN=F": 104.61, "NQ=F": 26800.0, "ES=F": 7650.0,
                     "NKD=F": 68500.0, "JPY=X": 157.5, "^VIX": 16.0},
          "after": {"ZQ=F": 96.075, "ZT=F": 101.95, "ZN=F": 105.02, "NQ=F": 27030.0, "ES=F": 7690.0,
                    "NKD=F": 69300.0, "JPY=X": 157.9, "^VIX": 15.3}}


def _provider(monkeypatch, phase):
    calls = []
    class Response:
        status_code = 200
        def __init__(self, symbol): self.symbol = symbol
        def json(self):
            return {"chart": {"result": [{"meta": {"regularMarketPrice": PRICES[phase[0]][self.symbol],
                                                   "regularMarketTime": 1790945400}}]}}
    def get(url, **kwargs):
        calls.append(url)
        return Response(url.rsplit("/", 1)[1])
    monkeypatch.setattr(scanner.requests, "get", get)
    return calls


def _seed(monkeypatch, actual_available=False):
    scanner._MACRO_ANALYSIS.clear()
    scanner._MACRO_ANALYSIS_STATE["restored"] = True
    rec = MA.new_record(EVENT, now_iso="2026-10-02T10:00:00Z")
    rec["pre"] = {"summaryJa": "雇用の鈍化が焦点", "argusScenarioJa": "弱ければ利上げ観測が後退", "generatedAt": "2026-10-02T10:00:00Z"}
    if actual_available:
        rec["actual"] = {"available": True, "headline": "+29千人 / 失業率4.2%", "metrics": {"nfp": 29},
                         "source": "BLS", "releasedAt": "2026-10-02T12:30:00Z", "receivedAt": "2026-10-02T12:33:00Z"}
    scanner._MACRO_ANALYSIS[EVENT["id"]] = rec
    monkeypatch.setattr(scanner, "_macro_analysis_persist", lambda: None)


def test_baseline_then_window_measure_from_one_provider(monkeypatch):
    _seed(monkeypatch)
    phase = ["before"]; calls = _provider(monkeypatch, phase)
    scanner._macro_release_baseline(EVENT)
    assert len(calls) == 8 and all("query1.finance.yahoo.com" in u for u in calls)
    rr = scanner._MACRO_ANALYSIS[EVENT["id"]]["releaseReaction"]
    assert rr["basis"] == "PRE_RELEASE_BASELINE" and rr["baseline"]["values"]["ZQ=F"]["price"] == 96.05
    assert rr["windows"] == {} and rr["readingJa"] == "反応を測れていない"
    phase[0] = "after"
    scanner._macro_release_window(EVENT, "+5m")
    rr = scanner._MACRO_ANALYSIS[EVENT["id"]]["releaseReaction"]
    assert rr["latestWindow"] == "+5m" and rr["windows"]["+5m"]["moves"]["ffImpliedRateMoveBp"] == -2.5
    assert rr["readingJa"].startswith("利上げ観測の後退")
    assert rr["actionAuthority"] is False and rr["automaticAiCalls"] == 0
    # The second baseline capture before the release replaces the first and keeps the window.
    phase[0] = "before"
    scanner._macro_release_baseline(EVENT)
    assert scanner._MACRO_ANALYSIS[EVENT["id"]]["releaseReaction"]["latestWindow"] == "+5m"


def test_post_waits_for_the_result_and_the_window_then_runs_once(monkeypatch):
    _seed(monkeypatch)
    ran = []
    monkeypatch.setattr(scanner, "_generate_macro_event_analysis", lambda limit=8: (ran.append(limit), {"status": "done"})[1])
    assert scanner._macro_release_post(EVENT, "+5m") is False          # no result, no window
    phase = ["before"]; _provider(monkeypatch, phase)
    scanner._macro_release_baseline(EVENT); phase[0] = "after"; scanner._macro_release_window(EVENT, "+5m")
    assert scanner._macro_release_post(EVENT, "+5m") is False          # window yes, result no
    scanner._MACRO_ANALYSIS[EVENT["id"]]["actual"] = {"available": True, "headline": "x", "metrics": {}}
    assert scanner._macro_release_post(EVENT, "+60m") is False         # that window is not captured
    assert scanner._macro_release_post(EVENT, "+5m") is True and ran == [8]
    monkeypatch.setattr(scanner, "_generate_macro_event_analysis", lambda limit=8: {"status": "already_running"})
    assert scanner._macro_release_post(EVENT, "+5m") is False          # asked again next tick


def test_post_prompt_reads_the_measured_reaction_and_is_replaced_once_at_sixty(monkeypatch):
    _seed(monkeypatch, actual_available=True)
    phase = ["before"]; _provider(monkeypatch, phase)
    scanner._macro_release_baseline(EVENT); phase[0] = "after"; scanner._macro_release_window(EVENT, "+5m")
    prompts = []
    def prose(prompt, **kwargs):
        prompts.append(prompt)
        return {"verdict": "partial", "answerCheckJa": "概ね想定どおり", "marketReactionJa": "政策金利の予想が下がった",
                "marketReadingJa": "利上げ観測の後退を安心材料に株高", "nikkeiImplicationJa": "先物は上昇",
                "changeConditionJa": "FOMCで利上げ示唆が続けば読みは変わる", "limitationsJa": []}
    monkeypatch.setattr(scanner, "_openai_prose", prose)
    monkeypatch.setattr(scanner, "_macro_important_events", lambda limit=8: [{**EVENT, "eventId": EVENT["id"],
                        "daysUntil": 0, "displayImpact": "critical"}])
    monkeypatch.setattr(scanner, "_macro_market_context_ja", lambda: "US10Y=5.28")
    monkeypatch.setattr(scanner, "_ai_now_iso", lambda: "2026-10-02T12:36:00Z")
    scanner._generate_macro_event_analysis(limit=8)
    assert len(prompts) == 1
    assert "発表前の織り込み: FF金利先物の示す政策金利の予想 3.950%(次回FOMC 2026-10-28)" in prompts[0]
    assert "政策金利の予想-2.5bp" in prompts[0] and "他の数字を作らない" in prompts[0]
    post = scanner._MACRO_ANALYSIS[EVENT["id"]]["post"]
    assert post["reactionWindow"] == "+5m" and post["marketReadingJa"].startswith("利上げ観測の後退")
    assert "sk-" not in json.dumps(post)
    # Nothing changes until the +60m window exists; then exactly one more generation.
    scanner._generate_macro_event_analysis(limit=8)
    assert len(prompts) == 1
    scanner._macro_release_window(EVENT, "+30m"); scanner._generate_macro_event_analysis(limit=8)
    assert len(prompts) == 1
    scanner._macro_release_window(EVENT, "+60m"); scanner._generate_macro_event_analysis(limit=8)
    assert len(prompts) == 2 and scanner._MACRO_ANALYSIS[EVENT["id"]]["post"]["reactionWindow"] == "+60m"
    scanner._generate_macro_event_analysis(limit=8)
    assert len(prompts) == 2
    scanner._macro_release_window(EVENT, "+8h"); scanner._generate_macro_event_analysis(limit=8)
    assert len(prompts) == 3 and scanner._MACRO_ANALYSIS[EVENT["id"]]["post"]["reactionWindow"] == "+8h"
    scanner._generate_macro_event_analysis(limit=8)
    assert len(prompts) == 3
    # The event card prefers the measured reaction and exposes the reading.
    import argus_dashboard_event_summary as DS
    item = DS.build_summary_item(important_event={**EVENT, "eventId": EVENT["id"]},
                                 macro_record=scanner._MACRO_ANALYSIS[EVENT["id"]], now_iso="2026-10-02T14:00:00Z")
    assert item["releaseReaction"]["latestWindow"] == "+8h" and item["caos"]["marketReadingJa"].startswith("利上げ観測の後退")
    assert item["caos"]["changeConditionJa"].startswith("FOMC")


def test_next_fomc_continues_into_2027_with_the_published_dates():
    """Federal Reserve calendar (checked 2026-10-03): 2027 decision days, tentative until confirmed."""
    assert scanner._FOMC_2027 == ["2027-01-27", "2027-03-17", "2027-04-28", "2027-06-09", "2027-07-28",
                                   "2027-09-15", "2027-10-27", "2027-12-08"]
    assert scanner._next_fomc_after("2026-12-10") == "2027-01-27"
    assert scanner._next_fomc_after("2026-10-03") == "2026-10-28"
    assert scanner._next_fomc_after("2027-12-09") is None
    assert all(__import__("datetime").date.fromisoformat(d).weekday() == 2 for d in scanner._FOMC_2027)   # Wednesdays
    spec = next(row for row in scanner._EVENT_SPECS if row[2] == "fomc")
    assert spec[0] == scanner._FOMC_2026 + scanner._FOMC_2027
