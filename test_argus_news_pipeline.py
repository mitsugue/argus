"""v13.5.3 news pipeline e2e (§32 PRODUCT): mocked Gmail → live endpoints."""
import base64
import time

import pytest

import scanner
import argus_gmail_intake as gi
import argus_causal_event_memory as cem
import argus_news_i18n as news_i18n


NOW_MS = str(int(time.time() * 1000))


class Resp:
    def __init__(self, status, body=None):
        self.status_code = status
        self._body = body or {}

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"http_{self.status_code}")


def b64(text):
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


def mail(mid, subject, *, sender="newsmail@nikkei.com",
         auth="spf=pass dkim=pass header.d=nikkei.com",
         body="詳細は本文参照 https://www.nikkei.com/article/a1"):
    return {
        "id": mid, "internalDate": NOW_MS,
        "payload": {
            "mimeType": "multipart/alternative",
            "headers": [
                {"name": "From", "value": f"日経 <{sender}>"},
                {"name": "Return-Path", "value": "<b@nikkei.com>"},
                {"name": "Authentication-Results",
                 "value": f"mx.google.com; {auth}"},
                {"name": "Subject", "value": subject},
                {"name": "Message-ID", "value": f"<{mid}@nikkei.com>"},
            ],
            "parts": [{"mimeType": "text/plain",
                       "body": {"data": b64(body)}}],
        },
    }


@pytest.fixture()
def news_env(monkeypatch, tmp_path):
    monkeypatch.setenv("ARGUS_NEWS_GMAIL_CLIENT_ID", "cid")
    monkeypatch.setenv("ARGUS_NEWS_GMAIL_CLIENT_SECRET", "sec")
    monkeypatch.setenv("ARGUS_NEWS_GMAIL_REFRESH_TOKEN", "rt")
    monkeypatch.setenv("ARGUS_NEWS_ALLOWED_SENDER_DOMAINS", "nikkei.com")
    monkeypatch.setattr(scanner, "_news_intake_file",
                        lambda: str(tmp_path / "news_state.json"))
    monkeypatch.setattr(scanner, "_causal_memory_file",
                        lambda: str(tmp_path / "causal_events.jsonl"))
    monkeypatch.setattr(scanner, "_CAUSAL_MEMORY", {
        "loaded": False, "state": cem.empty_state(), "loadStatus": "NOT_LOADED",
        "lastAppendAt": None, "lastRefreshAt": None, "lastRefreshEpoch": 0.0,
        "skippedLowValue": 0, "appendFailures": 0, "lastErrorClass": None,
    })
    monkeypatch.setitem(scanner._NEWS_LOADED, "value", True)
    fresh = {
        "intakeState": {}, "events": {}, "order": [], "audit": [],
        "aiCache": {}, "observedSenders": {},
        "health": dict(scanner._NEWS_INTEL["health"],
                       status="MAILBOX_UNCONFIGURED", emailsSeen=0,
                       quarantined=0, duplicatesSuppressed=0,
                       parseFailures=0, alertsEligible=0),
    }
    monkeypatch.setattr(scanner, "_NEWS_INTEL", fresh)
    # Never let a developer or production translation cache leak into this
    # deterministic public-surface contract.
    monkeypatch.setattr(scanner, "_NEWS_JA_CACHE", {})
    monkeypatch.setattr(scanner, "_NEWS_JA_STATE", {
        "restored": True, "lastTranslateAt": None,
        "translatedToday": 0, "translatedDay": None,
        "lastErrorClass": None, "restoredFrom": ["test"],
    })
    # keep corroboration deterministic and offline
    monkeypatch.setattr(scanner, "_news_corroboration",
                        lambda family, polarity=None: {
        "confirmed": True, "signals": ["vix_spike", "rates_move"],
        "readings": [{"key": "us30y", "labelJa": "米30年債", "value": 5.31,
                      "change": 22.0, "unit": "%", "asOf": "2026-08-19"}],
        "missing": []})
    monkeypatch.setattr(scanner, "_openai_prose",
                        lambda *a, **k: None)  # AI unavailable path
    return fresh


def gmail_routes(messages):
    responses = {
        "oauth2.googleapis.com": Resp(200, {"access_token": "at"}),
        "/messages?": None,
    }

    def http(method, url, **kw):
        if "oauth2.googleapis.com" in url:
            return Resp(200, {"access_token": "at"})
        for mid, raw in messages.items():
            if url.endswith(f"/messages/{mid}"):
                return Resp(200, raw)
        if "/messages" in url:
            return Resp(200, {"messages": [{"id": mid} for mid in messages]})
        if "/profile" in url:
            return Resp(200, {"historyId": "42"})
        if "/history" in url:
            return Resp(404, {})
        raise AssertionError(url)
    return http


def run_cycle(monkeypatch, messages, backfill=False):
    monkeypatch.setattr(scanner.requests, "request", gmail_routes(messages))
    return scanner._news_intake_cycle(backfill=backfill)


def test_material_mail_reaches_major_news_and_alert(monkeypatch, news_env):
    status = run_cycle(monkeypatch, {
        "m1": mail("m1", "米30年債利回りが5%を突破 急騰続く"),
        "m2": mail("m2", "コラム:今週の読まれた記事まとめ"),
    })
    assert status == "HEALTHY"
    client = scanner.app.test_client()
    body = client.get("/api/argus/news-intelligence").get_json()
    assert body["intakeStatus"] == "HEALTHY"
    events = body["events"]
    assert len(events) == 2
    top = events[0]
    assert top["eventType"] == "RATES"
    # Severity comes from the news content alone (family + extreme language);
    # the confirmed market reaction is reported on the independent axis and
    # never edits severity (owner spec §7).
    assert top["severity"] == "HIGH"
    assert top["confirmationState"] == "MARKET_CONFIRMED"
    assert top["alertEligible"] is True
    assert top["analysisState"] == "AI_ANALYSIS_UNAVAILABLE"
    assert top["sdaAuthority"] is False
    assert top["eventMemory"]["status"] in (
        "OPEN", "WATCHING", "PARTIALLY_CONFIRMED")
    assert top["eventMemory"]["calibrationMode"] == "SHADOW"
    low = events[1]
    assert low["severity"] == "INFO"              # low-value stays quiet
    assert low["alertEligible"] is False
    # copyright boundary: no body text in the public payload
    assert "詳細は本文参照" not in str(body)

    health = client.get("/api/argus/news-intake/health").get_json()
    assert health["status"] == "HEALTHY"
    assert health["emailsSeen"] == 2
    assert health["alertsEligible"] == 1
    assert health["observedSenderDomains"]["nikkei.com"]["count"] == 2
    memory = client.get("/api/argus/event-memory").get_json()
    assert memory["eventCount"] == 1  # INFO editorial mail never pollutes memory
    assert memory["automaticCalibrationEnabled"] is False


def test_generic_boj_mail_subject_is_not_major_news(monkeypatch, news_env):
    monkeypatch.setenv("ARGUS_NEWS_ALLOWED_SENDER_DOMAINS", "boj.or.jp")
    message = mail(
        "boj1", "日本銀行メール配信サービス 2026-08-21",
        sender="notice@boj.or.jp",
        auth="spf=pass dkim=pass header.d=boj.or.jp",
        body="日本銀行ホームページを更新しました。配信停止はこちら。 https://www.boj.or.jp/")
    run_cycle(monkeypatch, {"boj1": message})
    event = scanner.app.test_client().get(
        "/api/argus/news-intelligence").get_json()["events"][0]
    assert event["severity"] == "INFO"
    assert "メール配信サービス" not in event["headlineJa"]


def test_duplicate_email_and_spoof_quarantine(monkeypatch, news_env):
    subject = "日銀が臨時会合を開催へ"
    run_cycle(monkeypatch, {"d1": mail("d1", subject)})
    # same content arrives again under a new gmail id (newsletter re-send)
    run_cycle(monkeypatch, {"d1": mail("d1", subject),
                            "d2": mail("d2", subject)})
    health = scanner._NEWS_INTEL["health"]
    assert health["duplicatesSuppressed"] >= 1

    run_cycle(monkeypatch, {"s1": mail(
        "s1", "重要:口座確認のお願い", sender="x@nikkei.com.evil.jp",
        auth="spf=fail dkim=fail")})
    assert health["quarantined"] == 1
    client = scanner.app.test_client()
    events = client.get("/api/argus/news-intelligence").get_json()["events"]
    assert all("口座確認" not in e["headlineJa"] for e in events)


def test_backfill_is_marked_and_never_alert_eligible(monkeypatch, news_env):
    run_cycle(monkeypatch, {"r1": mail("r1", "米長期金利が急騰 財政懸念")},
              backfill=True)
    client = scanner.app.test_client()
    events = client.get("/api/argus/news-intelligence").get_json()["events"]
    assert events and events[0]["backfill"] is True
    assert events[0]["alertEligible"] is False


def test_escalation_realerts_but_cosmetic_duplicate_does_not(
        monkeypatch, news_env):
    subject = "イラン情勢が緊迫"
    monkeypatch.setattr(scanner, "_news_corroboration",
                        lambda family, polarity=None: {
        "confirmed": False, "signals": [], "readings": [], "missing": []})
    run_cycle(monkeypatch, {"e1": mail("e1", subject)})
    first = scanner.app.test_client().get(
        "/api/argus/news-intelligence").get_json()["events"][0]
    assert first["severity"] in ("WATCH", "HIGH")
    # market later confirms → severity increase on the SAME event → re-alert
    monkeypatch.setattr(scanner, "_news_corroboration",
                        lambda family, polarity=None: {
        "confirmed": True, "signals": ["vix_spike", "fx_shock"],
        "readings": [], "missing": []})
    run_cycle(monkeypatch, {"e2": mail(
        "e2", subject + " ホルムズ海峡で攻撃と報道")})
    events = scanner.app.test_client().get(
        "/api/argus/news-intelligence").get_json()["events"]
    assert any(e["severity"] in ("HIGH", "CRITICAL") and e["alertEligible"]
               for e in events)


def test_market_confirmation_transition_realerts_without_severity_change(
        monkeypatch, news_env):
    """Owner spec §7 end-to-end: the market CONFIRMING a material headline
    re-alerts (PENDING→CONFIRMED transition), while the severity axis itself
    never moves on confirmation."""
    subject = "米30年債利回りが5%を突破 急騰続く"
    monkeypatch.setattr(scanner, "_news_corroboration",
                        lambda family, polarity=None: {
        "confirmed": False, "signals": [], "readings": [], "missing": []})
    run_cycle(monkeypatch, {"c1": mail("c1", subject)})
    first = scanner.app.test_client().get(
        "/api/argus/news-intelligence").get_json()["events"][0]
    assert first["severity"] in ("HIGH", "CRITICAL")
    assert first["confirmationState"] == "MARKET_CONFIRMATION_PENDING"
    monkeypatch.setattr(scanner, "_news_corroboration",
                        lambda family, polarity=None: {
        "confirmed": True, "signals": ["us10y_shock"],
        "readings": [], "missing": []})
    run_cycle(monkeypatch, {"c2": mail("c2", subject + " 続報")})
    second = scanner.app.test_client().get(
        "/api/argus/news-intelligence").get_json()["events"][0]
    assert second["confirmationState"] == "MARKET_CONFIRMED"
    assert second["severity"] == first["severity"]
    assert second["alertEligible"] is True


def test_multi_source_families_resolve_and_apply_policy(monkeypatch, news_env):
    monkeypatch.setenv("ARGUS_NEWS_ALLOWED_SENDER_DOMAINS",
                       "nikkei.com,treas.gov,govdelivery.com,fdic.gov")
    messages = {
        "t1": mail("t1", "Daily Treasury Yield Curve Rates",
                   sender="treasury@subscriptions.treas.gov",
                   auth="spf=pass dkim=pass header.d=subscriptions.treas.gov",
                   body="rates table https://home.treasury.gov/rates"),
        "b1": mail("b1", "Consumer Price Index - July 2026",
                   sender="bls@service.govdelivery.com",
                   auth="spf=pass dkim=pass header.d=service.govdelivery.com",
                   body="CPI release https://www.bls.gov/cpi/latest.htm"),
        "f1": mail("f1", "FDIC press release",
                   sender="fdic@subscriptions.fdic.gov",
                   auth="spf=pass dkim=pass header.d=subscriptions.fdic.gov",
                   body="fdic https://www.fdic.gov/news"),
    }
    status = run_cycle(monkeypatch, messages)
    assert status == "HEALTHY"
    client = scanner.app.test_client()
    body = client.get("/api/argus/news-intelligence").get_json()
    # English agency titles remain classified evidence but are withheld from
    # owner surfaces until their Japanese cache entry exists.
    by_family = {e["sourceFamily"]: e
                 for e in news_env["events"].values()}
    assert body["events"] == []
    assert body["pendingTranslationCount"] == 2
    # Treasury daily rates: data input, never an alert (§14A)
    treasury = by_family["US_TREASURY"]
    assert treasury["severity"] == "INFO"
    assert treasury["dataInput"] is True
    assert treasury["alertEligible"] is False
    # GovDelivery-delivered BLS release keeps agency identity (§9) and stays
    # WATCH without invented surprise (§14A)
    bls = by_family["BLS"]
    assert bls["source"] == "米労働統計局"
    assert bls["severity"] == "WATCH"
    # FDIC is out of the six-family scope → quarantined, never Major News
    assert "FDIC" not in str(body)

    health = client.get("/api/argus/news-intake/health").get_json()
    per_source = health["perSource"]
    assert per_source["US_TREASURY"]["state"] == "OBSERVED"
    assert per_source["BLS"]["state"] == "OBSERVED"
    assert per_source["BANK_OF_JAPAN"]["state"] \
        == "SUBSCRIBED_NO_MESSAGE_OBSERVED_YET"
    assert health["quarantined"] >= 1
    statuses = {row["messageId"]: row["status"]
                for row in health["recentMessages"]}
    assert statuses["t1"] == "LOW_RELEVANCE"
    assert statuses["b1"] == "SURFACED"
    assert statuses["f1"] == "QUARANTINED"


def test_english_news_is_withheld_until_japanese_translation_exists(
        monkeypatch, news_env):
    subject = "Treasury Increases Sanctions on Target Network"
    run_cycle(monkeypatch, {"en1": mail("en1", subject)})
    client = scanner.app.test_client()

    pending = client.get("/api/argus/news-intelligence").get_json()
    assert pending["events"] == []
    assert pending["pendingTranslationCount"] == 1

    scanner._NEWS_JA_CACHE[news_i18n.text_hash(subject)] = {
        "ja": "米財務省、対象ネットワークへの制裁を強化",
        "at": "2026-08-21T00:00:00Z",
    }
    translated = client.get("/api/argus/news-intelligence").get_json()
    assert translated["pendingTranslationCount"] == 0
    assert translated["eventCount"] == 1
    event = translated["events"][0]
    assert event["headlineJa"] == "米財務省、対象ネットワークへの制裁を強化"
    assert event["translationStatus"] == "translated"
    assert event["titleOriginal"] == subject
    assert subject not in event["headlineJa"]


def test_admin_audit_view_is_gated_and_answers_why(monkeypatch, news_env):
    run_cycle(monkeypatch, {"m9": mail("m9", "FOMC statement: policy action",
                                       sender="frb@announcements.federalreserve.gov",
                                       auth="spf=pass dkim=pass")})
    client = scanner.app.test_client()
    denied = client.get("/api/argus/admin/news-intake/audit")
    assert denied.status_code in (401, 403, 503)
    monkeypatch.setattr(scanner, "_ARGUS_ADMIN_TOKEN", "audit-test-token")
    allowed = client.get("/api/argus/admin/news-intake/audit",
                         headers={"X-ARGUS-ADMIN-TOKEN": "audit-test-token"})
    assert allowed.status_code == 200
    rows = allowed.get_json()["audit"]
    assert any(r.get("stage") == "quarantined" or r.get("stage") == "classified"
               for r in rows)


# ━━━ v13.5.22 — durable source acceptance + classification-first display ━━━

def _seed_event(eid, family, severity, title, ja, received):
    return {
        "schemaVersion": "argus-news-event-v1", "eventId": eid, "revision": 1,
        "source": family, "sourceFamily": family,
        "sourceTier": "official_agency", "dataInput": False,
        "sourceFingerprint": "fp-" + eid, "sourceReceivedAt": received,
        "sourcePublishedAt": None, "processedAt": received,
        "titleOriginal": title, "headlineJa": ja, "eventType": "RATES",
        "themeTags": [], "facts": [], "entities": [], "sourceUrl": None,
        "staleness": "FRESH_UPDATE", "severity": severity,
        "severityReasons": ["r"],
        "confirmationState": "MARKET_CONFIRMATION_PENDING",
        "whyJa": "w", "japanImpactJa": None, "uncertaintyJa": None,
        "marketReadings": [], "analysisState": "DETERMINISTIC_ONLY",
        "policyVersion": "news-policy-v3", "authority": "NEWS_RISK_EVIDENCE",
        "sdaAuthority": False, "backfill": False, "alertEligible": False,
    }


def _reset_news_store(tmp_path, monkeypatch):
    monkeypatch.setattr(scanner, "_news_intake_file",
                        lambda: str(tmp_path / "news_intake_state.json"))
    scanner._NEWS_INTEL["events"] = {}
    scanner._NEWS_INTEL["order"] = []
    scanner._NEWS_INTEL["audit"] = []
    scanner._NEWS_INTEL["sources"] = {}
    scanner._NEWS_INTEL["observedSenders"] = {}
    scanner._NEWS_INTEL["messageStatus"] = {}
    scanner._NEWS_INTEL["messageOrder"] = []


def test_source_acceptance_is_derived_from_durable_evidence(tmp_path, monkeypatch):
    """外部レビュー: 受理実証はプロセスメモリでなく永続ストアから導出。
    実イベントあり=REAL_MAIL_ACCEPTED / 検疫のみ=QUARANTINED /
    それ以外=NO_MAIL_RECEIVED_YET(受理と偽らない)。"""
    _reset_news_store(tmp_path, monkeypatch)
    scanner._NEWS_INTEL["events"]["e1"] = _seed_event(
        "e1", "BANK_OF_JAPAN", "INFO", "BOJ schedule", "日銀の定期配信",
        "2026-08-21T08:52:10Z")
    scanner._NEWS_INTEL["audit"].append(
        {"stage": "quarantined", "source": "EIA", "fromDomain": "x.example"})
    acceptance = scanner._news_source_acceptance()
    per = acceptance["perSource"]
    assert per["BANK_OF_JAPAN"]["verdict"] == "REAL_MAIL_ACCEPTED"
    assert per["BANK_OF_JAPAN"]["latestReceivedAt"] == "2026-08-21T08:52:10Z"
    assert per["EIA"]["verdict"] == "QUARANTINED"
    for family in ("NIKKEI", "FEDERAL_RESERVE_BOARD", "US_TREASURY", "BLS"):
        assert per[family]["verdict"] == "NO_MAIL_RECEIVED_YET"
    assert acceptance["overallVerdict"] == "PARTIAL_SOURCE_ACCEPTANCE"


def test_source_ledgers_survive_persist_and_reload(tmp_path, monkeypatch):
    _reset_news_store(tmp_path, monkeypatch)
    scanner._news_source_row("US_TREASURY")["observedCount"] = 8
    scanner._news_source_row("US_TREASURY")["lastAuthenticatedAt"] = \
        "2026-08-23T11:14:00Z"
    scanner._news_message_status("m-77", "SURFACED", "US_TREASURY")
    scanner._NEWS_INTEL["health"]["quarantined"] = 3
    scanner._news_intel_persist()
    scanner._NEWS_INTEL["sources"] = {}
    scanner._NEWS_INTEL["messageStatus"] = {}
    scanner._NEWS_INTEL["health"]["quarantined"] = 0
    scanner._news_intel_load()
    assert scanner._NEWS_INTEL["sources"]["US_TREASURY"]["observedCount"] == 8
    assert scanner._NEWS_INTEL["messageStatus"]["m-77"]["status"] == "SURFACED"
    assert scanner._NEWS_INTEL["health"]["quarantined"] == 3


def test_material_english_event_surfaces_before_translation(tmp_path, monkeypatch):
    """翻訳は表示レイヤー: HIGH/CRITICALの英文イベントはプレースホルダで
    即時表示(認識を翻訳待ちにしない)。INFO/WATCHは従来どおり要約待ち。"""
    _reset_news_store(tmp_path, monkeypatch)
    scanner._NEWS_INTEL["events"]["hi"] = _seed_event(
        "hi", "US_TREASURY", "HIGH",
        "Treasury announces new sanctions package", "翻訳処理中",
        "2026-08-23T11:14:00Z")
    scanner._NEWS_INTEL["events"]["lo"] = _seed_event(
        "lo", "BLS", "INFO", "Regular data release note", "翻訳処理中",
        "2026-08-23T10:00:00Z")
    scanner._NEWS_INTEL["order"] = ["lo", "hi"]
    body = scanner.app.test_client().get(
        "/api/argus/news-intelligence").get_json()
    served = {e["eventId"]: e for e in body["events"]}
    assert "hi" in served, "material English mail must not stay invisible"
    assert served["hi"]["translationPending"] is True
    assert "重要発表を検知" in served["hi"]["headlineJa"]
    assert "Treasury announces" not in served["hi"]["headlineJa"]
    assert "lo" not in served
    assert body["pendingTranslationCount"] >= 1
