"""2026-11-13 の点検で見つけた、つながっていない所・古くなった表の修正。

どれも「片方だけ名前や形が変わっていて、黙って空になる」「公式があとで変えた日付を
追えていない」という型。検査の見本が本物と違う形だったので、既存の検査では拾えなかった。
"""
from datetime import datetime, timezone

import argus_market_brief as mb
import argus_market_position_memory as mpm
import argus_news_intelligence as ni
import scanner


# ── 見立ての根拠: 波及経路 ──────────────────────────────────────────────

def _material_news(direction):
    return {"severity": "HIGH", "staleness": "FRESH_UPDATE",
            "confirmationState": "MARKET_CONFIRMATION_PENDING",
            "headlineJa": "米長期金利が上昇", "sourceFamily": "US_TREASURY",
            "sourceLabelJa": "米財務省", "impactDirection": direction}


def _path_facts(brief):
    return [fact["text"] for fact in brief["facts"] if fact["text"].startswith("波及経路: ")]


def test_the_path_the_news_engine_actually_writes_reaches_the_brief():
    # The engine's own output shape, not a hand-written fixture.
    direction = ni.resolve_impact_direction("RATES", "up") if hasattr(ni, "resolve_impact_direction") else None
    chain = (direction or {}).get("transmissionChain") or list(ni._DIR_TRANSMISSION_CHAINS[("RATES", "up")])
    assert chain and all(isinstance(step, str) for step in chain)
    brief = mb.compose_brief(now_iso="2026-11-13T00:00:00Z",
                             news_events=[_material_news({"transmissionChain": chain})])
    facts = _path_facts(brief)
    assert len(facts) == 1
    assert chain[0] in facts[0] and " → " in facts[0]


def test_an_older_single_string_path_still_wins_and_an_empty_chain_adds_nothing():
    brief = mb.compose_brief(now_iso="2026-11-13T00:00:00Z", news_events=[
        _material_news({"transmissionJa": "米長期金利↑→割引率上昇", "transmissionChain": ["別の経路"]})])
    assert _path_facts(brief) == ["波及経路: 米長期金利↑→割引率上昇"]
    for empty in ({}, {"transmissionChain": []}, {"transmissionChain": ["", " "]}, {"transmissionChain": None}):
        brief = mb.compose_brief(now_iso="2026-11-13T00:00:00Z", news_events=[_material_news(empty)])
        assert _path_facts(brief) == []


# ── 市場の現在位置の記憶 ────────────────────────────────────────────────

def test_an_ordinary_headline_count_is_not_remembered_as_a_theme_entry():
    assert {scanner._news_theme_level(n) for n in (0, 7, 8, 19, 20, 500)} == {"calm", "elevated", "high"}
    radar = {"status": "live", "asOf": "2026-11-13T01:40:00Z", "themes": [
        {"key": "energy_geopolitics", "labelJa": "エネルギー・地政学", "count": 5,
         "level": scanner._news_theme_level(5)},
        {"key": "rates_shock", "labelJa": "米長期金利ショック", "count": 9,
         "level": scanner._news_theme_level(9)}]}
    memory = mpm.empty()
    assert mpm.ingest_radar(memory, radar) == 1
    row, = [entry for entry in memory["entries"] if entry["kind"] == "RADAR"]
    assert row["measured"] == {"count": 9, "level": "elevated"}
    assert "calm" not in row["textJa"] and "elevated" in row["textJa"]


def test_rss_dated_headlines_are_kept_and_an_unreadable_date_uses_first_seen():
    items = [
        {"sourceId": "bloomberg", "title": "イラン革命防衛隊、ホルムズ海峡で艦船を拿捕",
         "publishedAt": "Thu, 12 Nov 2026 20:00:00 GMT", "firstDetectedAt": "2026-11-12T20:05:00Z"},
        {"sourceId": "cnbc", "title": "FRB高官、追加利上げに慎重",
         "publishedAt": "Fri, 13 Nov 2026 09:30:00 +0900", "firstDetectedAt": "2026-11-13T00:35:00Z"},
        {"sourceId": "odd", "title": "イラン、制裁に反発",
         "publishedAt": "yesterday evening", "firstDetectedAt": "2026-11-12T23:00:00Z"},
        {"sourceId": "old", "title": "イラン、協議を拒否",
         "publishedAt": "Tue, 20 Oct 2026 00:00:00 GMT", "firstDetectedAt": "2026-11-12T23:00:00Z"},
    ]
    memory = mpm.empty()
    added = mpm.ingest_public_headlines(memory, items, ni.classify_event, now_iso="2026-11-13T02:00:00Z")
    stamps = {entry["ref"]["sourceId"]: entry["at"] for entry in memory["entries"]
              if entry["kind"] == "PUBLIC_HEADLINE"}
    assert added == len(stamps) == 3
    assert stamps["bloomberg"] == "2026-11-12T20:00:00Z"
    assert stamps["cnbc"] == "2026-11-13T00:30:00Z"          # +09:00 is converted, not dropped
    assert stamps["odd"] == "2026-11-12T23:00:00Z"           # first seen
    assert "old" not in stamps                               # a readable old date is still too old
    assert mpm._rfc822_instant("2026-11-12T20:00:00Z") is None
    assert mpm._rfc822_instant(None) is None and mpm._rfc822_instant("") is None


# ── CFTC の次の公表を過ぎたか ──────────────────────────────────────────

def _held(monkeypatch, position_date):
    monkeypatch.setattr(scanner.jp_market_positioning, "latest_from_ledger",
                        lambda ledger, cutoff=None: {"positionDate": position_date})


def _utc(*parts):
    return datetime(*parts, tzinfo=timezone.utc)


def test_a_holiday_week_is_not_due_until_the_shifted_monday_release(monkeypatch):
    # Veterans Day week: the 2026-11-10 report is published Monday 2026-11-16,
    # 15:30 Eastern standard time = 20:30Z, not Friday 2026-11-13.
    _held(monkeypatch, "2026-11-03")
    assert not scanner._cftc_jpy_next_report_due(_utc(2026, 11, 13, 19, 45))
    assert not scanner._cftc_jpy_next_report_due(_utc(2026, 11, 15, 12, 0))
    assert not scanner._cftc_jpy_next_report_due(_utc(2026, 11, 16, 20, 30))
    assert scanner._cftc_jpy_next_report_due(_utc(2026, 11, 16, 20, 45))


def test_winter_time_moves_the_ordinary_friday_release_one_hour_later(monkeypatch):
    _held(monkeypatch, "2026-11-10")
    assert not scanner._cftc_jpy_next_report_due(_utc(2026, 11, 20, 19, 45))
    assert not scanner._cftc_jpy_next_report_due(_utc(2026, 11, 20, 20, 30))
    assert scanner._cftc_jpy_next_report_due(_utc(2026, 11, 20, 20, 45))


def test_a_release_year_outside_the_table_keeps_the_previous_rule(monkeypatch):
    _held(monkeypatch, "2026-12-29")           # next report: position 2027-01-05, released in 2027
    assert not scanner._cftc_jpy_next_report_due(_utc(2027, 1, 8, 19, 44))
    assert scanner._cftc_jpy_next_report_due(_utc(2027, 1, 8, 19, 45))


# ── 予定の表と銘柄の記号 ───────────────────────────────────────────────

def test_fomc_2027_follows_the_page_as_published_on_2026_11_12():
    assert scanner._FOMC_2027[-2:] == ["2027-10-27", "2027-11-17"]
    assert "2027-12-08" not in scanner._FOMC_2027
    assert scanner._next_fomc_after("2027-10-28") == "2027-11-17"
    assert scanner._next_fomc_after("2027-11-18") is None


def test_jolts_2027_is_scheduled_from_the_official_bls_page():
    assert scanner._JOLTS_2027 == [
        "2027-01-05", "2027-02-02", "2027-03-09", "2027-03-30", "2027-05-04", "2027-06-02",
        "2027-06-29", "2027-08-03", "2027-08-31", "2027-10-05", "2027-11-02", "2027-12-01"]
    spec = next(row for row in scanner._EVENT_SPECS if row[2] == "jolts")
    assert spec[0] == scanner._JOLTS_2026 + scanner._JOLTS_2027 and spec[1] == "10:00"
    assert scanner._JOLTS_2026[-1] < scanner._JOLTS_2027[0]


def test_renamed_us_tickers_are_followed_under_their_current_symbols():
    universe = scanner._US_MOVER_UNIVERSE
    assert "MRSH" in universe and "MMC" not in universe      # Marsh McLennan, 2026-01-14
    assert "FISV" in universe and "FI" not in universe       # Fiserv, 2025-11-11
    assert len(universe) == len(set(universe))


# ── 日本株の直近の決算開示(J-Quants) ───────────────────────────────────

class _JqResponse:
    def __init__(self, body, status=200):
        self._body, self.status_code = body, status

    def json(self):
        return self._body


def test_recent_disclosures_are_read_from_the_v2_list_with_its_field_names(monkeypatch):
    # 2026-11-13 12:00 JST, a trading day. V2 rows carry DiscDate / DocType.
    fixed = datetime(2026, 11, 13, 3, 0, tzinfo=timezone.utc).timestamp()
    calls = []

    def get(url, **kwargs):
        calls.append((url, dict(kwargs.get("params") or {})))
        if url.endswith("/equities/earnings-calendar"):
            return _JqResponse({"data": [{"Code": "80580", "Date": "2026-11-16"}]})
        assert url.endswith("/fins/summary"), url          # the retired /fins/details is not read
        code = kwargs["params"]["code"]
        if code == "8058":
            return _JqResponse({"data": [
                {"Code": "80580", "DiscDate": "2026-08-04", "DocType": "1QFinancialStatements_Consolidated_IFRS"},
                {"Code": "80580", "DiscDate": "2026-11-11", "DocType": "2QFinancialStatements_Consolidated_IFRS"},
                {"Code": "80580", "DiscDate": "", "DocType": "ignored"}]})
        if code == "9984":
            return _JqResponse({"data": [{"Code": "99840", "DiscDate": "2026-05-13", "DocType": "FYFinancialStatements"}]})
        return _JqResponse({"data": []})

    monkeypatch.setattr(scanner, "_JQUANTS_API_KEY", "test-key")
    monkeypatch.setattr(scanner, "_JQ_CAT_CACHE", {"data": None, "expires": 0.0})
    monkeypatch.setattr(scanner.requests, "get", get)
    monkeypatch.setattr(scanner.time, "time", lambda: fixed)
    data, status = scanner._jquants_catalysts()
    assert status == "delayed"
    assert data["nextEarn"] == {"8058": "2026-11-16"}
    # The newest disclosure within the bounded window is kept, with the V2 document type.
    assert data["details"]["8058"]["date"] == "2026-11-11"
    assert data["details"]["8058"]["type"] == "2QFinancialStatements_Consolidated_IFRS"
    assert "9984" not in data["details"]                   # a disclosure from May is outside the window
    assert {params.get("code") for url, params in calls if url.endswith("/fins/summary")} == {
        symbol for symbol, _ in scanner._JP_CAT_SYMBOLS}
