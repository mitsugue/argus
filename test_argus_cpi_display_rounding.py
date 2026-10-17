"""CPI display correction preserves index-derived metrics and original revisions."""
from copy import deepcopy
from decimal import Decimal
import ast
from pathlib import Path

import pytest
import argus_macro_results as results
import argus_macro_event_store as store
import argus_macro_event_analysis as analysis
import argus_dashboard_event_summary as summary

RECEIVED = "2026-10-14T12:32:59Z"
EVENT = {"eventCode": "CPI", "eventDate": "2026-10-14", "eventTimeUtc": "2026-10-14T12:30:00Z"}


def raw_for(current=100.649, previous=100, *, partial=False):
    ids = ["CUSR0000SA0", "CUSR0000SA0L1E", "CUUR0000SA0", "CUUR0000SA0L1E"]
    if partial:
        ids = ids[:1]
    rows = [{"year": "2026", "period": "M09", "value": str(current)},
            {"year": "2026", "period": "M08", "value": str(previous)},
            {"year": "2025", "period": "M09", "value": str(previous)}]
    return {"Results": {"series": [{"seriesID": key, "data": deepcopy(rows)} for key in ids]}}


def old_stored_actual(*, partial=False):
    actual = results.parse_cpi(raw_for(partial=partial), EVENT, RECEIVED)
    actual["headline"] = actual["headline"].replace("+0.6%", "+0.7%")
    return actual


@pytest.mark.parametrize("current,previous", [
    (100.649, 100), (100.651, 100), (99.351, 100), (99.349, 100),
    (101.249, 100), (100.001, 100), (336.298, 334.131)])
def test_parser_formats_index_pair_once_and_retains_two_decimal_metric(current, previous):
    raw = raw_for(current, previous)
    before = deepcopy(raw)
    actual = results.parse_cpi(raw, EVENT, RECEIVED)
    direct = (Decimal(str(current)) / Decimal(str(previous)) - 1) * 100
    assert f"{direct:+.1f}%" in actual["headline"]
    assert actual["metrics"]["headlineCpiMoM"] == round((current / previous - 1) * 100, 2)
    assert raw == before
    assert actual["receivedAt"] == actual["availableFrom"] == RECEIVED
    assert actual["releasedAt"] is None
    assert actual["metricDefinitions"]["headlineCpiMoM"]["method"] == "DERIVED_FROM_PUBLISHED_INDEX"
    assert "公表文の丸め済み変化率そのものではありません" in " ".join(actual["limitationsJa"])


def test_reader_changes_only_headline_and_preserves_stored_revision_digest():
    actual = old_stored_actual()
    before = deepcopy(actual)
    projected = results.project_cpi_headline(actual)
    assert "+0.6%" in projected["headline"] and "+0.7%" in actual["headline"]
    assert {k: v for k, v in actual.items() if k != "headline"} == {
        k: v for k, v in projected.items() if k != "headline"}
    assert store.actual_revision_id(actual) == store.actual_revision_id(projected)
    assert store._snapshot_digest(actual) == store._snapshot_digest(before)
    assert actual == before and results.project_cpi_headline(projected) == projected


@pytest.mark.parametrize("mutation", [
    lambda v: v.update(referenceMatched=False),
    lambda v: v.update(source="FRED/BEA"),
    lambda v: v.update(schemaVersion="macro-result-v1"),
    lambda v: v.update(available=False),
    lambda v: v.update(headline="別の原典の結果"),
    lambda v: v.pop("metricInputs"),
    lambda v: v["metricInputs"]["headlineCpiMoM"].update(comparisonMonth="2026-07"),
    lambda v: v["metricDefinitions"]["headlineCpiMoM"].update(seriesId="OTHER"),
    lambda v: v["metricDefinitions"]["headlineCpiYoY"].update(seasonalAdjustment="SA"),
    lambda v: v["metrics"].update(headlineCpiMoM=0.66),
    lambda v: v["metricInputs"]["headlineCpiMoM"].update(comparisonIndex=0),
    lambda v: v["metricInputs"]["headlineCpiMoM"].update(currentIndex=True),
    lambda v: v["metricInputs"]["headlineCpiMoM"].update(currentIndex="100.649"),
    lambda v: v["metricInputs"]["headlineCpiMoM"].update(currentIndex=float("inf")),
    lambda v: v["metricInputs"]["headlineCpiMoM"].update(currentIndex=10**1000),
])
def test_reader_refuses_incomplete_or_inconsistent_legacy_input(mutation):
    actual = old_stored_actual()
    mutation(actual)
    before = deepcopy(actual)
    assert results.project_cpi_headline(actual) == before
    assert actual == before


def test_partial_result_stays_partial_and_missing_series_stay_missing():
    actual = old_stored_actual(partial=True)
    projected = results.project_cpi_headline(actual)
    assert projected["status"] == "partial" and "+0.6%" in projected["headline"]
    assert projected["metrics"]["coreCpiMoM"] is None
    assert projected["metrics"]["headlineCpiYoY"] is None
    empty = results.parse_cpi({}, EVENT, RECEIVED)
    assert results.project_cpi_headline(empty) == empty


def test_current_api_projection_keeps_original_revisions_pre_and_post_intact():
    actual = old_stored_actual()
    record = {**EVENT, "actual": actual, "pre": {"summaryJa": "事前"},
              "post": {"answerCheckJa": "保存済み説明"},
              "resultRevisions": [{"actual": deepcopy(actual), "snapshotSha256": store._snapshot_digest(actual)}],
              "actualRevisionId": store.actual_revision_id(actual)}
    before = deepcopy(record)
    public = results.project_macro_result_record(record)
    assert "+0.6%" in public["actual"]["headline"]
    assert public["resultRevisions"] == before["resultRevisions"]
    assert record == before
    assert {k: v for k, v in public.items() if k != "actual"} == {
        k: v for k, v in before.items() if k != "actual"}
    record["eventCode"] = "PPI"
    assert results.project_macro_result_record(record) == record


def test_dashboard_and_post_prompt_use_same_corrected_display_without_generating():
    actual = old_stored_actual()
    record = {**EVENT, "eventId": "cpi-fixture", "actual": actual}
    before = deepcopy(record)
    item = summary.build_summary_item(important_event=EVENT, macro_record=record,
                                     now_iso="2026-10-14T13:00:00Z")
    assert "+0.6%" in item["officialResult"]["headlineJa"]
    prompt = analysis.build_post_prompt(EVENT, {}, actual)
    assert "+0.6%" in prompt and '"headlineCpiMoM": 0.65' in prompt
    assert record == before


def test_cache_get_boundary_uses_projection_and_never_mutates_saved_cache():
    tree = ast.parse(Path(__file__).with_name("scanner.py").read_text())
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                and n.name == "api_argus_macro_event_analysis")
    helper = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_macro_event_display_record')
    module = ast.Module(body=[helper, node], type_ignores=[])
    node.decorator_list = []
    record = {**EVENT, "actual": old_stored_actual()}
    before = deepcopy(record)
    class Request:
        args = {"eventCode": "CPI", "limit": "30"}
    class Watch:
        @staticmethod
        def status():
            return {"running": True}
    namespace = {"_MACRO_ANALYSIS": {"fixture": record}, "_MACRO_ANALYSIS_STATE": {},
                 "_macro_analysis_restore_once": lambda: None, "_event_news_context_cached": lambda *a, **k: {}, "request": Request(),
                 "_ai_now_iso": lambda: RECEIVED, "jsonify": lambda value: value,
                 "argus_macro_event_store": store, "argus_macro_results": results,
                 "argus_macro_release_watch": Watch(), "_OPENAI_EVENT_MODEL": "unchanged"}
    exec(compile(ast.fix_missing_locations(module), "scanner-cpi-get", "exec"), namespace)
    response = namespace["api_argus_macro_event_analysis"]()
    assert "+0.6%" in response["items"][0]["actual"]["headline"]
    assert record == before
