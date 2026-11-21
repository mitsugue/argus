"""The luna shadow of the news reading (owner 2026-11-22 【ニュースの読みを luna へ】).

Each fresh news reading is sent once more to gpt-6-luna; luna's answer is
recorded as counts and field values only and never changes the event, its
alert, the cache or the judgment. A failing shadow is ignored; it is bounded
per UTC day, ends after 7 days or 200 compared answers, and has an off switch.
"""
import copy
import json
import queue
import sys
from pathlib import Path

import pytest

import argus_cost_policy as cp
import argus_news_intelligence as ni
import argus_openai_tier
import scanner
from test_argus_news_pipeline import mail, news_env, run_cycle  # noqa: F401  (fixture)

sys.path.insert(0, str(Path(__file__).resolve().parent / "scripts"))
import ai_usage_report  # noqa: E402

BASELINE = {"facts": ["米長期金利が急上昇したと報じられた"], "eventTypeCandidate": "RATES",
            "entities": ["米国債"], "causalPathJa": "金利上昇は株の重荷", "uncertaintyJa": None,
            "secondOrderJa": None, "materialityGuess": 1}
LUNA = {**BASELINE, "eventTypeCandidate": "FED", "materialityGuess": 3,
        "facts": ["ルナの別の要約"]}


@pytest.fixture()
def shadow_on(monkeypatch, news_env):  # noqa: F811
    monkeypatch.setenv("ARGUS_NEWS_LUNA_SHADOW", "1")
    monkeypatch.setattr(scanner, "_NEWS_LUNA_SHADOW_PENDING", {})
    monkeypatch.setattr(scanner, "_NEWS_LUNA_SHADOW_QUEUE", queue.Queue(maxsize=8))
    started = []
    monkeypatch.setattr(scanner, "_news_luna_shadow_start_worker", lambda: started.append(1))
    calls = []

    def prose(user, max_out=600, system=None, *, purpose="prose", model=None,
              diagnostic=None, **kwargs):
        calls.append({"purpose": purpose, "model": model, "user": user})
        if isinstance(diagnostic, dict):
            diagnostic.update(requestedModel=model or "gpt-5.6-terra",
                              returnedModel=model or "gpt-5.6-terra", outcome="ok",
                              inputTokens=900, outputTokens=150, cachedInputTokens=0,
                              estUsd=0.000165)
        return copy.deepcopy(LUNA if purpose == "news_intel_shadow" else BASELINE)

    monkeypatch.setattr(scanner, "_openai_prose", prose)
    return {"env": news_env, "calls": calls, "started": started}


def _drain(monkeypatch=None):
    outcomes = []
    while not scanner._NEWS_LUNA_SHADOW_QUEUE.empty():
        outcomes.append(scanner._news_luna_shadow_run(scanner._NEWS_LUNA_SHADOW_QUEUE.get_nowait()))
    return outcomes


# ── permission, wait and lane ──

def test_luna_is_allowed_only_for_the_shadow_purpose():
    assert scanner._openai_model_allowed("gpt-6-luna", "news_intel_shadow")
    assert not scanner._openai_model_allowed("gpt-5.6-terra", "news_intel_shadow")
    assert not scanner._openai_model_allowed("gpt-6.2-sol", "news_intel_shadow")
    for purpose in ("news_intel", "market_brief", "ai_judgment", "prose"):
        assert not scanner._openai_model_allowed("gpt-6-luna", purpose)
    assert scanner._openai_model_allowed("gpt-5.6-terra", "news_intel")
    assert scanner._AI_PRICING["gpt-6-luna"] == {"in": 0.10, "out": 0.50, "cachedIn": 0.01}


def test_the_shadow_waits_briefly_on_standard_and_runs_in_the_scheduled_lane():
    assert scanner._openai_request_timeout("gpt-6-luna", "news_intel_shadow", 60) == 20
    assert scanner._openai_request_timeout("gpt-5.6-terra", "news_intel", 60) == 60
    assert "news_intel_shadow" not in argus_openai_tier.FLEX_PURPOSES
    state = cp.default_state("SCHEDULED_AI")
    allowed = cp.authorize(state, provider="openai", purpose="news_intel_shadow", automatic=True,
                           now_iso="2026-11-22T01:00:00Z", estimated_cost_usd=0.001,
                           estimated_tokens=3000)
    assert allowed["allowed"]


def test_a_refused_shadow_request_does_not_replace_the_last_reading_record(monkeypatch):
    monkeypatch.setitem(scanner._OPENAI_PROSE_LAST, "purpose", "news_intel")
    monkeypatch.setitem(scanner._OPENAI_PROSE_LAST, "outcome", "ok")
    diagnostic = {}
    # Terra on the shadow purpose is refused before any request or reservation.
    assert scanner._openai_prose("x", purpose="news_intel_shadow", model="gpt-5.6-terra",
                                 diagnostic=diagnostic) is None
    assert diagnostic["outcome"] == "skipped" and diagnostic["reason"] == "production_model_not_allowed"
    assert scanner._OPENAI_PROSE_LAST["purpose"] == "news_intel"
    assert scanner._OPENAI_PROSE_LAST["outcome"] == "ok"


# ── the shadow never changes the news result ──

def test_the_shadow_answer_is_recorded_and_never_used(monkeypatch, shadow_on):
    run_cycle(monkeypatch, {"m1": mail("m1", "米30年債利回りが5%を突破 急騰続く")})
    env = shadow_on["env"]
    (event,) = env["events"].values()
    assert [c["purpose"] for c in shadow_on["calls"]] == ["news_intel"]
    assert scanner._NEWS_LUNA_SHADOW_QUEUE.qsize() == 1 and shadow_on["started"]
    before_event = copy.deepcopy(event)
    before_cache = copy.deepcopy(env["aiCache"])
    before_judgment = copy.deepcopy(env.get("judgmentOpen"))
    assert _drain() == ["compared"]
    shadow_call = shadow_on["calls"][-1]
    assert shadow_call["purpose"] == "news_intel_shadow" and shadow_call["model"] == "gpt-6-luna"
    # Exactly the same request as the reading itself.
    assert shadow_call["user"] == shadow_on["calls"][0]["user"]
    assert env["events"][event["eventId"]] == before_event
    assert env["aiCache"] == before_cache and env.get("judgmentOpen") == before_judgment
    assert event["judgmentDecision"]["aiMaterialityGuess"] == 1
    state = env["lunaShadow"]
    assert state["counts"]["submitted"] == 1 and state["counts"]["compared"] == 1
    (row,) = state["mismatches"]
    assert row["baseline"]["severity"] == event["severity"]
    assert row["baseline"]["materialityGuess"] == 1 and row["luna"]["materialityGuess"] == 3
    assert row["baseline"]["family"] == "RATES" and row["luna"]["family"] == "FED"
    assert {"family", "materialityGuess"} <= set(row["fields"])
    assert state["luna"]["inputTokens"] == 900 and state["luna"]["answered"] == 1
    # No mail, fact or explanation text is kept.
    saved = json.dumps(state, ensure_ascii=False)
    for text in ("米30年債", "急上昇", "ルナの別の要約", "金利上昇は株の重荷"):
        assert text not in saved


def test_a_cached_or_failed_reading_sends_no_shadow(monkeypatch, shadow_on):
    scanner._news_analyze_ai("米30年債利回りが5%を突破 急騰続く", "", "fp-x")
    assert "fp-x" in scanner._NEWS_LUNA_SHADOW_PENDING
    # A reading that is not fresh is not compared; its request is let go.
    assert scanner._news_luna_shadow_submit("fp-x", False, {}) is False
    assert not scanner._NEWS_LUNA_SHADOW_PENDING
    # The same fingerprint again is answered from the cache: no request, no shadow.
    assert scanner._news_analyze_ai("米30年債利回りが5%を突破 急騰続く", "", "fp-x")[1] == "AI_CACHED"
    assert not scanner._NEWS_LUNA_SHADOW_PENDING and scanner._NEWS_LUNA_SHADOW_QUEUE.empty()
    monkeypatch.setattr(scanner, "_openai_prose", lambda *a, **k: None)
    run_cycle(monkeypatch, {"m2": mail("m2", "米10年債利回りが急騰 株安")})
    assert scanner._NEWS_LUNA_SHADOW_QUEUE.empty()


def test_a_failing_shadow_is_ignored(monkeypatch, shadow_on):
    def broken(*args, purpose="prose", diagnostic=None, **kwargs):
        if purpose == "news_intel_shadow":
            raise RuntimeError("boom")
        if isinstance(diagnostic, dict):
            diagnostic.update(outcome="ok", returnedModel="gpt-5.6-terra")
        return copy.deepcopy(BASELINE)

    monkeypatch.setattr(scanner, "_openai_prose", broken)
    run_cycle(monkeypatch, {"m1": mail("m1", "米30年債利回りが5%を突破 急騰続く")})
    assert _drain() == ["error"]
    state = shadow_on["env"]["lunaShadow"]
    assert state["counts"]["workerErrors"] == 1 and state["failureReasons"] == {"RuntimeError": 1}

    def refused(*args, purpose="prose", diagnostic=None, **kwargs):
        if purpose == "news_intel_shadow":
            diagnostic.update(outcome="error", reason="model_call_failed", errorClass="APITimeoutError")
            return None
        return copy.deepcopy(BASELINE)

    monkeypatch.setattr(scanner, "_openai_prose", refused)
    run_cycle(monkeypatch, {"m2": mail("m2", "米10年債利回りが急騰 株安")})
    assert _drain() == ["failed"]
    assert state["counts"]["lunaFailed"] == 1 and state["failureReasons"]["APITimeoutError"] == 1

    monkeypatch.setattr(scanner, "_openai_prose",
                        lambda *a, purpose="prose", **k: {"bad": 1} if purpose == "news_intel_shadow"
                        else copy.deepcopy(BASELINE))
    run_cycle(monkeypatch, {"m3": mail("m3", "日銀が追加利上げを決定 円高")})
    assert _drain() == ["rejected"]
    assert state["counts"]["lunaRejected"] == 1 and state["counts"]["compared"] == 0


def test_a_broken_shadow_never_stops_the_news_processing(monkeypatch, shadow_on):
    def explode(*a, **k):
        raise RuntimeError("admit broke")

    monkeypatch.setattr(ni, "shadow_admit", explode)
    run_cycle(monkeypatch, {"m1": mail("m1", "米30年債利回りが5%を突破 急騰続く")})
    (event,) = shadow_on["env"]["events"].values()
    assert event["analysisState"] == "ANALYZED"
    assert shadow_on["env"]["health"]["parseFailures"] == 0


def test_the_switch_turns_the_shadow_off(monkeypatch, shadow_on):
    monkeypatch.setenv("ARGUS_NEWS_LUNA_SHADOW", "0")
    run_cycle(monkeypatch, {"m1": mail("m1", "米30年債利回りが5%を突破 急騰続く")})
    assert scanner._NEWS_LUNA_SHADOW_QUEUE.empty() and not scanner._NEWS_LUNA_SHADOW_PENDING
    assert [c["purpose"] for c in shadow_on["calls"]] == ["news_intel"]
    assert scanner._news_luna_shadow_view()["status"] == "SWITCHED_OFF"


def test_a_full_queue_skips_without_counting_a_request(monkeypatch, shadow_on):
    monkeypatch.setattr(scanner, "_NEWS_LUNA_SHADOW_QUEUE", queue.Queue(maxsize=1))
    scanner._NEWS_LUNA_SHADOW_QUEUE.put_nowait({"placeholder": True})
    run_cycle(monkeypatch, {"m1": mail("m1", "米30年債利回りが5%を突破 急騰続く")})
    counts = shadow_on["env"]["lunaShadow"]["counts"]
    assert counts["skippedQueueFull"] == 1 and counts["submitted"] == 0
    assert shadow_on["env"]["lunaShadow"]["dayAttempts"] == 0


# ── bounds ──

def _admit(state, epoch, iso, **kw):
    args = {"enabled": True, "daily_cap": 2, "period_days": 7, "target_compared": 3, **kw}
    return ni.shadow_admit(state, now_epoch=epoch, now_iso=iso, **args)


def test_daily_cap_resets_each_utc_day():
    state = ni.shadow_empty_state()
    assert _admit(state, 0, "2026-11-22T00:00:00Z") == (True, None)
    assert _admit(state, 1, "2026-11-22T00:00:01Z") == (True, None)
    assert _admit(state, 2, "2026-11-22T23:59:59Z") == (False, "daily_cap")
    assert state["counts"]["skippedDailyCap"] == 1
    assert _admit(state, 86400, "2026-11-23T00:00:00Z") == (True, None)
    assert state["counts"]["submitted"] == 3 and state["startedAt"] == "2026-11-22T00:00:00Z"


def test_the_shadow_ends_after_its_period_or_its_target():
    state = ni.shadow_empty_state()
    assert _admit(state, 1000, "2026-11-22T00:00:00Z")[0]
    assert _admit(state, 1000 + 7 * 86400, "2026-11-29T00:00:00Z") == (False, "ended")
    assert state["endReason"] == "period"
    # An ended shadow does not restart by itself.
    assert _admit(state, 1000 + 8 * 86400, "2026-11-30T00:00:00Z") == (False, "ended")
    state = ni.shadow_empty_state()
    assert _admit(state, 0, "2026-11-22T00:00:00Z")[0]
    state["counts"]["compared"] = 3
    assert _admit(state, 1, "2026-11-22T00:00:01Z") == (False, "ended")
    assert state["endReason"] == "count"
    assert _admit(ni.shadow_empty_state(), 0, "2026-11-22T00:00:00Z", enabled=False) == (False, "switched_off")


def test_production_bounds_and_their_cost():
    assert scanner._NEWS_LUNA_SHADOW_DAILY_CAP == 80
    assert scanner._NEWS_LUNA_SHADOW_PERIOD_DAYS == 7
    assert scanner._NEWS_LUNA_SHADOW_TARGET == 200
    # Worst case: every admitted request reserves at most the call's bound.
    one = scanner.argus_ai_cost.estimate_cost("gpt-6-luna", 3000, 1200, scanner._AI_PRICING)
    assert one * scanner._NEWS_LUNA_SHADOW_DAILY_CAP * scanner._NEWS_LUNA_SHADOW_PERIOD_DAYS < 1.0


# ── agreement counts, saving and the owner-only reading ──

def test_agreement_counts_and_alert_disagreements():
    state = ni.shadow_empty_state()
    same = ni.shadow_decision_fields(BASELINE, "HIGH")
    ni.shadow_record(state, outcome="compared", at="t1", terra=same, luna=dict(same))
    ni.shadow_record(state, outcome="compared", at="t2", terra=same,
                     luna=ni.shadow_decision_fields(LUNA, "WATCH"), fingerprint="abcdef0123456789")
    ni.shadow_record(state, outcome="compared", at="t3", terra=ni.shadow_decision_fields(BASELINE, "WATCH"),
                     luna=ni.shadow_decision_fields(BASELINE, "CRITICAL"))
    view = ni.shadow_summary(state, enabled=True, now_epoch=0, daily_cap=80, period_days=7,
                             target_compared=200, model="gpt-6-luna", baseline_model="gpt-5.6-terra")
    assert view["counts"]["compared"] == 3 and view["answerUsed"] is False
    assert view["agreeCounts"]["severity"] == 1 and view["agreePercent"]["severity"] == 33
    assert view["agreePercent"]["alertCapable"] == 33
    assert view["alertDisagreements"] == {"baselineOnly": 1, "lunaOnly": 1}
    assert view["severityPairs"] == {"HIGH>HIGH": 1, "HIGH>WATCH": 1, "WATCH>CRITICAL": 1}
    assert view["mismatches"][0]["fingerprint"] == "abcdef012345"
    for index in range(ni.SHADOW_MISMATCH_CAP + 5):
        ni.shadow_record(state, outcome="compared", at=f"x{index}", terra=same,
                         luna=ni.shadow_decision_fields(LUNA, "HIGH"))
    assert len(state["mismatches"]) == ni.SHADOW_MISMATCH_CAP


def test_the_shadow_survives_a_restart_and_reads_in_the_owner_document(monkeypatch, shadow_on):
    run_cycle(monkeypatch, {"m1": mail("m1", "米30年債利回りが5%を突破 急騰続く")})
    _drain()
    scanner._news_intel_persist()
    saved = json.loads(Path(scanner._news_intake_file()).read_text(encoding="utf-8"))
    assert saved["lunaShadow"]["counts"]["compared"] == 1
    shadow_on["env"].pop("lunaShadow")
    scanner._news_intel_load()
    assert shadow_on["env"]["lunaShadow"]["counts"]["compared"] == 1
    monkeypatch.setattr(scanner, "_ARGUS_ADMIN_TOKEN", "shadow-test")
    monkeypatch.setattr(scanner, "_ai_usage_snapshot", lambda: {"readStatus": "NOT_CONFIGURED"})
    body = scanner.app.test_client().get(
        "/api/argus/ai-cost", headers={"X-ARGUS-ADMIN-TOKEN": "shadow-test"}).get_json()
    shadow = body["newsLunaShadow"]
    assert shadow["status"] == "RUNNING" and shadow["counts"]["compared"] == 1
    assert shadow["model"] == "gpt-6-luna" and shadow["baselineModel"] == "gpt-5.6-terra"
    text = ai_usage_report.report(body)
    assert "ニュースの読みの影" in text and "| 種類 | 0 | 0% |" in text
    assert ai_usage_report.money_leaks(body, text) == 0
