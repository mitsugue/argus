"""ARGUS V12.0.6 — 安定化ハウスキーピング+オーナー報告3件の恒久ガード。

①機関ビュー: 英語見出しを主表示にしない(displayTitleJa必須)+古い記事(>14日)は
  カードの「現在の動き」文脈から除外 ②需給: ?symbols=でデバイスのウォッチリスト
  銘柄も判定(検証・上限・非漏洩) ③DQ: 機関シグナル鮮度は実測のみ(捏造なし)
④FE: 折りたたみ記憶/FIRE Core文言/即時調査ボタン露出/Pack caveat重複なし。
"""
import json
import os
import time

import argus_news_i18n
import scanner

WEB = os.path.join(os.path.dirname(__file__), "web", "src")


def _read(*parts):
    return open(os.path.join(WEB, *parts), encoding="utf-8").read()


def _seed_intel(monkeypatch, now_iso):
    monkeypatch.setitem(scanner._NEWS_JA_STATE, "restored", True)
    monkeypatch.setattr(scanner, "_INTEL_STORE", [
        {"intelligenceId": "i1",
         "title": "Moody's places all of MegaCorp ratings on review for a downgrade",
         "publicSnippet": "", "institutionId": None, "sourceId": "reuters_jp",
         "linkedAssets": ["7011"], "linkedThemes": [], "language": "en",
         "publishedAt": now_iso, "fetchedAt": now_iso,
         "canonicalUrl": "https://x/1", "sourceTier": "wire",
         "accessClass": "PUBLIC_METADATA"},
        {"intelligenceId": "i2",
         "title": "Old analyst action from two years ago",
         "publicSnippet": "", "institutionId": None, "sourceId": "reuters_jp",
         "linkedAssets": ["7011"], "linkedThemes": [], "language": "en",
         "publishedAt": "2024-09-13T17:02:00Z", "fetchedAt": "2024-09-13T17:02:00Z",
         "canonicalUrl": "https://x/2", "sourceTier": "wire",
         "accessClass": "PUBLIC_METADATA"},
        {"intelligenceId": "i3",
         "title": "中国海軍が発射実験に成功と報道",
         "publicSnippet": "", "institutionId": None, "sourceId": "nhk",
         "linkedAssets": ["7011"], "linkedThemes": [], "language": "ja",
         "publishedAt": now_iso, "fetchedAt": now_iso,
         "canonicalUrl": "https://x/3", "sourceTier": "wire",
         "accessClass": "PUBLIC_METADATA"},
    ])


# ── ① 機関ビュー: 日本語優先+鮮度除外 ──────────────────────────────────────

def test_intel_view_never_shows_raw_english_as_primary(monkeypatch):
    now_iso = scanner._ai_now_iso()
    _seed_intel(monkeypatch, now_iso)
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/events/7011/institutional-intelligence").get_json()
    assert d["count"] == 2                      # 2024年の記事は除外
    assert d["omittedOldCount"] == 1
    for it in d["items"]:
        disp = it["displayTitleJa"] or ""
        assert disp, "displayTitleJa must always exist"
        # 主表示が原文英語そのままになっていない(V11.5.1規律)
        if it["translationStatus"] == "pending":
            assert "翻訳待ち" in disp or "翻訳未取得" in disp
            assert disp != it["title"]
    ja = [it for it in d["items"] if it["translationStatus"] == "not_needed"]
    assert ja and ja[0]["displayTitleJa"] == "中国海軍が発射実験に成功と報道"


def test_intel_view_uses_translation_cache(monkeypatch):
    now_iso = scanner._ai_now_iso()
    _seed_intel(monkeypatch, now_iso)
    title = "Moody's places all of MegaCorp ratings on review for a downgrade"
    monkeypatch.setitem(scanner._NEWS_JA_CACHE, argus_news_i18n.text_hash(title),
                        {"ja": "ムーディーズ、メガコープの全格付けを格下げ方向で見直し", "at": now_iso})
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/events/7011/institutional-intelligence").get_json()
    hit = [it for it in d["items"] if it["title"] == title]
    assert hit and hit[0]["displayTitleJa"].startswith("ムーディーズ")
    assert hit[0]["translationStatus"] == "translated"


def test_intel_view_old_item_never_relabelled_as_current(monkeypatch):
    now_iso = scanner._ai_now_iso()
    _seed_intel(monkeypatch, now_iso)
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/events/7011/institutional-intelligence").get_json()
    blob = json.dumps(d, ensure_ascii=False)
    assert "Old analyst action" not in blob
    assert "14日より古い記事" in (d.get("freshnessNoteJa") or "")


# ── ② 需給 ?symbols= — 検証・上限・非漏洩 ───────────────────────────────────

def test_sd_symbols_param_adds_device_watchlist_symbols():
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/supply-demand?symbols=6965,7011,bad!!,ionq").get_json()
    syms = [s["symbol"] for s in d["signals"]]
    assert "6965" in syms and "7011" in syms and "IONQ" in syms
    assert not any("!" in s for s in syms)          # 不正トークンは黙って拒否
    # レジストリに登録済み(cron warm対象)
    assert "6965" in scanner._SD_EXTRA_SYMBOLS
    assert scanner._SD_EXTRA_SYMBOLS["6965"]["market"] == "JP"
    assert scanner._SD_EXTRA_SYMBOLS["IONQ"]["market"] == "US"


def test_sd_symbols_param_bounded_to_ten_extras():
    many = ",".join(f"{7000 + i}" for i in range(20))
    with scanner.app.test_client() as c:
        d = c.get(f"/api/argus/supply-demand?symbols={many}").get_json()
    base = {s["symbol"] for s in scanner._supply_demand_list(cap=12)}
    extras = [s for s in d["signals"] if s["symbol"] not in base]
    assert len(extras) <= 10
    assert len(scanner._SD_EXTRA_SYMBOLS) <= scanner._SD_EXTRA_MAX


def test_sd_symbols_response_leak_free():
    import argus_portfolio_sync
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/supply-demand?symbols=6965,7011").get_json()
    assert not argus_portfolio_sync.contains_sensitive(d)
    blob = json.dumps(d, ensure_ascii=False)
    for banned in ("quantity", "avgCost", "vaultPass", "login_pwd"):
        assert banned not in blob


def test_sd_unknown_extra_symbol_stays_honest_unknown():
    # キャッシュが無い銘柄はUnknown(好条件に化けない — RC原則)
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/supply-demand?symbols=9997").get_json()
    row = [s for s in d["signals"] if s["symbol"] == "9997"]
    if row:                                          # test環境はキャッシュコールドが前提
        assert row[0]["supplyDemandRank"] in ("Unknown", "C", "D", "E", "B", "A", "S")
        assert "買い" not in (row[0].get("actionImplicationJa") or "") or \
            row[0]["supplyDemandRank"] != "Unknown"


# ── ③ DQ: 機関シグナル鮮度は実測のみ ────────────────────────────────────────

def test_dq_institutional_freshness_measured_or_unknown(monkeypatch):
    monkeypatch.setitem(scanner._INTEL_LAST, "ts", 0.0)
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/data-quality").get_json()
    row = [r for r in d["sourceHealth"] if r["sourceName"] == "institutional-intel"][0]
    assert row["lastSuccessAt"] is None              # 未収集はunknownのまま(捏造なし)
    assert row["freshnessBucket"] == "unknown"
    monkeypatch.setitem(scanner._INTEL_LAST, "ts", time.time())
    with scanner.app.test_client() as c:
        d2 = c.get("/api/argus/data-quality").get_json()
    row2 = [r for r in d2["sourceHealth"] if r["sourceName"] == "institutional-intel"][0]
    assert row2["lastSuccessAt"] is not None         # 収集済みは実測時刻
    assert row2["freshnessBucket"] in ("fresh", "recent")


# ── ④ FEソース検査(grep) — 折りたたみ記憶/FIRE Core/即時調査/Pack簡潔化 ────

def test_fe_collapse_persistence_local_only():
    src = _read("components", "common", "CollapsibleSection.tsx")
    assert "argus.todayCollapse.v1" in src
    assert "localStorage" in src
    assert "fetch(" not in src                       # 端末内のみ(サーバー送信なし)
    assert "resetTodayLayout" in src
    # v13: Todayは単一view modelと単一decision cardへ縮約。
    # 市場選択は端末内だけに保存し、判断詳細は同カード内で開閉する。
    cc = _read("routes", "CommandCenter.tsx")
    assert "argus.today.marketSelection.v1" in cc
    assert "localStorage" in cc
    panel = _read("components", "today", "ArgusTodayPanel.tsx")
    assert "useState(false)" in panel
    assert "aria-expanded={detail}" in panel


def test_fe_fire_core_manual_update_wording():
    src = _read("components", "dashboard", "FireCoreCard.tsx")
    assert "リアルタイムでなくてOK" in src
    assert "週1程度の評価額更新" in src
    assert "lastValueDate" in src                    # staleは日付+次の一歩を出す
    assert "評価額を更新" in src


def test_fe_investigate_button_outside_details():
    # v12.2.12: 銘柄カードはAsset Desk(AssetWhyPanel)へ移設 — ガード意図は不変。
    src = _read("components", "assetDesk", "AssetWhyPanel.tsx")
    btn = src.index("AiExplanationBlock symbol=")
    details = src.index("詳細データ(値動き・原因分析)を見る")
    assert btn < details, "即時調査ボタンは詳細データ折りたたみの外(前)に出す"


def test_fe_institutional_view_japanese_first():
    src = _read("components", "dashboard", "InstitutionalView.tsx")
    assert "displayTitleJa" in src
    assert "autoQueueTranslations" in src
    assert "原文を見る" in src


def test_review_pack_single_concise_jp_caveat():
    src = _read("lib", "reviewPack.ts")
    assert src.count("moomoo側メンテナンス中") == 1   # 長文caveatの重複なし
    assert "代替データ" in src and "意図的に無効" in src


# ── ⑤ 文言整合: メンテナンス確認済みが全域で一貫 ────────────────────────────

def test_maintenance_confirmed_wording_consistent():
    import argus_data_quality as dq
    assert "メンテナンス" in dq.EXPECTED_DISABLED[0]["reasonJa"]
    assert "サポート確認済み" in dq.EXPECTED_DISABLED[0]["reasonJa"]
    src = scanner._supply_demand_sources()
    moomoo = [x for x in src["disabled"] if "moomoo" in x["source"]][0]
    assert "メンテナンス" in moomoo["reasonJa"]
    assert "意図的に無効" in moomoo["reasonJa"]
