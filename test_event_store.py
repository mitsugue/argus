"""Unit tests for the Lean durable event store (argus_event_store.py)."""
import argus_event_store as st


def _parse(iso):
    # tiny ISO→epoch for tests (UTC 'YYYY-MM-DDTHH:MM:SSZ')
    import datetime
    try:
        return datetime.datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=datetime.timezone.utc).timestamp()
    except Exception:
        return None


def _key(env):
    return f"{env['market']}:{env['symbol']}:{env['eventType']}"


def _env(sym, et="LIMIT_UP", expires="2099-01-01T00:00:00Z"):
    return {"market": "JP", "symbol": sym, "eventType": et, "severity": 5,
            "eventId": f"e-{sym}", "expiresAt": expires}


def test_serialize_round_trips():
    active = [_env("9999"), _env("8888")]
    snap = st.serialize_state(active, active, now_iso="2026-06-22T01:00:00Z")
    assert snap["schemaVersion"] == "event-store-v1" and snap["activeCount"] == 2
    rest, log = st.restore_state(snap, _parse("2026-06-22T02:00:00Z"), _parse, _key)
    assert set(rest.keys()) == {"JP:9999:LIMIT_UP", "JP:8888:LIMIT_UP"}
    assert len(log) == 2


def test_restore_drops_expired():
    active = [_env("9999", expires="2000-01-01T00:00:00Z"),   # expired
              _env("8888", expires="2099-01-01T00:00:00Z")]   # live
    snap = st.serialize_state(active, [], now_iso="2026-06-22T01:00:00Z")
    rest, _ = st.restore_state(snap, _parse("2026-06-22T02:00:00Z"), _parse, _key)
    assert list(rest.keys()) == ["JP:8888:LIMIT_UP"]          # expired dropped on restore


def test_restore_rejects_malformed():
    assert st.restore_state(None, 0, _parse, _key) == ({}, [])
    assert st.restore_state({"schemaVersion": "wrong"}, 0, _parse, _key) == ({}, [])
    assert st.restore_state({"schemaVersion": "event-store-v1", "active": "bad"}, 0, _parse, _key) == ({}, [])


def test_restart_recovery_simulation():
    # state before "restart"
    active = [_env("9999"), _env("8888")]
    snap = st.serialize_state(active, active, now_iso="2026-06-22T01:00:00Z")
    # ...process dies, snapshot persisted to branch, new process restores it
    rest, log = st.restore_state(snap, _parse("2026-06-22T01:05:00Z"), _parse, _key)
    assert len(rest) == 2 and len(log) == 2                   # events survived the restart
