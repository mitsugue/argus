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


# ━━━ v12.0.8 追補(スクショ起因のtrust修正) ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# ── 追補1: リスクチップ分離(裸のLOW RISK禁止) ───────────────────────────────

def test_addendum_risk_chips_split_in_fe():
    src = _read("components", "action", "CommandSummaryCard.tsx")
    assert "MARKET RISK:" in src
    assert "POSITION RISK:" in src
    assert "保有銘柄のリスク確認が先" in src          # HOLD理由の一行
    cc = _read("routes", "CommandCenter.tsx")
    assert "保有銘柄に要確認あり" in cc
    assert "保有数量未入力" in cc


# ── 追補2: JP OPEN ≠ JPリアルタイム ─────────────────────────────────────────

def test_addendum_jp_open_does_not_imply_realtime():
    src = _read("components", "dashboard", "MarketSessionLamps.tsx")
    assert "MARKET ${m.state" in src                 # 「JP OPEN」単独でなくJP MARKET OPEN表示
    assert "JPリアルタイムAPIはメンテ中・代替データで判定" in src
    assert "jpRealtimeStatus" in src                 # bridge/statusから自動判定(復旧で消える)
    for banned in ("JP LIVE", "JP REALTIME OK"):
        assert banned not in src, banned


# ── 追補3: 単一のイベント時計 ───────────────────────────────────────────────

def test_addendum_single_event_clock():
    clock = _read("lib", "eventClock.ts")
    assert "D+1" in clock                            # 発表済(過去)は次に出さない
    assert "日時がパースできる未来のイベントだけ" in clock or "パースできる" in clock
    assert "あと${days}日" in clock or "あと" in clock
    app = _read("App.tsx")
    assert "nextUpcomingEvent" in app                # 右上Nextチップ
    cc = _read("routes", "CommandCenter.tsx")
    assert cc.count("nextUpcomingEvent") >= 2        # import+スティッキーバー
    # 旧「countdown === 'D'先頭拾い」ロジックが残っていない
    assert "find((e) => e.countdown === 'D' || e.countdown === 'D-1')" not in cc


# ── 追補4: Session Briefの入れ子スクロール禁止 ──────────────────────────────

def test_addendum_brief_no_nested_scroll():
    src = _read("components", "dashboard", "SessionBriefSection.tsx")
    assert "overflow" not in src                     # 内部スクロールを作らない
    assert "maxHeight" not in src
    assert "詳細を見る" in src                        # 要約+展開型
    assert "slice(0, 4)" in src


# ── 追補5: 出典プロビナンス ─────────────────────────────────────────────────

def test_addendum_provenance_fields_present():
    r = osint.review("6965", "JP", -4.2, [
        _cand("浜松ホトニクス、開示", source="tdnet"),
        _cand("AI半導体テーマ記事", source="reuters"),
        _cand("古い記事", published="2024-01-01T00:00:00Z"),
    ], company_names=["浜松ホトニクス"], theme_words=["AI", "半導体"], now_iso=NOW)
    for c in r["causes"]:
        assert c["sourceType"] in osint.SOURCE_TYPES
        assert c["directness"] in osint.DIRECTNESS
        assert c["freshness"] in osint.FRESHNESS
        assert c["whyThisMightBeWrongJa"]
    assert isinstance(r["evidenceCount"], int)
    direct = [c for c in r["causes"] if "浜松" in c["titleJa"]][0]
    assert direct["sourceType"] == "official_disclosure"
    assert direct["directness"] == "direct_company"
    stale = [c for c in r["causes"] if c["titleJa"] == "古い記事"][0]
    assert stale["freshness"] == "stale_14d_plus"
    assert stale["directness"] == "background"


def test_addendum_no_direct_evidence_note():
    r = osint.review("6965", "JP", -4.2, [
        _cand("SamsungとAnthropicのAIチップ提携で半導体に思惑", source="reuters"),
    ], company_names=["浜松ホトニクス"], theme_words=["AI", "半導体", "Samsung"], now_iso=NOW)
    assert r["noDirectEvidenceNoteJa"] == "原因未特定。候補はテーマ連想であり、直接材料ではありません。"
    # 直接材料があればnoteは消える
    r2 = osint.review("6965", "JP", -4.2, [
        _cand("浜松ホトニクスが業績修正", source="tdnet"),
    ], company_names=["浜松ホトニクス"], now_iso=NOW)
    assert r2["noDirectEvidenceNoteJa"] is None


# ── 追補6: 総合コマンドの買い増し禁止が下位ラベルを上書き ────────────────────

def test_addendum_global_add_prohibited_suppresses_small_add():
    r = ps.resolve({"isHeld": False, "apLabel": "SMALL_ADD_ALLOWED",
                    "planStance": "unknown", "globalAddProhibited": True})
    assert r["primaryStance"] == "deferred_today"
    assert r["stanceJa"] == "候補だが今日は保留"
    assert any("総合コマンドが買い増し禁止のため保留" in x for x in r["capNotesJa"])
    # 通常日はそのまま
    r2 = ps.resolve({"isHeld": False, "apLabel": "SMALL_ADD_ALLOWED",
                     "planStance": "unknown", "globalAddProhibited": False})
    assert r2["primaryStance"] == "small_add_allowed"


def test_addendum_global_add_prohibited_pullback_also_deferred():
    r = ps.resolve({"isHeld": False, "apLabel": "ADD_ONLY_ON_PULLBACK",
                    "planStance": "unknown", "globalAddProhibited": True})
    assert r["primaryStance"] == "deferred_today"
    assert any("押し目限定" in x for x in r["capNotesJa"])   # 条件は詳細として保存


# ── 追補7: P0/P1は対応不要を構造禁止 ────────────────────────────────────────

def test_addendum_p1_never_no_action_even_unheld():
    r = ps.resolve({"isHeld": False, "apRank": "P1", "apLabel": "NO_ACTION",
                    "planStance": "no_action"})
    assert r["primaryStance"] != "no_action"
    r2 = ps.resolve({"isHeld": True, "apRank": "P1", "apLabel": "NO_ACTION",
                     "planStance": "no_action"})
    assert r2["primaryStance"] == "risk_review"
    # 対応不要が許されるのは低優先×非保有×シグナルなしのみ
    r3 = ps.resolve({"isHeld": False, "apRank": "P3", "apLabel": "NO_ACTION",
                     "planStance": "no_action"})
    assert r3["primaryStance"] == "no_action"


# ── 追補8: CAOS遅延の数値化 ─────────────────────────────────────────────────

def test_addendum_caos_delay_numeric():
    src = _read("components", "dashboard", "CaosHub.tsx")
    assert "TARGET_MIN = 15" in src
    assert "目標${TARGET_MIN}分以内" in src
    assert "巡回正常" in src                          # 目標内は遅延と言わない
    assert "ニュース原因の確度を下げています" in src   # 遅延時の影響明示
    assert "TARGET_MIN * 3" in src                    # 3倍超で遅延判定


# ── 追補9: JP行列の暫定 ─────────────────────────────────────────────────────

def test_addendum_jp_matrix_provisional_label():
    src = _read("routes", "MarketRegime.tsx")
    assert "暫定" in src
    assert "provisional" in src
    assert "toJpMatrixState(data.jpMatrix, data?.status !== 'live')" in src


# ── 追補10: スクショ再現fixture(決定論) ─────────────────────────────────────

def test_addendum_screenshot_fixture_5803_held_risk_partial():
    # IMG_7900/7902系: JP開場×部分データ×保有5803リスク×総合買い増し禁止
    r = ps.resolve({
        "isHeld": True, "apRank": "P1", "apLabel": "NO_ACTION",
        "planStance": "risk_review", "scenarioDominant": "bearish",
        "sdCondition": "improving_but_heavy", "flowClass": "distribution",
        "dataPartial": True, "globalAddProhibited": True, "baseConfidence": 0.9,
    })
    assert r["primaryStance"] == "risk_review"        # 対応不要は不可能
    assert r["confidence"] <= 0.55                     # capを超えない
    assert any("部分データ" in x for x in r["capNotesJa"])


def test_addendum_screenshot_fixture_no_small_add_visible_on_prohibited_day():
    # IMG_7903/7904系: 総合=買い増し禁止の日に小さく買い増し可が主表示にならない
    for label in ("SMALL_ADD_ALLOWED", "ADD_ONLY_ON_PULLBACK"):
        r = ps.resolve({"isHeld": False, "apLabel": label,
                        "planStance": "unknown", "globalAddProhibited": True})
        assert r["stanceJa"] != "小さく買い増し可"
        assert r["stanceJa"] != "買うなら押し目限定"
        assert r["primaryStance"] == "deferred_today"


def test_addendum_stance_ts_parity_new_rules():
    ts = _read("domain", "primaryStance.ts")
    assert "deferred_today" in ts and "候補だが今日は保留" in ts
    assert "globalAddProhibited" in ts
    assert "対応不要にはしない" in ts
