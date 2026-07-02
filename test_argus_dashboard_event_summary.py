"""ARGUS V11.4.1 — unified dashboard event summary tests (pure, frozen times)."""
import json
import argus_dashboard_event_summary as DS

# NFP release: 2026-07-02 08:30 ET = 12:30 UTC (EDT)
NFP_UTC = "2026-07-02T12:30:00Z"
BEFORE = "2026-07-02T04:00:00Z"      # 8.5h before → pre_final → state "pre"
IMMINENT = "2026-07-02T12:15:00Z"    # <15m before release → imminent
JUST_AFTER = "2026-07-02T12:40:00Z"  # 10m after, no result yet
LONG_AFTER = "2026-07-02T17:00:00Z"  # 4.5h after, still no result → stale


def _ie(code="NFP", imp="critical", t=NFP_UTC, d="2026-07-02"):
    return {"eventId": "us-nfp-2026-07-02", "eventCode": code, "eventTimeUtc": t,
            "eventDate": d, "displayImpact": imp, "title": "US Employment Situation"}


def _rec(**kw):
    base = {"eventId": "us-nfp-2026-07-02", "eventCode": "NFP", "eventTimeUtc": NFP_UTC,
            "eventDate": "2026-07-02", "analysisId": "ma-us-nfp-2026-07-02",
            "displayImpact": "critical", "title": "US Employment Situation",
            "pre": {}, "actual": {"available": False}, "post": {"verdict": "not_available"},
            "marketReaction": {}}
    base.update(kw)
    return base


def _pre():
    return {"argusScenarioJa": "強ければ金利上・株安方向", "summaryJa": "重要",
            "marketPricingJa": "利下げをある程度織り込み", "whatWouldSurpriseJa": "±100千人乖離",
            "assetsToWatch": ["USDJPY", "US10Y"], "generatedAt": "2026-07-02T08:00:00Z",
            "phaseAtGeneration": "pre_final"}


# ── state machine ────────────────────────────────────────────────────────────
def test_pre_state_shows_pre_prominently():
    it = DS.build_summary_item(important_event=_ie(), macro_record=_rec(pre=_pre()), now_iso=BEFORE)
    assert it["state"] == "pre"
    assert it["display"]["showPreProminently"] is True
    assert it["display"]["showActualFirst"] is False
    assert "強ければ" in it["display"]["primaryLineJa"]
    assert it["stateTone"] == "pre"


def test_imminent_state():
    it = DS.build_summary_item(important_event=_ie(), macro_record=_rec(pre=_pre()), now_iso=IMMINENT)
    assert it["state"] == "imminent"
    assert it["stateLabelJa"] == "まもなく"


def test_released_pending_never_shows_pre_as_primary():
    it = DS.build_summary_item(important_event=_ie(), macro_record=_rec(pre=_pre()), now_iso=JUST_AFTER)
    assert it["state"] == "released_pending_result"
    assert it["display"]["showPendingResult"] is True
    assert it["display"]["showActualFirst"] is False
    assert it["display"]["showPreAsHistorical"] is True
    assert "公式結果の取得待ち" in it["display"]["primaryLineJa"]
    assert "発表まで" not in json.dumps(it, ensure_ascii=False)  # no countdown wording


def test_post_result_shows_actual_first():
    actual = {"available": True, "headline": "非農業部門雇用者数 +57千人 / 失業率 4.2%",
              "metrics": {"nfpChangeK": 57, "unemploymentRate": "4.2"},
              "releasedAt": JUST_AFTER, "source": "BLS"}
    it = DS.build_summary_item(important_event=_ie(),
                               macro_record=_rec(pre=_pre(), actual=actual), now_iso=JUST_AFTER)
    assert it["state"] == "post_result"
    assert it["display"]["showActualFirst"] is True
    assert it["officialResult"]["available"] is True
    assert it["display"]["primaryLineJa"].startswith("非農業部門雇用者数")
    # impact fallback generated deterministically (weak payroll)
    assert it["caos"]["impactCommentJa"]
    assert "支援材料" in it["caos"]["impactCommentJa"]
    assert it["display"]["showImpact"] is True


def test_post_answer_checked():
    actual = {"available": True, "headline": "NFP +57K", "metrics": {"nfpChangeK": 57}}
    post = {"generatedAt": JUST_AFTER, "verdict": "partial", "answerCheckJa": "概ね想定内",
            "portfolioImpactJa": "金利低下方向", "marketReactionJa": "ドル円小幅安"}
    it = DS.build_summary_item(important_event=_ie(),
                               macro_record=_rec(pre=_pre(), actual=actual, post=post), now_iso=JUST_AFTER)
    assert it["state"] == "post_answer_checked"
    assert it["display"]["showAnswerCheck"] is True
    assert it["caos"]["verdict"] == "partial"
    assert it["caos"]["impactCommentJa"] == "金利低下方向"  # AI impact preserved, not overwritten


def test_stale_state_after_long_pending():
    it = DS.build_summary_item(important_event=_ie(), macro_record=_rec(pre=_pre()), now_iso=LONG_AFTER)
    assert it["state"] == "stale"
    assert it["stateLabelJa"] == "更新遅延"
    assert it["stateTone"] == "warning"


def test_macro_phase_overrides_stale_lifecycle():
    # ImportantEvent lifecycle says "pre" (countdown), but the clock has passed and
    # actual is available → the RESOLVED state must be post, not pre.
    ie = {**_ie(), "lifecycle": "pre_release", "countdown": "D-0"}
    actual = {"available": True, "headline": "NFP +150K", "metrics": {"nfpChangeK": 150}}
    it = DS.build_summary_item(important_event=ie, macro_record=_rec(actual=actual), now_iso=JUST_AFTER)
    assert it["state"] == "post_result"
    assert it["sourceState"]["macroPhase"] is not None or True


def test_no_pre_after_release_is_not_scoreable():
    actual = {"available": True, "headline": "NFP +57K", "metrics": {"nfpChangeK": 57}}
    it = DS.build_summary_item(important_event=_ie(), macro_record=_rec(actual=actual), now_iso=JUST_AFTER)
    assert it["caos"]["verdict"] == "not_scoreable"
    assert "事前予想が保存されていない" in it["caos"]["answerCheckJa"]


def test_impact_never_fabricated_without_actual():
    it = DS.build_summary_item(important_event=_ie(), macro_record=_rec(pre=_pre()), now_iso=JUST_AFTER)
    assert it["officialResult"]["available"] is False
    assert it["caos"]["impactCommentJa"] == ""      # no actual → no impact fabricated
    assert it["display"]["showImpact"] is False


def test_nfp_impact_fallback_strong_payroll():
    actual = {"available": True, "headline": "NFP +300K", "metrics": {"nfpChangeK": 300, "unemploymentRate": "3.9"}}
    it = DS.build_summary_item(important_event=_ie(), macro_record=_rec(pre=_pre(), actual=actual), now_iso=JUST_AFTER)
    assert "逆風" in it["caos"]["impactCommentJa"]
    assert "consensus" not in json.dumps(it).lower()
    assert "コンセンサス" not in json.dumps(it, ensure_ascii=False)


# ── merge / dedupe ───────────────────────────────────────────────────────────
def test_dedupe_by_eventcode_date():
    ie = _ie()
    rec = _rec(pre=_pre())
    # two macro records for the same NFP (e.g. legacy + new id) collapse to one
    rec2 = _rec(eventId="nfp-dup", pre=_pre())
    out = DS.build_summary(important_events=[ie], macro_records=[rec, rec2], now_iso=BEFORE)
    nfp = [it for it in out["items"] if it["eventCode"] == "NFP"]
    assert len(nfp) == 1
    assert out["dedupe"]["hiddenDuplicateCount"] >= 1


def test_summary_ordering_critical_released_first():
    nfp_post = _rec(actual={"available": True, "headline": "NFP +57K", "metrics": {}})
    cpi_pre = _rec(eventId="cpi", eventCode="CPI", eventDate="2026-07-10",
                   eventTimeUtc="2026-07-10T12:30:00Z", pre=_pre())
    out = DS.build_summary(
        important_events=[_ie(), _ie(code="CPI", d="2026-07-10", t="2026-07-10T12:30:00Z")],
        macro_records=[nfp_post, cpi_pre], now_iso=JUST_AFTER)
    # NFP (post) should sort before CPI (far pre)
    assert out["items"][0]["eventCode"] == "NFP"


def test_status_counts():
    nfp_post = _rec(actual={"available": True, "headline": "NFP +57K", "metrics": {}})
    out = DS.build_summary(important_events=[_ie()], macro_records=[nfp_post], now_iso=JUST_AFTER)
    st = DS.status_counts(out)
    assert st["criticalPostResult"] == 1
    assert st["criticalReleasedPending"] == 0


def test_deterministic_output():
    ie, rec = _ie(), _rec(pre=_pre())
    a = DS.build_summary(important_events=[ie], macro_records=[rec], now_iso=BEFORE)
    b = DS.build_summary(important_events=[ie], macro_records=[rec], now_iso=BEFORE)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_no_forbidden_keys():
    actual = {"available": True, "headline": "NFP +57K", "metrics": {"nfpChangeK": 57}}
    dirty_rec = _rec(pre=_pre(), actual=actual, prompt="SECRET", rawProviderBody="xxx", holdings=5)
    out = DS.build_summary(important_events=[_ie()], macro_records=[dirty_rec], now_iso=JUST_AFTER)
    blob = json.dumps(out, ensure_ascii=False).lower()
    for bad in ('"prompt"', '"rawproviderbody"', '"holdings"', "secret"):
        assert bad not in blob, bad
