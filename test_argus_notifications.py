"""V11.14.0 Notification engine — pure-module tests (noise control is the product)."""
import argus_notifications as nt

NOW = "2026-07-06T10:00:00+09:00"


def _ap(sym="TSLA", rank="P0", held=True, cat="held_risk", name="Tesla"):
    return {"symbol": sym, "market": "US", "assetName": name, "priorityRank": rank,
            "isHeld": held, "category": cat, "ownerReadableWhyJa": "リスク重複",
            "checkNextJa": "原因確認", "whatWouldChangeJa": "圧力解消で解除"}


# ── triggers (diff-based; steady state never fires) ─────────────────────────
def test_p0_fires_on_new_only():
    cur = {"apItems": [_ap()]}
    evs = nt.generate({}, cur, NOW)
    assert any(e["eventType"] == "p0_priority" and e["severity"] == "critical" for e in evs)
    again = nt.generate(cur, cur, NOW)                  # unchanged → no re-fire
    assert not any(e["eventType"] == "p0_priority" for e in again)


def test_p1_held_and_watch_only_not_fired():
    evs = nt.generate({}, {"apItems": [_ap(rank="P1", held=True, cat="supply_demand_watch")]}, NOW)
    assert any(e["eventType"] == "p1_held_priority" for e in evs)
    evs2 = nt.generate({}, {"apItems": [_ap(rank="P1", held=False, cat="supply_demand_watch")]}, NOW)
    assert not any(e["eventType"] == "p1_held_priority" for e in evs2)


def test_ignore_never_notifies():
    evs = nt.generate({}, {"apItems": [_ap(rank="Ignore", cat="no_action")]}, NOW)
    assert evs == []


def test_event_before_and_flow_and_sd_transitions():
    prev = {"eventNames": [], "flowBySymbol": {"5803": {"flowClass": "neutral"}},
            "sdBySymbol": {"9984": {"rank": "C", "condition": "neutral"}}}
    cur = {"eventNames": ["PCE"],
           "flowBySymbol": {"5803": {"flowClass": "distribution", "isHeld": True,
                                     "name": "フジクラ"}},
           "sdBySymbol": {"9984": {"rank": "D", "condition": "credit_overhang",
                                   "name": "ソフトバンクグループ", "isHeld": True}}}
    evs = nt.generate(prev, cur, NOW)
    types = {e["eventType"] for e in evs}
    assert "event_before" in types
    fl = next(e for e in evs if e["eventType"] == "flow_deterioration")
    assert fl["severity"] == "high" and "5803 フジクラ" in fl["titleJa"]
    sdev = next(e for e in evs if e["eventType"] == "supply_demand_deterioration")
    assert sdev["severity"] == "high" and "戻り売り" in sdev["bodyJa"]


def test_sd_improvement_while_heavy_is_honest_and_low():
    prev = {"sdBySymbol": {"5803": {"rank": "C", "condition": "improving_but_heavy"}}}
    cur = {"sdBySymbol": {"5803": {"rank": "B", "condition": "improving_but_heavy",
                                   "level": "very_heavy", "name": "フジクラ"}}}
    evs = nt.generate(prev, cur, NOW)
    ev = next(e for e in evs if e["eventType"] == "supply_demand_improvement")
    assert ev["severity"] == "low"
    assert "まだ重い" in ev["bodyJa"]
    assert "需給良好" not in ev["bodyJa"] and "需給良好" not in ev["titleJa"]


def test_brief_ready_and_backup_warnings():
    evs = nt.generate({"briefSession": "morning"},
                      {"briefSession": "weekend", "hasHoldings": True,
                       "snapshotAgeDays": None, "vaultConfigured": False}, NOW)
    types = {e["eventType"] for e in evs}
    assert "session_brief_ready" in types
    assert "snapshot_missing" in types and "sync_backup_warning" in types


# ── noise control ───────────────────────────────────────────────────────────
def test_cooldown_and_daily_caps_and_dedupe():
    ev = nt.generate({}, {"apItems": [_ap()]}, NOW)
    r1 = nt.apply_noise_control(ev, {}, NOW)
    assert len(r1["deliver"]) == 1
    # same dedupe within cooldown → suppressed
    r2 = nt.apply_noise_control(ev, r1["state"], "2026-07-06T10:30:00+09:00")
    assert r2["deliver"] == [] and r2["suppressed"] == 1


def test_quiet_hours_only_critical():
    night = "2026-07-06T23:30:00+09:00"
    evs = nt.generate({}, {"apItems": [_ap()],
                           "eventNames": ["CPI"]}, night)
    r = nt.apply_noise_control(evs, {}, night)
    assert all(e["severity"] == "critical" for e in r["deliver"])
    assert r["suppressed"] >= 1


def test_weekend_calm():
    evs = nt.generate({}, {"eventNames": ["AUCTION"],
                           "apItems": [_ap(rank="P2", held=False, cat="avoid_chase")]}, NOW)
    r = nt.apply_noise_control(evs, {}, NOW, weekend=True)
    assert all(nt._SEV_ORDER[e["severity"]] <= nt._SEV_ORDER["high"]
               or e["eventType"] in ("snapshot_missing", "sync_backup_warning",
                                     "session_brief_ready")
               for e in r["deliver"])


def test_global_daily_cap():
    many = []
    for i in range(20):
        many += nt.generate({}, {"eventNames": [f"EV{i}"]}, NOW)
    r = nt.apply_noise_control(many, {}, NOW)
    assert len(r["deliver"]) <= nt.GLOBAL_MAX_PER_DAY


# ── digest / status / compliance ────────────────────────────────────────────
def test_digest_and_public_status_redacted():
    evs = nt.generate({}, {"apItems": [_ap()]}, NOW)
    d = nt.digest(evs, NOW, suppressed=3)
    assert d["unreadCount"] == len(evs) and d["criticalCount"] >= 1
    st = nt.public_status(now_iso=NOW, sources={"actionPriority": True})
    assert st["serverStoresNotifications"] is False
    assert st["publicLeakSafe"] is True
    assert st["deliveryChannelsDisabled"] == ["browser_push", "email", "webhook"]
    blob = str(st)
    for banned in ("quantity", "averageCost", "ownerAction", "weightPct"):
        assert banned not in blob


def test_no_trading_and_pure():
    src = open("argus_notifications.py", encoding="utf-8").read()
    for banned in ("place_order", "order(", "broker_login", "trd_env", "unlock_trade",
                   "今すぐ買", "全力"):
        assert banned not in src, banned
    for banned_import in ("import requests", "import urllib", "import socket"):
        assert banned_import not in src, banned_import
    for e in nt.generate({}, {"apItems": [_ap()]}, NOW):
        assert "売買指示ではない" in e["complianceNote"]
