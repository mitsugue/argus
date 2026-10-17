"""ARGUS V11.4.0 — Learning Memory pure-module tests.

Discipline under test: pending excluded, burn-in never strong, low-n never a
strong cap, official evidence beats history (caution-only), deterministic output.
"""
import json
import argus_learning_memory as LM
import argus_learning_memory_store as LMS

NOW = "2026-07-02T09:00:00Z"


def _obs(ct, ck, outcome=None, pending=False, market=None, symbol=None):
    return {"cohortType": ct, "cohortKey": ck, "outcome": outcome,
            "pending": pending, "market": market, "symbol": symbol}


def _macro(code, verdict):
    return _obs("macroEventCode", code, outcome=verdict)


# ── sample-size ladder ───────────────────────────────────────────────────────
def test_stage_ladder():
    assert LM.stage_for(0) == "none"
    assert LM.stage_for(9) == "burn_in"
    assert LM.stage_for(10) == "early_signal"
    assert LM.stage_for(29) == "early_signal"
    assert LM.stage_for(30) == "usable"
    assert LM.stage_for(99) == "usable"
    assert LM.stage_for(100) == "mature"


def test_small_sample_is_burn_in_and_insufficient():
    obs = [_macro("NFP", "hit") for _ in range(5)]
    mem = LM.build_memory(obs, now_iso=NOW)
    L = mem["lessons"][0]
    assert L["cohortType"] == "macroEventCode" and L["cohortKey"] == "NFP"
    assert L["sampleSize"] == 5
    assert L["stage"] == "burn_in"
    assert L["signal"] == "insufficient"     # n<10 → never a strong signal
    assert L["confidence"] == 0.0            # burn-in can never be strong
    assert mem["sampleStage"] == "burn_in"


def test_pending_outcomes_are_excluded():
    obs = ([_macro("CPI", "hit") for _ in range(12)]
           + [_obs("macroEventCode", "CPI", outcome=None, pending=True) for _ in range(50)]
           + [_obs("macroEventCode", "CPI", outcome="not_scoreable") for _ in range(20)])
    mem = LM.build_memory(obs, now_iso=NOW)
    L = next(x for x in mem["lessons"] if x["cohortKey"] == "CPI")
    assert L["sampleSize"] == 12, "pending / not_scoreable must not count"
    assert L["stage"] == "early_signal"


def test_scored_macro_creates_cohort_with_signal():
    obs = [_macro("NFP", "hit") for _ in range(24)] + [_macro("NFP", "miss") for _ in range(6)]
    mem = LM.build_memory(obs, now_iso=NOW)
    L = next(x for x in mem["lessons"] if x["cohortKey"] == "NFP")
    assert L["sampleSize"] == 30 and L["stage"] == "usable"
    assert L["hitRate"] == 0.8 and L["signal"] == "positive"
    assert L["confidence"] > 0.0
    assert "NFP" in mem["cohorts"]["macroEventCode"]


def test_repeated_misses_create_negative_caution_lesson():
    obs = [_obs("sourceFamily", "yanoshin", outcome="miss") for _ in range(40)] \
        + [_obs("sourceFamily", "yanoshin", outcome="hit") for _ in range(10)]
    mem = LM.build_memory(obs, now_iso=NOW)
    L = next(x for x in mem["lessons"] if x["cohortKey"] == "yanoshin")
    assert L["signal"] == "negative"
    assert "外れやすい" in L["lessonJa"]
    assert L["doNotOveruseJa"]
    # a usable negative lesson yields a confidence cap
    caps = mem["capsAndHints"]["confidenceCaps"]
    assert any(c["cohortKey"] == "yanoshin" and c["cap"] <= 0.6 for c in caps)


def test_low_sample_lesson_cannot_create_strong_cap():
    # 8 misses (burn_in) — decisively bad hit-rate but n too small for any cap
    obs = [_obs("sourceFamily", "flaky", outcome="miss") for _ in range(8)]
    mem = LM.build_memory(obs, now_iso=NOW)
    assert mem["capsAndHints"]["confidenceCaps"] == []
    L = next(x for x in mem["lessons"] if x["cohortKey"] == "flaky")
    assert L["confidence"] == 0.0 and L["signal"] == "insufficient"


def test_mover_candidate_later_not_confirmed_reduces_reliability():
    obs = [_obs("causeCategory", "entity_association", outcome="miss") for _ in range(30)] \
        + [_obs("causeCategory", "entity_association", outcome="hit") for _ in range(5)]
    mem = LM.build_memory(obs, now_iso=NOW)
    L = next(x for x in mem["lessons"] if x["cohortKey"] == "entity_association")
    assert L["signal"] == "negative"
    assert L["stage"] in ("usable", "mature")


def test_official_evidence_beats_history_caution_only():
    # even a strong negative lesson is caution-only: the compact block never
    # grounds/confirms/forces — it can only cap/caution.
    obs = [_obs("sourceFamily", "yanoshin", outcome="miss") for _ in range(120)]
    mem = LM.build_memory(obs, now_iso=NOW)
    compact = LM.compact_for_evidence(mem, source_families={"yanoshin"})
    assert compact["cautionOnly"] is True
    assert any("公式証拠" in x for x in compact["limitationsJa"])
    assert LM.applies_as_caution_only() is True


def test_burn_in_compact_adds_limitation():
    obs = [_macro("NFP", "hit") for _ in range(4)]
    mem = LM.build_memory(obs, now_iso=NOW)
    compact = LM.compact_for_evidence(mem, macro_codes={"NFP"})
    assert compact["sampleStage"] == "burn_in"
    assert any("サンプル不足のため参考情報。判断を強制しません。" in x for x in compact["limitationsJa"])


def test_compact_relevance_filter():
    obs = ([_macro("NFP", "hit") for _ in range(30)]
           + [_obs("symbol", "9984", outcome="hit") for _ in range(30)]
           + [_obs("symbol", "5801", outcome="miss") for _ in range(30)])
    mem = LM.build_memory(obs, now_iso=NOW)
    compact = LM.compact_for_evidence(mem, symbol="9984", macro_codes={"NFP"})
    keys = {(L["cohortType"], L["cohortKey"]) for L in compact["lessons"]}
    assert ("symbol", "9984") in keys
    assert ("symbol", "5801") not in keys       # unrelated symbol excluded


def test_prompt_injection_frames_as_caution():
    obs = [_obs("sourceFamily", "yanoshin", outcome="miss") for _ in range(50)]
    mem = LM.build_memory(obs, now_iso=NOW)
    compact = LM.compact_for_evidence(mem, source_families={"yanoshin"})
    txt = LM.compact_for_ai(compact)
    assert "参考" in txt and "公式証拠が優先" in txt
    assert "売買指示ではない" in txt


def test_deterministic_serialization():
    obs = [_macro("NFP", "hit"), _obs("market", "JP", outcome="miss"),
           _macro("CPI", "partial")]
    a = LM.build_memory(obs, now_iso=NOW)
    b = LM.build_memory(list(reversed(obs)), now_iso=NOW)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_empty_is_none_stage():
    mem = LM.build_memory([], now_iso=NOW)
    assert mem["sampleStage"] == "none"
    assert mem["lessons"] == []
    assert any("サンプルが少ない" in x for x in mem["limitationsJa"])


# ── store ────────────────────────────────────────────────────────────────────
def test_store_strips_forbidden_keys_recursively():
    mem = LM.build_memory([_macro("NFP", "hit") for _ in range(12)], now_iso=NOW)
    dirty = {**mem, "prompt": "SECRET", "apiKey": "sk-x",
             "lessons": mem["lessons"] + [{"lessonId": "x", "holdings": 5,
                                           "messages": ["y"], "rawProviderBody": "z"}]}
    snap = LMS.serialize_snapshot(dirty, as_of=NOW)
    blob = json.dumps(snap, ensure_ascii=False).lower()
    # JSON-key form: promptHints is a legitimate safe field (lesson text), so scan
    # for the forbidden KEYS, not bare substrings.
    for bad in ('"prompt":', '"apikey":', "sk-x", '"holdings":', '"messages":',
                '"rawproviderbody":'):
        assert bad not in blob, bad


def test_store_restore_round_trip():
    mem = LM.build_memory([_macro("NFP", "hit") for _ in range(30)], now_iso=NOW)
    snap = LMS.serialize_snapshot(mem, as_of=NOW)
    back = LMS.restore_from_snapshot(snap)
    assert back["sampleStage"] == "usable"
    assert any(L["cohortKey"] == "NFP" for L in back["lessons"])


def test_merge_does_not_reduce_counts():
    big = LM.build_memory([_macro("NFP", "hit") for _ in range(60)],
                          now_iso="2026-07-01T09:00:00Z")
    small = LM.build_memory([_macro("NFP", "hit") for _ in range(12)],
                            now_iso="2026-07-02T09:00:00Z")   # newer but smaller
    merged = LMS.merge_memory(big, small, now_iso=NOW)
    L = next(x for x in merged["lessons"] if x["cohortKey"] == "NFP")
    assert L["sampleSize"] == 60, "newer-but-smaller rebuild must not shrink counts"
    assert merged["counts"]["totalScoredSamples"] >= 60
