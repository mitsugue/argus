"""ARGUS V12.0.8 — OSINT帰属/イベント日付真実/スタンス統一/PARTIAL理由/象限の恒久ガード。"""
import json
import os

import argus_osint_attribution as osint
import argus_primary_stance as ps
import scanner

WEB = os.path.join(os.path.dirname(__file__), "web", "src")
NOW = "2026-07-07T05:00:00Z"


def _read(*parts):
    return open(os.path.join(WEB, *parts), encoding="utf-8").read()


# ── Part A: OSINT帰属 ────────────────────────────────────────────────────────

def _cand(title, source="nikkei", published="2026-07-07T01:00:00Z", **kw):
    return {"titleJa": title, "source": source, "publishedAt": published, **kw}


def test_osint_stale_article_never_primary():
    r = osint.review("6965", "JP", -4.2, [
        _cand("ムーディーズ、大手企業の格付けを見直し", published="2024-09-13T17:02:00Z"),
        _cand("AI半導体の収益性に懸念", published="2026-07-06T22:00:00Z"),
    ], company_names=["浜松ホトニクス"], theme_words=["AI", "半導体"], now_iso=NOW)
    assert r["primary"] is not None
    assert "格付け" not in r["primary"]["titleJa"]          # 2024年記事は主因不可
    old = [c for c in r["causes"] if "格付け" in c["titleJa"]][0]
    assert old["category"] == "stale_background"
    assert old["primaryEligible"] is False


def test_osint_undated_never_primary():
    r = osint.review("6965", "JP", -4.2, [
        {"titleJa": "日付のない古そうな記事", "source": "rss"},
    ], company_names=["浜松ホトニクス"], theme_words=["AI"], now_iso=NOW)
    assert r["primary"] is None
    assert "原因不明" in r["headlineJa"]                     # 憶測で断定しない


def test_osint_direct_vs_theme_separated():
    r = osint.review("6965", "JP", -4.2, [
        _cand("浜松ホトニクス、業績予想を修正", source="tdnet"),
        _cand("SamsungとAnthropicがAIチップで提携 — AI半導体に思惑", source="reuters"),
    ], company_names=["浜松ホトニクス"], theme_words=["AI", "半導体", "Samsung", "Anthropic"],
        sector_confirm=True, now_iso=NOW)
    cats = {c["titleJa"][:6]: c["category"] for c in r["causes"]}
    assert cats["浜松ホトニク"] == "direct_official"
    assert [c for c in r["causes"] if "Samsung" in c["titleJa"]][0]["category"] == "sector_theme"
    # 直接材料が1位(テーマ連想より上)
    assert r["causes"][0]["category"].startswith("direct")


def test_osint_theme_inference_not_stated_as_fact():
    r = osint.review("6965", "JP", -4.2, [
        _cand("AI半導体バリューチェーンに収益性懸念", source="reuters"),
    ], company_names=["浜松ホトニクス"], theme_words=["AI", "半導体"], now_iso=NOW)
    assert r["primary"]["category"] == "sector_theme"
    assert "テーマ連想" in r["headlineJa"]                   # 事実として断定しない
    assert "候補" in r["headlineJa"]
    assert "浜松ホトニクス固有の開示・報道は見つかっていない" in r["primary"]["whyWrongJa"]
    assert r["osintConfidence"] in ("low", "medium")         # 連想のみはhigh不可


def test_osint_confidence_ladder():
    hi = osint.review("6965", "JP", -4.2, [
        _cand("浜松ホトニクス関連の材料A", source="tdnet"),
        _cand("浜松ホトニクス関連の報道B", source="nikkei"),
    ], company_names=["浜松ホトニクス"], sector_confirm=True, now_iso=NOW)
    assert hi["osintConfidence"] == "high"
    unk = osint.review("9999", "JP", -1.0, [], now_iso=NOW)
    assert unk["osintConfidence"] == "unknown"
    assert unk["primary"] is None


def test_osint_sources_missing_flag():
    r = osint.review("6965", "JP", -4.2, [_cand("テーマ記事", source="google_news_jp")],
                     theme_words=["テーマ"], now_iso=NOW)
    assert any("公式開示" in x for x in r["sourcesMissingJa"])


def test_osint_wired_into_cause_attribution(monkeypatch):
    monkeypatch.setitem(scanner._NEWS_JA_STATE, "restored", True)
    st = scanner.get_cause_attribution("6965", "JP")
    assert "osint" in st
    if st["osint"]:                                          # cached-only環境では空もあり得る
        assert st["osint"]["schemaVersion"] == "osint-attribution-v1"
        blob = json.dumps(st["osint"], ensure_ascii=False)
        assert "断定ではない" in blob


def test_theme_map_includes_hamamatsu():
    assert "6965" in scanner._DOWNSIDE_THEMES["ai_semis_cable"]
    assert any("Samsung" in w or "サムスン" in w
               for w in scanner._THEME_WORDS_JA["ai_semis_cable"])


# ── Part C: Primary Stance(矛盾排除の5ハードルール) ─────────────────────────

def test_stance_held_p1_never_no_action():
    r = ps.resolve({"isHeld": True, "apRank": "P1", "apLabel": "NO_ACTION",
                    "planStance": "unknown"})
    assert r["primaryStance"] == "risk_review"
    assert r["stanceJa"] == "リスク確認が先"


def test_stance_plan_risk_review_overrides_no_action():
    r = ps.resolve({"isHeld": True, "apRank": "P3", "apLabel": "NO_ACTION",
                    "planStance": "risk_review"})
    assert r["primaryStance"] == "risk_review"


def test_stance_event_wait_blocks_add_labels():
    r = ps.resolve({"isHeld": False, "apLabel": "SMALL_ADD_ALLOWED",
                    "planStance": "unknown", "eventWait": True})
    assert r["primaryStance"] == "wait_event"


def test_stance_improving_but_heavy_never_bullish():
    r = ps.resolve({"isHeld": False, "apLabel": "SMALL_ADD_ALLOWED",
                    "planStance": "unknown", "sdCondition": "improving_but_heavy"})
    assert r["primaryStance"] == "add_only_on_pullback"      # 強気化しない


def test_stance_squeeze_never_chase():
    r = ps.resolve({"isHeld": False, "apLabel": "SMALL_ADD_ALLOWED",
                    "planStance": "unknown", "sdCondition": "squeeze_prone"})
    assert r["primaryStance"] == "avoid_chase"


def test_stance_partial_data_caps_confidence_and_demotes_bullish():
    r = ps.resolve({"isHeld": False, "apLabel": "SMALL_ADD_ALLOWED",
                    "planStance": "unknown", "dataPartial": True, "baseConfidence": 0.9})
    assert r["confidence"] <= 0.55
    assert r["primaryStance"] == "unknown"                   # 強気は判定保留へ
    assert any("部分データ" in x for x in r["capNotesJa"])


def test_stance_py_ts_parity():
    ts = _read("domain", "primaryStance.ts")
    for ja in ps.STANCE_JA.values():
        assert ja in ts, ja
    # ハードルールの構造がTS側にも存在
    for marker in ("risk_review", "wait_event", "improving_but_heavy",
                   "squeeze_prone", "PARTIAL_CONF_CAP"):
        assert marker in ts, marker


# ── Part B: イベント日付真実 ─────────────────────────────────────────────────

def test_fe_event_rows_show_date_and_dcount():
    src = _read("components", "dashboard", "ImportantEventsCard.tsx")
    assert "eventWhenJa" in src
    assert "あと${diffDays}日" in src or "あと" in src
    assert "日時未確認" in src                               # 日時不明を隠さない
    # 「時刻だけ」の旧表示が復活していない
    assert "[ev.eventDate, jstFromUtc(ev.eventTimeUtc)]" not in src


def test_fe_pack_event_lines_include_date():
    src = _read("routes", "CommandCenter.tsx")
    assert "日付未確認" in src
    assert "ie.date ??" in src


def test_event_date_issues_flagged_in_dq():
    assert "dateIssues" in open("scanner.py", encoding="utf-8").read()


# ── Part D/E/F: FE検査 ──────────────────────────────────────────────────────

def test_fe_partial_data_reasons():
    hero = _read("components", "dashboard", "HeroCard.tsx")
    assert "PARTIAL DATAの理由" in hero
    assert "解消条件" in hero
    cc = _read("routes", "CommandCenter.tsx")
    assert "partialReasonsJa" in cc
    assert "moomoo側メンテナンス中" in cc


def test_fe_matrix_axes_and_provisional():
    m = _read("components", "regime", "RegimeMatrix.tsx")
    assert "provisional" in m and "暫定" in m
    assert "中立" in m                                       # 欠損→中立の説明
    assert "入力の内訳" in m
    mr = _read("routes", "MarketRegime.tsx")
    assert "axisHelpJa" in mr


def test_jp_matrix_missing_data_maps_neutral():
    m = scanner._jp_regime_matrix([])
    assert m["x"] == 0.0 and m["y"] == 0.0                   # 欠損は中立(右上に寄せない)
    assert m["available"] is False
    assert m["points"] == []


def test_fe_osint_pack_and_ui():
    rp = _read("lib", "reviewPack.ts")
    assert "'osint'" in rp or "| 'osint'" in rp
    assert "公式開示・主要ニュース・セクター連想を分けて検証してください" in rp
    assert "候補であり断定ではない" in rp
    csc = _read("components", "dashboard", "CauseStackCard.tsx")
    assert "候補原因" in csc
    assert "OSINT確度" in csc
    assert "外れの可能性" in csc
    assert "publishOsint" in csc


def test_fe_unified_stance_chip_everywhere():
    card = _read("components", "dashboard", "UnifiedAssetCard.tsx")
    assert "primaryStance" in card and "構え:" in card
    ap = _read("components", "dashboard", "ActionPrioritySection.tsx")
    assert "stances" in ap and "統一スタンス" in ap
    cc = _read("routes", "CommandCenter.tsx")
    assert "resolvePrimaryStance" in cc
    assert cc.count("stances={stanceBySymbol}") >= 3          # JP/US/CRYPTO/AP


# ── 非漏洩/文言(新規面) ─────────────────────────────────────────────────────

def test_osint_block_leak_and_wording_safe(monkeypatch):
    monkeypatch.setitem(scanner._NEWS_JA_STATE, "restored", True)
    with scanner.app.test_client() as c:
        d = c.get("/api/argus/cause-attribution?symbol=6965&market=JP").get_json()
    blob = json.dumps(d, ensure_ascii=False)
    import argus_portfolio_sync
    assert not argus_portfolio_sync.contains_sensitive(d)
    for w in ("今すぐ買", "今すぐ売", "成行で買", "全力買い", "login_pwd", "vaultPass"):
        assert w not in blob, w
