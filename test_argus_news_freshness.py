"""ARGUS V11.5.3 — news freshness gate (pure) + mover-cause demotion regression.

The bug this locks down: a June-19 article surfaced as the CURRENT lead for a
July-3 move (フジクラ). Old/stale news must demote to background/過去材料 and can
never earn the ladder status or bestLeadJa.
"""
import argus_mover_cause as MC
import argus_news_freshness as NF

NOW = "2026-07-03T06:00:00Z"


def test_classify_thresholds():
    assert NF.classify("2026-07-03T04:00:00Z", NOW)["freshness"] == "fresh"        # 2h
    assert NF.classify("2026-07-02T10:00:00Z", NOW)["freshness"] == "recent"       # 20h
    assert NF.classify("2026-07-01T06:00:00Z", NOW)["freshness"] == "stale"        # 48h
    assert NF.classify("2026-06-19T09:00:00Z", NOW)["freshness"] == "old"          # ~14d
    assert NF.classify(None, NOW)["freshness"] == "unknown_time"
    assert NF.classify("garbage", NOW)["freshness"] == "unknown_time"


def test_eligibility_and_roles():
    assert NF.classify("2026-07-03T04:00:00Z", NOW)["eligibleAsPrimaryLead"] is True
    assert NF.classify("2026-07-02T10:00:00Z", NOW)["eligibleAsPrimaryLead"] is True
    assert NF.classify("2026-07-01T06:00:00Z", NOW)["eligibleAsPrimaryLead"] is False
    old = NF.classify("2026-06-19T09:00:00Z", NOW)
    assert old["eligibleAsPrimaryLead"] is False and old["role"] == "historical"
    assert "過去材料" in old["staleReasonJa"]
    assert NF.classify(None, NOW)["eligibleAsPrimaryLead"] is False   # unknown time never primary


def test_label_ja():
    assert "過去材料" in NF.label_ja("old", 14 * 24)
    assert "日前" in NF.label_ja("old", 14 * 24)
    assert NF.label_ja("unknown_time") == "時刻不明"


def _resolve_with_news(news, chg=-8.0):
    mover = {"symbol": "5803", "market": "JP", "changePct": chg, "name": "フジクラ",
             "asOf": NOW, "direction": "down"}
    evidence = {"jpNews": news, "coverage": {"jpNewsChecked": True},
                "moveStartedAt": "2026-07-03T00:05:00Z"}
    return MC.resolve(mover, evidence, NOW)


def test_ten_day_old_news_cannot_be_lead():
    """フジクラ回帰: 6/19の記事しか無い7/3の急落は「候補: <古い記事>」にしない。"""
    rec = _resolve_with_news([{"titleJa": "フジクラ、データセンター向け光配線で新工場",
                               "publishedAt": "2026-06-19T09:00:00Z",
                               "publisher": "GoogleNewsJP", "source": "google_news_jp"}])
    assert rec["causeStatus"] == "no_lead_yet"                 # old news earns nothing
    assert "フジクラ、データセンター" not in rec["bestLeadJa"]
    assert rec["bestLeadJa"] == "最新材料は未確認"
    assert "過去材料" in rec["whyNotConfirmedJa"]
    assert any("最新ニュース" in c for c in rec["nextChecksJa"])
    # the old article is still visible — but demoted to background with the reason
    cand = next(c for c in rec["causeCandidates"] if c["category"] == "direct_news")
    assert cand["role"] == "background_only"
    assert cand["newsFreshness"]["freshness"] == "old"
    assert cand["confidence"] <= 0.15


def test_fresh_news_still_becomes_candidate():
    rec = _resolve_with_news([{"titleJa": "フジクラ、決算下方修正を発表",
                               "publishedAt": "2026-07-03T05:30:00Z",
                               "publisher": "Reuters", "source": "reuters_jp"}])
    assert rec["causeStatus"] in ("candidate_catalyst", "probable_catalyst")
    assert "下方修正" in rec["bestLeadJa"]


def test_stale_48h_news_demoted():
    rec = _resolve_with_news([{"titleJa": "フジクラ関連の48時間前の記事",
                               "publishedAt": "2026-07-01T06:00:00Z",
                               "publisher": "GoogleNewsJP", "source": "google_news_jp"}])
    cand = next(c for c in rec["causeCandidates"] if c["category"] == "direct_news")
    assert cand["role"] == "background_only"
    assert cand["newsFreshness"]["freshness"] == "stale"
    assert rec["causeStatus"] == "no_lead_yet"


def test_old_caos_association_lead_demoted():
    mover = {"symbol": "5803", "market": "JP", "changePct": -8.0, "asOf": NOW, "direction": "down"}
    evidence = {"caosLead": {"titleJa": "AIケーブル特需の解説記事",
                             "via": "theme", "corroboration": "single",
                             "publishedAt": "2026-06-19T09:00:00Z"},
                "coverage": {"caosChecked": True}}
    rec = MC.resolve(mover, evidence, NOW)
    lead = next(c for c in rec["causeCandidates"] if c["category"] in ("theme", "entity_association"))
    assert lead["role"] == "background_only"
    assert rec["causeStatus"] == "no_lead_yet"


def test_caos_lead_without_timestamp_keeps_working():
    """後方互換: publishedAtの無い既存リードはunknown_timeのまま候補資格を維持。"""
    mover = {"symbol": "9984", "market": "JP", "changePct": -5.0, "asOf": NOW, "direction": "down"}
    evidence = {"caosLead": {"titleJa": "関連テーマのリード", "via": "theme",
                             "corroboration": "single"},
                "coverage": {"caosChecked": True}}
    rec = MC.resolve(mover, evidence, NOW)
    assert rec["causeStatus"] == "candidate_catalyst"


def test_compact_carries_news_freshness():
    rec = _resolve_with_news([{"titleJa": "古い記事", "publishedAt": "2026-06-19T09:00:00Z",
                               "publisher": "X", "source": "google_news_jp"}])
    comp = MC.compact(rec)
    assert any((c.get("newsFreshness") or {}).get("freshness") == "old"
               for c in comp["topCandidates"])
