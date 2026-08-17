"""ARGUS Event Intelligence durable store — Lean serialize/restore (v10.42).

Pure, stdlib-only. The 24/7 event state lives in Render process memory, so a
restart/deploy would erase active events + revisions + dossiers. This module is
the serialize/restore floor for the LEAN durable adapter: a GitHub Actions
workflow snapshots the live state to the `ledger` branch (events/snapshot.json),
and Render restores from it on boot (raw read — no secret, same pattern as the
AI-judgment / closepin ledgers). NO DynamoDB/SQS (that stays the enterprise
option); this is the right-sized personal-app store.

Durability is best-effort by design (snapshot granularity): events created and
lost between snapshots are not recovered — but they re-detect on the next push
and the notification already fired. The event HISTORY on the branch is durable
and auditable. A future DynamoDB adapter can implement the same interface.
"""
SNAPSHOT_SCHEMA = "event-store-v1"


def serialize_state(active_events, log_events, *, now_iso):
    """Build the durable snapshot dict from the in-memory state. active_events is
    the list of current envelopes (with any attached dossier); log_events is the
    recent history. Pure."""
    return {
        "schemaVersion": SNAPSHOT_SCHEMA,
        "snapshotAt": now_iso,
        "activeCount": len(active_events),
        "active": list(active_events),
        "log": list(log_events)[:200],
    }


def _expired(env, now_epoch, parse_iso):
    exp = env.get("expiresAt")
    if not exp:
        return False
    ts = parse_iso(exp)
    return ts is not None and ts < now_epoch


def restore_state(snapshot, now_epoch, parse_iso, dedup_key_of):
    """Rebuild (active_by_key, log) from a snapshot, dropping already-expired
    active events. Returns ({} , []) on a missing/malformed snapshot. Pure given
    the injected parse_iso (ISO→epoch|None) and dedup_key_of(env)→key helpers."""
    if not isinstance(snapshot, dict) or snapshot.get("schemaVersion") != SNAPSHOT_SCHEMA:
        return {}, []
    active = {}
    for env in snapshot.get("active") or []:
        if not isinstance(env, dict):
            continue
        if _expired(env, now_epoch, parse_iso):
            continue
        try:
            active[dedup_key_of(env)] = env
        except Exception:
            continue
    log = [e for e in (snapshot.get("log") or []) if isinstance(e, dict)][:200]
    return active, log
