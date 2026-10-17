"""Notification / Today edition parity and quiet migration, synthetic only."""
import copy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import scanner
import argus_notification_brief as N

NOW = datetime(2026, 10, 13, 0, 0, tzinfo=timezone.utc)
REF = "brief-fact-" + "b" * 64


def edition(text="今は材料を見極めています。"):
    sections = {k: {"textJa": text if k == "view" else "取得した根拠を確認します。",
                    "kind": "INFERENCE", "evidenceIds": [REF]} for k in N.SECTIONS}
    for k in ("changes", "impact"):
        sections[k] = {"textJa": "まだ確認できていません。", "kind": "UNKNOWN", "evidenceIds": []}
    fact = {"evidenceId": REF, "text": "取得した根拠です。", "source": "market",
            "priority": "P0", "verification": "VERIFIED"}
    return {"schemaVersion": "argus-market-brief-v1", "sdaAuthority": False,
            "generatedAt": NOW.isoformat(), "unifiedStatus": "GENERATED",
            "now": "今", "why": "理由", "next": "次", "facts": [fact],
            "chips": dict.fromkeys(("chart", "news", "nextEvent", "mainRisk"), "確認中"),
            "unifiedContext": {"contextId": "a" * 64, "facts": [fact], "previousFacts": []},
            "unifiedSummary": {"schemaVersion": "argus-unified-brief-v1", "contextId": "a" * 64,
                "ownerContextAvailable": False, "actionAuthority": False,
                "historyStatus": "LOCAL_DURABLE", "sections": sections}}


def compose(value, events=None):
    return N.compose(value, events or {}, now=NOW)


def test_exact_complete_sections_and_original_time_without_legacy_or_mixed_numbers():
    b = edition(); original = copy.deepcopy(b)
    got = compose(b)
    assert got["edition"]["contextId"] == b["unifiedSummary"]["contextId"]
    assert got["edition"]["generatedAt"] == b["generatedAt"]
    for key in ("view", "reasons", "next", "invalidation"):
        assert b["unifiedSummary"]["sections"][key]["textJa"] in got["textJa"]
    for old in ("CAUTIOUS", "EVENT_WAIT", "確信度", "旧ラベル", "AI見解", "burn-in"):
        assert old not in got["textJa"]
    assert b == original
    assert got["automaticAiCalls"] == got["externalFetches"] == 0
    assert got["finalDecisionAuthorityActive"] is False


def test_pending_keeps_previous_prose_and_time_together():
    b = edition("保存版の見立てです。")
    b["generatedAt"] = (NOW - timedelta(days=1)).isoformat()
    current = edition("新しい未完成文です。")
    current.update(unifiedStatus="AWAITING_AI", unifiedSummary=None,
                   retainedPresentation=b, generationWorker={"status": "RUNNING"})
    got = compose(current)
    assert got["edition"]["retained"] is True
    assert got["edition"]["generatedAt"] == b["generatedAt"]
    assert "作成中・保存版" in got["textJa"] and "1時間以上" in got["textJa"]
    assert "新しい未完成文" not in got["textJa"]


def test_source_date_only_provenance_is_readable_without_inventing_receipt_time():
    b = edition()
    b["unifiedContext"]["facts"][0]["provenance"] = {
        "scope": "published_metadata_snapshot", "eventId": None, "revision": None,
        "publishedAt": None, "receivedAt": None, "observedAt": "2026-10-12",
        "url": None, "sourceLabel": "公式観測"}
    got = compose(b)
    assert got["edition"]["contextId"] == b["unifiedSummary"]["contextId"]
    assert got["edition"]["generatedAt"] == b["generatedAt"]
    assert "2026-10-12" not in got["textJa"]
    b["unifiedContext"]["facts"][0]["provenance"]["observedAt"] = "2026-02-30"
    assert compose(b)["status"] == "unavailable"


@pytest.mark.parametrize("mutation", [
    lambda b: b.update(unifiedStatus="AWAITING_AI"),
    lambda b: b.update(generatedAt=(NOW + timedelta(seconds=1)).isoformat()),
    lambda b: b["unifiedSummary"].update(contextId="c" * 64),
    lambda b: b["unifiedSummary"].update(actionAuthority=True),
    lambda b: b["unifiedSummary"].update(ownerContextAvailable=True),
    lambda b: b["unifiedSummary"]["sections"].pop("next"),
    lambda b: b["unifiedSummary"]["sections"]["view"].update(evidenceIds=["unknown"]),
    lambda b: b["unifiedSummary"]["sections"]["view"].update(textJa="長" * 241),
    lambda b: b.update(chips={}),
])
def test_invalid_missing_or_future_edition_is_not_a_legacy_fallback(mutation):
    b = edition(); mutation(b)
    got = compose(b)
    assert got["status"] == "unavailable" and got["edition"]["generatedAt"] is None
    assert "更新待ち" in got["textJa"]


def test_long_sections_remain_complete_under_push_byte_limit():
    b = edition("あ" * 240)
    for k in ("reasons", "next", "invalidation"):
        b["unifiedSummary"]["sections"][k]["textJa"] = "い" * 240
    assert len(compose(b)["textJa"].encode()) <= 4096
    assert ("あ" * 240) in compose(b)["textJa"]


def test_multibyte_push_limit_never_truncates_a_section_mid_sentence():
    b = edition("📊" * 240)
    for key in ("reasons", "next", "invalidation"):
        b["unifiedSummary"]["sections"][key]["textJa"] = "🔎" * 240
    got = compose(b)
    assert len(got["textJa"].encode()) <= 4096
    assert "📊" * 240 in got["textJa"]
    assert "続きはToday" in got["textJa"]


def test_migration_and_repeated_reads_do_not_buzz_or_emit_posture_enums():
    got = compose(edition())
    state, text = N.diff(got, {"posture": "EVENT_WAIT", "urgent": []})
    assert text is None
    assert N.diff(got, state)[1] is None
    got["edition"]["contextId"] = "c" * 64
    assert N.diff(got, state)[1] is None
    changed = compose(edition("見方が変わりました。"))
    state2, text = N.diff(changed, state)
    assert "統合AIの見立てが変わりました" in text
    assert "見方が変わりました。" in text
    assert N.diff(changed, state2)[1] is None
    assert N.diff(compose({}), state2)[1] is None


def test_event_notice_is_japanese_scheduled_and_deduplicated_separate_from_edition():
    state, _ = N.diff(compose(edition()), {})
    e = {"id": "cpi-synthetic", "title": "US CPI (Consumer Price Index)",
         "status": "live", "impact": "high", "daysUntil": 1,
         "escalation": "D-1", "eventTimeUtc": (NOW + timedelta(days=1)).isoformat()}
    got = compose(edition(), {"status": "live", "events": [e]})
    state2, text = N.diff(got, state)
    assert "米消費者物価指数(CPI)" in text and "日本時間・予定" in text
    assert "姿勢が変化" not in text and "D-1" not in text
    assert N.diff(got, state2)[1] is None
    e["status"] = "mock"
    assert compose(edition(), {"status": "live", "events": [e]})["topEvents"] == []


def test_scanner_route_reads_same_saved_edition_and_never_generates_or_fetches(monkeypatch):
    b = edition()
    b["generatedAt"] = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    monkeypatch.setattr(scanner, "_market_brief_history_restore", lambda: None)
    monkeypatch.setattr(scanner, "_market_brief_generation_gate", lambda: {})
    monkeypatch.setitem(scanner._MARKET_BRIEF, "data", b)
    def forbidden(*a, **k):
        pytest.fail("notification must not collect or generate")
    for name in ("get_action_labels", "get_market_regime_snapshot", "get_rates_snapshot",
                 "get_news_radar", "_market_brief_refresh", "_market_brief_ai_polish"):
        monkeypatch.setattr(scanner, name, forbidden)
    monkeypatch.setattr(scanner, "get_events_snapshot", lambda **kw: (
        {} if kw == {"allow_provider_fetch": False} else forbidden()))
    with scanner.app.test_request_context():
        page = scanner.api_argus_market_brief().get_json()
    digest = scanner.get_daily_digest()
    assert digest["edition"]["contextId"] == page["unifiedSummary"]["contextId"]
    assert digest["edition"]["sections"]["view"] == page["unifiedSummary"]["sections"]["view"]["textJa"]
    assert digest["posture"]["call"] is None and not digest["labelHighlights"]


def test_existing_two_slots_fetch_near_delivery_and_workflow_uses_projection_diff():
    s = Path(".github/workflows/market-alerts.yml").read_text()
    assert "25 23 * * 0-4" in s and "55 12 * * 1-5" in s
    assert "from argus_notification_brief import diff" in s
    assert "${GITHUB_REPOSITORY}/${GITHUB_SHA}/argus_notification_brief.py" in s
    assert "contents: read" not in s and "permissions: {}" in s
    assert "CAUTIOUS" not in s and "姿勢が変化" not in s
    assert "X-ARGUS-ADMIN-TOKEN" in s and "No Click header" in s
