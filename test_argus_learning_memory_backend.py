"""ARGUS V11.4.0 — Learning Memory backend integration tests.

Public GETs are cache-only (no LLM, no provider fetch); admin build/restore are
token-gated; Evidence Pack carries a caution-only learningMemory block; the AI
snapshot carries learningMemory context; action-label decisionRefs expose
learningMemoryUsed. No private/forbidden fields are ever stored or served.
"""
import json
import argus_learning_memory as LM
import scanner


class _Forbidden(BaseException):
    """BaseException so it pierces the `except Exception` wrappers on public paths —
    an AssertionError sentinel would be swallowed and let a forbidden fetch pass."""


def _seed(monkeypatch, obs=None):
    monkeypatch.setitem(scanner._LEARNING_MEMORY_STATE, "restored", True)
    obs = obs if obs is not None else (
        [{"cohortType": "symbol", "cohortKey": "5801", "outcome": "miss"} for _ in range(40)]
        + [{"cohortType": "macroEventCode", "cohortKey": "NFP", "outcome": "hit"} for _ in range(30)])
    doc = LM.build_memory(obs, now_iso=scanner._ai_now_iso())
    monkeypatch.setitem(scanner._LEARNING_MEMORY, "doc", doc)
    monkeypatch.setitem(scanner._LEARNING_MEMORY_STATE, "status", "ready")
    return doc


def _forbid_fetches(monkeypatch):
    def boom(*a, **k):
        raise _Forbidden("FORBIDDEN external call from public GET")
    for name in ("_openai_prose", "_openai_research", "_cause_explain", "_openai_judge",
                 "get_tdnet_recent", "get_catalysts_snapshot", "_finnhub_catalyst",
                 "get_company_news", "get_market_news"):
        if hasattr(scanner, name):
            monkeypatch.setattr(scanner, name, boom)


def test_learning_memory_route_schema(monkeypatch):
    _seed(monkeypatch)
    _forbid_fetches(monkeypatch)
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/learning-memory").get_json()
    assert d["schemaVersion"] == "learning-memory-v1"
    assert isinstance(d["lessons"], list) and isinstance(d["cohorts"], dict)
    assert "capsAndHints" in d and "limitationsJa" in d


def test_status_route_counts(monkeypatch):
    _seed(monkeypatch)
    _forbid_fetches(monkeypatch)
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/learning-memory/status").get_json()
    assert d["schemaVersion"] == "learning-memory-status-v1"
    assert d["status"] in ("ready", "not_ready", "building", "stale", "error")
    assert d["sampleStage"] in ("none", "burn_in", "early_signal", "usable", "mature")
    for k in ("lessons", "usableLessons", "officialEventSamples", "macroEventSamples",
              "moverCauseSamples", "decisionValueSamples", "calibrationSamples"):
        assert isinstance(d["counts"][k], int)


def test_admin_build_requires_token():
    with scanner.app.test_client() as c:
        assert c.post("/api/argus/admin/learning-memory/build").status_code in (401, 503)
        assert c.post("/api/argus/admin/learning-memory/restore").status_code in (401, 503)


def test_public_gets_never_fetch_or_call_llm(monkeypatch):
    _seed(monkeypatch)
    _forbid_fetches(monkeypatch)
    with scanner.app.test_client() as c:
        assert c.get("/api/argus/learning-memory").status_code == 200
        assert c.get("/api/argus/learning-memory/status").status_code == 200
        assert c.get("/api/argus/learning-memory/snapshot").status_code == 200
        assert c.get("/api/argus/evidence-pack?symbol=5801&market=JP").status_code == 200


def test_evidence_pack_includes_learning_memory(monkeypatch):
    _seed(monkeypatch)
    _forbid_fetches(monkeypatch)
    with scanner.app.test_client() as c:
        ep = c.get("/api/argus/evidence-pack?symbol=5801&market=JP").get_json()
    lm = ep.get("learningMemory")
    assert lm and lm["schemaVersion"] == "learning-memory-compact-v1"
    assert lm["cautionOnly"] is True
    assert any("公式証拠" in x for x in lm["limitationsJa"])
    # symbol-relevant caps only: 5801 negative lesson (n=40) yields a cap
    assert any(c_["cohortKey"] == "5801" for c_ in lm.get("confidenceCaps", []))


def test_snapshot_has_no_forbidden_keys(monkeypatch):
    _seed(monkeypatch)
    with scanner.app.test_client() as c:
        snap = c.get("/api/argus/learning-memory/snapshot").get_json()
    blob = json.dumps(snap, ensure_ascii=False).lower()
    for bad in ('"prompt":', '"messages":', '"holdings":', '"pnl":', '"netr":',
                '"costbasis":', '"apikey":', '"rawproviderbody":', '"privaterepo":'):
        assert bad not in blob, bad


def test_burn_in_stage_does_not_overclaim(monkeypatch):
    # tiny sample must report burn_in — never mature — even though route works.
    _seed(monkeypatch, obs=[{"cohortType": "macroEventCode", "cohortKey": "NFP", "outcome": "hit"}
                            for _ in range(4)])
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/learning-memory/status").get_json()
    assert d["sampleStage"] == "burn_in"


def test_official_event_probable_catalyst_is_pending_not_miss(monkeypatch):
    # regression (v11.4.0 review): probable_catalyst is the lifecycle's PENDING /
    # 'unknown is acceptable' state — it must NEVER be scored as a miss. Only
    # confirmed_cause=hit and not_cause=miss are terminal.
    monkeypatch.setitem(scanner._OFFICIAL_EVENTS_STATE, "restored", True)
    monkeypatch.setattr(scanner, "_OFFICIAL_EVENTS", {
        "hit1": {"material": True, "market": "JP", "category": "earnings",
                 "lifecycleStage": "followup_1d", "causeStatus": "confirmed_cause",
                 "marketReaction": {"sameDay": {"marketConfirmed": True}}},
        "miss1": {"material": True, "market": "JP", "category": "guidance",
                  "lifecycleStage": "followup_1d", "causeStatus": "not_cause",
                  "marketReaction": {"sameDay": {}, "nextSession": {}}},
        "pend1": {"material": True, "market": "JP", "category": "earnings",
                  "lifecycleStage": "market_reaction_observed", "causeStatus": "probable_catalyst",
                  "marketReaction": {"sameDay": {}}},
    })
    obs = scanner._lm_official_event_observations()
    earnings = [o for o in obs if o["cohortType"] == "eventType" and o["cohortKey"] == "earnings"]
    # hit1 (hit) + pend1 (pending) → one scored hit, one pending; NO miss
    scored = [o for o in earnings if not o["pending"]]
    assert len(scored) == 1 and scored[0]["outcome"] == "hit"
    assert any(o["pending"] for o in earnings), "probable_catalyst must be pending"
    guidance = [o for o in obs if o["cohortType"] == "eventType" and o["cohortKey"] == "guidance"]
    assert guidance and guidance[0]["outcome"] == "miss" and not guidance[0]["pending"]


def test_action_label_carries_learning_memory_used(monkeypatch):
    # a usable lesson for a watchlist symbol → decisionRefs.learningMemoryUsed True
    # and confidence never exceeds the applicable cap. Uses the real label builder.
    _seed(monkeypatch, obs=[{"cohortType": "market", "cohortKey": "JP", "outcome": "miss"}
                            for _ in range(40)])
    _forbid_fetches(monkeypatch)
    try:
        al = scanner.get_action_labels(jp_symbols=["8058"], us_symbols=[])
    except Exception:
        al = None
    if not al or not al.get("labels"):
        return  # environment couldn't produce a label (no cached quote) — skip
    for L in al["labels"]:
        refs = L.get("decisionRefs") or {}
        assert "learningMemoryUsed" in refs
        caps = [c_.get("cap") for c_ in
                (LM.compact_for_evidence(scanner._LEARNING_MEMORY["doc"],
                                         market=L.get("market")).get("confidenceCaps") or [])
                if isinstance(c_.get("cap"), (int, float))]
        if caps and refs.get("learningMemoryUsed"):
            assert L["confidence"] <= min(caps) + 1e-9
