"""V11.20.0 AI Review Pack tests — spec §11."""
import json

import argus_review_pack as rp

NOW = "2026-07-05T15:00:00+09:00"


def _ctx(**kw):
    base = {
        "commandJa": "HOLD EXISTING ONLY — 新規禁止・追加禁止・既存は維持。",
        "sessionBriefJa": "週末レビューの日。攻めない。",
        "regimeJa": "地合いは中立圏。",
        "eventsJa": ["米雇用統計(NFP) 発表済 — 結果+57千人/失業率4.2%"],
        "apLinesJa": ["[P2] 6584 三櫻工業 — 追いかけ買い注意"],
        "scenarioLinesJa": ["6584: 踏み上げ→失速に注意(帯: 中程度)"],
        "planLinesJa": ["6584: 追いかけ買い注意 — 大口買い確認まで待ち"],
        "strategyJa": "コア+ヘッジ約45% / 戦術枠約20%。FIRE整合は「概ね整合」。",
        "strategyWarningsJa": ["AI関連への集中が高め"],
        "fireCoreJa": "投信合計は既知資産の40%。毎月積立 月5万円 登録済み。",
        "sdAggregateJa": "需給: A/B 3件・D/E 1件・踏み上げ候補1件。",
        "flowAggregateJa": "フロー: 大口買い集め推定1件・売り抜け推定1件。",
        "instAggregateJa": "機関: 強気2件/弱気1件(見解であり建玉ではない)。",
        "dqCaveatJa": "判断記録n=12 — まだ履歴が少なく成績としては扱わない。",
        "lrCaveatJa": None,
        "notifLinesJa": ["[注意] 6584 追いかけ注意(新規)"],
        "backupSafeJa": "バックアップ保護: 保護済み / 復元確認済",
        "assets": [{"symbol": "6584", "market": "JP", "assetName": "三櫻工業",
                    "heldStatus": "held", "role": "tactical",
                    "scenarioSummaryJa": "踏み上げ→失速に注意",
                    "planSummaryJa": "追いかけ買い注意",
                    "supplyDemandSummaryJa": "需給B・売り長",
                    "flowSummaryJa": "買い戻し主導の可能性",
                    "positionRiskSummaryJa": "保有中・比率高め",
                    "missingEvidenceJa": ["逆日歩(未取込)"]}],
        "topRisksJa": ["6584の踏み上げ失速リスク", "AIテーマ集中"],
        "topOpportunitiesJa": ["押し目候補2件"],
        "blockedJa": ["イベント待ち: なし"],
        "missingJa": ["逆日歩(未取込)", "毎月積立額の一部未入力"],
        "contradictionsJa": [],
        "opposingJa": None,
    }
    base.update(kw)
    return base


def _pack(pt="daily", **kw):
    return rp.build_pack(pt, _ctx(), now_iso=NOW, app_version="11.20.0", **kw)


# ── validation ───────────────────────────────────────────────────────────────

def test_pack_schema():
    p = _pack()
    assert p["packType"] in rp.PACK_TYPES
    assert p["privacyMode"] in rp.PRIVACY_MODES
    assert p["generatedLocally"] is True
    for s in p["sections"]:
        assert s["sectionType"] in rp.SECTION_TYPES
        assert s["privacyLevel"] in ("public_safe", "private_local",
                                     "encrypted_vault", "redacted")
    for a in p["assets"]:
        assert a["heldStatus"] in rp.HELD_STATUSES


def test_all_pack_types_generate():
    for pt in ("daily", "asset", "portfolio", "event", "emergency"):
        p = _pack(pt)
        md = rp.render_markdown(p)
        assert "# ARGUS AI Review Pack" in md
        assert "## Instructions for reviewer" in md
        assert rp.INSTRUCTIONS_JA[pt][:20] in md          # 指示文variant
        assert "## Strongest Opposing View" in md or "反対view" in md
        assert "## Missing Evidence" in md


# ── privacy ──────────────────────────────────────────────────────────────────

def test_redacted_excludes_private():
    p = _pack(privacy_mode="redacted")
    md = rp.render_markdown(p)
    for marker in ("保有中", "含み益", "積立", "投信合計", "NISA", "比率高め"):
        assert marker not in md, marker
    assert "個人投資情報は除外済み" in md
    types = [s["sectionType"] for s in p["sections"]]
    assert "portfolio_strategy" not in types
    assert "fire_core" not in types
    assert p["publicLeakSafe"] is True
    assert all(a["heldStatus"] == "unknown" for a in p["assets"])


def test_owner_copy_labels_privacy():
    p = _pack(privacy_mode="owner_copy")
    assert "共有先に注意" in p["privacyLabelJa"]
    md = rp.render_markdown(p)
    assert "共有先に注意" in md


def test_no_secrets_in_any_variant():
    for pt in ("daily", "asset", "portfolio", "event", "emergency"):
        for pm in ("redacted", "owner_copy"):
            for ln in ("full", "short"):
                md = rp.render_markdown(_pack(pt, privacy_mode=pm, length=ln))
                for bad in rp.FORBIDDEN_SECRETS:
                    assert bad not in md, (bad, pt, pm, ln)
                low = md.lower()
                for bad in rp.FORBIDDEN_EXECUTION:
                    assert bad.lower() not in low, (bad, pt, pm, ln)


# ── length / dedupe / hierarchy ──────────────────────────────────────────────

def test_short_pack_is_shorter():
    full = rp.render_markdown(_pack(length="full"))
    short = rp.render_markdown(_pack(length="short"))
    assert len(short) < len(full)
    assert "## Instructions for reviewer" in short     # 指示文は短縮版にも必須


def test_no_duplicate_event_summary():
    md = rp.render_markdown(_pack())
    assert md.count("米雇用統計(NFP) 発表済") == 1      # イベント要約は1回だけ


def test_asset_details_consolidated_once():
    md = rp.render_markdown(_pack())
    assert md.count("需給B・売り長") == 1               # 銘柄別需給文はAssets欄のみ
    assert "銘柄別はAssets欄" in md                     # 集計セクションは委譲を明示


def test_hierarchy_order():
    md = rp.render_markdown(_pack())
    idx = [md.index(h) for h in ("## Owner question", "## Top risks",
                                 "## Missing Evidence", "## Strongest Opposing View",
                                 "## Instructions for reviewer")]
    assert idx == sorted(idx)


# ── honesty ──────────────────────────────────────────────────────────────────

def test_missing_evidence_included():
    md = rp.render_markdown(_pack())
    assert "逆日歩(未取込)" in md


def test_opposing_view_default_when_absent():
    p = _pack()
    assert p["strongestOpposingViewJa"]
    assert "疑うこと" in p["strongestOpposingViewJa"]


def test_empty_ctx_honest():
    p = rp.build_pack("daily", {}, now_iso=NOW, app_version="11.20.0")
    md = rp.render_markdown(p)
    assert "## Missing Evidence" in md
    assert "## Instructions for reviewer" in md
    assert p["sections"]                                # 最低限のセクションは存在


# ── status ───────────────────────────────────────────────────────────────────

def test_public_status_redacted():
    d = rp.public_status(now_iso=NOW)
    assert d["serverStoresPacks"] is False
    assert d["autoExternalAICall"] is False
    assert d["generatedLocally"] is True
    assert d["storageMode"] == "public_redacted"
    blob = json.dumps(d, ensure_ascii=False)
    for banned in ("quantity", "averageCost", "fundName", "monthlyContribution",
                   "ownerAction", "weightPct"):
        assert banned not in blob


def test_deterministic():
    a = rp.render_markdown(_pack())
    b = rp.render_markdown(_pack())
    assert a == b
