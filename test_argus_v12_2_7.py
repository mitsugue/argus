"""ARGUS V12.2.7 — write-throughジャーナル/発行判定/スキーマ検証の恒久ガード。"""
import argus_schemas as sch
import argus_state_journal as j
import scanner

NOW = "2026-07-11T08:30:00+09:00"


def _ev(seq=1, agg="6965:d", et="forecast_issued"):
    return j.event(event_type=et, aggregate_type="forecast", aggregate_id=agg,
                   sequence=seq, occurred_at=NOW,
                   payload={"symbol": "6965"}, origin="forward_live")


def test_journal_idempotent_and_monotonic():
    J = []
    e1 = _ev(1)
    assert j.append(J, e1) is True
    assert j.append(J, dict(e1)) is False          # 冪等
    e0 = _ev(1); e0["idempotencyKey"] = "other"
    assert j.append(J, e0) is False                # 単調性違反拒否
    assert j.append(J, _ev(2)) is True


def test_journal_rejects_private_payload():
    assert j.event(event_type="forecast_issued", aggregate_type="f",
                   aggregate_id="x", sequence=1, occurred_at=NOW,
                   payload={"quantity": 100}) is None
    assert j.event(event_type="forecast_issued", aggregate_type="f",
                   aggregate_id="x", sequence=1, occurred_at=NOW,
                   payload={"avgCost": 5}) is None


def test_journal_corruption_detection_last_known_good():
    e1, e2 = _ev(1), _ev(2)
    bad = dict(e2); bad["integrityHash"] = "broken"
    r = j.load_valid([e1, bad, "garbage"])
    assert r["corruptCount"] == 2
    assert len(r["events"]) == 1 and j.verify(r["events"][0])


def test_journal_restart_restore(monkeypatch):
    scanner._OPS_JOURNAL.clear()
    scanner._OPS_SEQ.clear()
    scanner._journal("incident_opened", "incident", "t1", {"x": 1})
    saved = list(scanner._OPS_JOURNAL)
    scanner._OPS_JOURNAL.clear()
    r = j.load_valid(saved)
    for e in r["events"]:
        j.append(scanner._OPS_JOURNAL, e)
    assert len(scanner._OPS_JOURNAL) == 1          # 再起動相当の復元


def test_issuance_decision_matrix():
    f = j.forecast_issuance_decision
    assert f(store_ready=False, mock_data=False, already_issued_today=False,
             now_hhmm="10:00", market="JP")["decision"] == "insufficient_data"
    assert f(store_ready=True, mock_data=True, already_issued_today=False,
             now_hhmm="10:00", market="JP")["decision"] == "mock_blocked"
    assert f(store_ready=True, mock_data=False, already_issued_today=True,
             now_hhmm="10:00", market="JP")["decision"] == "duplicate"
    rec = f(store_ready=True, mock_data=False, already_issued_today=False,
            now_hhmm="10:00", market="JP")
    assert rec["decision"] == "recovered_intraday_eligible"
    assert rec["recoveryPermitted"] is True
    late = f(store_ready=True, mock_data=False, already_issued_today=False,
             now_hhmm="14:00", market="JP")
    assert late["decision"] == "stale_opportunity"
    assert "翌営業日" in late["nextOpportunityJa"]
    closed = f(store_ready=True, mock_data=False, already_issued_today=False,
               now_hhmm="16:00", market="JP")
    assert closed["decision"] == "wait_next_session"


def test_schema_validation_gates():
    ok, _ = sch.validate("CatalystVerdict", {"verdict": "x",
                                             "confidence": "high"})
    assert ok
    bad, why = sch.validate("CatalystVerdict", {"verdict": "x",
                                                "confidence": "certain"})
    assert not bad and "invalid_enum" in why
    miss, why2 = sch.validate("ResearchQualityScore", {"argusScore": 90})
    assert not miss and "missing_required" in why2
    badurl, why3 = sch.validate("EvidenceItem",
                                {"titleJa": "t", "verificationStatus": "unknown",
                                 "url": "not a url"})
    assert not badurl and why3 == "invalid_url"


def test_structured_outputs_flagged_off_and_malformed_rejected():
    assert sch.STRUCTURED_OUTPUTS_ENABLED is False   # SDK実測まで互換パーサ維持
    r = sch.validate_claims(["not-a-dict"])
    assert r["rejectedCount"] == 1 and r["schemaFailed"] is True


def test_dq_journal_and_decision_no_leak():
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/data-quality").get_json() or {}
        oj = d.get("operationalJournal") or {}
        assert "buffered write-through" in oj.get("durabilityJa", "")
        assert "≦30分" in oj.get("durabilityJa", "")
        fd = d.get("forecastIssuanceDecision") or {}
        assert fd.get("decision") in j.ISSUANCE_DECISIONS
        body = str(d)
        for banned in ("passphrase", "hmac", "quantity", "avgCost"):
            assert banned not in body
