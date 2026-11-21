"""2026-11-21 owner【足す】: five materials added to the integrated view.

FUTURE MAP, the PER level map, the overnight Nikkei future, the six signs'
breakdown and the view's own issued-forecast record. Each enters only when
ARGUS already holds the value, stays a P1 within the 160-character fact,
never pushes out a P0, and passes the page's brief check unchanged.
"""
import copy
import json
import pathlib
import re
import shutil
import subprocess

import pytest

import argus_market_brief as mb
from argus_explanation_contract import _FORBIDDEN_BRIEF_PATTERNS, validate_unified_ai
import scanner

ROOT = pathlib.Path(__file__).resolve().parent
NOW = "2026-11-21T01:00:00Z"     # 10:00 JST
NEW_SOURCES = {"future_map", "level_map_calculation", "overnight_futures", "forecast_track_record"}


def _future_display():
    return {"schemaVersion": "argus-future-map-public-v1", "updatedAt": "2026-11-21T09:39:48+09:00",
            "status": {"position": "11月の下落の途中で、12月前半の底を待つ局面",
                       "nextAlert": {"date": "2026-11-24", "label": "週明けの戻り売り"},
                       "nextBottom": {"date": "2026-12-08", "label": "12月前半の底"}},
            "rows": [{"id": "r1", "periodLabel": "11月後半", "start": "2026-11-17", "end": "2026-11-30",
                      "view": "戻りは限定的で下値を試す", "tag": "下落", "level": {"low": 47000, "high": 48000},
                      "isNow": True},
                     {"id": "r2", "periodLabel": "12月", "start": "2026-12-01", "end": "2026-12-30",
                      "view": "年末の戻り", "tag": "戻り", "level": None, "isNow": False}],
            "record": {"scored": 17, "reached": 10}, "externalViewsOnly": True,
            "argusValidated": False, "actionAuthority": False}


def _morning(day="2026-11-21"):
    return {"schemaVersion": "jp-market-level-map-v1", "morningOf": day, "createdAt": "2026-11-20T22:30:00Z",
            "recordId": "lm-" + "a" * 32, "previousSession": "2026-11-20", "previousClose": 48521.3,
            "eps": 2412.3456, "per": 20.1141,
            "epsCoverage": {"members": 225, "missingMarketCap": 0, "missingEarnings": 0, "marketCapShareUsed": 1.0},
            "rows": [{"side": "UP", "kinds": ["PER_LINE"], "price": 50661.26, "distancePct": 4.411, "multiple": 21},
                     {"side": "UP", "kinds": ["SAME_MULTIPLE"], "price": 49000.0, "distancePct": 0.987, "multiple": 20.3125},
                     {"side": "DOWN", "kinds": ["PER_LINE"], "price": 48246.91, "distancePct": -0.566, "multiple": 20}]}


def _futures(traded="2026-11-20T20:45:00Z", symbol="NKD=F"):
    return {"schemaVersion": "argus-index-live-v1", "instrumentId": "NIKKEI_225_CME_FUTURES_USD", "symbol": symbol,
            "price": 49015.0, "previousClose": 48600.0, "changePct": 0.85, "tradedAt": traded,
            "receivedAt": "2026-11-20T21:00:00Z", "delaySeconds": 900, "sessionOpen": True,
            "source": "Yahoo Finance (CME, delayed)", "realtime": False, "actionAuthority": False}


def _sign(n, family, state, **extra):
    names = ("信用売り残が少ない", "日経レバの制度信用倍率", "日本株の優位性低下", "推計EPSの下方修正",
             "海外投資家の売り越し", "VIXのMACDが上向き", "好決算でも株価下落")
    row = {"id": f"WARN-0{n}", "family": family, "nameJa": names[n - 1], "state": state,
           "status": "AVAILABLE", "conditionMet": state == "ACTIVE" if state in ("ACTIVE", "CLEAR") else None,
           "ruleStatus": "DEFINED", "lineage": "ORIGINAL_DIRECTION",
           "value": 1.0, "knowledgeTime": "2026-11-20T09:00:00Z"}
    row.update(extra)
    return row


def _projection(**patch):
    cutoff = "2026-11-21T00:58:00Z"
    signals = [_sign(1, "D01", "CLEAR"), _sign(2, "D02", "ACTIVE"),
               _sign(3, "D03", "ACTIVE"),                       # no adopted lineage: 判定不能 on the page
               _sign(4, "D04", "CLEAR", lineage="ARGUS_VALIDATION_RULE"),
               _sign(5, "D05", "ACTIVE"), _sign(6, "D06", "STALE", status="STALE", value=None),
               _sign(7, "D07", "ACTIVE")]
    warning = {"schemaVersion": "jp-warning-conditions-v3", "informationCutoff": cutoff, "signals": signals,
               "countPredictsCrash": False, "actionAuthority": False, "rejectedEvidence": False}
    warning.update(patch)
    return {"informationCutoff": cutoff, "warningSignals": warning}


def _record(n=633, status="NOT_ABOVE_BASELINE"):
    return {"schemaVersion": "argus-forecast-track-record-v1", "instrumentId": "NIKKEI_225_INDEX",
            "minimumDirectionalForecasts": 20,
            "horizons": {str(h): {"horizonSessions": h, "scoredForecasts": n + 5, "directionalForecasts": n,
                                  "hits": n // 2, "hitRate": 0.5, "hitRateWilsonLower95": 0.46,
                                  "naiveMajorityRate": 0.563, "status": status,
                                  "firstTargetDate": "2026-09-01", "lastTargetDate": "2026-11-2" + str(h % 10)}
                         for h in (1, 5, 10, 20)},
            "predictiveProbabilities": None, "actionAuthority": False}


def _all_new_facts():
    return (mb.future_map_facts(_future_display(), scoring={"scored": 12, "reached": 5, "status": "UNVALIDATED"},
                                read_at="2026-11-21T00:00:05Z")
            + mb.level_map_facts(_morning(), now_iso=NOW)
            + mb.overnight_futures_facts(_futures(), close=48521.3, close_day="2026-11-20",
                                         close_at="2026-11-20T06:30:00Z", tokyo_session_open=False)
            + mb.warning_sign_facts(_projection())
            + mb.track_record_facts(_record(), checked_at="2026-11-21T00:50:00Z"))


def _shape_ok(row):
    assert row["priority"] == "P1" and len(row["text"]) <= 160 and row["text"]
    assert not any(p in row["text"] for p in _FORBIDDEN_BRIEF_PATTERNS) and "確率" not in row["text"]
    assert mb.page_provenance(row["provenance"]) == row["provenance"]   # already the page's shape


def test_each_material_enters_when_the_value_exists():
    facts = _all_new_facts()
    by_source = {}
    for row in facts:
        _shape_ok(row)
        by_source.setdefault(row["source"], []).append(row)
    assert set(by_source) == NEW_SOURCES | {"market_view"}
    fm = [r["text"] for r in by_source["future_map"]]
    assert fm[0].startswith("FUTURE MAP（外部の見立てでARGUSは未検証・2026-11-21更新）: 現在の位置「11月の下落")
    assert "次の注意 2026-11-24「週明けの戻り売り」" in fm[0] and "次の底 2026-12-08" in fm[0]
    assert "11月後半（2026-11-17〜2026-11-30）戻りは限定的で下値を試す［下落］" in fm[1]
    assert "水準47,000〜48,000円" in fm[1] and "採点12件中5件が到達（有効性は未検証）" in fm[1]
    level = by_source["level_map_calculation"][0]["text"]
    assert "ARGUS推計EPS2,412.35円で公式値ではない" in level and "2026-11-20終値48,521円はPER20.11倍" in level
    assert "上の線 PER20.31倍＝49,000円（+1.0%）" in level and "下の線 PER20倍＝48,247円（-0.6%）" in level
    futures = by_source["overnight_futures"][0]
    assert futures["verification"] == "VERIFIED"
    assert futures["text"] == ("日経先物（CME・遅延、11/21 05:45時点）: 49,015。2026-11-20の日経平均48,521円との差+1.02%"
                               "（東京の取引時間外の値）。")
    signs = by_source["market_view"][0]["text"]
    assert signs == ("6サインの内訳（点灯2/6）: 信用売り残が少ない=消灯、日経レバの制度信用倍率=点灯、"
                     "日本株の優位性低下=判定不能、推計EPSの下方修正=消灯、海外投資家の売り越し=点灯、VIXのMACDが上向き=古い。")
    assert "好決算でも株価下落" not in signs      # the closed seventh condition stays out
    record = by_source["forecast_track_record"][0]["text"]
    for h in (1, 5, 10, 20):
        assert f"{h}日後633件中316件一致・多数派56%を上回らず。" in record


@pytest.mark.parametrize("facts", [
    lambda: mb.future_map_facts(None),
    lambda: mb.future_map_facts({**_future_display(), "externalViewsOnly": False}),
    lambda: mb.future_map_facts({**_future_display(), "status": {}}),
    lambda: mb.level_map_facts(None, now_iso=NOW),
    lambda: mb.level_map_facts(_morning("2026-11-10"), now_iso=NOW),          # older than seven days
    lambda: mb.level_map_facts({**_morning(), "rows": []}, now_iso=NOW),
    lambda: mb.level_map_facts({**_morning(), "eps": None}, now_iso=NOW),
    lambda: mb.overnight_futures_facts(None, close=48521.3, close_day="2026-11-20",
                                       close_at="2026-11-20T06:30:00Z", tokyo_session_open=False),
    lambda: mb.overnight_futures_facts(_futures(), close=48521.3, close_day="2026-11-20",
                                       close_at="2026-11-20T06:30:00Z", tokyo_session_open=True),
    lambda: mb.overnight_futures_facts(_futures("2026-11-20T05:00:00Z"), close=48521.3, close_day="2026-11-20",
                                       close_at="2026-11-20T06:30:00Z", tokyo_session_open=False),
    lambda: mb.overnight_futures_facts(_futures("2026-11-25T05:00:00Z"), close=48521.3, close_day="2026-11-20",
                                       close_at="2026-11-20T06:30:00Z", tokyo_session_open=False),
    lambda: mb.overnight_futures_facts(_futures(symbol="^N225"), close=48521.3, close_day="2026-11-20",
                                       close_at="2026-11-20T06:30:00Z", tokyo_session_open=False),
    lambda: mb.overnight_futures_facts(_futures(), close=None, close_day=None, close_at=None,
                                       tokyo_session_open=False),
    lambda: mb.warning_sign_facts(None),
    lambda: mb.warning_sign_facts({"informationCutoff": "2026-11-21T00:58:00Z"}),
    lambda: mb.warning_sign_facts(_projection(rejectedEvidence=True)),
    lambda: mb.warning_sign_facts(_projection(informationCutoff="2026-11-21T00:59:00Z")),
    lambda: mb.warning_sign_facts(_projection(signals=_projection()["warningSignals"]["signals"][:6])),
    lambda: mb.track_record_facts(None),
    lambda: mb.track_record_facts(_record(n=0)),
])
def test_nothing_enters_without_a_value(facts):
    assert facts() == []


def test_six_signs_follow_the_page_gates():
    projection = _projection()
    rows = projection["warningSignals"]["signals"]
    rows[1]["knowledgeTime"] = "2026-11-21T02:00:00Z"            # after the cutoff: not countable
    rows[4]["ruleStatus"] = "RULE_NOT_DEFINED"
    text = mb.warning_sign_facts(projection)[0]["text"]
    assert text.startswith("6サインの内訳（点灯0/6）") and "日経レバの制度信用倍率=判定不能" in text
    assert "海外投資家の売り越し=判定不能" in text


def test_track_record_says_when_the_sample_is_too_small():
    text = mb.track_record_facts(_record(n=7, status="INSUFFICIENT_SAMPLE"))[0]["text"]
    assert "1日後7件採点・20件未満。" in text and "一致" not in text.split("）: ")[1]


def test_texts_fit_even_with_long_external_wording_and_large_counts():
    long = "あ" * 40
    display = _future_display()
    display["status"] = {"position": long, "nextAlert": {"date": "2026-11-24", "label": long},
                         "nextBottom": {"date": "2026-12-08", "label": long}}
    display["rows"][0].update(periodLabel=long, view=long)
    for row in mb.future_map_facts(display, scoring={"scored": 12345, "reached": 999}):
        assert len(row["text"]) <= 160 and not row["text"].endswith("「")
    record = mb.track_record_facts(_record(n=4321))[0]["text"]
    assert len(record) <= 160 and "20日後4321件中2160件一致" in record


def test_sell_mark_reaches_the_view_in_neutral_words():
    display = _future_display()
    display["rows"][0]["tag"] = "売り時"
    text = mb.future_map_facts(display)[1]["text"]
    assert "売り時" not in text and "［高値警戒］" in text


def _existing_full_brief():
    """A brief at the page limit shaped like the 2026-11-20 edition (P0 2, P1 54, P2 6, P3 2)."""
    brief = mb.compose_brief(now_iso=NOW, market_view_summary={"label": "6サイン成立2/6"},
        news_events=[{"severity": "HIGH", "staleness": "FRESH", "headlineJa": f"重要発表{i}",
                      "sourceLabelJa": "公式", "confirmationState": "MARKET_CONFIRMED"} for i in range(2)],
        next_events=[{"title": "米CPI", "date": "2026-12-10", "countdown": "D-19"}])
    filler = [mb._fact(f"市場条件{i}: {i}.0000。", "P1", "market_feature_calculation", "UNCONFIRMED")
              for i in range(52)]
    filler += [mb._fact(f"過去の頻度{i}。", "P2", "macro_frequency", "UNCONFIRMED") for i in range(6)]
    brief["facts"].extend(filler)
    assert len(brief["facts"]) == mb.PAGE_FACT_LIMIT
    return brief


def test_new_materials_never_push_out_a_p0_and_respect_the_page_limit():
    brief = _existing_full_brief()
    p0 = [r["text"] for r in brief["facts"] if r["priority"] == "P0"]
    brief["facts"].extend(_all_new_facts())
    bounded = mb.bound_facts(brief["facts"])
    assert len(bounded) == mb.PAGE_FACT_LIMIT
    assert [r["text"] for r in bounded if r["priority"] == "P0"] == p0
    assert NEW_SOURCES <= {r["source"] for r in bounded}
    # What gives way is the lowest priority (P3, then the last P2), never a P0 or P1.
    dropped = [r for r in brief["facts"] if r not in bounded]
    assert len(dropped) == len(_all_new_facts()) and {r["priority"] for r in dropped} <= {"P2", "P3"}


def _summary_citing(context, sources):
    ids = [r["evidenceId"] for r in context["facts"] if r["source"] in sources][:6]
    sections = {key: {"textJa": "外部の見立てと水準の地図、夜間の先物、サインの内訳、見通しの成績を材料に読みます。",
                      "evidenceIds": ids, "kind": "INFERENCE"} for key in mb.UNIFIED_SECTIONS}
    for key in ("changes", "impact"):
        sections[key] = {"textJa": "未確認です。", "evidenceIds": [], "kind": "UNKNOWN"}
    return sections


def test_unified_context_binds_the_new_facts_and_the_explanation_may_cite_them():
    brief = {**mb.compose_brief(now_iso=NOW), "marketPosition": {"themes": []}}
    brief["facts"].extend(_all_new_facts())
    context = mb.unified_context(brief)
    cited = {r["source"] for r in context["facts"]}
    assert NEW_SOURCES | {"market_view"} <= cited
    summary = validate_unified_ai(_summary_citing(context, NEW_SOURCES), context)
    assert summary is not None


def test_composer_reads_the_cached_values_and_adds_nothing_without_them(monkeypatch):
    def compose(*, with_values):
        monkeypatch.setattr(scanner, "_ai_now_iso", lambda: NOW)
        monkeypatch.setattr(scanner, "_brief_news_events", lambda **_: [])
        monkeypatch.setattr(scanner, "_important_events_data", lambda: {"events": [], "imminent": []})
        public = {k: v for k, v in _future_display().items() if k != "rows"}
        public["rows"] = [{k: v for k, v in r.items() if k != "isNow"} for r in _future_display()["rows"]]
        monkeypatch.setitem(scanner._FUTURE_MAP, "loaded", True)
        monkeypatch.setitem(scanner._FUTURE_MAP, "public", public if with_values else None)
        monkeypatch.setitem(scanner._FUTURE_MAP, "lastReadOkAt", "2026-11-21T00:00:05Z")
        monkeypatch.setattr(scanner, "_FUTURE_MAP_SCORING", {"status": "AVAILABLE", "record": {"scored": 3, "reached": 1}})
        monkeypatch.setitem(scanner._LEVEL_MAP, "mornings", [_morning()] if with_values else [])
        live = {"status": "AVAILABLE", "quote": {"price": 48521.3, "tradedAt": "2026-11-20T06:15:00Z",
                                                  "sessionOpen": False},
                "overnightFutures": _futures() if with_values else None}
        monkeypatch.setattr(scanner.argus_index_live, "current_quote_safe", lambda: live)
        monkeypatch.setattr(scanner, "_nikkei_chart_rows", lambda: [
            {"date": "2026-11-19", "close": 48000.0, "high": 48100.0, "low": 47900.0}])
        monkeypatch.setattr(scanner, "_jp_market_engine_market_view",
                            lambda: {"projection": _projection() if with_values else None})
        def record():
            return (_record(), "2026-11-21T00:50:00Z") if with_values else (None, None)
        monkeypatch.setattr(scanner, "_market_brief_track_record_cached", record)
        return scanner._compose_market_brief()

    brief = compose(with_values=True)
    sources = [r["source"] for r in brief["facts"]]
    assert NEW_SOURCES <= set(sources)
    assert sum(r["text"].startswith("6サインの内訳") for r in brief["facts"]) == 1
    futures = next(r for r in brief["facts"] if r["source"] == "overnight_futures")
    # The delayed quote after the 11/20 close is newer than the stored 11/19 bar, as on Today.
    assert "2026-11-20の日経平均48,521円との差+1.02%" in futures["text"]
    empty = compose(with_values=False)
    assert not NEW_SOURCES & {r["source"] for r in empty["facts"]}
    assert not any(r["text"].startswith("6サインの内訳") for r in empty["facts"])


def test_the_page_accepts_a_brief_carrying_the_new_facts(tmp_path):
    """The page rejects a whole brief over a fact it cannot read (2026-10-04)."""
    web = ROOT / "web"
    node = shutil.which("node")
    if not node or not (web / "node_modules" / "typescript").is_dir():
        pytest.skip("web dependencies are not installed")
    brief = _existing_full_brief()
    brief["facts"].extend(_all_new_facts())
    brief["facts"] = mb.bound_facts(brief["facts"])
    brief["marketPosition"] = {"themes": []}
    context = mb.unified_context(brief)
    sections = validate_unified_ai(_summary_citing(context, NEW_SOURCES), context)["sections"]
    brief.update(unifiedContext=context, unifiedStatus="GENERATED", unifiedSummary={
        "schemaVersion": "argus-unified-brief-v1", "contextId": context["contextId"], "sections": sections,
        "actionAuthority": False, "ownerContextAvailable": False, "historyStatus": "PROCESS_MEMORY_ONLY"})
    brief.pop("marketPosition")
    path = tmp_path / "brief.json"
    path.write_text(json.dumps(brief, ensure_ascii=False))
    script = ("const ts=require('typescript'),fs=require('fs'),vm=require('vm');"
              "const ctx={exports:{},Date,Set,URL};"
              "vm.runInNewContext(ts.transpileModule(fs.readFileSync('src/lib/marketBrief.ts','utf8'),"
              "{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText,ctx);"
              "const doc=JSON.parse(fs.readFileSync(process.argv[1],'utf8'));"
              "process.stdout.write(JSON.stringify({valid:ctx.exports.validMarketBrief(doc),"
              "sources:[...new Set(doc.unifiedContext.facts.map(f=>f.source))]}));")
    result = subprocess.run([node, "-e", script, str(path)], cwd=web, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    assert out["valid"] is True
    assert NEW_SOURCES <= set(out["sources"])
