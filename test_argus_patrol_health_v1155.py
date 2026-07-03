"""ARGUS V11.5.5 — patrol-health endpoint / self-check / durability wiring."""
import json
import argus_caos_patrol_store as PL
import scanner


class _Boom(BaseException):
    pass


def _no_fetch(monkeypatch):
    def boom(*a, **k):
        raise _Boom("no fetch/LLM on public GET")
    for name in ("_fetch_public_text", "_translate_headlines_ja", "_openai_prose",
                 "_openai_research", "_google_news_jp_rss", "_google_news_us_rss",
                 "_finnhub_catalyst", "get_tdnet_recent", "_probe_article",
                 "collect_institutional_intel"):
        if hasattr(scanner, name):
            monkeypatch.setattr(scanner, name, boom)


def _reset(monkeypatch, ledger=None):
    monkeypatch.setitem(scanner._NEWS_JA_STATE, "restored", True)
    monkeypatch.setitem(scanner._MOVER_CAUSES_STATE, "restored", True)
    monkeypatch.setitem(scanner._SWEEP_STATE, "restored", True)
    monkeypatch.setattr(scanner, "_MOVER_CAUSES", {})
    monkeypatch.setitem(scanner._PATROL_LEDGER, "restored", True)
    monkeypatch.setitem(scanner._PATROL_LEDGER, "doc",
                        ledger or PL.new_ledger(scanner._ai_now_iso()))


def _healthy_ledger():
    now = scanner._ai_now_iso()
    lg = PL.new_ledger(now)
    PL.record_run(lg, now_iso=now, ok=True, deep_sweeps=2, baseline_checked=True,
                  fresh_items=5, new_items=30, source_success=20, source_errors=1,
                  active_movers=2)
    PL.record_sweep(lg, now_iso=now, symbol="5803", market="JP", kind="deep",
                    status="completed", fresh=3)
    PL.update_source(lg, "nhk_business", now_iso=now, ok=True,
                     newest_published_at=now)
    return lg


def test_patrol_health_schema_and_healthy(monkeypatch):
    _no_fetch(monkeypatch)
    _reset(monkeypatch, _healthy_ledger())
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/caos/patrol-health").get_json()
    assert d["schemaVersion"] == "caos-patrol-health-v1"
    assert d["status"] == "healthy"
    assert d["lastPatrolAt"] and d["lastDeepSweepAt"] and d["lastBaselineSweepAt"]
    assert d["nextScheduledPatrolAt"]
    assert d["summary"]["runs24h"] == 1 and d["summary"]["deepSweeps24h"] == 1
    assert d["targetHealth"], "target health from the live plan"
    assert any(s["sourceId"] == "nhk_business" and s["status"] == "live"
               for s in d["sourceHealth"])
    # the 24h ledger rides along (restore source for a restarted dyno)
    assert d["ledger"]["runs"] and "sources" in d["ledger"]
    assert "true realtime" in d["noteJa"] or "near-real-time" in d["noteJa"]


def test_patrol_health_not_ready_when_no_runs(monkeypatch):
    _no_fetch(monkeypatch)
    _reset(monkeypatch)                            # empty ledger
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/caos/patrol-health").get_json()
    assert d["status"] == "not_ready"


def test_patrol_health_degraded_when_movers_but_no_deep(monkeypatch):
    _no_fetch(monkeypatch)
    now = scanner._ai_now_iso()
    lg = PL.new_ledger(now)
    PL.record_run(lg, now_iso=now, ok=True, deep_sweeps=0, baseline_checked=True,
                  active_movers=3)
    _reset(monkeypatch, lg)
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/caos/patrol-health").get_json()
    assert d["status"] == "degraded"
    assert any("deep sweep" in a["messageJa"] for a in d["alerts"])


def test_patrol_health_error_on_old_primary_violation(monkeypatch):
    _no_fetch(monkeypatch)
    _reset(monkeypatch, _healthy_ledger())
    today = scanner._ai_now_iso()[:10].replace("-", "")
    bad = {"moverCauseId": f"mc-JP-9999-{today}", "symbol": "9999", "market": "JP",
           "asOf": scanner._ai_now_iso(), "causeStatus": "candidate_catalyst",
           "causeStatusJa": "候補", "bestLeadJa": "直接ニュース: 古い記事",
           "causeCandidates": [{"titleJa": "古い記事", "category": "direct_news",
                                "role": "background_only", "confidence": 0.15,
                                "timingRelation": "unknown", "corroborationLevel": "single_source",
                                "linkType": "direct_mention", "marketConfirmed": False,
                                "sourceTier": "media", "candidateId": "c1",
                                "newsFreshness": {"freshness": "old", "ageHours": 340.0}}],
           "freshness": {}, "refreshPolicy": {}}
    monkeypatch.setattr(scanner, "_MOVER_CAUSES", {bad["moverCauseId"]: bad})
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/caos/patrol-health").get_json()
    assert d["status"] == "error"
    assert d["summary"]["oldPrimaryViolations"] >= 1


def test_baseline_only_note_when_no_movers(monkeypatch):
    _no_fetch(monkeypatch)
    now = scanner._ai_now_iso()
    lg = PL.new_ledger(now)
    PL.record_run(lg, now_iso=now, ok=True, deep_sweeps=0, baseline_checked=True,
                  active_movers=0, note_ja="active mover sweepなし。Core Portfolio baselineのみ確認。")
    _reset(monkeypatch, lg)
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/caos/patrol-health").get_json()
    assert d["status"] == "healthy"                # baseline-only is honest success
    assert any("baselineのみ確認" in a["messageJa"] for a in d["alerts"])


def test_watchtower_status_carries_patrol_ref(monkeypatch):
    _no_fetch(monkeypatch)
    _reset(monkeypatch, _healthy_ledger())
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/caos-watchtower/status").get_json()
    ph = d.get("patrolHealth")
    assert ph and ph["status"] == "healthy"
    assert "deepSweeps24h" in ph and "baselineSweeps24h" in ph


def test_deep_research_carries_patrol_ref(monkeypatch):
    _no_fetch(monkeypatch)
    _reset(monkeypatch, _healthy_ledger())
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/caos/deep-research/status").get_json()
    assert "patrolHealth" in d and d["patrolHealth"]["deepSweeps24h"] == 1


def test_restore_merges_from_snapshot(monkeypatch, tmp_path):
    """dyno-restart path: /tmp gone → merge from the ledger-branch patrol snapshot."""
    _no_fetch(monkeypatch)
    monkeypatch.setitem(scanner._NEWS_JA_STATE, "restored", True)
    monkeypatch.setitem(scanner._PATROL_LEDGER, "restored", False)
    monkeypatch.setitem(scanner._PATROL_LEDGER, "doc", PL.new_ledger(""))
    monkeypatch.setattr(scanner, "_PATROL_LEDGER_FILE", str(tmp_path / "none.json"))
    snap_ledger = _healthy_ledger()
    class _R:
        status_code = 200
        text = json.dumps({"schemaVersion": "caos-patrol-health-v1",
                           "ledger": snap_ledger})
    monkeypatch.setattr(scanner.requests, "get", lambda *a, **k: _R())
    scanner._patrol_ledger_restore_once()
    assert scanner._PATROL_LEDGER["doc"]["runs"], "snapshot history restored"


def test_self_check_requires_token():
    with scanner.app.test_client() as c:
        assert c.post("/api/argus/admin/caos/patrol-self-check").status_code in (401, 503)


def test_self_check_diagnostics(monkeypatch):
    _no_fetch(monkeypatch)
    _reset(monkeypatch, _healthy_ledger())
    monkeypatch.setattr(scanner, "_ARGUS_ADMIN_TOKEN", "tok")
    with scanner.app.test_client() as c:
        d = c.post("/api/argus/admin/caos/patrol-self-check",
                   headers={"X-ARGUS-ADMIN-TOKEN": "tok"}).get_json()
    assert d["schemaVersion"] == "caos-patrol-self-check-v1"
    names = {ch["name"] for ch in d["checks"]}
    assert {"baseline_targets_exist", "patrol_ledger_present", "last_run_recent",
            "sources_alive", "no_old_primary_violation"} <= names
    assert d["status"] == "healthy" and d["ok"] is True


def test_no_forbidden_keys(monkeypatch):
    _no_fetch(monkeypatch)
    _reset(monkeypatch, _healthy_ledger())
    with scanner.app.test_client() as c:
        blob = json.dumps(c.get("/api/argus/caos/patrol-health").get_json(),
                          ensure_ascii=False).lower()
    for bad in ('"prompt":', '"messages":', '"rawproviderbody":', '"holdings":',
                '"apikey":', '"api_key":', '"pnl":', '"costbasis":'):
        assert bad not in blob, bad
