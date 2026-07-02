"""ARGUS V11.3.1 — durable Official Event store tests.

Deterministic serialization; merge by officialEventId never loses reaction windows;
older snapshots can't wipe newer progress; snapshots carry no full text / secrets /
private portfolio; restore round-trips; endpoints are safe + admin-gated.
"""
import json
import argus_official_event_store as ST
import argus_official_event_lifecycle as OL
import scanner

NOW = "2026-07-02T12:00:00Z"
ITEM = {"code": "8058", "name": "三菱商事", "title": "業績予想の修正（下方修正）に関するお知らせ",
        "time": "2026-07-02T08:00", "category": "guidance_down", "categoryJa": "業績下方修正",
        "sentiment": "negative", "material": True, "official": True, "provider": "jquants-tdnet"}


def base_record():
    return OL.from_disclosure(ITEM, first_seen_at=NOW)


# ── serialization ────────────────────────────────────────────────────────────
def test_snapshot_serialization_deterministic():
    recs = [base_record(), OL.from_disclosure({**ITEM, "code": "7012", "title": "増資"},
                                              first_seen_at=NOW)]
    a = ST.serialize_snapshot(recs, as_of=NOW, date_jst="2026-07-02")
    b = ST.serialize_snapshot(list(reversed(recs)), as_of=NOW, date_jst="2026-07-02")
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)   # order-independent
    assert a["schemaVersion"] == "official-event-ledger-v1"
    assert a["summary"]["total"] == 2 and a["summary"]["material"] == 2


def test_snapshot_contains_no_forbidden_fields():
    dirty = {**base_record(), "fullText": "秘密の本文", "pdf": "bytes", "holdings": 100,
             "pnl": -5, "costBasis": 4000, "apiKey": "sk-xxx", "headers": {"x-api-key": "k"}}
    snap = ST.serialize_snapshot([dirty], as_of=NOW, date_jst="2026-07-02")
    blob = json.dumps(snap, ensure_ascii=False).lower()
    for bad in ("fulltext", "pdf", "holdings", "pnl", "costbasis", "apikey", "x-api-key", "sk-xxx"):
        assert bad not in blob, bad


# ── merge policy ─────────────────────────────────────────────────────────────
def test_merge_updates_reaction_without_duplicating():
    r = base_record()
    reacted = OL.apply_market_reaction(
        r, OL.build_market_reaction(window="same_day", observed_at=NOW, price_move_pct=-4.0))
    reacted["updatedAt"] = "2026-07-02T13:00:00Z"
    store = ST.merge_records({}, [r], now_iso=NOW)
    store = ST.merge_records(store, [reacted], now_iso="2026-07-02T13:00:00Z")
    assert len(store) == 1                                       # dedup by id
    m = store[r["officialEventId"]]
    assert m["marketReaction"]["sameDay"]["priceMovePct"] == -4.0
    assert m["causeStatus"] == "confirmed_cause"


def test_older_snapshot_cannot_wipe_newer_windows():
    r = base_record()
    newer = OL.apply_market_reaction(
        r, OL.build_market_reaction(window="same_day", observed_at="2026-07-02T15:00:00Z",
                                    price_move_pct=-4.0))
    newer["updatedAt"] = "2026-07-02T15:00:00Z"
    older = dict(base_record())                                  # no reactions, older
    older["updatedAt"] = "2026-07-02T09:00:00Z"
    store = ST.merge_records({newer["officialEventId"]: newer}, [older],
                             now_iso="2026-07-02T16:00:00Z")
    m = store[newer["officialEventId"]]
    assert m["marketReaction"]["sameDay"], "older empty snapshot wiped the newer reaction!"
    assert m["lifecycleStage"] == newer["lifecycleStage"]        # stage never regresses


def test_restore_round_trip():
    recs = [base_record()]
    snap = ST.serialize_snapshot(recs, as_of=NOW, date_jst="2026-07-02")
    back = ST.restore_from_snapshot(snap)
    assert recs[0]["officialEventId"] in back
    assert back[recs[0]["officialEventId"]]["title"] == recs[0]["title"]
    assert ST.restore_from_snapshot(None) == {}                  # junk-tolerant


# ── endpoints ────────────────────────────────────────────────────────────────
def test_durability_endpoint_safe_shape(monkeypatch):
    # ledger meta read stubbed (no network in tests)
    monkeypatch.setattr(scanner, "_official_ledger_latest_cached",
                        lambda: {"configured": True, "reachable": False,
                                 "latestLedgerDate": None, "latestCount": 0, "lastPersistAt": None})
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/official-events/durability").get_json()
    assert d["schemaVersion"] == "official-event-durability-v1"
    s = d["safety"]
    assert s["publicGetFetchesProvider"] is False
    assert s["storesFullText"] is False and s["storesPrivatePortfolio"] is False


def test_snapshot_endpoint_store_only(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("FORBIDDEN provider fetch from snapshot GET")
    for name in ("_jquants_tdnet_fetch", "_get_tdnet_yanoshin", "get_tdnet_recent",
                 "_fetch_public_text", "_openai_judge", "_gemini_check"):
        monkeypatch.setattr(scanner, name, boom)
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/official-events/snapshot").get_json()
    assert d["schemaVersion"] == "official-event-ledger-v1"


def test_admin_snapshot_restore_require_token():
    with scanner.app.test_client() as c:
        r1 = c.post("/api/argus/admin/official-events/snapshot")
        r2 = c.post("/api/argus/admin/official-events/restore")
    assert r1.status_code in (401, 503) and r2.status_code in (401, 503)
