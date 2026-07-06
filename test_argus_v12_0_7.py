"""ARGUS V12.0.7 — 最終監査P1クローズアウトの恒久ガード。

①missed GET=公開は集計のみ(オーナー自由記述の非公開) ②/api/state=公開redacted
(ログ本文・sentinel・執行系enumゼロ)+admin full ③runtime-manifestのJP文言
(bridge稼働≠JPリアルタイム) ④JSF鮮度スタンプのパース可能化 ⑤日付不明の古い
機関記事のすり抜け防止 ⑥FE: 安全優先展開effect/二重ボタン抑止/STALE_DAYS同期。
"""
import json
import os

import argus_data_quality as dq
import scanner

WEB = os.path.join(os.path.dirname(__file__), "web", "src")


def _read(*parts):
    return open(os.path.join(WEB, *parts), encoding="utf-8").read()


# ── ① missed エンドポイント施錠 ─────────────────────────────────────────────

def _seed_missed(monkeypatch):
    monkeypatch.setattr(scanner, "_MISSED_INTEL", [
        {"title": "some article title", "url": "https://x/1", "symbol": "6146",
         "whyJa": "保有中の銘柄に効くはずの記事を見逃した(オーナー自由記述)",
         "diagnosis": {"likelyCause": "source_not_registered"}},
    ])


def test_missed_public_is_aggregate_only(monkeypatch):
    _seed_missed(monkeypatch)
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/institutional-intelligence/missed").get_json()
    assert d["count"] == 1
    assert d["byCause"] == {"source_not_registered": 1}
    assert "items" not in d                       # 公開に本文なし
    blob = json.dumps(d, ensure_ascii=False)
    for banned in ("whyJa", "オーナー自由記述", "some article title", "https://x/1", "6146"):
        assert banned not in blob, banned
    assert d["itemsAccess"] == "admin_only"


def test_missed_admin_gets_items(monkeypatch):
    _seed_missed(monkeypatch)
    monkeypatch.setattr(scanner, "_ARGUS_ADMIN_TOKEN", "test-admin-token-1234")
    with scanner.app.test_client() as c:
        pub = c.get("/api/argus/institutional-intelligence/missed").get_json()
        adm = c.get("/api/argus/institutional-intelligence/missed",
                    headers={"X-ARGUS-ADMIN-TOKEN": "test-admin-token-1234"}).get_json()
    assert "items" not in pub
    assert len(adm.get("items") or []) == 1       # adminは従来どおり詳細を読める
    assert adm["items"][0]["whyJa"].startswith("保有中")


# ── ② /api/state redact ────────────────────────────────────────────────────

def test_api_state_public_is_redacted(monkeypatch):
    # 危機日を再現: sentinelとログが載っていても公開応答には出ない
    monkeypatch.setattr(scanner, "load_state", lambda: {
        "phase": 3, "log": ["secret-ish log line", "moomoo: 10.0.0.1:11111"],
        "sentinel": {"action": "SELL_ALL", "reason": "crisis"},
    })
    with scanner.app.test_client() as c:
        r = c.get("/api/state")
        assert r.status_code == 200
        d = r.get_json()
    assert d["publicRedacted"] is True
    blob = json.dumps(d, ensure_ascii=False)
    assert "SELL_ALL" not in blob
    assert "sentinel" not in blob
    assert "secret-ish log line" not in blob
    assert "10.0.0.1" not in blob
    assert d["phase"] == 3                        # ランディングの進捗表示は生きる
    # 執行語ゼロ(RCと同じ検査)
    for w in ("今すぐ買", "成行", "全力買い", "place order"):
        assert w not in blob, w


def test_api_state_admin_gets_full(monkeypatch):
    monkeypatch.setattr(scanner, "load_state", lambda: {
        "phase": 3, "log": ["line-a"], "sentinel": {"action": "NONE"}})
    monkeypatch.setattr(scanner, "_ARGUS_ADMIN_TOKEN", "test-admin-token-1234")
    with scanner.app.test_client() as c:
        d = c.get("/api/state",
                  headers={"X-ARGUS-ADMIN-TOKEN": "test-admin-token-1234"}).get_json()
    assert "sentinel" in d and isinstance(d.get("log"), list)
    assert d.get("publicRedacted") is not True


# ── ③ runtime-manifest JP文言 ───────────────────────────────────────────────

def test_runtime_manifest_no_jp_live_implication():
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/runtime-manifest").get_json()
    lims = " | ".join(d.get("currentLimitations") or [])
    assert "then realtime" not in lims            # 旧文言の復活防止
    assert "UNAVAILABLE" in lims
    assert "confirmed by support" in lims
    assert "does NOT mean JP realtime" in lims
    assert "ret=0" in lims and "OpenD restart" in lims
    assert "US-only" in lims


# ── ④ JSF鮮度スタンプ(スラッシュ日付の正規化) ────────────────────────────────

def test_jsf_slash_date_normalizes_and_parses():
    assert dq._parse_iso("2026/07/03T16:00:00+09:00") is None      # 旧形式は読めない(前提)
    assert dq._parse_iso("2026-07-03T16:00:00+09:00") is not None  # 正規化後は読める


def test_jsf_freshness_measured_when_table_warm(monkeypatch):
    from datetime import datetime, timedelta
    import pytz
    recent = (datetime.now(pytz.timezone("Asia/Tokyo")) - timedelta(days=1)).strftime("%Y/%m/%d")
    monkeypatch.setitem(scanner._JSF_CACHE, "date", recent)
    monkeypatch.setitem(scanner._JSF_CACHE, "table", {"6146": {"loan": 1, "short": 1}})
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/data-quality").get_json()
    row = [r for r in d["sourceHealth"] if r["sourceName"] == "jsf-daily-balance"][0]
    assert "-" in (row["lastSuccessAt"] or "")     # ハイフン正規化済み
    assert row["freshnessBucket"] in ("fresh", "recent")   # 実測でunknownを脱する
    # 日付が無ければ従来どおりunknown(捏造しない)
    monkeypatch.setitem(scanner._JSF_CACHE, "date", None)
    with scanner.app.test_client() as c:
        d2 = c.get("/api/argus/data-quality").get_json()
    row2 = [r for r in d2["sourceHealth"] if r["sourceName"] == "jsf-daily-balance"][0]
    assert row2["lastSuccessAt"] is None
    assert row2["freshnessBucket"] == "unknown"


# ── ⑤ 日付不明の古い機関記事のすり抜け防止 ──────────────────────────────────

def test_intel_undated_item_excluded_from_current_view(monkeypatch):
    now_iso = scanner._ai_now_iso()
    monkeypatch.setitem(scanner._NEWS_JA_STATE, "restored", True)
    monkeypatch.setattr(scanner, "_INTEL_STORE", [
        {"intelligenceId": "u1", "title": "Undated old analyst note",
         "publicSnippet": "", "institutionId": None, "sourceId": "x",
         "linkedAssets": ["7011"], "linkedThemes": [], "language": "en",
         "publishedAt": None, "fetchedAt": None,        # 日付が全く取れない記事
         "canonicalUrl": "https://x/u", "sourceTier": "wire",
         "accessClass": "PUBLIC_METADATA"},
        {"intelligenceId": "f1", "title": "再報道された新しい記事(日本語)",
         "publicSnippet": "", "institutionId": None, "sourceId": "nhk",
         "linkedAssets": ["7011"], "linkedThemes": [], "language": "ja",
         "publishedAt": now_iso, "fetchedAt": now_iso,  # freshな再報道は通る
         "canonicalUrl": "https://x/f", "sourceTier": "wire",
         "accessClass": "PUBLIC_METADATA"},
    ])
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/events/7011/institutional-intelligence").get_json()
    titles = [it["title"] for it in d["items"]]
    assert "Undated old analyst note" not in titles
    assert "再報道された新しい記事(日本語)" in titles
    assert d["omittedOldCount"] == 1


def test_intel_publishedat_missing_falls_back_to_detected(monkeypatch):
    now_iso = scanner._ai_now_iso()
    monkeypatch.setitem(scanner._NEWS_JA_STATE, "restored", True)
    monkeypatch.setattr(scanner, "_INTEL_STORE", [
        {"intelligenceId": "d1", "title": "publishedAt無しだがfetchedAtは新しい",
         "publicSnippet": "", "institutionId": None, "sourceId": "x",
         "linkedAssets": ["7011"], "linkedThemes": [], "language": "ja",
         "publishedAt": None, "fetchedAt": now_iso,
         "canonicalUrl": "https://x/d", "sourceTier": "wire",
         "accessClass": "PUBLIC_METADATA"},
    ])
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/events/7011/institutional-intelligence").get_json()
    assert d["count"] == 1                         # fallback時刻がfreshなら表示


# ── ⑥ FEソース検査 — 安全優先展開/二重ボタン抑止/閾値同期 ────────────────────

def test_fe_collapsible_risk_escalation_effect():
    src = _read("components", "common", "CollapsibleSection.tsx")
    assert "React.useEffect" in src
    assert "if (defaultOpen) setOpenRaw(true);" in src
    # effectはdefaultOpenの変化に反応する(依存配列)
    assert "[defaultOpen]" in src
    # リスク展開は記憶を書き換えない(setOpenRaw直呼び — writeCollapseStateを通らない)
    idx = src.index("if (defaultOpen) setOpenRaw(true);")
    assert "writeCollapseState" not in src[idx - 80:idx + 80]


def test_fe_no_duplicate_investigate_button_in_card():
    card = _read("components", "dashboard", "UnifiedAssetCard.tsx")
    assert "hideInvestigateButton" in card          # カードは抑止フラグを渡す
    csc = _read("components", "dashboard", "CauseStackCard.tsx")
    assert "hideInvestigateButton" in csc
    assert "二重" in csc or "duplicate" in csc.lower()


def test_fire_core_stale_days_synced_at_ten():
    py = open("argus_fire_core.py", encoding="utf-8").read()
    ts = _read("lib", "fireCore.ts")
    assert "STALE_DAYS = 10" in py
    assert "STALE_DAYS = 10;" in ts


def test_handoff_marked_deprecated():
    src = open("HANDOFF.md", encoding="utf-8").read()
    assert "DEPRECATED" in src.splitlines()[0] or "旧版" in src.splitlines()[0]
    assert "bridge/README.md" in src[:1200]        # 現行一次情報への誘導
