"""ARGUS V11.6.0 — institutional-intel endpoints: public cached-only, secret-free,
asset filter, cause-attribution notes, handoff section, bridge status unaffected."""
import json

import scanner


class _Boom(BaseException):
    pass


def _no_fetch(monkeypatch):
    def boom(*a, **k):
        raise _Boom("no fetch/LLM on public GET")
    for name in ("_fetch_public_text", "_translate_headlines_ja", "_openai_prose",
                 "_openai_research", "_google_news_jp_rss", "_google_news_us_rss",
                 "_finnhub_catalyst", "get_tdnet_recent", "_probe_article",
                 "collect_institutional_intel"):
        if hasattr(scanner, name):
            monkeypatch.setattr(scanner, name, boom)


def _seed(monkeypatch):
    now = scanner._ai_now_iso()
    monkeypatch.setitem(scanner._NEWS_JA_STATE, "restored", True)
    monkeypatch.setattr(scanner, "_INTEL_STORE", [
        {"intelligenceId": "s1", "title": "Goldman upgrades NVDA price target",
         "publicSnippet": "", "institutionId": "goldman_sachs", "sourceId": "cnbc_public",
         "linkedAssets": ["NVDA"], "linkedThemes": [], "language": "en",
         "publishedAt": now, "fetchedAt": now, "canonicalUrl": "https://x/1",
         "sourceTier": "reputable"},
        {"intelligenceId": "s2", "title": "JPMorgan warns of AI bubble correction risk",
         "publicSnippet": "risk-off and ai capex caution", "institutionId": "jpmorgan",
         "sourceId": "reuters_jp", "linkedAssets": [], "linkedThemes": [], "language": "en",
         "publishedAt": now, "fetchedAt": now, "canonicalUrl": "https://x/2",
         "sourceTier": "wire"},
    ])


def test_cause_attribution_carries_institutional_notes(monkeypatch):
    _no_fetch(monkeypatch)
    _seed(monkeypatch)
    monkeypatch.setitem(scanner._MOVER_CAUSES_STATE, "restored", True)
    monkeypatch.setattr(scanner, "_MOVER_CAUSES", {})
    monkeypatch.setattr(scanner, "get_company_news", lambda *a, **k: [])
    # pre-existing catalysts path fans out to Finnhub/SEC — stub the snapshot
    monkeypatch.setattr(scanner, "get_catalysts_snapshot", lambda *a, **k: {"items": []})
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/cause-attribution?symbol=NVDA&market=US").get_json()
    sigs = d.get("institutionalSignals") or []
    assert sigs and sigs[0]["sourceName"] == "Goldman Sachs"
    assert len(sigs) <= 2


def test_pro_handoff_includes_summary(monkeypatch):
    _seed(monkeypatch)
    monkeypatch.setitem(scanner._PRO_HANDOFF_CACHE, "data", None)
    monkeypatch.setitem(scanner._PRO_HANDOFF_CACHE, "expires", 0.0)
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/pro-handoff").get_json()
    assert "Institutional Intelligence Summary" in d["promptText"]
    assert "自動売買の指示ではありません" in d["promptText"]


def test_bridge_status_unaffected(monkeypatch):
    """v11.6.0 must not disturb the bridge: segmented status + us_only semantics."""
    monkeypatch.setattr(scanner, "_ARGUS_ADMIN_TOKEN", "tok")
    hb = {"at": scanner._ai_now_iso(), "bridgeMode": "us_only", "openDStatus": "connected",
          "lastUSQuotePushAt": scanner._ai_now_iso(), "acceptedCountLastPush": 12,
          "usRealtimeStatus": "ok", "jpRealtimeStatus": "disabled",
          "jpFallbackActive": True, "diskUsagePct": 15.6, "intervalSec": 15}
    with scanner.app.test_client() as c:
        c.post("/api/argus/bridge/heartbeat", json={"heartbeat": hb},
               headers={"X-ARGUS-ADMIN-TOKEN": "tok"})
        d = c.get("/api/argus/bridge/status").get_json()
    assert d["bridgeMode"] == "us_only" and d["bridgeProcess"] == "ok"
    assert d["jpRealtimeStatus"] == "disabled" and d["jpFallbackActive"] is True
