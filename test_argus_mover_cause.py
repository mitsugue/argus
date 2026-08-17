"""ARGUS V11.3.3 — Mover Cause Engine discipline tests (pure, frozen times).

The product bug: sharp movers all showed 原因未確認. The ladder must (a) never
overclaim confirmed causes, (b) never waste candidate evidence as "unknown",
(c) always say what was checked and what to check next when there is no lead.
"""
import json
import argus_mover_cause as MC
import argus_mover_cause_store as MS

NOW = "2026-07-02T05:00:00Z"
MOVE_START = "2026-07-02T00:05:00Z"          # JP session open proxy

COVER_ALL = {k: True for k in (
    "tdnetChecked", "officialEventsChecked", "edinetSecChecked", "companyNewsChecked",
    "jpNewsChecked", "caosChecked", "sectorPeerChecked", "macroChecked",
    "flowChecked", "technicalChecked")}


def _mover(chg=-6.0, market="JP", sym="5801"):
    return {"symbol": sym, "market": market, "changePct": chg,
            "direction": "down" if chg < 0 else "up",
            "name": "テスト銘柄", "asOf": NOW, "moveStartedAt": MOVE_START}


def _tdnet(disclosed="2026-07-01T23:30:00Z", material=True, sentiment="negative",
           official=True):
    return {"symbol": "5801", "title": "業績予想の下方修正", "categoryJa": "業績修正",
            "disclosedAt": disclosed, "material": material, "sentiment": sentiment,
            "official": official, "provider": "jquants-tdnet"}


# ── ladder rules ─────────────────────────────────────────────────────────────
def test_official_before_move_with_market_confirmation_is_confirmed():
    rec = MC.resolve(_mover(-6.0), {"tdnetItems": [_tdnet()], "coverage": COVER_ALL}, NOW)
    assert rec["causeStatus"] == "confirmed_cause"
    assert "業績修正" in rec["bestLeadJa"]


def test_official_without_market_confirmation_is_probable():
    # sentiment unknown → direction consistency unprovable → not confirmed
    rec = MC.resolve(_mover(-6.0), {"tdnetItems": [_tdnet(sentiment=None)],
                                    "coverage": COVER_ALL}, NOW)
    assert rec["causeStatus"] == "probable_catalyst"
    assert rec["whyNotConfirmedJa"]


def test_post_move_article_cannot_be_trigger():
    # published 2h AFTER the move started → confirmation at best, never confirmed
    rec = MC.resolve(_mover(-6.0), {"tdnetItems": [_tdnet(disclosed="2026-07-02T02:05:00Z")],
                                    "coverage": COVER_ALL}, NOW)
    assert rec["causeStatus"] != "confirmed_cause"
    top = rec["causeCandidates"][0]
    assert top["timingRelation"] == "after_move"
    assert top["role"] in ("confirmation", "amplifier", "background_only")


def test_single_source_direct_news_is_candidate():
    news = [{"headline": "5801に関する報道", "publisher": "MediaX",
             "publishedAt": "2026-07-01T23:00:00Z", "sentiment": None}]
    rec = MC.resolve(_mover(-6.0), {"companyNews": news, "coverage": COVER_ALL}, NOW)
    assert rec["causeStatus"] == "candidate_catalyst"
    assert "有力候補" in MC.reason_suffix_ja(rec) or "候補" in rec["causeStatusJa"]
    assert "単一ソース" in rec["whyNotConfirmedJa"]


def test_entity_association_is_candidate_never_more():
    lead = {"titleJa": "OpenAI関連の報道", "via": "entity", "relationJa": "出資先",
            "corroboration": "single"}
    rec = MC.resolve(_mover(-6.0, sym="9984"), {"caosLead": lead, "coverage": COVER_ALL}, NOW)
    assert rec["causeStatus"] == "candidate_catalyst"
    assert any("連想" in (c["limitationsJa"][0] if c["limitationsJa"] else "")
               for c in rec["causeCandidates"] if c["category"] == "entity_association")


def test_theme_only_never_confirms():
    lead = {"titleJa": "AI半導体テーマ", "via": "theme", "corroboration": "single"}
    rec = MC.resolve(_mover(-6.0), {"caosLead": lead, "coverage": COVER_ALL}, NOW)
    assert rec["causeStatus"] in ("candidate_catalyst",)
    assert rec["causeStatus"] != "confirmed_cause"


def test_no_evidence_is_no_lead_with_coverage_and_next_checks():
    rec = MC.resolve(_mover(-6.0), {"coverage": COVER_ALL}, NOW)
    assert rec["causeStatus"] == "no_lead_yet"
    assert rec["nextChecksJa"], "no_lead must include next checks"
    assert rec["checkedJa"], "no_lead must show what WAS checked"
    suffix = MC.reason_suffix_ja(rec)
    assert "確認済み" in suffix and "次に確認" in suffix
    assert suffix != "原因未確認"


def test_strong_peer_move_is_probable():
    peers = {"theme": "ai_semis_cable", "peersTotal": 5, "peersSameDirection": 4}
    rec = MC.resolve(_mover(-6.0), {"peers": peers, "coverage": COVER_ALL}, NOW)
    assert rec["causeStatus"] == "probable_catalyst"


def test_upside_official_positive_disclosure():
    up_tdnet = {"symbol": "5801", "title": "自己株式取得を決議", "categoryJa": "自社株買い",
                "disclosedAt": "2026-07-01T23:30:00Z", "material": True,
                "sentiment": "positive", "official": True, "provider": "jquants-tdnet"}
    rec = MC.resolve(_mover(+9.0), {"tdnetItems": [up_tdnet], "coverage": COVER_ALL}, NOW)
    assert rec["causeStatus"] == "confirmed_cause"
    # spike must NOT convert into buy advice — caution instead
    assert "高値追い注意" in rec["impactCommentJa"]
    assert "BUY" not in json.dumps(rec)


def test_momentum_spike_is_not_buy_advice():
    rec = MC.resolve(_mover(+15.0), {"technical": {"priorRunupPct": 20},
                                     "coverage": COVER_ALL}, NOW)
    assert "高値追い注意" in rec["impactCommentJa"]
    blob = json.dumps(rec, ensure_ascii=False)
    # no affirmative buy instruction anywhere (denials like 「〜推奨ではない」 are fine)
    for bad in ("BUY NOW", "今すぐ買", "買い推奨です", "買うべき"):
        assert bad not in blob, bad


def test_not_scoreable_without_change_pct():
    rec = MC.resolve({"symbol": "5801", "market": "JP", "changePct": None,
                      "asOf": NOW}, {"coverage": {}}, NOW)
    assert rec["causeStatus"] == "not_scoreable"


def test_multi_source_before_move_with_confirmation_confirms():
    news = [
        {"headline": "大型受注を獲得", "publisher": "WireA", "tier": "wire",
         "publishedAt": "2026-07-01T23:00:00Z", "sentiment": "positive"},
        {"headline": "受注報道を各社が確認", "publisher": "WireB", "tier": "wire",
         "publishedAt": "2026-07-01T23:20:00Z", "sentiment": "positive"},
    ]
    rec = MC.resolve(_mover(+7.0), {"companyNews": news, "coverage": COVER_ALL}, NOW)
    assert rec["causeStatus"] == "confirmed_cause"


def test_stale_news_days_before_is_not_before_move():
    assert MC.timing_relation("2026-06-25T00:00:00Z", MOVE_START) == "unknown"
    assert MC.timing_relation("2026-07-01T23:00:00Z", MOVE_START) == "before_move"
    assert MC.timing_relation("2026-07-02T00:20:00Z", MOVE_START) == "during_move"
    assert MC.timing_relation("2026-07-02T03:00:00Z", MOVE_START) == "after_move"


# ── review-confirmed regression tests (v11.3.3 adversarial review) ──────────
def test_lifecycle_cause_status_does_not_passthrough_as_confirmation():
    # the lifecycle record earned confirmed_cause against ITS disclosure-day move —
    # that must not auto-confirm TODAY's (possibly unrelated/opposite) move.
    ev = {"officialEventId": "oe-x", "title": "旧開示", "categoryJa": "業績修正",
          "disclosedAt": "2026-07-02T02:30:00Z", "material": True, "sentiment": None,
          "causeStatus": "confirmed_cause", "provider": "jquants-tdnet"}
    rec = MC.resolve(_mover(-6.0), {"officialEvents": [ev], "coverage": COVER_ALL}, NOW)
    assert rec["causeStatus"] != "confirmed_cause"


def test_official_event_after_move_is_not_probable():
    ev = {"officialEventId": "oe-y", "title": "後出し開示", "categoryJa": "その他",
          "disclosedAt": "2026-07-02T03:00:00Z", "material": True, "sentiment": "negative",
          "provider": "jquants-tdnet"}   # 3h after the 00:05 move start
    rec = MC.resolve(_mover(-6.0), {"officialEvents": [ev], "coverage": COVER_ALL}, NOW)
    top_official = next(c for c in rec["causeCandidates"] if c["category"] == "official_disclosure")
    assert top_official["timingRelation"] == "after_move"
    assert rec["causeStatus"] not in ("confirmed_cause", "probable_catalyst")


def test_jst_naive_tdnet_timestamp_reads_before_move():
    # TDnet stamps are JST-naive: 08:30 JST on 07-02 = 23:30 UTC on 07-01,
    # i.e. BEFORE the 00:05 UTC session open — must not read as after_move.
    td = _tdnet(disclosed="2026-07-02T08:30", sentiment="negative")   # naive JST
    rec = MC.resolve(_mover(-6.0), {"tdnetItems": [td], "coverage": COVER_ALL}, NOW)
    assert rec["causeCandidates"][0]["timingRelation"] == "before_move"
    assert rec["causeStatus"] == "confirmed_cause"


def test_unrelated_stories_are_not_multi_source():
    news = [
        {"headline": "新製品を発表", "publisher": "MediaA",
         "publishedAt": "2026-07-01T23:00:00Z", "sentiment": "positive"},
        {"headline": "役員人事のお知らせ", "publisher": "MediaB",
         "publishedAt": "2026-07-01T23:20:00Z", "sentiment": "positive"},
    ]
    rec = MC.resolve(_mover(+7.0), {"companyNews": news, "coverage": COVER_ALL}, NOW)
    assert all(c["corroborationLevel"] != "multi_source" for c in rec["causeCandidates"])
    assert rec["causeStatus"] != "confirmed_cause"


def test_best_lead_comes_from_status_earning_candidate():
    # a HIGH-confidence tdnet fact (after_move, non-material) + a status-earning
    # peer candidate — bestLead must reflect what earned the status.
    peers = {"theme": "ai_semis_cable", "peersTotal": 5, "peersSameDirection": 4}
    td = _tdnet(disclosed="2026-07-02T13:05:00Z", material=False, sentiment=None)  # after move (Z)
    rec = MC.resolve(_mover(-6.0), {"tdnetItems": [td], "peers": peers,
                                    "coverage": COVER_ALL}, NOW)
    assert rec["causeStatus"] == "probable_catalyst"
    assert "同業" in rec["bestLeadJa"]


# ── store invariants ─────────────────────────────────────────────────────────
def _rec_with_candidates():
    return MC.resolve(_mover(-6.0), {"tdnetItems": [_tdnet()], "coverage": COVER_ALL}, NOW)


def test_blank_refresh_never_wipes_candidates():
    good = _rec_with_candidates()
    blank = MC.resolve(_mover(-6.0), {"coverage": COVER_ALL}, "2026-07-02T06:00:00Z")
    merged = MS.merge_record(good, blank, now_iso="2026-07-02T06:01:00Z")
    assert merged["causeCandidates"], "candidates must survive a blank refresh"
    assert merged["causeStatus"] == "confirmed_cause"


def test_explanation_survives_refresh():
    good = _rec_with_candidates()
    good["explanationJa"] = "AI解説テキスト"
    newer = _rec_with_candidates()
    newer["asOf"] = "2026-07-02T07:00:00Z"
    merged = MS.merge_record(good, newer, now_iso="2026-07-02T07:01:00Z")
    assert merged["explanationJa"] == "AI解説テキスト"


def test_snapshot_deterministic_and_metadata_only():
    a = _rec_with_candidates()
    b = MC.resolve(_mover(+9.0, sym="7203"), {"coverage": COVER_ALL}, NOW)
    s1 = MS.serialize_snapshot([a, b], as_of=NOW)
    s2 = MS.serialize_snapshot([b, a], as_of=NOW)
    assert json.dumps(s1, sort_keys=True) == json.dumps(s2, sort_keys=True)
    assert s1["summary"]["total"] == 2
    dirty = {**a, "apiKey": "sk-x", "holdings": 3, "prompt": "secret", "fullText": "本文"}
    blob = json.dumps(MS.serialize_snapshot([dirty], as_of=NOW), ensure_ascii=False).lower()
    for bad in ("apikey", "holdings", "prompt", "fulltext", "sk-x"):
        assert bad not in blob, bad


def test_restore_round_trip():
    recs = [_rec_with_candidates()]
    snap = MS.serialize_snapshot(recs, as_of=NOW)
    back = MS.restore_from_snapshot(snap)
    assert recs[0]["moverCauseId"] in back


# ── scanner integration ──────────────────────────────────────────────────────
import scanner


class _ForbiddenCall(BaseException):
    """BaseException on purpose: the public paths wrap everything in
    `except Exception`, which would swallow an AssertionError sentinel and let a
    forbidden fetch pass silently. BaseException pierces those handlers."""


def test_public_mover_cause_gets_never_fetch_or_call_llm(monkeypatch):
    # STRICT guard for the new mover-cause surfaces: no provider fetch, no LLM.
    monkeypatch.setitem(scanner._MOVER_CAUSES_STATE, "restored", True)
    def boom(*a, **k):
        raise _ForbiddenCall("FORBIDDEN external call from public GET")
    for name in ("_openai_prose", "_openai_research", "_cause_explain",
                 "get_tdnet_recent", "get_catalysts_snapshot", "_finnhub_catalyst",
                 "_jp_stock_news_intel", "get_company_news", "get_market_news"):
        monkeypatch.setattr(scanner, name, boom)
    with scanner.app.test_client() as c:
        assert c.get("/api/argus/mover-causes").status_code == 200
        assert c.get("/api/argus/mover-causes/status").status_code == 200
        assert c.get("/api/argus/mover-causes/snapshot").status_code == 200
        assert c.get("/api/argus/mover-causes/JP/5801").status_code == 200


def test_public_explain_never_calls_llm(monkeypatch):
    # cause-attribution keeps its (pre-existing) free-provider evidence reads,
    # but explain=1 must NEVER reach an LLM/web-search from a public GET.
    monkeypatch.setitem(scanner._MOVER_CAUSES_STATE, "restored", True)
    def boom(*a, **k):
        raise _ForbiddenCall("FORBIDDEN LLM call from public GET")
    for name in ("_openai_prose", "_openai_research", "_cause_explain", "_openai_judge"):
        monkeypatch.setattr(scanner, name, boom)
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/cause-attribution?symbol=5801&market=JP&explain=1").get_json()
    assert d.get("explanationStatus") in ("cached", "not_generated")
    assert "moverCause" in d


def test_admin_mover_cause_endpoints_require_token():
    with scanner.app.test_client() as c:
        r1 = c.post("/api/argus/admin/mover-causes/refresh")
        r2 = c.post("/api/argus/admin/mover-causes/explain")
    assert r1.status_code in (401, 503) and r2.status_code in (401, 503)


def test_mover_causes_list_shape_and_filters(monkeypatch):
    monkeypatch.setitem(scanner._MOVER_CAUSES_STATE, "restored", True)
    rec = _rec_with_candidates()
    up = MC.resolve(_mover(+9.0, market="US", sym="NVDA"), {"coverage": COVER_ALL}, NOW)
    monkeypatch.setattr(scanner, "_MOVER_CAUSES",
                        {rec["moverCauseId"]: rec, up["moverCauseId"]: up})
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/mover-causes").get_json()
        assert d["schemaVersion"] == "mover-cause-v2" and d["count"] == 2
        for it in d["items"]:
            for k in ("moverCauseId", "causeStatus", "causeStatusJa", "evidenceCoverage",
                      "nextChecksJa", "whyNotConfirmedJa"):
                assert k in it, k
        u = c.get("/api/argus/mover-causes?direction=up").get_json()
        assert all(x["direction"] == "up" for x in u["items"]) and u["count"] == 1
        blob = json.dumps(d).lower()
        for bad in ("apikey", "x-api-key", "holdings", "costbasis", "prompt"):
            assert bad not in blob, bad


def test_downside_incident_carries_mover_cause():
    # incident dict passed through the scanner attach path shape (compact projection)
    rec = _rec_with_candidates()
    comp = MC.compact(rec)
    for k in ("causeStatus", "causeStatusJa", "bestLeadJa", "whyNotConfirmedJa",
              "nextChecksJa", "topCandidates"):
        assert k in comp, k
    assert len(comp["topCandidates"]) <= 3
