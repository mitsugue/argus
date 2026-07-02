"""ARGUS V11.4.1 — dashboard-events backend integration tests."""
import json
import scanner


class _Forbidden(BaseException):
    pass


def _forbid(monkeypatch):
    def boom(*a, **k):
        raise _Forbidden("FORBIDDEN external call from public GET")
    for name in ("_openai_prose", "_openai_research", "_cause_explain", "_bls_nfp_result",
                 "_macro_result_fetch", "get_tdnet_recent", "get_company_news",
                 "get_catalysts_snapshot"):
        if hasattr(scanner, name):
            monkeypatch.setattr(scanner, name, boom)


def _seed_released_nfp(monkeypatch, actual_available=True, with_post=False):
    monkeypatch.setitem(scanner._MACRO_ANALYSIS_STATE, "restored", True)
    now = scanner._ai_now_iso()
    rec = {
        "eventId": "us-nfp-x", "eventCode": "NFP", "eventTimeUtc": "2026-07-02T12:30:00Z",
        "eventDate": "2026-07-02", "analysisId": "ma-us-nfp-x", "displayImpact": "critical",
        "title": "US Employment Situation", "phase": "pre_final",   # STALE stored phase
        "pre": {"argusScenarioJa": "強ければ金利上", "summaryJa": "重要",
                "generatedAt": "2026-07-02T08:00:00Z"},
        "actual": ({"available": True, "headline": "非農業部門雇用者数 +57千人 / 失業率 4.2%",
                    "metrics": {"nfpChangeK": 57, "unemploymentRate": "4.2"},
                    "source": "BLS", "releasedAt": now} if actual_available
                   else {"available": False, "limitationsJa": ["公式結果未取得"]}),
        "post": ({"verdict": "partial", "generatedAt": now, "answerCheckJa": "概ね想定内",
                  "portfolioImpactJa": "金利低下方向"} if with_post
                 else {"verdict": "not_available", "generatedAt": None}),
        "marketReaction": {}}
    monkeypatch.setattr(scanner, "_MACRO_ANALYSIS", {"us-nfp-x": rec})


def test_dashboard_events_schema(monkeypatch):
    _seed_released_nfp(monkeypatch)
    _forbid(monkeypatch)
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/dashboard-events").get_json()
    assert d["schemaVersion"] == "dashboard-event-summary-v1"
    assert isinstance(d["items"], list) and "dedupe" in d and "status" in d


def test_nfp_released_is_post_not_pre(monkeypatch):
    _seed_released_nfp(monkeypatch, actual_available=True)
    _forbid(monkeypatch)
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/dashboard-events?eventCode=NFP").get_json()
    nfp = next(it for it in d["items"] if it["eventCode"] == "NFP")
    assert nfp["state"] in ("post_result", "post_answer_checked")
    assert nfp["state"] != "pre"
    assert nfp["display"]["showActualFirst"] is True
    assert nfp["officialResult"]["headlineJa"]
    assert nfp["caos"]["impactCommentJa"]           # non-empty when actual available


def test_pending_when_actual_unavailable(monkeypatch):
    _seed_released_nfp(monkeypatch, actual_available=False)
    _forbid(monkeypatch)
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/dashboard-events?eventCode=NFP").get_json()
    nfp = next(it for it in d["items"] if it["eventCode"] == "NFP")
    # released clock passed but no actual → pending (or stale), never pre/post_result
    assert nfp["state"] in ("released_pending_result", "stale")
    assert nfp["display"]["showActualFirst"] is False
    assert nfp["officialResult"]["available"] is False


def test_public_get_never_calls_llm_or_provider(monkeypatch):
    _seed_released_nfp(monkeypatch)
    _forbid(monkeypatch)
    with scanner.app.test_client() as c:
        assert c.get("/api/argus/dashboard-events").status_code == 200
        assert c.get("/api/argus/dashboard-events?importance=critical&includeDetails=true").status_code == 200


def test_no_forbidden_keys_in_summary(monkeypatch):
    _seed_released_nfp(monkeypatch)
    _forbid(monkeypatch)
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/dashboard-events").get_json()
    blob = json.dumps(d, ensure_ascii=False).lower()
    for bad in ('"prompt":', '"messages":', '"rawproviderbody":', '"holdings":',
                '"pnl":', '"costbasis":', '"apikey":'):
        assert bad not in blob, bad


def test_repair_requires_token():
    with scanner.app.test_client() as c:
        assert c.post("/api/argus/admin/macro-event-analysis/repair-post-release").status_code in (401, 503)


def test_impact_summary_nonempty_when_actual_available(monkeypatch):
    _seed_released_nfp(monkeypatch, actual_available=True, with_post=False)
    _forbid(monkeypatch)
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/dashboard-events?eventCode=NFP").get_json()
    nfp = next(it for it in d["items"] if it["eventCode"] == "NFP")
    assert nfp["caos"]["impactCommentJa"].strip() != ""
