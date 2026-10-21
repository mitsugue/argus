"""Blank valuation members supplied from daily bars and prior forecasts (2026-10-21)."""
import jp_market_level_map as m
import argus_level_map_backfill as b


def _row(cap, fwd_per):
    return {'MktCap': cap, 'FwdPER': fwd_per}


def _valuation():
    rows = {'1001': _row(1000.0, 10.0), '1002': _row(2000.0, 20.0),
            '543A': {'MktCap': '', 'FwdPER': '', 'PER': '', 'FwdEPS': '', 'EPS': '', 'PBR': ''}}
    return rows


BARS = {'543A': [{'Date': '2026-07-14', 'Code': '543A0', 'MktCap': 3000.0},
                 {'Date': '2026-07-15', 'Code': '543A0', 'MktCap': 3100.0}]}
DISCLOSURES = {'543A': [
    {'Code': '543A0', 'DiscDate': '2026-05-14', 'DiscTime': '15:30:00', 'DiscNo': 'A', 'DocType': 'EarnForecastRevision', 'FNP': '150000000'},
    {'Code': '543A0', 'DiscDate': '2026-07-15', 'DiscTime': '15:30:00', 'DiscNo': 'B', 'DocType': '1QFinancialStatements', 'FNP': '600000000'},
]}


def test_blank_member_detected_only_when_all_fields_blank():
    rows = _valuation()
    assert m.blank_members(rows, ['1001', '1002', '543A', '9999']) == ['543A']
    rows['543A']['EPS'] = 5.0
    assert m.blank_members(rows, ['1001', '1002', '543A']) == []


def test_forecast_uses_newest_disclosure_before_the_day():
    value, disclosure = m.forecast_net_income(DISCLOSURES['543A'], before='2026-07-15')
    assert value == 150.0 and disclosure['discNo'] == 'A'      # same-day disclosure excluded
    value, disclosure = m.forecast_net_income(DISCLOSURES['543A'], before='2026-07-16')
    assert value == 600.0 and disclosure['discNo'] == 'B'
    assert m.forecast_net_income(DISCLOSURES['543A'], before='2026-05-14') is None


def test_full_year_statement_uses_next_year_forecast_and_non_consolidated_fallback():
    rows = [{'DiscDate': '2026-05-01', 'DocType': 'FYFinancialStatements_Consolidated_JP', 'FNP': '1', 'NxFNp': '2000000'},
            {'DiscDate': '2026-04-01', 'DocType': '3QFinancialStatements_NonConsolidated_JP', 'FNP': '', 'FNCNP': '9000000'}]
    assert m.forecast_net_income(rows, before='2026-05-02')[0] == 2.0
    assert m.forecast_net_income(rows, before='2026-05-01')[0] == 9.0


def test_supplied_estimate_is_complete_and_counted_apart():
    rows = _valuation()
    members = ['1001', '1002', '543A']
    plain = m.weighted_eps(rows, members, index_close=10000.0, date='2026-07-14', constituents_as_of='t')
    assert plain['coverage']['missingMarketCap'] == 1
    assert not m.estimate_input_usable(plain, strict=True)
    joined, supplied = m.valuation_with_supplied_members(rows, members, BARS, DISCLOSURES, date='2026-07-14')
    assert list(supplied) == ['543A'] and supplied['543A']['marketCap'] == 3000.0
    assert rows['543A']['MktCap'] == ''                         # the original rows are not changed
    est = m.weighted_eps(joined, members, index_close=10000.0, date='2026-07-14', constituents_as_of='t')
    assert est['coverage']['suppliedMarketCap'] == 1 and est['coverage']['suppliedEarnings'] == 1
    assert est['coverage']['missingMarketCap'] == 0 and est['coverage']['missingEarnings'] == 0
    assert m.estimate_input_usable(est, strict=True)
    # cap 6000 / income (100 + 100 + 150)
    assert abs(est['per'] - 6000.0 / 350.0) < 1e-9


def test_complete_days_keep_their_coverage_shape():
    rows = {'1001': _row(1000.0, 10.0), '1002': _row(2000.0, 20.0)}
    est = m.weighted_eps(rows, ['1001', '1002'], index_close=10000.0, date='2026-07-14', constituents_as_of='t')
    assert 'suppliedEarnings' not in est['coverage'] and 'suppliedMarketCap' not in est['coverage']


def test_nothing_supplied_without_a_bar_a_forecast_or_with_duplicates():
    rows, members = _valuation(), ['1001', '1002', '543A']
    assert m.valuation_with_supplied_members(rows, members, BARS, DISCLOSURES, date='2026-07-16')[1] == {}
    assert m.valuation_with_supplied_members(rows, members, BARS, DISCLOSURES, date='2026-05-13')[1] == {}
    doubled = {'543A': BARS['543A'] + [{'Date': '2026-07-14', 'Code': '543A0', 'MktCap': 3001.0}]}
    assert m.valuation_with_supplied_members(rows, members, doubled, DISCLOSURES, date='2026-07-14')[1] == {}
    zero = {'543A': [{'Date': '2026-07-14', 'Code': '543A0', 'MktCap': 0}]}
    assert m.valuation_with_supplied_members(rows, members, zero, DISCLOSURES, date='2026-07-14')[1] == {}


def test_all_blank_members_must_be_fillable_and_bounded():
    rows, members = _valuation(), ['1001', '1002', '543A', '9147']
    rows['9147'] = {'MktCap': None}
    assert m.valuation_with_supplied_members(rows, members, BARS, DISCLOSURES, date='2026-07-14')[1] == {}
    many = {str(2000 + i): {} for i in range(m.SUPPLY_MAX_MEMBERS + 1)}
    bars = {code: [{'Date': '2026-07-14', 'Code': code, 'MktCap': 1.0}] for code in many}
    disc = {code: [{'DiscDate': '2026-07-01', 'FNP': '1000000'}] for code in many}
    assert m.valuation_with_supplied_members(many, list(many), bars, disc, date='2026-07-14')[1] == {}


def test_backfill_state_from_the_previous_method_starts_afresh():
    old = {'schemaVersion': b.SCHEMA, 'cursor': '2025-06-26',
           'exhausted': {'2026-07-14': {'signature': 'INPUT_INCOMPLETE:1:0', 'attempts': 3, 'since': '2026-10-21T00:00:00Z'}}}
    state = b.parse(old)
    assert state['cursor'] is None and state['exhausted'] == {} and state['method'] == b.METHOD
    kept = b.parse({**old, 'method': b.METHOD})
    assert kept['cursor'] == '2025-06-26' and '2026-07-14' in kept['exhausted']


def _warm_scope(blank_days):
    """The real _level_map_warm and supply reader against synthetic J-Quants rows."""
    import ast, copy, hashlib, json, threading, time
    from datetime import date, datetime, timedelta
    from pathlib import Path
    from types import SimpleNamespace
    tree = ast.parse(Path("scanner.py").read_text(encoding="utf-8"))
    names = {"_level_map_warm", "_level_map_supply_inputs"}
    functions = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    bars = [{"date": (date(2026, 7, 1) + timedelta(days=i)).isoformat(), "close": 1000} for i in range(30)]
    members = ["1001", "1002", "543A"]
    requests, writes, provider = [], [], []
    state = {"loaded": True, "eps": {}, "mornings": [], "missedMornings": [], "conflicts": 0,
             "epsBackfillCursor": None, "status": "NOT_RUN"}

    def valuation(day, headers):
        requests.append(day)
        rows = {"1001": {"MktCap": 1000.0, "FwdPER": 10.0}, "1002": {"MktCap": 2000.0, "FwdPER": 20.0},
                "543A": {"MktCap": 3000.0, "FwdPER": 20.0}}
        if day in blank_days:
            rows["543A"] = {"MktCap": None, "FwdPER": None}
        return rows

    def paginated(path, params, max_pages=40, request_timeout=None):
        provider.append((path, params["code"]))
        if path == "/equities/bars/daily":
            return [{"Date": bar["date"], "Code": "543A0", "MktCap": 3000.0, "C": 1.0} for bar in bars]
        return [{"Code": "543A0", "DiscDate": "2026-05-14", "DiscTime": "15:30:00", "DiscNo": "D1",
                 "DocType": "EarnForecastRevision", "FNP": "150000000", "Sales": "ignored"}]

    def original(path, estimate):
        writes.append(copy.deepcopy(estimate))
        return {"inserted": True, "conflict": False}

    def no_map(*a, **k):
        raise m.LevelMapError("synthetic_no_morning")
    arithmetic = SimpleNamespace(**{k: getattr(m, k) for k in (
        "pending_eps_sessions", "weighted_eps", "estimate_input_usable", "daily_close_repairable", "LevelMapError",
        "blank_members", "valuation_with_supplied_members", "SUPPLY_MAX_MEMBERS")})
    arithmetic.zigzag = lambda rows: []
    arithmetic.constituents_on = lambda day, constituents, as_of, changes: (members, day)
    arithmetic.score_records = lambda *a: {}
    arithmetic.morning_map = no_map
    supply = {"bars": {}, "disclosures": {}, "requests": 0, "lastError": None, "suppliedDays": 0, "lastSuppliedDate": None}
    scope = {"_LEVEL_MAP": state, "_LEVEL_MAP_LOCK": threading.Lock(), "hashlib": hashlib, "json": json, "time": time,
             "datetime": datetime, "TZ_JST": None,
             "_ai_now_iso": lambda: "2026-10-21T09:00:00Z", "_level_map_history_path": lambda: "synthetic-history",
             "argus_analysis_history": SimpleNamespace(initialize=lambda p: None, append_level_map_eps=original,
                                                       append_level_map_eps_correction=original),
             "_level_map_admitted_eps": lambda: dict(state["eps"]),
             "_level_map_completed_bars": lambda rows, now: bars, "_N225_ANALOG_HISTORY": {"data": []},
             "_JP_INDEX_PROXY": {"factors": {"factors": dict.fromkeys(members, 1)}, "weightsAsOf": bars[-1]["date"]},
             "_JQUANTS_API_KEY": "synthetic-api", "_LEVEL_MAP_EPS_SINCE": "2016-10-03", "_LEVEL_MAP_EPS_PER_WARM": 20,
             "_LEVEL_MAP_MAP_SINCE": "2026-06-01", "jp_market_level_map": arithmetic,
             "_jq_valuation_for_date": valuation, "_nikkei225_constituent_changes": lambda: [],
             "_JQ_VALUATION_DAY_CACHE": {}, "_level_map_next_session": lambda day: None,
             "_CANDIDATES": {}, "_candidates_warm": lambda *a: None, "_level_map_remote": lambda: None,
             "argus_level_map_backfill": b, "_level_map_backfill_state": lambda: b.empty(),
             "_level_map_backfill_save": lambda: None, "_jquants_paginated": paginated,
             "_jq_all_for_date": lambda *a, **k: (_ for _ in ()).throw(AssertionError("no daily-close join")),
             "_LEVEL_MAP_SUPPLY": supply, "_LEVEL_MAP_SUPPLY_REQUESTS_PER_WARM": 2,
             "_LEVEL_MAP_SUPPLY_REFRESH_SECONDS": 6 * 3600,
             "_LEVEL_MAP_SUPPLY_FIELDS": {"bars": ("Date", "Code", "MktCap"),
                                          "disclosures": ("Code", "DiscDate", "DiscTime", "DiscNo", "DocType", "FNP", "NxFNp", "FNCNP", "NxFNCNP")},
             "_LEVEL_MAP_SUPPLY_PATHS": {"bars": "/equities/bars/daily", "disclosures": "/fins/summary"}}
    scope["datetime"] = SimpleNamespace(now=lambda tz=None: datetime(2026, 10, 21, 18, 0))
    exec(compile(ast.Module(body=functions, type_ignores=[]), "scanner.py", "exec"), scope)
    return scope, requests, writes, provider, supply


def test_warm_supplies_blank_member_once_per_code_and_marks_the_record():
    blank = {"2026-07-14", "2026-07-15", "2026-07-16"}
    scope, requests, writes, provider, supply = _warm_scope(blank)
    scope["_level_map_warm"]([])
    supplied = [w for w in writes if w.get("memberSupplement")]
    assert sorted(w["date"] for w in supplied) == sorted(blank)
    assert provider == [("/equities/bars/daily", "543A"), ("/fins/summary", "543A")]   # one read per kind
    for row in supplied:
        assert row["coverage"]["suppliedEarnings"] == 1 and row["coverage"]["missingMarketCap"] == 0
        assert row["memberSupplement"]["members"] == ["543A"] and row["memberSupplement"]["disclosures"] == {"543A": "D1"}
        assert row["memberSupplement"]["historicalPublicationTimeVerified"] is False
        assert "Sales" not in json_dump(supply)
    complete = [w for w in writes if not w.get("memberSupplement")]
    assert complete and all("suppliedEarnings" not in w["coverage"] for w in complete)
    assert supply["suppliedDays"] == 3 and supply["requests"] == 2


def json_dump(value):
    import json
    return json.dumps(value, sort_keys=True, default=str)
