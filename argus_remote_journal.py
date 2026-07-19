# -*- coding: utf-8 -*-
"""ARGUS Remote Journal Durability — v12.2.10(純・stdlibのみ)。

v12.2.9本番診断で確定した欠陥の是正:
A. 運用ジャーナルがリモートsnapshot(memory-snapshot→ledger)に含まれず、
   再起動でWAL 146件が消失した → argus-durable-v3でopsJournal同乗。
B. ack=復元時刻プロキシは両方向に不正確 → remote_committedは
   「リモートsnapshotのread-backで当該イベントの冪等キー+整合hashを検証」
   した場合のみ。復元時刻・生成時刻・HTTP成功だけではackにならない。
C. 損失窓の主張はスケジュール存在ではなく実測ラグ(SLO)から導出する。
"""
import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

SCHEMA_V3 = "argus-durable-v3"
JST = timezone(timedelta(hours=9))

# v12.2.10: criticalイベント分類(Phase 3 — soak_interruptedをcriticalへ)
CRITICAL_EVENT_TYPES = ("forecast_issued", "forecast_superseded",
                        "outcome_unresolved", "outcome_retry_scheduled",
                        "outcome_resolved", "outcome_expired", "incident_opened",
                        "incident_resolved", "soak_started",
                        "soak_interrupted", "soak_invalidated",
                        "soak_completed", "material_learning_approved",
                        "champion_promoted", "champion_rolled_back")
_PRIVATE_FIELDS = ("quantity", "avgCost", "acquisitionPrice", "pnl",
                   "fundValue", "passphrase", "hmac", "token", "apiKey",
                   "secret", "credential")


def _h(o: Any) -> str:
    return hashlib.sha256(json.dumps(o, sort_keys=True,
                                     ensure_ascii=False).encode()).hexdigest()[:16]


def _ep(iso: Optional[str]) -> Optional[float]:
    """naive時刻はJST解釈(マシンTZ非依存の決定論・v12.2.9の教訓)。"""
    if not iso:
        return None
    try:
        d = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=JST)
        return d.timestamp()
    except Exception:
        return None


def event_criticality(event_type: str) -> str:
    return "critical" if event_type in CRITICAL_EVENT_TYPES else "routine"


def _event_public_safe(ev: Dict[str, Any]) -> Optional[str]:
    """イベントが公開安全か。違反理由(redacted)を返す — Noneなら安全。"""
    if not isinstance(ev, dict):
        return "not_a_dict"
    flat = json.dumps(ev, ensure_ascii=False)
    for k in _PRIVATE_FIELDS:
        if f'"{k}"' in flat:
            return f"private_field:{k}"
    if ev.get("privacyClassification") not in (None, "public_safe"):
        return "not_public_safe"
    return None


def _verify_event(ev: Dict[str, Any]) -> bool:
    body = {k: v for k, v in ev.items() if k != "integrityHash"}
    return ev.get("integrityHash") == _h(body)


def outcome_read_back_receipt(*, remote_blob: Any,
                              local_outcomes: List[Dict[str, Any]],
                              read_back_at: str = "") -> Dict[str, Any]:
    """remote snapshot内のOutcome ID+integrity hash一致だけをackする。"""
    if not isinstance(remote_blob, dict):
        return {"verificationStatus": "invalid_remote",
                "ackedOutcomeIds": [], "readBackAt": read_back_at}
    remote = {str(o.get("id")): o for o in (remote_blob.get("outcomes") or [])
              if isinstance(o, dict) and o.get("id")}
    acked = []
    for local in (local_outcomes or []):
        oid = str(local.get("id") or "")
        other = remote.get(oid)
        local_hash = local.get("integrityHash")
        local_valid = local_hash and local_hash == _h({
            k: v for k, v in local.items() if k != "integrityHash"})
        remote_valid = other and other.get("integrityHash") == _h({
            k: v for k, v in other.items() if k != "integrityHash"})
        if oid and local_valid and remote_valid and \
                other.get("integrityHash") == local_hash:
            acked.append(oid)
    return {"verificationStatus": ("verified" if acked else "no_match"),
            "ackedOutcomeIds": acked, "readBackAt": read_back_at,
            "remoteGeneratedAt": remote_blob.get("generatedAt")
            or remote_blob.get("asOf")}


# ── Phase 1: Remote Snapshot Schema v3 ──────────────────────────────────────

def snapshot_journal_section(*, events: List[Dict[str, Any]],
                             meta: Dict[str, Any],
                             compacted: Optional[List[Dict[str, Any]]] = None,
                             now_iso: str = "") -> Dict[str, Any]:
    """リモートsnapshotへ同乗するジャーナル区画。イベントは検証済みの
    原文(WALと同一のhash対象)のみ — 1件の不正イベントが全体を落とさない。"""
    valid, rejected = [], []
    for ev in (events or []):
        reason = _event_public_safe(ev)
        if reason is None and not _verify_event(ev):
            reason = "integrity_hash_mismatch"
        if reason is None and not ev.get("idempotencyKey"):
            reason = "missing_idempotency_key"
        if reason:
            rejected.append(reason[:40])
        else:
            valid.append(ev)
    seq_by_agg: Dict[str, int] = {}
    crit_map: Dict[str, str] = {}
    for ev in valid:
        k = f"{ev.get('aggregateType')}:{ev.get('aggregateId')}"
        seq_by_agg[k] = max(seq_by_agg.get(k, 0), int(ev.get("sequence") or 0))
        crit_map[str(ev.get("eventId"))] = event_criticality(
            ev.get("eventType") or "")
    manifest = {
        "schemaVersion": SCHEMA_V3,
        "eventCount": len(valid),
        "eventIds": [str(e.get("eventId")) for e in valid],
        "idempotencyKeys": [str(e.get("idempotencyKey")) for e in valid],
        "eventHashes": {str(e.get("eventId")): e.get("integrityHash")
                        for e in valid},
        "highestSequenceByAggregate": seq_by_agg,
        "criticalityByEventId": crit_map,
        "compactedBatchCount": len(compacted or []),
        "rejectedCount": len(rejected),
        "rejectedReasonsRedacted": sorted(set(rejected))[:8],
        "generatedAt": now_iso,
    }
    manifest["manifestHash"] = _h({k: v for k, v in manifest.items()
                                   if k != "manifestHash"})
    return {"opsJournal": valid,
            "opsJournalMeta": dict(meta or {}),
            "opsJournalCompacted": list(compacted or []),
            "integrityManifest": manifest}


def parse_remote_snapshot(blob: Any) -> Dict[str, Any]:
    """リモートsnapshot(v2/v3)の読み取り。v2にはジャーナルが無い —
    legacy_no_remote_journalとして正直に報告(過去イベントを再構成しない)。"""
    if not isinstance(blob, dict):
        return {"status": "unreadable", "schemaVersion": None,
                "journalEvents": [], "manifest": None,
                "ownerReadableJa": "リモートsnapshotが読めない/破損"}
    sv = blob.get("schemaVersion")
    if "opsJournal" not in blob or "integrityManifest" not in blob:
        return {"status": "legacy_no_remote_journal", "schemaVersion": sv,
                "journalEvents": [], "manifest": None,
                "generatedAt": blob.get("generatedAt") or blob.get("asOf"),
                "ownerReadableJa": ("v2以前のsnapshot — リモートジャーナルなし"
                                    "(per-event ackは提供されない)")}
    manifest = blob.get("integrityManifest") or {}
    recomputed = _h({k: v for k, v in manifest.items() if k != "manifestHash"})
    if manifest.get("manifestHash") != recomputed:
        return {"status": "manifest_invalid", "schemaVersion": sv,
                "journalEvents": [], "manifest": manifest,
                "ownerReadableJa": "integrityManifest不一致 — ackに使わない"}
    return {"status": "ok", "schemaVersion": sv,
            "journalEvents": [e for e in (blob.get("opsJournal") or [])
                              if isinstance(e, dict)],
            "manifest": manifest,
            "generatedAt": blob.get("generatedAt") or blob.get("asOf"),
            "ownerReadableJa": "v3 snapshot読み取り成功"}


# ── Phase 2: Verified Read-Back Ack ─────────────────────────────────────────

ACK_STATUSES = ("verified", "hash_mismatch", "sequence_conflict",
                "missing_event", "unreadable", "legacy_snapshot")


def read_back_receipt(*, remote_blob: Any,
                      local_events: List[Dict[str, Any]],
                      remote_commit_sha: Optional[str] = None,
                      read_back_at: str = "") -> Dict[str, Any]:
    """検証済みread-back ack。remote_committedになれるのは
    「remoteに当該冪等キーが存在し、イベントhashが一致」した場合のみ。
    復元時刻・生成時刻・HTTP書込成功はackにならない。1件の不一致は
    そのイベントのみ非ack(他の正当なackを巻き添えにしない)。"""
    parsed = parse_remote_snapshot(remote_blob)
    base = {"remoteSnapshotId": None, "remoteCommitSha": remote_commit_sha,
            "remoteGeneratedAt": parsed.get("generatedAt"),
            "remoteReadBackAt": read_back_at,
            "remoteSchemaVersion": parsed.get("schemaVersion"),
            "includedEventIds": [], "includedIdempotencyKeys": [],
            "highestSequenceByAggregate": {}, "manifestHash": None,
            "ackedIdempotencyKeys": [], "mismatchedEventIds": [],
            "verificationStatus": None, "ownerReadableJa": ""}
    if parsed["status"] == "unreadable":
        return {**base, "verificationStatus": "unreadable",
                "ownerReadableJa": "リモート読み戻し不能 — ackなし"}
    if parsed["status"] == "legacy_no_remote_journal":
        return {**base, "verificationStatus": "legacy_snapshot",
                "ownerReadableJa": ("v2 snapshot — ジャーナル未同乗のため"
                                    "per-event ackは発生しない(偽ackなし)")}
    if parsed["status"] == "manifest_invalid":
        return {**base, "verificationStatus": "hash_mismatch",
                "ownerReadableJa": "manifest不一致 — ackなし"}
    man = parsed["manifest"] or {}
    remote_by_key = {str(e.get("idempotencyKey")): e
                     for e in parsed["journalEvents"]}
    acked, mismatched = [], []
    seq_conflict = False
    for ev in (local_events or []):
        key = str(ev.get("idempotencyKey"))
        rem = remote_by_key.get(key)
        if rem is None:
            continue                    # missing → pendingのまま(偽ackなし)
        if rem.get("integrityHash") != ev.get("integrityHash"):
            mismatched.append(str(ev.get("eventId")))
            continue
        if int(rem.get("sequence") or 0) != int(ev.get("sequence") or 0):
            seq_conflict = True
            mismatched.append(str(ev.get("eventId")))
            continue
        acked.append(key)
    local_keys = {str(e.get("idempotencyKey")) for e in (local_events or [])}
    status = ("sequence_conflict" if seq_conflict else
              "hash_mismatch" if mismatched else
              "verified" if acked or not local_keys else "missing_event")
    return {**base,
            "remoteSnapshotId": man.get("manifestHash"),
            "includedEventIds": man.get("eventIds") or [],
            "includedIdempotencyKeys": man.get("idempotencyKeys") or [],
            "highestSequenceByAggregate":
                man.get("highestSequenceByAggregate") or {},
            "manifestHash": man.get("manifestHash"),
            "ackedIdempotencyKeys": acked,
            "mismatchedEventIds": mismatched,
            "verificationStatus": status,
            "ownerReadableJa": (
                f"read-back検証: ack {len(acked)}件"
                + (f" / 不一致{len(mismatched)}件(非ack)" if mismatched else "")
                + (" / sequence競合あり" if seq_conflict else ""))}


LOSS_WINDOW_STATUSES = ("verified_within_target", "exceeded_target",
                        "not_measurable", "no_remote_journal")


def remote_durability_summary(*, local_events: List[Dict[str, Any]],
                              acked_keys, last_verified_ack_at: Optional[str],
                              now_iso: str,
                              target_interval_sec: int = 1800,
                              legacy_remote: bool = False,
                              failed_count: int = 0) -> Dict[str, Any]:
    """検証済みレシートのみからremote committed/pendingを導出。
    復元時刻プロキシは存在しない。"""
    ak = set(acked_keys or ())
    pend = [e for e in (local_events or [])
            if str(e.get("idempotencyKey")) not in ak]
    committed = len(local_events or []) - len(pend)
    pend_ts = [_ep(e.get("occurredAt")) for e in pend
               if _ep(e.get("occurredAt")) is not None]
    now_ep = _ep(now_iso)
    max_age = (round(now_ep - min(pend_ts)) if pend_ts and now_ep else None)
    if legacy_remote:
        claim = "no_remote_journal"
    elif last_verified_ack_at is None:
        claim = "not_measurable"
    elif max_age is None or max_age <= target_interval_sec:
        claim = "verified_within_target"
    else:
        claim = "exceeded_target"
    return {"localCommittedCount": len(local_events or []),
            "remotePendingCount": len(pend),
            "remoteCommittedCount": committed,
            "remoteFailedCount": int(failed_count),
            "oldestPendingAt": (min((e.get("occurredAt") for e in pend
                                     if e.get("occurredAt")), default=None)),
            "newestPendingAt": (max((e.get("occurredAt") for e in pend
                                     if e.get("occurredAt")), default=None)),
            "lastVerifiedRemoteAckAt": last_verified_ack_at,
            "maximumObservedPendingAgeSec": max_age,
            "lossWindowClaimStatus": claim,
            "ownerReadableJa": {
                "verified_within_target":
                    f"検証済みリモート永続 — 未ack最大{max_age or 0}秒"
                    f"(目標{target_interval_sec}秒内)",
                "exceeded_target":
                    f"未ackイベントが目標{target_interval_sec}秒を超過"
                    f"({max_age}秒) — ≦30分主張は現在成立しない",
                "not_measurable":
                    "検証済みread-backが未実施 — 損失窓は測定不能(主張しない)",
                "no_remote_journal":
                    "リモートジャーナル未同乗(v2) — 損失窓保証なし(正直表示)",
            }[claim]}


# ── Phase 3: 非critical大量イベントの決定論compaction ────────────────────────

def compact_events(*, events: List[Dict[str, Any]], acked_keys,
                   now_iso: str, keep_recent: int = 20
                   ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """非critical・ack済みイベントをtype毎に決定論バッチへ。criticalは
    検証済みリモートack前に絶対compactしない。総数はメタで保持(ゼロ化禁止)。"""
    ak = set(acked_keys or ())
    keep, groups = [], {}
    routine_acked = [e for e in (events or [])
                     if event_criticality(e.get("eventType") or "") == "routine"
                     and str(e.get("idempotencyKey")) in ak]
    tail_ids = {id(e) for e in routine_acked[-keep_recent:]}
    for ev in (events or []):
        et = ev.get("eventType") or ""
        if event_criticality(et) == "critical" \
                or str(ev.get("idempotencyKey")) not in ak \
                or id(ev) in tail_ids:
            keep.append(ev)
            continue
        groups.setdefault(et, []).append(ev)
    batches = []
    for et, evs in sorted(groups.items()):
        dims: Dict[str, int] = {}
        for e in evs:
            mt = (e.get("publicSafePayload") or {}).get("missionType") \
                or e.get("aggregateType") or "unknown"
            dims[mt] = dims.get(mt, 0) + 1
        batch = {"eventType": et, "count": len(evs),
                 "firstOccurredAt": min((e.get("occurredAt") or ""
                                         for e in evs)),
                 "lastOccurredAt": max((e.get("occurredAt") or ""
                                        for e in evs)),
                 "firstAggregateId": evs[0].get("aggregateId"),
                 "lastAggregateId": evs[-1].get("aggregateId"),
                 "groupingDimensions": dims,
                 "sourceEventHashRoot": _h(
                     [e.get("integrityHash") for e in evs]),
                 "compactedAt": now_iso,
                 "remoteAckStatus": "verified"}
        batch["batchId"] = f"cb-{_h(batch)}"
        batches.append(batch)
    return keep, batches


def merge_compacted(existing: List[Dict[str, Any]],
                    new_batches: List[Dict[str, Any]],
                    max_len: int = 40) -> List[Dict[str, Any]]:
    """バッチの冪等マージ(同一batchIdは1回)。"""
    have = {b.get("batchId") for b in (existing or [])}
    out = list(existing or [])
    for b in (new_batches or []):
        if b.get("batchId") not in have:
            out.append(b)
            have.add(b.get("batchId"))
    return out[-max_len:]


def compacted_type_counts(batches: List[Dict[str, Any]]) -> Dict[str, int]:
    c: Dict[str, int] = {}
    for b in (batches or []):
        et = b.get("eventType") or "unknown"
        c[et] = c.get(et, 0) + int(b.get("count") or 0)
    return c


# ── Phase 4/10: 実測SLOとbackend状態(暦日比較の廃止) ────────────────────────

BACKEND_STATES_V3 = ("healthy", "delayed", "breached", "unavailable",
                     "legacy_no_remote_journal", "unknown")


def persistence_slo(*, target_interval_sec: int,
                    last_snapshot_generated_at: Optional[str],
                    last_remote_commit_at: Optional[str],
                    last_verified_read_back_at: Optional[str],
                    now_iso: str,
                    max_observed_lag_sec: Optional[int] = None,
                    consecutive_missed: int = 0) -> Dict[str, Any]:
    """スケジュールの存在は実行の証明ではない — 実測タイムスタンプのみで判定。"""
    now_ep = _ep(now_iso)
    basis = last_verified_read_back_at or last_remote_commit_at \
        or last_snapshot_generated_at
    lag = (round(now_ep - _ep(basis)) if basis and now_ep and _ep(basis)
           else None)
    if lag is None:
        st = "unknown"
    elif lag <= target_interval_sec:
        st = "healthy"
    elif lag <= target_interval_sec * 3:
        st = "delayed"
    else:
        st = "breached"
    mx = max(int(max_observed_lag_sec or 0), lag or 0) or None
    return {"targetIntervalSec": int(target_interval_sec),
            "lastSnapshotGeneratedAt": last_snapshot_generated_at,
            "lastRemoteCommitAt": last_remote_commit_at,
            "lastVerifiedReadBackAt": last_verified_read_back_at,
            "currentLagSec": lag,
            "maximumObservedLagSec": mx,
            "consecutiveMissedIntervals": int(consecutive_missed),
            "status": st,
            "ownerReadableJa": {
                "healthy": f"実測ラグ{lag}秒 — 目標{target_interval_sec}秒内",
                "delayed": f"実測ラグ{lag}秒 — 目標超過(遅延)",
                "breached": f"実測ラグ{lag}秒 — 目標の3倍超(breached)",
                "unknown": "実測証拠なし — unknown(スケジュールから捏造しない)",
            }[st]}


def backend_state_v3(*, last_verified_read_back_at: Optional[str],
                     now_iso: str, target_interval_sec: int = 1800,
                     legacy_remote: bool = False,
                     unreachable: bool = False) -> Dict[str, Any]:
    """UTC暦日比較を廃止 — 経過時間/SLOのみでbackend状態を導出。"""
    if unreachable:
        st = "unavailable"
    elif legacy_remote:
        st = "legacy_no_remote_journal"
    else:
        ep_ack, ep_now = _ep(last_verified_read_back_at), _ep(now_iso)
        if ep_ack is None or ep_now is None:
            st = "unknown"
        else:
            lag = ep_now - ep_ack
            st = ("healthy" if lag <= target_interval_sec else
                  "delayed" if lag <= target_interval_sec * 3 else "breached")
    return {"backendType": "github_ledger_readback", "state": st,
            "lastVerifiedReadBackAt": last_verified_read_back_at,
            "guaranteeJa": ("損失窓は実測SLOのみで主張(スケジュール存在・"
                            "暦日跨ぎでは判定しない・60秒保証は主張しない)"),
            "ownerReadableJa": {
                "healthy": "検証済みread-backが目標間隔内",
                "delayed": "read-back遅延(目標超過)",
                "breached": "read-back途絶(目標の3倍超)",
                "unavailable": "リモート到達不能",
                "legacy_no_remote_journal": "v2 snapshot — ジャーナル未同乗",
                "unknown": "検証済みread-back未実施 — unknown",
            }[st]}
