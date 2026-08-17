"""ARGUS V11.3.4 — freshness/SLA, refresh queue, Market Confirmation v1.5 tests."""
import json
import argus_mover_cause as MC
import argus_mover_cause_refresh as MR
import argus_market_confirmation as MCF

NOW = "2026-07-02T05:00:00Z"
LATER_20M = "2026-07-02T05:20:00Z"
LATER_3H = "2026-07-02T08:00:00Z"
MOVE_START = "2026-07-02T00:05:00Z"
COVER_ALL = {k: True for k in (
    "tdnetChecked", "officialEventsChecked", "edinetSecChecked", "companyNewsChecked",
    "jpNewsChecked", "caosChecked", "sectorPeerChecked", "macroChecked",
    "flowChecked", "technicalChecked")}


def _mover(chg=-6.0, sym="5801", market="JP", owner=False):
    return {"symbol": sym, "market": market, "changePct": chg,
            "direction": "down" if chg < 0 else "up", "name": "テスト",
            "asOf": NOW, "moveStartedAt": MOVE_START, "ownerRelevant": owner}


def _tdnet_neg():
    return {"symbol": "5801", "title": "下方修正", "categoryJa": "業績修正",
            "disclosedAt": "2026-07-01T23:30:00Z", "material": True,
            "sentiment": "negative", "official": True, "provider": "jquants-tdnet"}


# ── freshness / SLA ──────────────────────────────────────────────────────────
def test_record_carries_freshness_and_policy():
    rec = MC.resolve(_mover(), {"coverage": COVER_ALL}, NOW)
    fr, rp = rec["freshness"], rec["refreshPolicy"]
    assert fr["lastEvidenceRefreshAt"] == NOW and fr["isStale"] is False
    assert fr["nextAutoCheckAt"], "nextAutoCheckAt must be generated"
    assert rp["priority"] in ("urgent", "high", "normal", "low")


def test_stale_candidate_flagged_at_read_time():
    rec = MC.resolve(_mover(-4.5), {"coverage": COVER_ALL}, NOW)   # high priority
    out = MC.annotate_freshness(dict(rec), LATER_3H)               # 3h later
    assert out["freshness"]["isStale"] is True
    assert "TTL" in out["freshness"]["staleReasonJa"]
    assert out["refreshPolicy"]["eligibleForAiExplain"] is True    # stale → re-eligible


def test_urgent_stale_over_15m_breaches_sla():
    rec = MC.resolve(_mover(-8.0), {"coverage": COVER_ALL}, NOW)   # urgent (|chg|>=7)
    assert rec["refreshPolicy"]["priority"] == "urgent"
    qs = MR.quality_and_sla([rec], LATER_20M)                      # 20min later
    assert any(b["symbol"] == "5801" and b["priority"] == "urgent"
               for b in qs["sla"]["breaches"])


def test_fresh_probable_remains_valid():
    peers = {"theme": "ai_semis_cable", "peersTotal": 5, "peersSameDirection": 4}
    rec = MC.resolve(_mover(-4.5), {"peers": peers, "coverage": COVER_ALL}, NOW)
    out = MC.annotate_freshness(dict(rec), "2026-07-02T05:10:00Z")   # 10min later
    assert rec["causeStatus"] == "probable_catalyst"
    assert out["freshness"]["isStale"] is False


def test_owner_relevance_is_transient_and_never_stored():
    # privacy: the RECORD must carry no owner data — even when the mover dict
    # hints ownerRelevant, resolve() ignores it for the stored priority/reason.
    rec = MC.resolve(_mover(-3.2, owner=True), {"coverage": COVER_ALL}, NOW)
    assert "ownerRelevant" not in rec
    assert "保有" not in json.dumps(rec, ensure_ascii=False)
    assert rec["refreshPolicy"]["priority"] != "urgent"     # no owner boost baked in
    # the boost exists only transiently via derive_priority(owner_relevant=True)
    prio, _ = MC.derive_priority("no_lead_yet", -3.2, owner_relevant=True)
    assert prio == "urgent"
    # and via the ADMIN-ONLY owner_map in build_queue — with 保有 stripped from output
    q = MR.build_queue([rec], LATER_20M, owner_map={"5801": True})
    assert q["queue"][0]["priority"] == "urgent"
    assert "保有" not in json.dumps(q, ensure_ascii=False)


def test_snapshot_strips_owner_fields():
    import argus_mover_cause_store as MS
    rec = MC.resolve(_mover(), {"coverage": COVER_ALL}, NOW)
    dirty = {**rec, "ownerRelevant": True, "ownerState": "held"}
    blob = json.dumps(MS.serialize_snapshot([dirty], as_of=NOW), ensure_ascii=False).lower()
    assert "ownerrelevant" not in blob and "ownerstate" not in blob


# ── refresh queue ────────────────────────────────────────────────────────────
def test_queue_priority_order_and_budget():
    recs = [
        MC.resolve(_mover(-8.0, sym="AAAA"), {"coverage": COVER_ALL}, NOW),    # urgent no_lead
        MC.resolve(_mover(-4.5, sym="BBBB"), {"coverage": COVER_ALL}, NOW),    # high candidate/no_lead
        MC.resolve(_mover(-6.0, sym="CCCC"),
                   {"tdnetItems": [dict(_tdnet_neg(), symbol="CCCC")],
                    "coverage": COVER_ALL}, NOW),                              # confirmed fresh
    ]
    q = MR.build_queue(recs, "2026-07-02T05:01:00Z", max_ai_explain=1)
    syms = [x["symbol"] for x in q["queue"]]
    assert syms[0] == "AAAA", "urgent no_lead first"
    assert "CCCC" not in syms or all(x["priority"] == "low" for x in q["queue"] if x["symbol"] == "CCCC")
    # AI budget of 1: only the top eligible mover gets the slot
    assert sum(1 for x in q["queue"] if x["aiExplainNeeded"]) <= 1
    assert q["budget"]["maxAiExplainPerRun"] == 1


def test_cooldown_prevents_repeated_ai():
    rec = MC.resolve(_mover(-8.0), {"coverage": COVER_ALL}, NOW)
    rec["freshness"]["lastAiExplainAt"] = NOW
    q = MR.build_queue([rec], "2026-07-02T05:10:00Z", ai_cooldown_min=30)
    assert all(not x["aiExplainNeeded"] for x in q["queue"])
    q2 = MR.build_queue([rec], "2026-07-02T05:45:00Z", ai_cooldown_min=30)
    assert any(x["aiExplainNeeded"] for x in q2["queue"]), "cooldown expired → eligible"


def test_ai_disabled_flag_zeroes_budget():
    rec = MC.resolve(_mover(-8.0), {"coverage": COVER_ALL}, NOW)
    q = MR.build_queue([rec], LATER_20M, ai_enabled=False)
    assert all(not x["aiExplainNeeded"] for x in q["queue"])


# ── market confirmation v1.5 ─────────────────────────────────────────────────
def test_relative_index_and_peer_basket_computed():
    mc = MCF.compute({"symbol": "5801", "changePct": -6.0},
                     {"indexMovePct": -0.5, "indexName": "TOPIX ETF(1306)",
                      "peerMoves": [-5.0, -7.0, -4.0]}, NOW)
    assert mc["relativeToIndexPct"] == -5.5
    assert mc["peerBasketMovePct"] == round((-5.0 - 7.0 - 4.0) / 3, 2)
    assert mc["status"] == "confirmed"          # |rel| >= 1.5, same direction


def test_index_driven_move_is_not_confirmed():
    # +2% stock on a +3.6% index day = UNDERPERFORMANCE — index-driven, not
    # stock-specific. Must be partial with the 逆方向 limitation, never confirmed.
    mc = MCF.compute({"symbol": "X", "changePct": 2.0}, {"indexMovePct": 3.6}, NOW)
    assert mc["status"] == "partial"
    assert any("逆方向" in l for l in mc["limitationsJa"])


def test_volume_less_push_points_yield_honest_null_vwap():
    pts = [{"ts": 1000, "price": 100.0, "volume": None},
           {"ts": 2000, "price": 98.0, "volume": None},
           {"ts": 5000, "price": 96.0, "volume": None}]
    mc = MCF.compute({"symbol": "X", "changePct": -4.0}, {"pushPoints": pts}, NOW)
    assert mc["vwapDistancePct"] is None
    assert any("VWAP" in l for l in mc["limitationsJa"])


def test_vwap_distance_from_push_points():
    pts = [{"ts": 1000, "price": 100.0, "volume": 1000},
           {"ts": 2000, "price": 98.0, "volume": 3000},
           {"ts": 5000, "price": 96.0, "volume": 6000}]
    mc = MCF.compute({"symbol": "X", "changePct": -4.0}, {"pushPoints": pts}, NOW)
    assert isinstance(mc["vwapDistancePct"], float)
    assert mc["vwapReclaim"] is False           # last price below VWAP


def test_missing_bars_partial_with_limitations():
    mc = MCF.compute({"symbol": "X", "changePct": -6.0}, {"indexMovePct": None}, NOW)
    assert mc["status"] == "missing"
    assert mc["limitationsJa"], "missing inputs must be stated"
    mc2 = MCF.compute({"symbol": "X", "changePct": -6.0}, {"todayVolume": 100, "avgVolume": 50}, NOW)
    assert mc2["status"] == "partial" and mc2["volumeRatio"] == 2.0


def test_market_confirmation_alone_cannot_confirm_cause():
    mc = MCF.compute({"symbol": "5801", "changePct": -6.0},
                     {"indexMovePct": -0.2, "peerMoves": [-1.0, -0.5, 0.1]}, NOW)
    assert mc["status"] == "confirmed"
    rec = MC.resolve(_mover(), {"coverage": COVER_ALL, "marketConfirmation": mc}, NOW)
    assert rec["causeStatus"] == "no_lead_yet", "no catalyst → mc alone must not confirm"


def test_official_plus_timing_plus_mc_confirms_and_stale_mc_cannot():
    mc = MCF.compute({"symbol": "5801", "changePct": -6.0}, {"indexMovePct": -0.2}, NOW)
    ev = {"tdnetItems": [_tdnet_neg()], "coverage": COVER_ALL, "marketConfirmation": mc}
    rec = MC.resolve(_mover(), ev, NOW)
    assert rec["causeStatus"] == "confirmed_cause"
    stale_mc = MCF.annotate(dict(mc), "2026-07-02T06:00:00Z")      # 60min later
    assert stale_mc["stale"] is True
    rec2 = MC.resolve(_mover(), {**ev, "marketConfirmation": stale_mc}, NOW)
    assert rec2["causeStatus"] != "confirmed_cause", "stale confirmation must not confirm"


def test_mc_missing_status_falls_back_to_magnitude_proxy():
    # no mc block at all → v11.3.3 behavior preserved (|move|>=2 proxy)
    rec = MC.resolve(_mover(), {"tdnetItems": [_tdnet_neg()], "coverage": COVER_ALL}, NOW)
    assert rec["causeStatus"] == "confirmed_cause"


def test_probable_without_mc_mentions_market_confirmation():
    peers = {"theme": "ai_semis_cable", "peersTotal": 5, "peersSameDirection": 4}
    rec = MC.resolve(_mover(-4.5), {"peers": peers, "coverage": COVER_ALL,
                                    "marketConfirmation": {"status": "missing",
                                                           "limitationsJa": []}}, NOW)
    assert rec["causeStatus"] == "probable_catalyst"
    assert "市場" in rec["whyNotConfirmedJa"]


# ── snapshot safety with new fields ──────────────────────────────────────────
def test_snapshot_new_fields_survive_and_no_forbidden_keys():
    import argus_mover_cause_store as MS
    rec = MC.resolve(_mover(), {"tdnetItems": [_tdnet_neg()], "coverage": COVER_ALL}, NOW)
    rec["explanationJa"] = "AI解説"
    rec["unverifiedAssumptions"] = ["仮定1"]
    dirty = {**rec, "prompt": "SECRET", "messages": ["x"], "rawProviderBody": "yy"}
    snap = MS.serialize_snapshot([dirty], as_of=NOW)
    blob = json.dumps(snap, ensure_ascii=False).lower()
    for bad in ('"prompt"', '"messages"', "rawproviderbody", "secret"):
        assert bad not in blob, bad
    item = snap["items"][0]
    assert item["freshness"]["lastEvidenceRefreshAt"] == NOW
    assert item["marketConfirmation"]["status"]
    assert item["refreshPolicy"]["priority"]


def test_store_merge_preserves_created_at_and_cooldown():
    import argus_mover_cause_store as MS
    old = MC.resolve(_mover(), {"coverage": COVER_ALL}, NOW)
    old["refreshPolicy"]["aiExplainCooldownUntil"] = "2026-07-02T05:30:00Z"
    old["freshness"]["lastAiExplainAt"] = NOW
    new = MC.resolve(_mover(), {"coverage": COVER_ALL}, LATER_20M)
    merged = MS.merge_record(old, new, now_iso=LATER_20M)
    assert merged["freshness"]["createdAt"] == NOW, "original createdAt survives"
    assert merged["freshness"]["lastAiExplainAt"] == NOW
    assert merged["refreshPolicy"]["aiExplainCooldownUntil"] == "2026-07-02T05:30:00Z"


# ── scanner integration ──────────────────────────────────────────────────────
import scanner


def test_new_public_routes_cached_only(monkeypatch):
    class Boom(BaseException):
        pass
    def boom(*a, **k):
        raise Boom("FORBIDDEN")
    monkeypatch.setitem(scanner._MOVER_CAUSES_STATE, "restored", True)
    rec = MC.resolve(_mover(), {"coverage": COVER_ALL}, scanner._ai_now_iso())
    monkeypatch.setattr(scanner, "_MOVER_CAUSES", {rec["moverCauseId"]: rec})
    monkeypatch.setitem(scanner._MOVER_REFRESH_QUEUE, "data", None)
    for name in ("_openai_prose", "_openai_research", "_cause_explain",
                 "get_tdnet_recent", "get_catalysts_snapshot", "_finnhub_catalyst",
                 "_jp_stock_news_intel", "get_company_news", "get_market_news"):
        monkeypatch.setattr(scanner, name, boom)
    with scanner.app.test_client() as c:
        assert c.get("/api/argus/mover-causes/refresh-queue").status_code == 200
        d = c.get("/api/argus/mover-causes/status").get_json()
        assert "quality" in d and "sla" in d
        mc = c.get("/api/argus/market-confirmation?symbol=5801&market=JP").get_json()
        assert mc.get("status") in ("confirmed", "partial", "missing", "not_applicable")
        it = c.get("/api/argus/mover-causes?limit=5").get_json()["items"][0]
        assert it["freshness"]["nextAutoCheckAt"]
        assert it.get("explanationStatus") in ("cached", "pending", "not_generated")


def test_new_admin_routes_require_token():
    with scanner.app.test_client() as c:
        assert c.post("/api/argus/admin/mover-causes/refresh-queue/run").status_code in (401, 503)
        assert c.post("/api/argus/admin/market-confirmation/refresh").status_code in (401, 503)
