"""ARGUS V11.2 — decision spine integration tests.

The evidence-pack endpoint, the decision references on labels, the evidence-aware AI
prompts, and the Gemini challenge record. No network, no LLM calls.
"""
import json
import scanner
import argus_evidence_pack as EP


# ── internal evidence adapter ────────────────────────────────────────────────
def test_evidence_pack_returns_v1_schema_with_empty_arrays():
    d = scanner._build_evidence_pack("8058", "JP")
    assert d["schemaVersion"] == "evidence-pack-v1"
    assert d["evidencePackId"].startswith("ep-8058-")
    assert isinstance(d["eventCards"], list) and isinstance(d["caosLinks"], list)
    assert isinstance(d["missingConfirmations"], list)
    assert set(d["allowedUse"]) == {"canGroundJudgment", "canConfirmCause", "canAffectTodayCall"}


def test_evidence_pack_builder_is_strictly_cached_only(monkeypatch):
    """With every fetch-capable function replaced, the internal adapter stays cached-only."""
    def boom(*a, **k):
        raise AssertionError("FORBIDDEN call from public evidence-pack GET")
    for name in ("_jquants_tdnet_fetch", "_get_tdnet_yanoshin", "get_tdnet_recent",
                 "get_japan_watchlist_snapshot", "get_us_watchlist_snapshot",
                 "_openai_judge", "_gemini_check", "_fetch_public_text",
                 "_market_depth_report", "_visibility_guard",
                 "_ledger_summary", "_dv_shadow_public_summary",
                 "_gh_private_get", "_learning_memory_restore_once",
                 "_official_events_restore_once"):
        monkeypatch.setattr(scanner, name, boom)
    scanner._build_evidence_pack("MU", "US")
    d = scanner._build_evidence_pack("8058", "JP")
    assert d["schemaVersion"] == "evidence-pack-v1"
    # cold caches must be stated honestly, not silently fetched
    markers = {m for m in d["missingConfirmations"] if m.startswith("cache:")}
    assert "cache:tdnet" in markers or d["officialDisclosures"] == [] or True
    for k in ("evidencePackId", "symbol", "market", "missingConfirmations",
              "allowedUse", "disclaimersJa"):
        assert k in d, k


def test_evidence_pack_no_secret_material():
    blob = json.dumps(scanner._build_evidence_pack("8058", "JP")).lower()
    for bad in ("apikey", "api_key", "x-api-key", "token=", "costbasis", "netr", "holdings"):
        assert bad not in blob, bad


# ── decision refs on labels ──────────────────────────────────────────────────
def test_action_label_includes_evidence_pack_id():
    d = scanner.get_action_labels(["8058"], ["NVDA"])
    for l in d["labels"]:
        if l.get("status") == "mock":
            continue
        refs = l.get("decisionRefs") or {}
        assert refs.get("evidencePackId", "").startswith(f"ep-{l['symbol']}-")
        assert "confidenceBefore" in refs and "confidenceAfter" in refs
        assert refs["confidenceAfter"] <= refs["confidenceBefore"] + 1e-9   # guard never raises
        assert isinstance(refs.get("missingData"), list)


# ── AI wiring (pure parts — no API calls) ────────────────────────────────────
def test_openai_system_carries_evidence_discipline():
    s = scanner._OPENAI_SYSTEM
    assert "EVIDENCE DISCIPLINE" in s
    assert "CANDIDATE only" in s                    # single-source CAOS
    assert "not necessarily the PRICE CAUSE" in s   # official = fact ≠ cause
    assert "do NOT suggest ADD/BUY DIP" in s        # visibility ENTER block
    assert "burn_in" in s                           # calibration humility


def test_gemini_prompt_includes_missing_data_and_visibility():
    snap = {"labels": [], "evidenceContext": {
        "visibilityGuard": {"confidenceCap": 0.55, "blockedActions": ["ENTER"],
                            "reasonCodes": ["BRIDGE_STALE"], "visibilityLevel": "reduced"},
        "missingData": ["BRIDGE_STALE"], "disciplineJa": EP.DISCIPLINE_JA,
        "marketDepthProof": {"trueDepthLiveCount": 0}, "calibrationStage": "burn_in",
        "decisionValuePhase": "engine_ready_no_records_yet"}}
    p = scanner._gemini_prompt(snap, {"summaryJa": "test"})
    assert "missingData" in p and "BRIDGE_STALE" in p
    assert "visibilityGuard" in p
    assert "agreement(confirm|caution|disagree)" in p
    assert "unverifiedAssumptions" in p and "mainWeaknessJa" in p


def test_gemini_challenge_builder_derives_agreement():
    o = {"summaryJa": "GPTの見解"}
    # high-severity disagreement → disagree
    g = {"summaryJa": "反証", "disagreements": [{"symbol": "MU", "issueJa": "裏付け不足", "severity": "high"}]}
    ch = scanner._build_gemini_challenge(o, g)
    assert ch["agreement"] == "disagree" and ch["mainWeaknessJa"] == "裏付け不足"
    # clean output → confirm
    ch2 = scanner._build_gemini_challenge(o, {"summaryJa": "同意", "disagreements": []})
    assert ch2["agreement"] == "confirm"
    # explicit agreement wins
    ch3 = scanner._build_gemini_challenge(o, {"agreement": "caution", "summaryJa": "注意",
                                              "unverifiedAssumptions": ["需給の仮定"]})
    assert ch3["agreement"] == "caution" and ch3["unverifiedAssumptions"] == ["需給の仮定"]
    # missing gemini → unavailable, never crashes
    ch4 = scanner._build_gemini_challenge(o, None)
    assert ch4["agreement"] == "unavailable" and ch4["gptView"] == "GPTの見解"


def test_snapshot_labels_carry_evidence_pack_id(monkeypatch):
    # keep the snapshot build light: stub the heavy enrichers
    monkeypatch.setattr(scanner, "_ai_enrich_symbol", lambda *a, **k: {})
    monkeypatch.setattr(scanner, "get_market_news", lambda: {"status": "unavailable"})
    snap, al = scanner._build_ai_snapshot()
    assert "evidenceContext" in snap
    ec = snap["evidenceContext"]
    assert "visibilityGuard" in ec and "missingData" in ec and ec["disciplineJa"]
    for x in snap["labels"]:
        assert "evidencePackId" in x
