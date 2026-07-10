"""ARGUS V12.2.8準備 — リモート耐久/FFLゲート/GPT-5.6プローブ/SO Shadowの恒久ガード。"""
import argus_remote_durability as rd
import argus_schemas as sch
import scanner

NOW = "2026-07-11T09:00:00+09:00"
EV = {"eventId": "e1", "aggregateType": "forecast", "aggregateId": "a",
      "sequence": 1, "integrityHash": "h", "idempotencyKey": "k1"}


def test_local_commit_is_not_remote_committed():
    r = rd.receipt(event=EV, local_at="t1")
    assert r["durabilityState"] == "remote_pending"
    assert r["maximumLossWindowSeconds"] == 1800
    assert "完全永続とは呼ばない" in r["ownerReadableJa"]


def test_remote_commit_requires_ack_and_failure_keeps_local():
    assert rd.receipt(event=EV, local_at="t1",
                      remote_at="t2")["durabilityState"] == "remote_committed"
    f = rd.receipt(event=EV, local_at="t1", failure="HTTPError")
    assert f["durabilityState"] == "remote_failed"
    assert "ローカル保持" in f["ownerReadableJa"]


def test_backend_not_configured_safe():
    b = rd.backend_status(ledger_cron_expected=False)
    assert b["state"] == "not_configured"
    r = rd.receipt(event=EV, local_at="t1", backend_type="not_configured")
    assert r["durabilityState"] == "local_committed"


def test_no_60s_guarantee_claim():
    b = rd.backend_status()
    assert "60秒保証は" in b["guaranteeJa"]
    assert "主張しない" in b["guaranteeJa"]


def test_reconcile_matrix():
    e2 = {"idempotencyKey": "k2", "integrityHash": "h2"}
    r = rd.reconcile([EV, e2], [EV])
    assert r["status"] == "reconciled" and r["retransmittedCount"] == 1
    r2 = rd.reconcile([EV], [EV, e2])
    assert r2["replayedCount"] == 1
    bad = dict(EV); bad["integrityHash"] = "X"
    r3 = rd.reconcile([EV], [bad])
    assert r3["status"] == "conflict"
    assert "黙殺しない" in r3["ownerReadableJa"]
    assert rd.reconcile([EV], [EV])["status"] == "consistent"


def test_ffl_gate_never_fabricates():
    assert rd.first_forward_live_evidence([])["state"] == "no_candidate"
    rep = {"origin": "historical_replay", "id": "r"}
    mock = {"origin": "forward_live", "mockData": True, "id": "m"}
    assert rd.first_forward_live_evidence([rep, mock])["state"] == "no_candidate"


def test_ffl_gate_backdate_and_proof_levels():
    fl = {"origin": "forward_live", "mockData": False,
          "researchMissionId": "rm", "issuedAt": "2026-07-11T08:30",
          "integrityHash": "h", "id": "f1"}
    late = dict(fl); late["issuedAt"] = "2026-07-12T00:00"
    g = rd.first_forward_live_evidence([late], now_iso=NOW)
    assert g["state"] == "candidate_ineligible"          # backdate/未来拒否
    g2 = rd.first_forward_live_evidence([fl], now_iso=NOW)
    assert g2["state"] == "locally_proven"
    g3 = rd.first_forward_live_evidence([fl],
                                        receipts={"f1": "remote_committed"},
                                        now_iso=NOW)
    assert g3["state"] == "remotely_proven"


def test_gpt56_probe_gates():
    p = rd.capability_probe_record(requested_model="", configured=False,
                                   pricing_known=True, budget_ok=True)
    assert p["status"] == "not_configured"
    p2 = rd.capability_probe_record(requested_model="m", configured=True,
                                    pricing_known=False, budget_ok=True)
    assert p2["status"] == "pricing_unknown"
    p3 = rd.capability_probe_record(requested_model="m", configured=True,
                                    pricing_known=True, budget_ok=False)
    assert p3["status"] == "budget_blocked"
    p4 = rd.capability_probe_record(
        requested_model="m", configured=True, pricing_known=True,
        budget_ok=True, fixture_result={"status": "available",
                                        "responses": True, "usage": True})
    assert p4["status"] == "available"
    assert p4["canPromote"] is False                      # 可用性≠昇格


def test_shadow_comparison_never_changes_production():
    sc2 = rd.shadow_comparison(champion={"epoch": "c", "coverage": 1.0},
                               challenger={"epoch": "x", "coverage": 1.2},
                               sample_count=3)
    assert sc2["productionChanged"] is False
    assert sc2["ownerApprovalRequired"] is True
    assert sc2["recommendation"] == "insufficient_data"


def test_structured_outputs_shadow_mode():
    assert sch.SCHEMA_MODE == "shadow_validate"
    r = sch.shadow_validate("CatalystVerdict",
                            {"verdict": "x", "confidence": "high"})
    assert r["ok"] and r["productionChanged"] is False
    bad = sch.shadow_validate("CatalystVerdict",
                              {"verdict": "x", "confidence": "certain"})
    assert not bad["ok"]
    m = sch.structured_output_metrics()
    assert m["mode"] == "shadow_validate"
    assert m["schemas"]["CatalystVerdict"]["discrepancyCount"] >= 1


def test_dq_new_blocks_no_leak():
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/data-quality").get_json() or {}
        for k in ("durabilityLevel", "firstForwardLiveEvidence", "gpt56",
                  "structuredOutputs", "rcBlockers"):
            assert k in d, k
        assert "60秒保証は未実測" in d["durabilityLevel"]["maxLossWindowJa"]
        assert d["gpt56"]["canPromote"] is False
        body = str(d)
        for banned in ("passphrase", "hmac", "quantity", "avgCost",
                       "OPENAI_API_KEY"):
            assert banned not in body
