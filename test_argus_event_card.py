"""ARGUS Pro — EventCard v2 discipline tests (Phase 2).

The card must never promote association to cause, never let a theme-only link move
the Today call, always apply the visibility cap, and always say what's missing.
"""
from datetime import datetime, timezone

import argus_event_card as EC
import scanner

ENV = {
    "eventId": "e1", "eventType": "PRICE_MOVE", "symbol": "NVDA", "market": "US",
    "source": "marketwatch_public", "reliabilityScore": 0.6, "triggerScore": 0.5,
    "reasonJa": "急落を検知", "linkedAssets": [], "evidenceIds": ["ev1"],
    "detectedAt": "2026-07-01T05:00:00Z", "lifecycleState": "DETECTED",
    "nextOpenAt": None, "recommendedPosture": "WATCH",
}


def card(**kw):
    return EC.build_card(ENV, **kw)


def test_single_source_is_never_confirmed_cause():
    c = card(independent_family_count=1, has_official=False, market_confirmed=False)
    assert c["corroborationLevel"] == "single_source"
    assert c["triggerRole"] == "candidate_catalyst"
    assert c["triggerRole"] != "confirmed_cause"


def test_market_confirmed_alone_without_official_is_not_confirmed_cause():
    c = card(independent_family_count=1, has_official=False, market_confirmed=True)
    assert c["corroborationLevel"] == "market_confirmed"
    assert c["triggerRole"] != "confirmed_cause"


def test_official_gives_official_corroboration():
    c = card(independent_family_count=1, has_official=True, market_confirmed=False)
    assert c["corroborationLevel"] == "official"
    assert c["triggerRole"] == "probable_catalyst"


def test_confirmed_cause_requires_official_and_market():
    c = card(independent_family_count=2, has_official=True, market_confirmed=True)
    assert c["corroborationLevel"] == "official_and_market_confirmed"
    assert c["triggerRole"] == "confirmed_cause"


def test_two_independent_families_are_probable_not_confirmed():
    c = card(independent_family_count=2, has_official=False, market_confirmed=False)
    assert c["corroborationLevel"] == "multi_source"
    assert c["triggerRole"] == "probable_catalyst"


def test_visibility_cap_lowers_confidence_final():
    g = {"confidenceCap": 0.3, "blockedActions": [], "reasonCodes": ["CALIBRATION_BURN_IN"],
         "visibilityLevel": "reduced"}
    c = card(independent_family_count=2, has_official=True, market_confirmed=True, guard=g)
    assert c["confidenceFinal"] <= 0.3
    assert c["confidenceFinal"] <= c["confidenceRaw"]
    assert c["visibility"]["confidenceCap"] == 0.3


def test_missing_market_depth_appears_in_missing_confirmations():
    c = card(independent_family_count=1, missing_depth=["L2", "TAPE"])
    assert "market_depth:L2" in c["missingConfirmations"]
    assert "market_depth:TAPE" in c["missingConfirmations"]


def test_every_card_states_missing_official_and_market():
    c = card(independent_family_count=1, has_official=False, market_confirmed=False)
    assert "official_confirmation" in c["missingConfirmations"]
    assert "market_confirmation" in c["missingConfirmations"]


def test_theme_only_cannot_move_today_call():
    c = card(independent_family_count=1, theme_only=True, market_confirmed=False)
    assert c["triggerRole"] == "background_theme"
    assert c["decisionImpact"]["canAffectTodayCall"] is False


def test_event_after_move_is_never_immediate_trigger():
    c = card(independent_family_count=2, has_official=True, market_confirmed=True,
             event_after_move=True)
    assert c["triggerRole"] in ("vulnerability_context", "background_theme")


def test_schema_version_and_empty_input():
    assert EC.build_card(ENV)["schemaVersion"] == "event-card-v2"
    assert EC.build_cards([]) == []


def test_blocked_entry_downgrades_posture_delta():
    g = {"confidenceCap": None, "blockedActions": ["ENTER"], "reasonCodes": ["BRIDGE_STALE"],
         "visibilityLevel": "reduced"}
    c = card(independent_family_count=2, has_official=True, market_confirmed=True, guard=g)
    assert c["decisionImpact"]["blockedActions"] == ["ENTER"]
    assert c["decisionImpact"]["postureDelta"] == "downgrade"
    assert c["decisionImpact"]["downgradeReasonJa"]


# ── TDnet → EventCard integration (v11.1.1) ─────────────────────────────────
def _tdnet_fixture(official, *, material=True, disclosed_at=None):
    row = {"code": "8058", "title": "業績予想の修正（下方修正）に関するお知らせ",
           "material": material, "official": official,
           "disclosedAt": disclosed_at or scanner._ai_now_iso(),
           "provider": ("jquants-tdnet" if official else "yanoshin-tdnet")}
    return {"status": ("official_tdnet_live" if official else "live"), "official": official,
            "provider": row["provider"], "items": [row], "bySymbol": {"8058": [row]}}


def test_official_tdnet_disclosure_sets_official_on_event_context(monkeypatch):
    monkeypatch.setattr(scanner, "get_tdnet_recent", lambda limit=150: _tdnet_fixture(True))
    env = {"eventId": "e-8058", "eventType": "PRICE_CRASH", "symbol": "8058",
           "source": "moomoo_push", "observedAt": scanner._ai_now_iso(),
           "detectedAt": scanner._ai_now_iso()}
    ctx = scanner._event_card_context([env])["e-8058"]
    assert ctx["has_official"] is True
    assert "official:tdnet" in (ctx["source_ids"] or [])
    assert "exchange_or_listing_venue" in ctx["source_tiers"]


def test_fallback_tdnet_does_not_set_official(monkeypatch):
    # yanoshin (official=False) is a lower-tier wrapper — it must NOT mint an
    # official confirmation on the EventCard.
    monkeypatch.setattr(scanner, "get_tdnet_recent", lambda limit=150: _tdnet_fixture(False))
    env = {"eventId": "e-8058", "eventType": "PRICE_CRASH", "symbol": "8058", "source": "moomoo_push"}
    ctx = scanner._event_card_context([env])["e-8058"]
    assert ctx["has_official"] is False
    assert "official:tdnet" not in (ctx["source_ids"] or [])


def test_fallback_row_cannot_be_laundered_by_official_snapshot_claim(monkeypatch):
    fallback = _tdnet_fixture(False)
    fallback.update({"official": True, "status": "official_tdnet_live"})
    monkeypatch.setattr(scanner, "get_tdnet_recent", lambda limit=150: fallback)
    env = {"eventId": "e-fallback", "eventType": "PRICE_MOVE",
           "symbol": "8058", "source": "moomoo_push",
           "detectedAt": scanner._ai_now_iso()}
    ctx = scanner._event_card_context([env])["e-fallback"]
    card = EC.build_card(env, **ctx)
    assert ctx["has_official"] is False
    assert ctx["independent_family_count"] == 0
    assert card["triggerRole"] == "candidate_catalyst"


def test_non_material_official_notice_does_not_confirm_price_cause(monkeypatch):
    monkeypatch.setattr(
        scanner, "get_tdnet_recent",
        lambda limit=150: _tdnet_fixture(True, material=False))
    env = {"eventId": "e-admin", "eventType": "PRICE_MOVE", "symbol": "8058",
           "source": "moomoo_push", "reliabilityScore": 0.8,
           "triggerScore": 0.8}
    ctx = scanner._event_card_context([env])["e-admin"]
    card = EC.build_card(env, **ctx)
    assert ctx["has_official"] is False
    assert ctx["independent_family_count"] == 0
    assert "official:tdnet" not in (ctx["source_ids"] or [])
    assert card["triggerRole"] == "candidate_catalyst"
    assert card["decisionImpact"]["canAffectTodayCall"] is False


def test_post_move_official_disclosure_is_not_the_price_trigger(monkeypatch):
    monkeypatch.setattr(scanner.time, "time", lambda: 1_786_669_200.0)
    monkeypatch.setattr(
        scanner, "get_tdnet_recent",
        lambda limit=150: _tdnet_fixture(
            True, disclosed_at="2026-08-14T00:59:00Z"))
    env = {"eventId": "e-post-move", "eventType": "PRICE_CRASH",
           "symbol": "8058", "source": "moomoo-bridge",
           "observedAt": "2026-08-14T00:30:00Z",
           "sourceTimeValidated": True,
           "detectedAt": "2026-08-14T00:31:00Z",
           "reliabilityScore": 0.8, "triggerScore": 0.8}
    ctx = scanner._event_card_context([env])["e-post-move"]
    card = EC.build_card(env, **ctx)
    assert ctx["has_official"] is False
    assert ctx["independent_family_count"] == 0
    assert card["corroborationLevel"] == "market_confirmed"
    assert card["triggerRole"] == "candidate_catalyst"
    assert card["decisionImpact"]["canAffectTodayCall"] is False


def test_fresh_detection_receipt_cannot_replace_price_source_time(monkeypatch):
    monkeypatch.setattr(scanner.time, "time", lambda: 1_786_669_200.0)
    env = {"eventId": "e-no-source-time", "eventType": "PRICE_MOVE",
           "symbol": "7203", "source": "moomoo-rt",
           "observedAt": None, "detectedAt": "2026-08-14T01:00:00Z",
           "reliabilityScore": 0.8, "triggerScore": 0.8}
    ctx = scanner._event_card_context(
        [env], tdnet_snapshot={})["e-no-source-time"]
    card = EC.build_card(env, **ctx)
    assert ctx["market_confirmed"] is False
    assert ctx["independent_family_count"] == 0
    assert card["corroborationLevel"] == "none"
    assert card["decisionImpact"]["canAffectTodayCall"] is False


def test_restored_event_source_never_mints_official_authority(monkeypatch):
    monkeypatch.setattr(scanner.time, "time", lambda: 1_786_669_200.0)
    for observed_at in (None, "malformed", "2026-08-10T01:00:00Z"):
        env = {"eventId": f"e-official-{observed_at}",
               "eventType": "CORPORATE_DISCLOSURE", "symbol": "8058",
               "source": "tdnet", "observedAt": observed_at,
               "detectedAt": "2026-08-14T01:00:00Z",
               "reliabilityScore": 0.8, "triggerScore": 0.8}
        ctx = scanner._event_card_context(
            [env], tdnet_snapshot={})[env["eventId"]]
        card = EC.build_card(env, **ctx)
        assert ctx["independent_family_count"] == 0
        assert ctx["has_official"] is False
        assert card["decisionImpact"]["canAffectTodayCall"] is False

    valid = {"eventId": "e-official-valid",
             "eventType": "CORPORATE_DISCLOSURE", "symbol": "8058",
             "source": "tdnet", "observedAt": "2026-08-14T00:59:00Z",
             "detectedAt": "2026-08-14T01:00:00Z",
             "reliabilityScore": 0.8, "triggerScore": 0.8}
    valid_ctx = scanner._event_card_context(
        [valid], tdnet_snapshot={})[valid["eventId"]]
    valid_card = EC.build_card(valid, **valid_ctx)
    assert valid_ctx["independent_family_count"] == 0
    assert valid_ctx["has_official"] is False
    assert valid_card["triggerRole"] == "candidate_catalyst"
    assert valid_card["decisionImpact"]["canAffectTodayCall"] is False


def test_card_defaults_and_malformed_authority_claims_fail_closed():
    direct = EC.build_card({**ENV, "source": "tdnet"})
    malformed = EC.build_card(
        ENV, source_ids="tdnet", independent_family_count=True,
        has_official="true", market_confirmed="true",
        theme_only="false", event_after_move="false")
    for result in (direct, malformed):
        assert result["corroborationLevel"] == "none"
        assert result["triggerRole"] == "candidate_catalyst"
        assert result["decisionImpact"]["canAffectTodayCall"] is False


def test_weak_intel_cannot_turn_price_confirmation_into_probable_cause(monkeypatch):
    now = 1_786_669_200.0
    monkeypatch.setattr(scanner.time, "time", lambda: now)
    env = {"eventId": "e-7203", "eventType": "PRICE_MOVE", "symbol": "7203",
           "source": "moomoo-rt", "reliabilityScore": 0.8,
           "triggerScore": 0.8, "reasonJa": "値動きを検知",
           "observedAt": "2026-08-14T01:00:00Z",
           "sourceTimeValidated": True}

    for source_id, claimed_grounding in (
            ("some_random_blog_xyz", False),
            ("yahoo_finance_public", True)):
        monkeypatch.setattr(scanner, "_INTEL_STORE", [{
            "sourceId": source_id,
            "sourceTier": "reputable_financial_media",  # forged claim is ignored
            "accessClass": "PUBLIC_METADATA",
            "canGroundJudgment": claimed_grounding,
            "weakSignal": not claimed_grounding,
            "publishedAt": "2026-08-14T00:59:00Z",
            "linkedAssets": ["7203"],
            "title": "7203 price story",
        }])
        ctx = scanner._event_card_context(
            [env], tdnet_snapshot={})["e-7203"]
        card = EC.build_card(env, **ctx)
        assert ctx["independent_family_count"] == 0
        assert source_id not in (ctx["source_ids"] or [])
        assert card["corroborationLevel"] == "market_confirmed"
        assert card["triggerRole"] == "candidate_catalyst"
        assert card["decisionImpact"]["canAffectTodayCall"] is False


def test_two_grounding_news_families_can_corroborate_a_price_event(monkeypatch):
    monkeypatch.setattr(scanner.time, "time", lambda: 1_786_669_200.0)
    monkeypatch.setattr(scanner, "_INTEL_STORE", [{
        "sourceId": source_id,
        "sourceTier": "reputable_financial_media",
        "accessClass": "PUBLIC_METADATA",
        "canGroundJudgment": True,
        "weakSignal": False,
        "publishedAt": "2026-08-14T00:59:00Z",
        "linkedAssets": ["7203"],
        "title": f"7203 coverage from {source_id}",
    } for source_id in ("reuters_jp", "bloomberg_public")])
    env = {"eventId": "e-grounded", "eventType": "PRICE_MOVE",
           "symbol": "7203", "source": "moomoo-rt",
           "observedAt": "2026-08-14T01:00:00Z",
           "sourceTimeValidated": True,
           "reliabilityScore": 0.8, "triggerScore": 0.8}
    ctx = scanner._event_card_context(
        [env], tdnet_snapshot={})["e-grounded"]
    card = EC.build_card(env, **ctx)
    assert ctx["independent_family_count"] == 2
    assert card["triggerRole"] == "probable_catalyst"
    assert card["decisionImpact"]["canAffectTodayCall"] is True


def test_unavailable_licensed_feed_cannot_add_a_grounding_family(monkeypatch):
    monkeypatch.setattr(scanner.time, "time", lambda: 1_786_669_200.0)
    raw_items = [{
        "sourceId": source_id,
        "publishedAt": "2026-08-14T00:59:00Z",
        "linkedAssets": ["7203"],
        "title": f"7203 coverage from {source_id}",
    } for source_id in ("reuters_jp", "bloomberg_feed")]
    monkeypatch.setattr(
        scanner, "_INTEL_STORE",
        [scanner.argus_research_mesh.normalize_item(raw) for raw in raw_items])
    assert scanner._INTEL_STORE[1]["accessClass"] == "UNAVAILABLE"
    assert scanner._INTEL_STORE[1]["canGroundJudgment"] is False
    env = {"eventId": "e-disabled-feed", "eventType": "PRICE_MOVE",
           "symbol": "7203", "source": "moomoo-rt",
           "observedAt": "2026-08-14T01:00:00Z",
           "sourceTimeValidated": True,
           "reliabilityScore": 0.8, "triggerScore": 0.8}
    ctx = scanner._event_card_context(
        [env], tdnet_snapshot={})[env["eventId"]]
    card = EC.build_card(env, **ctx)
    assert ctx["independent_family_count"] == 1
    assert "bloomberg_feed" not in (ctx["source_ids"] or [])
    assert card["triggerRole"] == "candidate_catalyst"
    assert card["decisionImpact"]["canAffectTodayCall"] is False


def test_post_move_news_families_cannot_corroborate_a_price_trigger(monkeypatch):
    monkeypatch.setattr(scanner.time, "time", lambda: 1_786_669_200.0)
    monkeypatch.setattr(scanner, "_INTEL_STORE", [{
        "sourceId": source_id,
        "sourceTier": "reputable_financial_media",
        "accessClass": "PUBLIC_METADATA",
        "canGroundJudgment": True,
        "weakSignal": False,
        "publishedAt": "2026-08-14T00:59:00Z",
        "linkedAssets": ["7203"],
        "title": f"7203 post-move coverage from {source_id}",
    } for source_id in ("reuters_jp", "bloomberg_public")])
    env = {"eventId": "e-post-news", "eventType": "PRICE_MOVE",
           "symbol": "7203", "source": "moomoo-rt",
           "observedAt": "2026-08-14T00:30:00Z",
           "sourceTimeValidated": True,
           "detectedAt": "2026-08-14T00:31:00Z",
           "reliabilityScore": 0.8, "triggerScore": 0.8}
    ctx = scanner._event_card_context(
        [env], tdnet_snapshot={})["e-post-news"]
    card = EC.build_card(env, **ctx)
    assert ctx["independent_family_count"] == 0
    assert card["triggerRole"] == "candidate_catalyst"
    assert card["decisionImpact"]["canAffectTodayCall"] is False


def test_push_event_preserves_provider_time_as_causal_boundary(monkeypatch):
    now_epoch = 1_786_669_200.0
    now_dt = datetime.fromtimestamp(now_epoch, timezone.utc)

    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return now_dt if tz is None else now_dt.astimezone(tz)

    monkeypatch.setattr(scanner, "datetime", FixedDatetime)
    monkeypatch.setattr(scanner.time, "time", lambda: now_epoch)
    monkeypatch.setattr(scanner, "_EVENT_BACKBONE_ENABLED", True)
    monkeypatch.setattr(scanner, "_us_market_open", lambda: True)
    monkeypatch.setattr(scanner.argus_events, "detect_acceleration",
                        lambda *_args, **_kwargs: [])
    monkeypatch.setattr(scanner, "_build_event_dossier",
                        lambda *_args, **_kwargs: {})
    monkeypatch.delenv("NTFY_TOPIC", raising=False)
    scanner._EVENTS_ACTIVE.clear()
    scanner._EVENTS_LOG.clear()
    monkeypatch.setattr(scanner, "_INTEL_STORE", [{
        "sourceId": source_id,
        "sourceTier": "reputable_financial_media",
        "accessClass": "PUBLIC_METADATA",
        "canGroundJudgment": True,
        "weakSignal": False,
        # Five minutes after the provider observed the move, but five minutes
        # before ARGUS received the quote.
        "publishedAt": "2026-08-14T00:55:00Z",
        "linkedAssets": ["AAPL"],
        "title": f"AAPL coverage from {source_id}",
    } for source_id in ("reuters_jp", "bloomberg_public")])

    scanner._process_events_from_push("US", [{
        "symbol": "AAPL", "price": 106.0, "changeAbs": 6.0,
        "changePct": 6.0, "exchangeTs": "2026-08-14T00:50:00Z",
        "entitlement": "realtime", "realtimeEvidence": True,
    }])

    env = next(iter(scanner._EVENTS_ACTIVE.values()))
    assert env["observedAt"] == "2026-08-14T00:50:00Z"
    assert env["detectedAt"] == "2026-08-14T01:00:00Z"
    assert env["sourceTimeValidated"] is True
    ctx = scanner._event_card_context([env], tdnet_snapshot={})[env["eventId"]]
    card = EC.build_card(env, **ctx)
    assert ctx["market_confirmed"] is True
    assert ctx["independent_family_count"] == 0
    assert card["triggerRole"] == "candidate_catalyst"
    assert card["decisionImpact"]["canAffectTodayCall"] is False


def test_restored_price_event_requires_admitted_market_provider(monkeypatch):
    monkeypatch.setattr(scanner.time, "time", lambda: 1_786_669_200.0)
    tdnet = _tdnet_fixture(
        True, disclosed_at="2026-08-14T00:40:00Z")
    for source in (None, "some_random_blog_xyz", "moomoo_push"):
        env = {"eventId": f"e-restored-{source}",
               "eventType": "PRICE_CRASH", "symbol": "8058",
               "source": source, "observedAt": "2026-08-14T00:50:00Z",
               "sourceTimeValidated": True,
               "reliabilityScore": 0.8, "triggerScore": 0.8}
        ctx = scanner._event_card_context(
            [env], tdnet_snapshot=tdnet)[env["eventId"]]
        card = EC.build_card(env, **ctx)
        assert ctx["has_official"] is True
        assert ctx["market_confirmed"] is False
        assert card["corroborationLevel"] == "official"
        assert card["triggerRole"] == "probable_catalyst"
        assert card["decisionImpact"]["canAffectTodayCall"] is True


def test_durable_restore_revokes_prior_price_source_attestation(monkeypatch):
    now = 1_786_669_200.0
    monkeypatch.setattr(scanner.time, "time", lambda: now)
    raw = {"eventId": "e-restored-authorized",
           "deduplicationKey": "JP:8058:PRICE_CRASH:1",
           "eventType": "PRICE_CRASH", "market": "JP", "symbol": "8058",
           "source": "moomoo-rt", "observedAt": "2026-08-14T00:50:00Z",
           "sourceTimestamp": "2026-08-14T00:50:00Z",
           "sourceTimeValidated": True,
           "expiresAt": "2026-08-14T02:00:00Z",
           "reliabilityScore": 0.8, "triggerScore": 0.8}
    snapshot = {"schemaVersion": "event-store-v1", "active": [raw], "log": []}
    active, _ = scanner.argus_event_store.restore_state(
        snapshot, now, scanner._parse_iso_epoch,
        lambda env: env.get("deduplicationKey"))
    restored = next(iter(active.values()))
    assert restored["sourceTimeValidated"] is False
    ctx = scanner._event_card_context(
        [restored], tdnet_snapshot=_tdnet_fixture(
            True, disclosed_at="2026-08-14T00:40:00Z"))[restored["eventId"]]
    card = EC.build_card(restored, **ctx)
    assert ctx["has_official"] is True
    assert ctx["market_confirmed"] is False
    assert card["corroborationLevel"] == "official"
    assert card["triggerRole"] == "probable_catalyst"
