"""ARGUS V11.1 — official J-Quants TDnet Add-on (pure) + provider diagnostics.

No network / no keys: pure classification + Flask-client shape/gating checks.
"""
import json
import argus_jquants_tdnet as T
import argus_tdnet
import scanner


# ── status vocabulary ────────────────────────────────────────────────────────
def test_status_from_http_vocabulary():
    assert T.status_from_http(200, has_rows=True) == "official_tdnet_live"
    assert T.status_from_http(200, has_rows=False) == "live"
    assert T.status_from_http(401) == "entitlement_missing"
    assert T.status_from_http(403) == "entitlement_missing"
    assert T.status_from_http(404) == "endpoint_not_found"
    assert T.status_from_http(429) == "rate_limited"
    assert T.status_from_http(500) == "unavailable"


# ── normalize + material ─────────────────────────────────────────────────────
def test_normalize_row_maps_and_classifies():
    row = {"Code": "80580", "CompanyName": "三菱商事", "Title": "業績予想の修正（下方修正）に関するお知らせ",
           "PubDate": "2026-07-01T15:00", "DocumentID": "D1"}
    it = T.normalize_row(row, argus_tdnet.classify_disclosure)
    assert it["symbol"] == "8058"                     # 5-digit → 4-digit
    assert it["category"] == "guidance_down" and it["material"] is True
    assert it["official"] is True and it["provider"] == "jquants-tdnet"


def test_material_disclosure_is_official_catalyst():
    it = T.normalize_row({"Code": "8058", "Title": "配当予想の修正（減配）"}, argus_tdnet.classify_disclosure)
    conf = T.event_confirmation(it)
    assert conf["corroborationLevel"] == "official"
    assert conf["triggerRole"] == "official_catalyst"


def test_non_material_disclosure_is_official_fact_not_cause():
    it = T.normalize_row({"Code": "8058", "Title": "月次売上高に関するお知らせ"}, argus_tdnet.classify_disclosure)
    conf = T.event_confirmation(it)
    assert conf["triggerRole"] == "official_fact"
    assert conf["triggerRole"] != "confirmed_cause"


def test_material_after_move_is_not_immediate_trigger():
    it = T.normalize_row({"Code": "8058", "Title": "特別損失の計上", "PubDate": "2026-07-01T15:00"},
                         argus_tdnet.classify_disclosure)
    conf = T.event_confirmation(it, move_started_at="2026-07-01T09:30")
    assert conf["triggerRole"] == "background_confirmation"   # post-move → never immediate


# ── official-first / yanoshin-fallback separation ────────────────────────────
def test_tdnet_recent_falls_back_to_yanoshin_without_key(monkeypatch):
    # no key → official not_configured → yanoshin fallback, clearly distinguishable
    monkeypatch.setattr(scanner, "_JQUANTS_API_KEY", None)
    scanner._TDNET_OFFICIAL_CACHE["data"] = None
    d = scanner.get_tdnet_recent(5)
    assert d.get("provider") == "yanoshin-tdnet" and d.get("official") is False
    assert d.get("officialStatus") == "not_configured"


# ── provider diagnostics ─────────────────────────────────────────────────────
def test_public_diagnostics_shape_and_no_admin_detail():
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/provider-diagnostics/public").get_json()
    assert d["schemaVersion"] == "provider-diagnostics-public-v1"
    for p in d["providers"]:
        assert set(p) == {"provider", "configured", "status"}   # no httpStatus/sampleCount/messages
    assert {"jquants-core", "jquants-tdnet", "edinet", "twelvedata-quote"} <= {p["provider"] for p in d["providers"]}


def test_admin_diagnostics_requires_token():
    with scanner.app.test_client() as c:
        r = c.get("/api/argus/admin/provider-diagnostics")
    assert r.status_code in (401, 503)          # never an open 200


def test_diagnostics_never_leak_secrets():
    full = scanner._provider_diagnostics()
    blob = json.dumps(full)
    for bad in ("apikey=", "api_key=", "token=", "Subscription-Key", "x-api-key", "Bearer "):
        assert bad not in blob, bad
