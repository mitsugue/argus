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
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

SCHEMA_V3 = "argus-durable-v3"
READBACK_RECEIPT_SCHEMA = "argus-remote-readback-v1"
JST = timezone(timedelta(hours=9))
_BUILD_SHA_RE = re.compile(r"(?:[0-9a-f]{7}|[0-9a-f]{40})")
_APP_VERSION_RE = re.compile(
    r"[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?")
_MAX_COMPACT_OUTCOMES = 200
MAX_COMPACT_JOURNAL_EVENTS = 400
# One finite serialized authority for every compact readback producer,
# publication validator, workflow transport and backend restore consumer.
#
# The encrypted plaintext contains the compact readback and the same journal /
# outcome projections again in ``targets``.  Reserve 1 MiB for every remaining
# bounded target and Recovery metadata, then divide the rest of the 4 MiB
# plaintext budget by that exact duplication factor.  Keep the derivation here
# because the ledger-branch publisher deliberately copies this standalone
# producer/validator module after switching away from the source branch.
COMPACT_READBACK_RECOVERY_PLAINTEXT_BYTES = 4 * 1024 * 1024
COMPACT_READBACK_NON_DUPLICATED_RESERVE_BYTES = 1 * 1024 * 1024
COMPACT_READBACK_DUPLICATION_FACTOR = 2
MAX_COMPACT_READBACK_BYTES = (
    COMPACT_READBACK_RECOVERY_PLAINTEXT_BYTES
    - COMPACT_READBACK_NON_DUPLICATED_RESERVE_BYTES
) // COMPACT_READBACK_DUPLICATION_FACTOR
MAX_COMPACT_JSON_NODES = 80_000
MAX_COMPACT_JSON_DEPTH = 32
MAX_COMPACT_STRING_CHARS = 1024 * 1024
COMPACT_READBACK_FIELDS = frozenset({
    "receiptSchemaVersion", "schemaVersion", "generatedAt", "asOf",
    "buildIdentity", "opsJournal", "integrityManifest", "outcomes",
    "missionTickDurability", "marketLedgerStateHash",
    "chartIntelligenceStateHash", "todayIntelligenceStateHash",
    "marketReplayStateHash", "receiptHash",
})
OPS_SEQUENCE_BY_AGGREGATE_LIMIT = 4096
OPS_SEQUENCE_HIGH_WATER_FIELD = "sequenceAllocatorHighWater"

# v12.2.10: criticalイベント分類(Phase 3 — soak_interruptedをcriticalへ)
CRITICAL_EVENT_TYPES = ("forecast_issued", "forecast_superseded",
                        "outcome_unresolved", "outcome_retry_scheduled",
                        "outcome_resolved", "outcome_expired", "incident_opened",
                        "incident_resolved", "soak_started",
                        "soak_interrupted", "soak_invalidated",
                        "soak_completed", "material_learning_approved",
                        "champion_promoted", "champion_rolled_back",
                        "research_benchmark_completed",
                        "research_benchmark_failed")
_PRIVATE_FIELDS = ("quantity", "avgCost", "acquisitionPrice", "pnl",
                   "fundValue", "passphrase", "hmac", "token", "apiKey",
                   "secret", "credential")


def _h(o: Any) -> str:
    return hashlib.sha256(json.dumps(o, sort_keys=True,
                                     ensure_ascii=False).encode()).hexdigest()[:16]


def compact_readback_serialized_size(value: Any) -> int:
    """Return exact canonical UTF-8 bytes, or -1 for invalid JSON."""
    try:
        return len(json.dumps(
            value, sort_keys=True, ensure_ascii=False,
            separators=(",", ":"), allow_nan=False).encode("utf-8"))
    except (RecursionError, TypeError, ValueError):
        return -1


def compact_readback_within_size_contract(value: Any) -> bool:
    size = compact_readback_serialized_size(value)
    return 0 < size <= MAX_COMPACT_READBACK_BYTES


def _compact_json_tree_within_contract(value: Any) -> bool:
    """Bound parsed hostile state before recursive semantic validation."""
    nodes = 0
    pending = [(value, 0)]
    while pending:
        current, depth = pending.pop()
        nodes += 1
        if nodes > MAX_COMPACT_JSON_NODES or depth > MAX_COMPACT_JSON_DEPTH:
            return False
        if isinstance(current, str):
            if len(current) > MAX_COMPACT_STRING_CHARS:
                return False
        elif isinstance(current, dict):
            for key, item in current.items():
                if not isinstance(key, str) or len(key) > 256:
                    return False
                pending.append((item, depth + 1))
        elif isinstance(current, list):
            pending.extend((item, depth + 1) for item in current)
        elif current is None or isinstance(current, (bool, int)):
            continue
        elif isinstance(current, float):
            if current != current or current in (float("inf"), float("-inf")):
                return False
        else:
            return False
    return True


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


def bounded_sequence_allocator_state(*, sequences: Any, events: Any,
                                     meta: Any
                                     ) -> Tuple[Dict[str, int], Dict[str, Any]]:
    """Return the complete bounded allocator state for encrypted recovery.

    Historic per-aggregate counters can grow without bound even though the
    public journal retains at most 400 events.  The high-water scalar records
    the greatest sequence ever allocated, so an aggregate evicted from this
    bounded map can safely reappear at ``highWater + 1`` without reusing an
    idempotency key.  Every aggregate still present in the live journal is
    retained; the remainder are selected deterministically.

    This helper is deliberately pure.  Legacy deployments do not call it, so
    the keys-unset checkpoint contract remains unchanged.
    """
    if not isinstance(sequences, dict) or not isinstance(events, list) or \
            not isinstance(meta, dict):
        raise ValueError("ops_sequence_allocator_invalid")

    normalized: Dict[str, int] = {}
    for key, value in sequences.items():
        if not isinstance(key, str) or not key or len(key) > 256 or \
                isinstance(value, bool) or not isinstance(value, int) or \
                value <= 0:
            raise ValueError("ops_sequence_allocator_invalid")
        normalized[key] = value

    stored_high_water = meta.get(OPS_SEQUENCE_HIGH_WATER_FIELD, 0)
    if isinstance(stored_high_water, bool) or not isinstance(
            stored_high_water, int) or stored_high_water < 0:
        raise ValueError("ops_sequence_allocator_invalid")

    live: Dict[str, int] = {}
    for event in events:
        if not isinstance(event, dict):
            raise ValueError("ops_sequence_allocator_invalid")
        aggregate_type = event.get("aggregateType")
        aggregate_id = event.get("aggregateId")
        sequence = event.get("sequence")
        if not isinstance(aggregate_type, str) or not aggregate_type or \
                not isinstance(aggregate_id, str) or not aggregate_id or \
                isinstance(sequence, bool) or not isinstance(sequence, int) or \
                sequence <= 0:
            raise ValueError("ops_sequence_allocator_invalid")
        key = f"{aggregate_type}:{aggregate_id}"
        if len(key) > 256:
            raise ValueError("ops_sequence_allocator_invalid")
        live[key] = max(live.get(key, 0), sequence)

    high_water = max(
        [stored_high_water] + list(normalized.values()) + list(live.values()))
    for key, value in live.items():
        normalized[key] = max(normalized.get(key, 0), value)

    if len(live) > OPS_SEQUENCE_BY_AGGREGATE_LIMIT:
        raise ValueError("ops_sequence_allocator_live_set_oversized")
    retained = set(live)
    remaining = OPS_SEQUENCE_BY_AGGREGATE_LIMIT - len(retained)
    candidates = sorted(
        ((key, value) for key, value in normalized.items()
         if key not in retained),
        key=lambda item: (-item[1], item[0]))
    retained.update(key for key, _value in candidates[:remaining])
    bounded = {key: normalized[key] for key in sorted(retained)}
    bounded_meta = dict(meta)
    bounded_meta[OPS_SEQUENCE_HIGH_WATER_FIELD] = high_water
    return bounded, bounded_meta


def next_bounded_ops_sequence(*, aggregate_key: Any, sequences: Any,
                              meta: Any) -> int:
    """Return the next sequence without mutating bounded allocator state.

    A retained aggregate continues its own sequence.  An aggregate absent
    from the bounded map (including an identifier reused after eviction and
    restart) advances from the authenticated global high-water value instead.
    """
    if not isinstance(aggregate_key, str) or not aggregate_key or \
            len(aggregate_key) > 256 or not isinstance(sequences, dict) or \
            not isinstance(meta, dict):
        raise ValueError("ops_sequence_allocator_invalid")
    high_water = meta.get(OPS_SEQUENCE_HIGH_WATER_FIELD)
    if isinstance(high_water, bool) or not isinstance(high_water, int) or \
            high_water < 0:
        raise ValueError("ops_sequence_allocator_invalid")
    previous = sequences.get(aggregate_key)
    if previous is None:
        return high_water + 1
    if isinstance(previous, bool) or not isinstance(previous, int) or \
            previous <= 0:
        raise ValueError("ops_sequence_allocator_invalid")
    return previous + 1


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


def verify_exact_journal_manifest(
        blob: Any, *, require_no_rejections: bool = False) -> bool:
    """Verify that ``opsJournal`` and its signed manifest are exactly paired.

    ``parse_remote_snapshot`` deliberately preserves the historical full
    snapshot compatibility contract: old snapshots can contain a valid
    manifest that reports rejected source rows.  New direct read-back and
    recovery projections have a stronger contract.  Every exported event must
    be public-safe and individually valid, identifiers must be unique, and all
    manifest projections must exactly equal the ordered journal projection.
    """
    if not isinstance(blob, dict) or blob.get("schemaVersion") != SCHEMA_V3:
        return False
    events = blob.get("opsJournal")
    manifest = blob.get("integrityManifest")
    if not isinstance(events, list) or len(events) > \
            MAX_COMPACT_JOURNAL_EVENTS or not isinstance(manifest, dict):
        return False
    if manifest.get("schemaVersion") != SCHEMA_V3:
        return False
    generated_at = str(blob.get("generatedAt") or blob.get("asOf") or "")
    if not generated_at or manifest.get("generatedAt") != generated_at:
        return False
    if manifest.get("manifestHash") != _h({
            key: value for key, value in manifest.items()
            if key != "manifestHash"}):
        return False

    event_ids: List[str] = []
    idempotency_keys: List[str] = []
    event_hashes: Dict[str, str] = {}
    highest: Dict[str, int] = {}
    criticality: Dict[str, str] = {}
    for event in events:
        if _event_public_safe(event) is not None or not _verify_event(event):
            return False
        event_id = event.get("eventId")
        idempotency_key = event.get("idempotencyKey")
        sequence = event.get("sequence")
        if not isinstance(event_id, str) or not event_id or \
                not isinstance(idempotency_key, str) or not idempotency_key or \
                isinstance(sequence, bool) or not isinstance(sequence, int) or \
                sequence <= 0:
            return False
        if event_id in event_hashes or idempotency_key in idempotency_keys:
            return False
        aggregate = f"{event.get('aggregateType')}:{event.get('aggregateId')}"
        event_ids.append(event_id)
        idempotency_keys.append(idempotency_key)
        event_hashes[event_id] = str(event.get("integrityHash") or "")
        highest[aggregate] = max(highest.get(aggregate, 0), sequence)
        criticality[event_id] = event_criticality(
            str(event.get("eventType") or ""))

    expected = {
        "eventCount": len(events),
        "eventIds": event_ids,
        "idempotencyKeys": idempotency_keys,
        "eventHashes": event_hashes,
        "highestSequenceByAggregate": highest,
        "criticalityByEventId": criticality,
    }
    if any(manifest.get(key) != value for key, value in expected.items()):
        return False
    compacted_count = manifest.get("compactedBatchCount")
    rejected_count = manifest.get("rejectedCount")
    if isinstance(compacted_count, bool) or not isinstance(
            compacted_count, int) or compacted_count < 0:
        return False
    if isinstance(rejected_count, bool) or not isinstance(
            rejected_count, int) or rejected_count < 0:
        return False
    if require_no_rejections and (rejected_count != 0 or
                                  manifest.get("rejectedReasonsRedacted") not in
                                  ([], None)):
        return False
    return True


def verify_compact_wal_projection(blob: Any) -> bool:
    """Validate exact, positive WAL scalars carried by a compact source proof."""
    if not isinstance(blob, dict):
        return False
    durability = blob.get("missionTickDurability")
    if not isinstance(durability, dict):
        return False
    local = durability.get("walAppliedSequence")
    exported = durability.get("remoteWalAppliedSequence")
    verified = durability.get("verifiedWalSequence")
    if any(isinstance(value, bool) or not isinstance(value, int)
           for value in (local, exported, verified)):
        return False
    return bool(local > 0 and exported == local and
                0 <= verified <= exported)


def verify_compact_public_projection(blob: Any) -> bool:
    """Validate bounded build/outcome fields outside the journal manifest."""
    if not isinstance(blob, dict):
        return False
    build = blob.get("buildIdentity")
    if not isinstance(build, dict) or not _APP_VERSION_RE.fullmatch(
            str(build.get("appVersion") or "")) or not \
            _BUILD_SHA_RE.fullmatch(str(build.get("buildSha") or "").lower()):
        return False
    outcomes = blob.get("outcomes")
    if not isinstance(outcomes, list) or len(outcomes) > _MAX_COMPACT_OUTCOMES:
        return False
    for outcome in outcomes:
        if not isinstance(outcome, dict) or _event_public_safe(outcome) is not None:
            return False
        integrity_hash = outcome.get("integrityHash")
        if not isinstance(integrity_hash, str) or integrity_hash != _h({
                key: value for key, value in outcome.items()
                if key != "integrityHash"}):
            return False
    for key in (
            "marketLedgerStateHash", "chartIntelligenceStateHash",
            "todayIntelligenceStateHash", "marketReplayStateHash"):
        if not isinstance(blob.get(key), str) or not re_full_hash(
                str(blob.get(key))):
            return False
    return True


def re_full_hash(value: str) -> bool:
    """Accept the existing bounded state-hash width without exporting content."""
    return bool(re.fullmatch(r"[0-9a-f]{16,64}", value.lower()))


def compact_readback_snapshot(blob: Any) -> Dict[str, Any]:
    """Build the bounded proof used by scheduler read-back.

    The durable snapshot can contain years of Market Ledger observations.  A
    scheduled heartbeat must not download that payload just to verify the WAL,
    outcomes, and state hashes.  This proof preserves the original signed
    journal records and integrity manifest; no event or hash is synthesized.
    """
    parsed = parse_remote_snapshot(blob)
    if parsed.get("status") != "ok":
        raise ValueError("remote_snapshot_not_verifiable")
    return build_compact_readback_snapshot(
        schema_version=blob.get("schemaVersion"),
        generated_at=blob.get("generatedAt"), as_of=blob.get("asOf"),
        build_identity=blob.get("buildIdentity"),
        ops_journal=blob.get("opsJournal"),
        integrity_manifest=blob.get("integrityManifest"),
        outcomes=blob.get("outcomes"),
        mission_tick_durability=blob.get("missionTickDurability"),
        market_ledger_state_hash=blob.get("marketLedgerStateHash"),
        chart_intelligence_state_hash=blob.get(
            "chartIntelligenceStateHash"),
        today_intelligence_state_hash=blob.get("todayIntelligenceStateHash"),
        market_replay_state_hash=blob.get("marketReplayStateHash"),
    )


def build_compact_readback_snapshot(
        *, schema_version: Any, generated_at: Any, as_of: Any,
        build_identity: Any, ops_journal: Any, integrity_manifest: Any,
        outcomes: Any, mission_tick_durability: Any,
        market_ledger_state_hash: Any,
        chart_intelligence_state_hash: Any,
        today_intelligence_state_hash: Any,
        market_replay_state_hash: Any) -> Dict[str, Any]:
    """Build the bounded proof directly from explicit public projections."""
    receipt = {
        "receiptSchemaVersion": READBACK_RECEIPT_SCHEMA,
        "schemaVersion": schema_version,
        "generatedAt": generated_at or as_of,
        "asOf": as_of or generated_at,
        "buildIdentity": dict(build_identity or {}),
        "opsJournal": list(ops_journal or []),
        "integrityManifest": dict(integrity_manifest or {}),
        "outcomes": list(outcomes or []),
        "missionTickDurability": dict(mission_tick_durability or {}),
        "marketLedgerStateHash": market_ledger_state_hash,
        "chartIntelligenceStateHash": chart_intelligence_state_hash,
        "todayIntelligenceStateHash": today_intelligence_state_hash,
        "marketReplayStateHash": market_replay_state_hash,
    }
    if parse_remote_snapshot(receipt).get("status") != "ok" or not \
            verify_exact_journal_manifest(
                receipt, require_no_rejections=True) or not \
            verify_compact_wal_projection(receipt) or not \
            verify_compact_public_projection(receipt):
        raise ValueError("remote_snapshot_not_verifiable")
    receipt["receiptHash"] = _h(receipt)
    if not compact_readback_within_size_contract(receipt):
        raise ValueError("remote_readback_oversized")
    return receipt


def verify_compact_readback_snapshot(blob: Any) -> bool:
    if not isinstance(blob, dict) or set(blob) != COMPACT_READBACK_FIELDS or \
            not compact_readback_within_size_contract(blob) or not \
            _compact_json_tree_within_contract(blob) or \
            blob.get("receiptSchemaVersion") != READBACK_RECEIPT_SCHEMA:
        return False
    expected = blob.get("receiptHash")
    body = {key: value for key, value in blob.items() if key != "receiptHash"}
    return bool(expected and expected == _h(body) and
                parse_remote_snapshot(blob).get("status") == "ok" and
                verify_exact_journal_manifest(
                    blob, require_no_rejections=True) and
                verify_compact_wal_projection(blob) and
                verify_compact_public_projection(blob))


def verify_strict_compact_readback_snapshot(blob: Any) -> bool:
    """Named recovery-v1 verifier; currently identical to the strict gate.

    Recovery callers use this explicit entry point so the historical compact
    receipt API can retain its separate compatibility contract without ever
    weakening encrypted recovery validation.
    """
    return verify_compact_readback_snapshot(blob)


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
