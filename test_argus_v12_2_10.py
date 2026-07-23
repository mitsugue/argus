# -*- coding: utf-8 -*-
"""ARGUS V12.2.10 — リモートジャーナル耐久+検証済みread-back ackの恒久ガード。

v12.2.9本番診断で確定した欠陥の是正を固定する:
snapshot v3(journal同乗)/ack=read-back検証のみ(復元時刻プロキシ禁止)/
critical個別保持+非criticalcompaction/実測SLO/FFLレシート配線/
outcome origin継承/採点・Research語彙分離/smoke循環解消/backend経過時間基準。
"""
import json
import os

import argus_decision_ledger as dl
import argus_remote_durability as rd
import argus_remote_journal as rj
import argus_runtime as rt
import argus_state_journal as sj
import scanner

ROOT = os.path.dirname(__file__)
NOW = "2026-07-15T12:00:00+09:00"


def _ev(i=1, etype="incident_opened", agg="incident", agg_id=None,
        payload=None):
    return sj.event(event_type=etype, aggregate_type=agg,
                    aggregate_id=agg_id or f"a{i}", sequence=1,
                    occurred_at=f"2026-07-15T0{i % 10}:00:00Z",
                    payload=payload or {})


def _snapshot(events, meta=None, compacted=None):
    return {"schemaVersion": rj.SCHEMA_V3, "generatedAt": NOW,
            **rj.snapshot_journal_section(events=events, meta=meta or {},
                                          compacted=compacted, now_iso=NOW)}


# ── Phase 1: Remote Snapshot Schema v3 ──────────────────────────────────────

def test_v3_round_trip():
    evs = [_ev(1), _ev(2, etype="mission_recovered", agg="mission")]
    snap = _snapshot(evs, meta={"totalObserved": 2})
    parsed = rj.parse_remote_snapshot(snap)
    assert parsed["status"] == "ok"
    assert len(parsed["journalEvents"]) == 2
    assert parsed["manifest"]["eventCount"] == 2
    assert snap["opsJournalMeta"]["totalObserved"] == 2


def test_v2_snapshot_reported_as_legacy():
    v2 = {"schemaVersion": "argus-durable-v2", "asOf": NOW,
          "soak": {}, "forecasts": []}
    parsed = rj.parse_remote_snapshot(v2)
    assert parsed["status"] == "legacy_no_remote_journal"
    assert parsed["journalEvents"] == []            # 過去イベントを再構成しない


def test_private_field_rejected_before_snapshot():
    bad = dict(_ev(1))
    bad["publicSafePayload"] = {"quantity": 5}       # 私的フィールド
    sec = rj.snapshot_journal_section(events=[_ev(2), bad], meta={},
                                      now_iso=NOW)
    assert len(sec["opsJournal"]) == 1               # 正当な1件は生存
    assert sec["integrityManifest"]["rejectedCount"] == 1
    assert any("private_field" in r for r in
               sec["integrityManifest"]["rejectedReasonsRedacted"])


def test_one_malformed_event_does_not_discard_valid():
    broken = dict(_ev(1))
    broken["integrityHash"] = "tampered"
    sec = rj.snapshot_journal_section(events=[broken, _ev(2)], meta={},
                                      now_iso=NOW)
    assert len(sec["opsJournal"]) == 1
    assert "integrity_hash_mismatch" in \
        sec["integrityManifest"]["rejectedReasonsRedacted"]


def test_manifest_hash_mismatch_rejected():
    snap = _snapshot([_ev(1)])
    snap["integrityManifest"]["eventCount"] = 999    # 改竄
    parsed = rj.parse_remote_snapshot(snap)
    assert parsed["status"] == "manifest_invalid"


def test_empty_and_large_journal():
    assert rj.parse_remote_snapshot(_snapshot([]))["status"] == "ok"
    big = [_ev(i, etype="mission_recovered", agg="mission", agg_id=f"m{i}")
           for i in range(150)]
    snap = _snapshot(big)
    assert rj.parse_remote_snapshot(snap)["manifest"]["eventCount"] == 150


def test_sequence_preserved_in_manifest():
    e = sj.event(event_type="incident_opened", aggregate_type="incident",
                 aggregate_id="x", sequence=7, occurred_at=NOW, payload={})
    snap = _snapshot([e])
    assert snap["integrityManifest"]["highestSequenceByAggregate"][
        "incident:x"] == 7


def test_compact_readback_preserves_proof_without_large_ledger():
    evs = [_ev(1), _ev(2, agg_id="b2")]
    full = {**_snapshot(evs),
            "outcomes": [],
            "marketLedger": {"observations": [{"id": f"o{i}"}
                                                 for i in range(1000)]},
            "marketLedgerStateHash": "market-hash",
            "chartIntelligence": {"snapshots": [{"id": "chart"}]},
            "chartIntelligenceStateHash": "chart-hash",
            "todayIntelligence": {"analyses": [{"id": "today"}]},
            "todayIntelligenceStateHash": "today-hash",
            "marketReplay": {"contexts": [{"id": "replay"}]},
            "marketReplayStateHash": "replay-hash"}
    receipt = rj.compact_readback_snapshot(full)
    assert rj.verify_compact_readback_snapshot(receipt) is True
    assert receipt["receiptSchemaVersion"] == rj.READBACK_RECEIPT_SCHEMA
    assert "marketLedger" not in receipt
    assert "chartIntelligence" not in receipt
    assert "todayIntelligence" not in receipt
    assert "marketReplay" not in receipt
    assert receipt["marketLedgerStateHash"] == "market-hash"
    assert receipt["todayIntelligenceStateHash"] == "today-hash"
    assert receipt["marketReplayStateHash"] == "replay-hash"
    rec = rj.read_back_receipt(remote_blob=receipt, local_events=evs,
                               read_back_at=NOW)
    assert rec["verificationStatus"] == "verified"
    assert len(rec["ackedIdempotencyKeys"]) == 2


def test_compact_readback_tamper_is_rejected():
    receipt = rj.compact_readback_snapshot(_snapshot([_ev(1)]))
    receipt["marketLedgerStateHash"] = "tampered"
    assert rj.verify_compact_readback_snapshot(receipt) is False


# ── Phase 2: Verified Read-Back Ack ─────────────────────────────────────────

def test_read_back_exact_success():
    evs = [_ev(1), _ev(2, agg_id="b2")]
    rec = rj.read_back_receipt(remote_blob=_snapshot(evs), local_events=evs,
                               read_back_at=NOW)
    assert rec["verificationStatus"] == "verified"
    assert sorted(rec["ackedIdempotencyKeys"]) == \
        sorted(e["idempotencyKey"] for e in evs)


def test_missing_event_stays_pending():
    local = [_ev(1), _ev(2, agg_id="b2")]
    rec = rj.read_back_receipt(remote_blob=_snapshot(local[:1]),
                               local_events=local, read_back_at=NOW)
    assert local[1]["idempotencyKey"] not in rec["ackedIdempotencyKeys"]
    assert local[0]["idempotencyKey"] in rec["ackedIdempotencyKeys"]


def test_hash_mismatch_blocks_that_event_only():
    a, b = _ev(1), _ev(2, agg_id="b2")
    remote_a = dict(a)
    remote_a["integrityHash"] = "different"
    blob = {"schemaVersion": rj.SCHEMA_V3, "generatedAt": NOW,
            "opsJournal": [remote_a, b],
            "opsJournalMeta": {},
            "integrityManifest": _snapshot([remote_a, b])["integrityManifest"]}
    # remote_aはhash不一致で除外される(snapshot生成が検証する)ため、
    # 手動blobでhash不一致を注入して照合側の拒否を検証
    blob["integrityManifest"] = _manifest_for(blob["opsJournal"])
    rec = rj.read_back_receipt(remote_blob=blob, local_events=[a, b],
                               read_back_at=NOW)
    assert a["idempotencyKey"] not in rec["ackedIdempotencyKeys"]
    assert b["idempotencyKey"] in rec["ackedIdempotencyKeys"]
    assert rec["verificationStatus"] == "hash_mismatch"


def _manifest_for(events):
    man = {"schemaVersion": rj.SCHEMA_V3, "eventCount": len(events),
           "eventIds": [str(e.get("eventId")) for e in events],
           "idempotencyKeys": [str(e.get("idempotencyKey")) for e in events],
           "eventHashes": {str(e.get("eventId")): e.get("integrityHash")
                           for e in events},
           "highestSequenceByAggregate": {}, "criticalityByEventId": {},
           "compactedBatchCount": 0, "rejectedCount": 0,
           "rejectedReasonsRedacted": [], "generatedAt": NOW}
    man["manifestHash"] = rj._h({k: v for k, v in man.items()
                                 if k != "manifestHash"})
    return man


def test_sequence_conflict_blocks_ack():
    a = _ev(1)
    remote_a = dict(a)
    remote_a["sequence"] = 99
    blob = {"schemaVersion": rj.SCHEMA_V3, "generatedAt": NOW,
            "opsJournal": [remote_a], "opsJournalMeta": {},
            "integrityManifest": _manifest_for([remote_a])}
    rec = rj.read_back_receipt(remote_blob=blob, local_events=[a],
                               read_back_at=NOW)
    assert rec["verificationStatus"] == "sequence_conflict"
    assert rec["ackedIdempotencyKeys"] == []


def test_v2_snapshot_gives_no_false_ack():
    rec = rj.read_back_receipt(remote_blob={"asOf": NOW, "soak": {}},
                               local_events=[_ev(1)], read_back_at=NOW)
    assert rec["verificationStatus"] == "legacy_snapshot"
    assert rec["ackedIdempotencyKeys"] == []


def test_restore_time_cannot_be_ack():
    # journal_summaryはackキー基準のみ — 復元時刻/生成時刻では committedにならない
    ev = _ev(1)
    s = rt.journal_summary(events=[ev], total_observed=1,
                           last_remote_ack_at="2026-07-15T23:59:59Z",
                           acked_keys=set(), now_iso=NOW)
    assert s["remoteCommittedCount"] == 0
    assert s["remotePendingCount"] == 1


def test_remote_durability_summary_states():
    evs = [_ev(1), _ev(2, agg_id="b2")]
    key0 = evs[0]["idempotencyKey"]
    s = rj.remote_durability_summary(local_events=evs, acked_keys={key0},
                                     last_verified_ack_at=NOW, now_iso=NOW)
    assert s["remoteCommittedCount"] == 1 and s["remotePendingCount"] == 1
    s2 = rj.remote_durability_summary(local_events=evs, acked_keys=set(),
                                      last_verified_ack_at=None, now_iso=NOW)
    assert s2["lossWindowClaimStatus"] == "not_measurable"
    s3 = rj.remote_durability_summary(local_events=evs, acked_keys=set(),
                                      last_verified_ack_at=None, now_iso=NOW,
                                      legacy_remote=True)
    assert s3["lossWindowClaimStatus"] == "no_remote_journal"
    old = sj.event(event_type="incident_opened", aggregate_type="incident",
                   aggregate_id="old", sequence=1,
                   occurred_at="2026-07-15T00:00:00Z", payload={})
    s4 = rj.remote_durability_summary(local_events=[old], acked_keys=set(),
                                      last_verified_ack_at=NOW,
                                      now_iso="2026-07-15T12:00:00Z")
    assert s4["lossWindowClaimStatus"] == "exceeded_target"


def test_ack_receipts_survive_restart(monkeypatch, tmp_path):
    ev = _ev(3, agg_id="persist1")
    monkeypatch.setattr(scanner, "_OSINT_PERSIST_FILE",
                        str(tmp_path / "wal.json"))
    monkeypatch.setitem(scanner._REMOTE_ACK, "ackedKeys",
                        [ev["idempotencyKey"]])
    monkeypatch.setitem(scanner._REMOTE_ACK, "lastVerifiedRemoteAckAt", NOW)
    scanner._osint_persist()
    scanner._REMOTE_ACK["ackedKeys"] = []
    scanner._REMOTE_ACK["lastVerifiedRemoteAckAt"] = None
    monkeypatch.setitem(scanner._OSINT_PERSIST_STATE, "restored", False)
    scanner._osint_restore_once()
    assert ev["idempotencyKey"] in scanner._REMOTE_ACK["ackedKeys"]
    assert scanner._REMOTE_ACK["lastVerifiedRemoteAckAt"] == NOW


def test_scanner_readback_updates_ack(monkeypatch):
    scanner._OPS_JOURNAL.clear()
    scanner._OPS_SEQ.clear()
    scanner._REMOTE_ACK.update({"ackedKeys": [], "lastVerifiedRemoteAckAt": None,
                                "legacyRemote": False})
    scanner._journal("incident_opened", "incident", "rb-1",
                     {"component": "scheduler"})
    evs = list(scanner._OPS_JOURNAL)
    rec = scanner._remote_readback_ack(now_iso=NOW, blob=_snapshot(evs))
    assert rec["verificationStatus"] == "verified"
    assert scanner._REMOTE_ACK["lastVerifiedRemoteAckAt"] == NOW
    assert evs[-1]["idempotencyKey"] in scanner._REMOTE_ACK["ackedKeys"]
    # 冪等: 再実行してもack重複なし
    n = len(scanner._REMOTE_ACK["ackedKeys"])
    scanner._remote_readback_ack(now_iso=NOW, blob=_snapshot(evs))
    assert len(scanner._REMOTE_ACK["ackedKeys"]) == n
    scanner._OPS_JOURNAL.clear()


# ── Phase 3: critical分類とcompaction ───────────────────────────────────────

def test_soak_interrupted_is_critical():
    assert "soak_interrupted" in rd.CRITICAL_EVENT_TYPES
    assert rj.event_criticality("soak_interrupted") == "critical"
    assert rj.event_criticality("mission_recovered") == "routine"


def test_mission_recovered_compacts_critical_stays():
    evs = [sj.event(event_type="mission_recovered", aggregate_type="mission",
                    aggregate_id=f"m{i}", sequence=1,
                    occurred_at=f"2026-07-14T{i % 24:02d}:00:00Z",
                    payload={"missionType": "session_open_check"})
           for i in range(135)]
    crit = _ev(1, etype="forecast_issued", agg="forecast", agg_id="f1")
    all_keys = {e["idempotencyKey"] for e in evs} | {crit["idempotencyKey"]}
    keep, batches = rj.compact_events(events=evs + [crit],
                                      acked_keys=all_keys, now_iso=NOW)
    assert crit in keep                               # criticalは個別保持
    assert sum(b["count"] for b in batches) == 135 - 20   # 直近20件は保持
    assert all(b["eventType"] == "mission_recovered" for b in batches)
    assert batches[0]["groupingDimensions"]["session_open_check"] > 0
    assert batches[0]["firstOccurredAt"] <= batches[0]["lastOccurredAt"]


def test_critical_not_compacted_before_ack():
    crit = _ev(1, etype="forecast_issued", agg="forecast", agg_id="f1")
    keep, batches = rj.compact_events(events=[crit],
                                      acked_keys={crit["idempotencyKey"]},
                                      now_iso=NOW)
    assert keep == [crit] and batches == []
    routine = _ev(2, etype="mission_recovered", agg="mission", agg_id="m1")
    keep2, batches2 = rj.compact_events(events=[routine], acked_keys=set(),
                                        now_iso=NOW)
    assert keep2 == [routine] and batches2 == []      # 未ackはcompact不可


def test_compaction_total_preserved_and_idempotent():
    evs = [sj.event(event_type="mission_recovered", aggregate_type="mission",
                    aggregate_id=f"n{i}", sequence=1,
                    occurred_at="2026-07-14T01:00:00Z", payload={})
           for i in range(60)]
    keys = {e["idempotencyKey"] for e in evs}
    keep, b1 = rj.compact_events(events=evs, acked_keys=keys, now_iso=NOW)
    merged = rj.merge_compacted([], b1)
    merged2 = rj.merge_compacted(merged, b1)          # 再compactは冪等
    assert merged2 == merged
    counts = rj.compacted_type_counts(merged)
    assert counts["mission_recovered"] == 40          # 60-20(直近保持)
    # journal_summaryの歴代合計はcompact後もゼロ化しない
    s = rt.journal_summary(events=keep, total_observed=60,
                           acked_keys=keys, compacted_type_counts=counts,
                           now_iso=NOW)
    assert s["totalEventsObserved"] == 60
    assert s["compactedEventCount"] >= 40


def test_compacted_batches_survive_restart(monkeypatch, tmp_path):
    monkeypatch.setattr(scanner, "_OSINT_PERSIST_FILE",
                        str(tmp_path / "wal.json"))
    batch = {"batchId": "cb-test1", "eventType": "mission_recovered",
             "count": 12, "firstOccurredAt": NOW, "lastOccurredAt": NOW,
             "groupingDimensions": {}, "sourceEventHashRoot": "x",
             "compactedAt": NOW, "remoteAckStatus": "verified"}
    scanner._OPS_JOURNAL_COMPACT[:] = [batch]
    scanner._osint_persist()
    scanner._OPS_JOURNAL_COMPACT[:] = []
    monkeypatch.setitem(scanner._OSINT_PERSIST_STATE, "restored", False)
    scanner._osint_restore_once()
    assert any(b.get("batchId") == "cb-test1"
               for b in scanner._OPS_JOURNAL_COMPACT)
    scanner._OPS_JOURNAL_COMPACT[:] = []


# ── Phase 4/10: 実測SLOとbackend状態 ────────────────────────────────────────

def test_slo_measured_not_scheduled():
    s = rj.persistence_slo(target_interval_sec=1800,
                           last_snapshot_generated_at=None,
                           last_remote_commit_at=None,
                           last_verified_read_back_at=None, now_iso=NOW)
    assert s["status"] == "unknown"                   # スケジュールから捏造しない
    ok = rj.persistence_slo(target_interval_sec=1800,
                            last_snapshot_generated_at=NOW,
                            last_remote_commit_at=NOW,
                            last_verified_read_back_at="2026-07-15T11:50:00+09:00",
                            now_iso=NOW)
    assert ok["status"] == "healthy"
    late = rj.persistence_slo(target_interval_sec=1800,
                              last_snapshot_generated_at=None,
                              last_remote_commit_at=None,
                              last_verified_read_back_at="2026-07-15T09:00:00+09:00",
                              now_iso=NOW)
    assert late["status"] == "breached"               # 3h>30分×3


def test_backend_state_elapsed_not_calendar():
    # UTC日付跨ぎでも経過時間が短ければhealthy(暦日比較の廃止)
    b = rj.backend_state_v3(
        last_verified_read_back_at="2026-07-14T23:55:00Z",
        now_iso="2026-07-15T00:10:00Z")
    assert b["state"] == "healthy"
    d = rj.backend_state_v3(
        last_verified_read_back_at="2026-07-15T10:00:00+09:00",
        now_iso="2026-07-15T11:00:00+09:00")
    assert d["state"] == "delayed"
    assert rj.backend_state_v3(last_verified_read_back_at=None,
                               now_iso=NOW)["state"] == "unknown"
    assert rj.backend_state_v3(last_verified_read_back_at=None, now_iso=NOW,
                               legacy_remote=True)["state"] == \
        "legacy_no_remote_journal"
    assert rj.backend_state_v3(last_verified_read_back_at=None, now_iso=NOW,
                               unreachable=True)["state"] == "unavailable"


def test_stale_writer_guard_in_workflows():
    for wf in ("caos-scan.yml", "caos-watchtower.yml"):
        txt = open(os.path.join(ROOT, ".github", "workflows", wf),
                   encoding="utf-8").read()
        assert "stale-writer guard" in txt, wf
        assert "NEW_ASOF" in txt and "OLD_ASOF" in txt, wf


# ── Phase 5: FFLレシート配線 ─────────────────────────────────────────────────

def _live_forecast():
    fc = dl.forecast_record(symbol="6965", market="JP",
                            issued_at="2026-07-15T08:30:00+09:00",
                            horizon="next_session",
                            target_type="catalyst_verdict",
                            forecast_value="unknown",
                            research_mission_id="rm",
                            now_iso="2026-07-15T08:30:00+09:00")
    fc["origin"] = "forward_live"
    return fc


def test_ffl_receipt_wiring_end_to_end():
    scanner._FORECAST_LEDGER.clear()
    scanner._OPS_JOURNAL.clear()
    scanner._OPS_SEQ.clear()
    scanner._REMOTE_ACK.update({"ackedKeys": [],
                                "lastVerifiedRemoteAckAt": None,
                                "legacyRemote": False})
    fc = _live_forecast()
    scanner._FORECAST_LEDGER.append(fc)
    agg = f"6965:2026-07-15:{fc['targetType']}"
    scanner._journal("forecast_issued", "forecast", agg,
                     {"symbol": "6965"}, origin="forward_live")
    # ①ローカルのみ → locally_proven(レシートなし)
    assert scanner._ffl_receipts() == {}
    g1 = rd.first_forward_live_evidence(scanner._FORECAST_LEDGER,
                                        receipts=scanner._ffl_receipts(),
                                        now_iso=scanner._ai_now_iso())
    assert g1["state"] == "locally_proven"
    # ②snapshotに予測レコードだけあってもjournalイベントack無しでは不十分
    #   (read-backはjournalイベントの一致で判定)
    blob_no_event = {"schemaVersion": rj.SCHEMA_V3, "generatedAt": NOW,
                     "forecasts": [fc],
                     **rj.snapshot_journal_section(events=[], meta={},
                                                   now_iso=NOW)}
    scanner._remote_readback_ack(now_iso=NOW, blob=blob_no_event)
    assert scanner._ffl_receipts() == {}
    # ③本物のread-back ack → remotely_proven
    blob = _snapshot(list(scanner._OPS_JOURNAL))
    scanner._remote_readback_ack(now_iso=NOW, blob=blob)
    recs = scanner._ffl_receipts()
    assert recs.get(str(fc["id"])) == "remote_committed"
    g2 = rd.first_forward_live_evidence(scanner._FORECAST_LEDGER,
                                        receipts=recs,
                                        now_iso=scanner._ai_now_iso())
    assert g2["state"] == "remotely_proven"
    scanner._FORECAST_LEDGER.clear()
    scanner._OPS_JOURNAL.clear()
    scanner._REMOTE_ACK.update({"ackedKeys": [],
                                "lastVerifiedRemoteAckAt": None})


def test_ffl_fixture_replay_shadow_excluded():
    rows = [{"id": "r1", "origin": "historical_replay"},
            {"id": "s1", "origin": "shadow"},
            {"id": "x1", "origin": "fixture"}]
    g = rd.first_forward_live_evidence(rows, now_iso=NOW)
    assert g["state"] == "no_candidate"


# ── Phase 6: outcome origin継承 ──────────────────────────────────────────────

def test_outcome_inherits_each_origin():
    for org in ("forward_live", "historical_replay", "shadow", "fixture"):
        fc = _live_forecast()
        fc["origin"] = org
        oc = dl.outcome_record(forecast=fc,
                               outcome_as_of="2026-07-16T16:00:00+09:00",
                               start_price=100.0, end_price=101.0,
                               now_iso="2026-07-16T16:00:00+09:00")
        assert oc["origin"] == org, org
        assert oc["forecastIntegrityHash"] == fc["integrityHash"]
        assert oc["informationCutoffAt"] == fc["informationCutoffAt"]


def test_legacy_forecast_outcome_stays_unknown():
    oc = dl.outcome_record(forecast={"id": "old-1"},
                           outcome_as_of=NOW, start_price=100.0,
                           end_price=101.0, now_iso=NOW)
    assert oc["origin"] == "unknown_legacy"


def test_missing_price_unresolved_keeps_origin():
    fc = _live_forecast()
    oc = dl.outcome_record(forecast=fc, outcome_as_of=NOW,
                           start_price=None, end_price=None, now_iso=NOW)
    assert oc["status"] == "unresolved" and oc["origin"] == "forward_live"


def test_resolved_forward_live_now_score_eligible():
    fc = _live_forecast()
    oc = dl.outcome_record(forecast=fc,
                           outcome_as_of="2026-07-16T16:00:00+09:00",
                           start_price=100.0, end_price=103.0,
                           now_iso="2026-07-16T16:00:00+09:00")
    s = rd.decision_ledger_origin_summary([fc], [oc])
    assert s["forwardLive"]["scoreEligible"] == 1     # v12.2.9では恒久0だった


# ── Phase 7: Decision Scoring Readiness ─────────────────────────────────────

def test_scoring_readiness_four_zero_completed():
    fcs = []
    for i in range(4):
        fc = dl.forecast_record(symbol=f"696{i}", market="JP",
                                issued_at="2026-07-15T08:30:00+09:00",
                                horizon="next_session",
                                target_type="catalyst_verdict",
                                forecast_value="unknown",
                                now_iso="2026-07-15T08:30:00+09:00")
        fc["origin"] = "forward_live"
        fcs.append(fc)
    oc = dl.outcome_record(forecast=fcs[0], outcome_as_of=NOW,
                           start_price=None, end_price=None, now_iso=NOW)
    oc2 = dl.outcome_record(forecast=fcs[1], outcome_as_of=NOW,
                            start_price=None, end_price=None, now_iso=NOW)
    r = dl.decision_scoring_readiness(fcs, [oc, oc2])
    assert r["forwardLiveForecastsIssued"] == 4
    assert r["forecastEligibleForFutureScoring"] == 4
    assert r["pendingMaturity"] == 2
    assert r["maturedAwaitingResolution"] == 2        # 価格欠損=未解決
    assert r["completedScoreableSamples"] == 0
    assert "完了採点サンプル0件" in r["ownerReadableJa"]
    assert "将来採点に適格4件" in r["ownerReadableJa"]


def test_scoring_readiness_resolved_and_exclusions():
    fc = _live_forecast()
    replay = dl.forecast_record(symbol="7777", market="JP",
                                issued_at="2026-07-15T08:30:00+09:00",
                                horizon="next_session",
                                target_type="catalyst_verdict",
                                forecast_value="unknown",
                                now_iso="2026-07-15T08:30:00+09:00")
    replay["origin"] = "historical_replay"
    oc = dl.outcome_record(forecast=fc,
                           outcome_as_of="2026-07-16T16:00:00+09:00",
                           start_price=100.0, end_price=99.0,
                           now_iso="2026-07-16T16:00:00+09:00")
    r = dl.decision_scoring_readiness([fc, replay], [oc])
    assert r["completedScoreableSamples"] == 1
    assert r["excludedForecasts"] == 1                # replayは除外
    total = (r["pendingMaturity"] + r["maturedAwaitingResolution"]
             + r["completedScoreableSamples"])
    assert total == r["forwardLiveForecastsIssued"]   # 合計整合


# ── Phase 8: Research Claim Readiness ───────────────────────────────────────

def test_stable_ratio_but_evidence_blocked():
    r = rd.research_claim_readiness(
        stable_median_ratio=1.18, latest_run_ratio=1.25,
        statistical_confidence="high", run_count=10,
        evidence_gate_passed=False, holdout_passed=None,
        primary_source_gate_passed=False, canary_gate_passed=False,
        blockers_ja=["一次情報不足", "canary見逃し1件"])
    assert r["statisticalRatioMeasurable"] is True
    assert r["superiorityClaimAllowed"] is False
    assert r["twoXClaimAllowed"] is False
    assert "安定倍率を算出可能: 1.18x" in r["ownerReadableJa"]
    assert "Gemini優位性の正式認定: 不可" in r["ownerReadableJa"]
    assert "2x認定: 不可" in r["ownerReadableJa"]


def test_superiority_without_two_x():
    r = rd.research_claim_readiness(
        stable_median_ratio=1.4, latest_run_ratio=1.5,
        statistical_confidence="high", run_count=6,
        evidence_gate_passed=True, holdout_passed=True,
        primary_source_gate_passed=True, canary_gate_passed=True)
    assert r["superiorityClaimAllowed"] is True
    assert r["twoXClaimAllowed"] is False


def test_full_two_x_and_low_confidence_and_ratio_below_one():
    ok = rd.research_claim_readiness(
        stable_median_ratio=2.1, latest_run_ratio=2.0,
        statistical_confidence="high", run_count=8,
        evidence_gate_passed=True, holdout_passed=True,
        primary_source_gate_passed=True, canary_gate_passed=True)
    assert ok["twoXClaimAllowed"] is True
    low = rd.research_claim_readiness(
        stable_median_ratio=2.5, latest_run_ratio=2.5,
        statistical_confidence="low", run_count=8,
        evidence_gate_passed=True, holdout_passed=True,
        primary_source_gate_passed=True, canary_gate_passed=True)
    assert low["statisticalRatioMeasurable"] is False
    assert low["twoXClaimAllowed"] is False
    below = rd.research_claim_readiness(
        stable_median_ratio=0.9, latest_run_ratio=3.0,   # 生runは上書き不可
        statistical_confidence="high", run_count=8,
        evidence_gate_passed=True, holdout_passed=True,
        primary_source_gate_passed=True, canary_gate_passed=True)
    assert below["superiorityClaimAllowed"] is False


def test_holdout_not_run_blocks_claim():
    r = rd.research_claim_readiness(
        stable_median_ratio=1.5, latest_run_ratio=None,
        statistical_confidence="high", run_count=6,
        evidence_gate_passed=True, holdout_passed=None,
        primary_source_gate_passed=True, canary_gate_passed=True)
    assert r["holdoutStatus"] == "not_run"
    assert r["superiorityClaimAllowed"] is False


def test_ambiguous_phrase_removed():
    s = rd.research_measurement_summary(
        latest={"symbol": "X", "ratio": 1.25},
        stability={"runCount": 10, "medianRatio": 1.185,
                   "confidence": "high", "currentRatioEligible": True},
        unresolved_important=0, primary_strength=0,
        fresh_pending=0, canary_misses=1)
    assert "正式倍率認定" not in s["ownerReadableJa"]
    assert "安定倍率算出: 可" in s["ownerReadableJa"]
    assert "Gemini優位性の正式認定: 不可" in s["ownerReadableJa"]
    assert s["superiorityClaimAllowed"] is False


# ── Phase 9: smoke循環の解消(静的検査) ─────────────────────────────────────

def _wf(name):
    return open(os.path.join(ROOT, ".github", "workflows", name),
                encoding="utf-8").read()


def test_smoke_has_no_main_push_trigger():
    txt = _wf("smoke-test.yml")
    on_sec = txt.split("\non:", 1)[1].split("\njobs:", 1)[0]
    assert "push:" not in on_sec                      # 循環の根を断つ
    assert "schedule:" in on_sec and "workflow_dispatch:" in on_sec


def test_pre_deploy_checks_unchanged():
    ci = _wf("ci.yml")
    assert "backend-rules" in ci and "frontend" in ci
    gate = _wf("release-gate.yml")
    assert "push:" in gate or "pull_request:" in gate


def test_no_circular_dependency_static():
    txt = _wf("smoke-test.yml")
    assert "Wait for Render to deploy" not in txt     # デプロイ待ちループ撤去
    assert "循環" in txt                              # 対策理由が文書化されている


def test_dq_pipeline_reports_clear():
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/data-quality").get_json() or {}
    dp = d.get("deploymentPipeline") or {}
    assert dp.get("cycleStatus") == "clear"
    assert dp.get("preDeployRequiredChecks") == ["backend-rules",
                                                 "frontend", "gate"]


# ── Phase 12: DQ+公開境界 ───────────────────────────────────────────────────

def test_dq_v12_2_10_sections_and_no_leak():
    scanner._STARTUP.update({"state": "ready"})
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/data-quality").get_json() or {}
    rjt = d.get("remoteJournalTruth") or {}
    for k in ("localCommittedCount", "remotePendingCount",
              "remoteCommittedCount", "lossWindowClaimStatus", "slo",
              "lastVerifiedRemoteAckAt"):
        assert k in rjt, k
    jb = d.get("journalEventBreakdown") or {}
    for k in ("criticalByType", "nonCriticalByType", "compactedTotals",
              "criticalPending", "corruptCount"):
        assert k in jb, k
    assert "fflDurability" in d and "decisionScoringReadiness" in d
    assert "researchClaimReadiness" in d
    body = str(d)
    for banned in ("passphrase", "hmac", "OPENAI_API_KEY", "GEMINI_API_KEY",
                   "quantity", "avgCost", "acquisitionPrice",
                   "保有判断も24時間365日稼働中"):
        assert banned not in body, banned


def test_snapshot_v3_public_safe_and_carries_journal():
    with scanner.app.test_client() as c:
        snap = c.get("/api/argus/osint/memory-snapshot").get_json() or {}
    assert snap.get("schemaVersion") == "argus-durable-v3"
    for k in ("opsJournal", "opsJournalMeta", "soakLastPersistAt",
              "integrityManifest", "generatedAt", "buildIdentity",
              "durableState", "missionState", "forecastStore",
              "decisionLedger", "soak", "missions", "forecasts", "outcomes"):
        assert k in snap, k
    body = str(snap)
    for banned in ("passphrase", "hmac", "quantity", "avgCost",
                   "acquisitionPrice", "OPENAI_API_KEY"):
        assert banned not in body, banned


def test_scheduler_remote_ack_accepts_compact_state_hash_proof():
    event = _ev(7, agg_id="compact-proof")
    full = {**_snapshot([event]), "outcomes": [],
            "marketLedgerStateHash": rj._h({"placeholder": "unused"}),
            "chartIntelligenceStateHash": rj._h({"placeholder": "unused"})}
    # Use the real current state hashes; the compact receipt must verify them
    # without carrying either full state.
    full["marketLedgerStateHash"] = scanner.argus_market_ledger.state_hash(
        scanner._MARKET_LEDGER)
    full["chartIntelligenceStateHash"] = \
        scanner.argus_chart_intelligence.state_hash(scanner._CHART_INTELLIGENCE)
    full["todayIntelligenceStateHash"] = \
        scanner.argus_today_intelligence.state_hash(scanner._TODAY_INTELLIGENCE)
    full["marketReplayStateHash"] = \
        scanner.argus_market_replay.state_hash(scanner._MARKET_REPLAY)
    receipt = rj.compact_readback_snapshot(full)
    old_events = list(scanner._OPS_JOURNAL)
    old_cycle = dict(scanner._REMOTE_CYCLE)
    old_market_remote = dict(scanner._MARKET_LEDGER_REMOTE)
    old_chart_remote = dict(scanner._CHART_INTELLIGENCE_REMOTE)
    old_today_remote = dict(scanner._TODAY_INTELLIGENCE_REMOTE)
    old_replay_remote = dict(scanner._MARKET_REPLAY_REMOTE)
    try:
        scanner._OPS_JOURNAL[:] = [event]
        scanner._REMOTE_CYCLE.update({
            "expectedHash": receipt["integrityManifest"]["manifestHash"],
            "remoteCommitSha": "a" * 40,
            "readBackVerified": False})
        result = scanner._remote_readback_ack(now_iso=NOW, blob=receipt)
        assert result["verificationStatus"] == "verified"
        assert scanner._REMOTE_CYCLE["readBackVerified"] is True
        assert scanner._MARKET_LEDGER_REMOTE["verificationStatus"] == "verified"
        assert scanner._CHART_INTELLIGENCE_REMOTE["verificationStatus"] == "verified"
        assert scanner._TODAY_INTELLIGENCE_REMOTE["verificationStatus"] == "verified"
        assert scanner._MARKET_REPLAY_REMOTE["verificationStatus"] == "verified"
    finally:
        scanner._OPS_JOURNAL[:] = old_events
        scanner._REMOTE_CYCLE.clear()
        scanner._REMOTE_CYCLE.update(old_cycle)
        for target, old in (
                (scanner._MARKET_LEDGER_REMOTE, old_market_remote),
                (scanner._CHART_INTELLIGENCE_REMOTE, old_chart_remote),
                (scanner._TODAY_INTELLIGENCE_REMOTE, old_today_remote),
                (scanner._MARKET_REPLAY_REMOTE, old_replay_remote)):
            target.clear()
            target.update(old)


def test_workflows_build_compact_receipt_before_ledger_checkout():
    for name in ("caos-scan.yml", "caos-watchtower.yml"):
        workflow = _wf(name)
        build_at = workflow.index("scripts/build_remote_readback_receipt.py")
        checkout_at = workflow.index("git checkout -B ledger")
        assert build_at < checkout_at
        assert 'ledger/osint/readback.json' in workflow


def test_semantic_version_format():
    # v12.2.11(Today UI再構築)でbump — 恒久不変条件のみ:
    # セマンティック形式でありGit SHAをappVersionにしない。
    import re
    v = scanner._semantic_app_version()
    assert re.fullmatch(r"\d+\.\d+\.\d+", v), v


def test_version_consistency_dynamic():
    """版数の整合(動的 — 特定版数をハードコードしない):
    package.json = lock root = lock packages[""] = Guide先頭エントリ = runtime。"""
    import json as _j
    import re as _re
    pj = _j.load(open(os.path.join(ROOT, "web", "package.json")))["version"]
    lock = _j.load(open(os.path.join(ROOT, "web", "package-lock.json")))
    assert lock["version"] == pj
    assert lock["packages"][""]["version"] == pj
    guide = open(os.path.join(ROOT, "web", "src", "routes", "Guide.tsx"),
                 encoding="utf-8").read()
    m = _re.search(
        r"const RECENT_UPDATES: \[string, string\]\[\] = \[\s*\n\s*\['v([0-9.]+)'",
        guide)
    assert m, "RECENT_UPDATES先頭エントリが見つからない"
    assert m.group(1) == pj, (m.group(1), pj)
    assert scanner._semantic_app_version() == pj


def test_qualification_docs_exist():
    doc = open(os.path.join(ROOT, "docs", "ARGUS_V12_2_9_QUALIFICATION.md"),
               encoding="utf-8").read()
    assert "invalidated_by_remote_journal_loss" in doc
    assert "211bc9c" in doc and "notProfessionalRcEvidence: true" in doc
