"""Tests for §12 Multi-Agent Research Mission orchestrator (argus_research_swarm.py).

No network, no LLM. Asserts the key safety/correctness properties:
  * dynamic staffing scales with severity + owner-relevance;
  * ADVERSARIAL_REVIEWER + SYNTHESIS_EDITOR are ALWAYS present;
  * a report published AFTER the move yields a stale/amplifier-as-trigger flag;
  * an unsupported synthesis (missing alternative) is downgraded (publishable False);
  * cost.llmCalls == 0 (deterministic);
  * a clean balanced case yields no adversarial flags.
"""
import argus_research_mesh as M
import argus_research_swarm as S


# ── fixtures ─────────────────────────────────────────────────────────────────
def _item(**kw):
    """Build an IntelligenceItem via the mesh normalizer, then patch fields."""
    raw = {
        "sourceId": kw.pop("sourceId", "bloomberg_public"),
        "title": kw.pop("title", "Goldman Sachs raises NVDA price target on strong demand"),
        "publicSnippet": kw.pop("publicSnippet", ""),
        "canonicalUrl": kw.pop("canonicalUrl", "https://example.com/a"),
        "author": kw.pop("author", "Goldman Sachs"),
        "linkedAssets": kw.pop("linkedAssets", ["NVDA"]),
        "publishedAt": kw.pop("publishedAt", "2026-06-23T13:00:00Z"),
        "firstDetectedAt": kw.pop("firstDetectedAt", "2026-06-23T13:00:00Z"),
    }
    it = M.normalize_item(raw)
    it.update(kw)  # allow overriding contentType / category / etc.
    return it


def _event(**kw):
    base = {
        "eventId": "evt1",
        "linkedAssets": ["NVDA"],
        "moveStartedAt": "2026-06-23T14:00:00Z",
        "severity": "HIGH",
    }
    base.update(kw)
    return base


# ── plan_mission: dynamic staffing ───────────────────────────────────────────
def test_plan_always_includes_reviewer_and_editor():
    # 最小イベントでも常時ロールは必ず含まれる。
    plan = S.plan_mission({"severity": "INFO"}, {})
    assert "ADVERSARIAL_REVIEWER" in plan["roles"]
    assert "SYNTHESIS_EDITOR" in plan["roles"]


def test_plan_staffs_more_for_high_severity_owner_relevant():
    low = S.plan_mission({"severity": "LOW"}, {"ownerRelevant": False})
    high = S.plan_mission(_event(severity="CRITICAL"),
                          {"ownerRelevant": True, "intelCount": 5})
    assert len(high["roles"]) > len(low["roles"])
    # 高severity+owner はギアも高い。
    assert high["gear"] > low["gear"]
    # 常時ロールは両方に存在。
    for plan in (low, high):
        assert "ADVERSARIAL_REVIEWER" in plan["roles"]
        assert "SYNTHESIS_EDITOR" in plan["roles"]


def test_plan_does_not_run_every_role_for_trivial_event():
    plan = S.plan_mission({"severity": "INFO"}, {})
    # 全ロールを走らせない(編成は ROLES より小さい)。
    assert len(plan["roles"]) < len(S.ROLES)


def test_plan_gear_capped_at_three():
    plan = S.plan_mission(_event(severity="CRITICAL", novelty=0.9),
                          {"ownerRelevant": True, "evidenceGap": True})
    assert 0 <= plan["gear"] <= 3
    assert plan["gear"] == 3


# ── run_mission: cost is zero / deterministic ────────────────────────────────
def test_run_mission_zero_llm_calls():
    res = S.run_mission(_event(), [_item()])
    assert res["cost"]["llmCalls"] == 0
    assert res["cost"]["deterministic"] is True
    assert res["cost"]["network"] is False


def test_run_mission_is_deterministic():
    items = [_item(), _item(canonicalUrl="https://example.com/b", title="NVDA demand strong upside")]
    a = S.run_mission(_event(), items)
    b = S.run_mission(_event(), items)
    assert a["adversarialFlags"] == b["adversarialFlags"]
    assert a["rolesRun"] == b["rolesRun"]
    assert a["confidence"] == b["confidence"]


def test_run_mission_always_runs_reviewer_and_editor():
    res = S.run_mission({"severity": "INFO", "linkedAssets": ["NVDA"]}, [])
    assert "ADVERSARIAL_REVIEWER" in res["rolesRun"]
    assert "SYNTHESIS_EDITOR" in res["rolesRun"]
    # reviewer は editor より前。
    assert res["rolesRun"].index("ADVERSARIAL_REVIEWER") < res["rolesRun"].index("SYNTHESIS_EDITOR")


# ── adversarial: stale / amplifier-as-trigger ────────────────────────────────
def test_report_published_after_move_flags_stale_amplifier():
    # 動意(14:00)の後に出た(15:30)レポート → AMPLIFIER。
    after = _item(publishedAt="2026-06-23T15:30:00Z",
                  firstDetectedAt="2026-06-23T15:30:00Z",
                  title="NVDA selloff explained: demand concerns")
    res = S.run_mission(_event(moveStartedAt="2026-06-23T14:00:00Z"), [after])
    # marketReaction が AMPLIFIER を数えている。
    assert res["evidence"]["marketReaction"]["amplifierCount"] >= 1
    # 反証フラグに stale-report-as-trigger が立つ。
    assert any(f["flag"] == "stale-report-as-trigger" for f in res["adversarialFlags"])


# ── adversarial: short-volume != short-interest ──────────────────────────────
def test_short_volume_confusion_flagged():
    bad = _item(title="short volume means short interest for NVDA whale",
                publishedAt="2026-06-23T13:00:00Z",
                firstDetectedAt="2026-06-23T13:00:00Z")
    res = S.run_mission(_event(), [bad])
    assert any(f["flag"] == "short-volume!=short-interest" for f in res["adversarialFlags"])


# ── adversarial: duplicate-source false confirmation ─────────────────────────
def test_duplicate_syndication_not_double_confirmation():
    # 同一見出し・同一機関・同一資産 = 1 origin の転載が2件。
    one = _item(sourceId="bloomberg_public", canonicalUrl="https://a.com/x",
                title="Goldman Sachs cuts NVDA estimate on demand weakness")
    two = _item(sourceId="bloomberg_public", canonicalUrl="https://b.com/x",
                title="Goldman Sachs cuts NVDA estimate on demand weakness")
    res = S.run_mission(_event(), [one, two])
    flags = {f["flag"] for f in res["adversarialFlags"]}
    assert "duplicate-source-false-confirmation" in flags
    # 独立確認はゼロ(同一系統)。
    assert res["evidence"]["corroboration"]["independentlyCorroboratedCount"] == 0


# ── adversarial: one-sided evidence ──────────────────────────────────────────
def test_one_sided_bull_only_flagged():
    bull_only = _item(title="NVDA strong upside, beat, tailwind on demand",
                      publishedAt="2026-06-23T13:00:00Z",
                      firstDetectedAt="2026-06-23T13:00:00Z")
    res = S.run_mission(_event(), [bull_only])
    assert res["evidence"]["bull"]["count"] > 0
    assert res["evidence"]["bear"]["count"] == 0
    assert any(f["flag"] == "one-sided-evidence" for f in res["adversarialFlags"])


# ── adversarial: clean balanced case yields no flags ─────────────────────────
def test_clean_balanced_case_no_flags():
    # 動意の前に出た、両論を含む独立2系統。機関名の売買断定なし。AMPLIFIERなし。
    a = _item(sourceId="cnbc_public", canonicalUrl="https://cnbc.com/1",
              author="staff",
              title="NVDA shows strong upside but also downside risk on valuation concern",
              publishedAt="2026-06-23T12:00:00Z", firstDetectedAt="2026-06-23T12:00:00Z")
    b = _item(sourceId="marketwatch_public", canonicalUrl="https://mw.com/2",
              author="staff",
              title="NVDA upside potential tempered by weakness and risk of catch-down",
              publishedAt="2026-06-23T12:30:00Z", firstDetectedAt="2026-06-23T12:30:00Z")
    res = S.run_mission(_event(moveStartedAt="2026-06-23T14:00:00Z"), [a, b])
    # 両論が揃っている。
    assert res["evidence"]["bull"]["count"] > 0
    assert res["evidence"]["bear"]["count"] > 0
    # 動意前なので AMPLIFIER は出ない。
    assert res["evidence"]["marketReaction"]["amplifierCount"] == 0
    assert res["adversarialFlags"] == []


# ── synthesis gate: unsupported synthesis is downgraded ──────────────────────
def test_unsupported_synthesis_missing_alternative_downgraded(monkeypatch):
    # alternative が欠けた synthesis を editor が作った場合、gate が落とし格下げ。
    # editor の組み立てを直接検査するため、alternative を強制的に空にするフックを使う。
    real_gate = M.gate_synthesis

    def _force_missing_alt(syn):
        syn = dict(syn)
        syn["alternative"] = ""  # 反対側セクションを欠落させる
        return real_gate(syn)

    monkeypatch.setattr(M, "gate_synthesis", _force_missing_alt)
    res = S.run_mission(_event(), [_item()])
    av = res["argusView"]
    assert av["publishable"] is False
    assert "alternative" in av["missingSections"]
    # 格下げされている(LOW か UNCONFIRMED)。
    assert av["confidence"] in ("LOW", "UNCONFIRMED")
    assert res["confidence"] == av["confidence"]


def test_argus_view_is_decision_support_only():
    res = S.run_mission(_event(), [_item()])
    av = res["argusView"]
    assert av["decisionSupportOnly"] is True
    assert av["noTradeInstruction"] is True
    # confidence は校正済み確率ではなくラベル。
    assert av["confidence"] in ("HIGH", "MODERATE", "LOW", "UNCONFIRMED")
    assert av["calibration"] == "uncalibrated_heuristic_v1"


def test_synthesis_always_has_not_confirmed_section():
    # 正直さの担保: notConfirmed は常に非空。
    res = S.run_mission(_event(), [_item()])
    syn = res["argusView"]["synthesis"]
    assert syn["notConfirmed"]  # truthy / non-empty


# ── hunter / official wiring ─────────────────────────────────────────────────
def test_official_verifier_flags_official_source():
    off = _item(sourceId="sec_press", author="staff",
                title="SEC press release regarding NVDA filing",
                linkedAssets=["NVDA"])
    res = S.run_mission(_event(severity="CRITICAL"),
                        [off], {"ownerRelevant": True})
    assert len(res["evidence"]["official"]) == 1
    assert M.source_rights("sec_press")["kind"] == "official"


def test_hunter_filters_by_asset_or_institution():
    on_asset = _item(linkedAssets=["NVDA"], author="staff", title="NVDA news")
    off_asset_with_inst = _item(linkedAssets=["AAPL"], author="Goldman Sachs",
                                title="Goldman Sachs note on AAPL")
    off_asset_no_inst = _item(linkedAssets=["TSLA"], author="staff", title="TSLA news")
    res = S.run_mission(_event(linkedAssets=["NVDA"]),
                        [on_asset, off_asset_with_inst, off_asset_no_inst])
    hunter = res["evidence"]["hunter"]
    # NVDA(資産一致)と Goldman(機関一致)は入り、無関係 TSLA は除外。
    assert on_asset in hunter
    assert off_asset_with_inst in hunter
    assert off_asset_no_inst not in hunter
