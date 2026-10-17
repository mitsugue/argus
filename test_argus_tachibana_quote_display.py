"""Synthetic cached quote boundary: no provider, AI, raw auth or order path."""
import ast
from pathlib import Path
from copy import deepcopy
from datetime import date, datetime, timezone
from types import SimpleNamespace
import pytest
from argus_tachibana_quote_display import quote_document

NOW = '2026-10-14T01:47:45Z'

def document():
    return {'provider': 'TACHIBANA', 'enabled': True, 'displayApproved': True,
            'mode': 'DISPLAY', 'shadowOnly': True, 'authoritative': False,
            'status': 'STALE', 'providerHealth': 'AVAILABLE',
            'secretFiles': {'privateKey': 'NEVER_RETURN'}, 'authDiagnostic': 'PRIVATE',
            'symbols': {'8058': {'provider': 'TACHIBANA', 'symbol': '8058', 'price': 123.4,
                'sourceTimestamp': '2026-10-14T01:47:00Z', 'sourceTimestampPrecision': 'MINUTE',
                'receivedAt': '2026-10-14T01:47:44Z', 'freshness': 'DELAYED',
                'realtimeClassification': 'CURRENT_MARKET_SNAPSHOT', 'marketStatus': 'OPEN',
                'raw': 'DO_NOT_RETURN', 'fieldAvailability': {'private': 'DO_NOT_RETURN'}},
                '9984': {'provider': 'TACHIBANA', 'symbol': '9984', 'price': 234.5}}}


def test_requested_scope_source_precision_and_original_timestamps():
    doc = document(); before = deepcopy(doc)
    out = quote_document(doc, ['8058', '8058', '0000'], read_at=NOW)
    assert list(out['symbols']) == ['8058']
    assert out['quoteRequestedSymbols'] == ['8058', '0000']
    assert out['symbols']['8058']['sourceTimestamp'] == doc['symbols']['8058']['sourceTimestamp']
    assert out['symbols']['8058']['receivedAt'] == doc['symbols']['8058']['receivedAt']
    assert out['symbols']['8058']['sourceTimestampPrecision'] == 'MINUTE'
    assert out['readAt'] == NOW
    assert 'authDiagnostic' not in out and 'secretFiles' not in out
    assert 'raw' not in out['symbols']['8058'] and 'fieldAvailability' not in out['symbols']['8058']
    out['symbols']['8058']['price'] = 987.6
    assert doc == before


@pytest.mark.parametrize(('stamp', 'opened'), [
    (NOW, True), ('2026-10-14T03:00:00Z', False),
    ('2026-10-14T04:00:00Z', True), ('2026-10-14T06:31:00Z', False),
    ('2026-10-12T01:00:00Z', False), ('2026-10-17T01:00:00Z', False),
])
def test_existing_official_calendar_controls_only_quote_cadence(stamp, opened):
    out = quote_document(document(), ['8058'], read_at=stamp)
    assert out['cashSessionOpen'] is opened
    assert out['symbols']['8058']['receivedAt'] == '2026-10-14T01:47:44Z'
    assert out['symbols']['8058']['sourceTimestamp'] == '2026-10-14T01:47:00Z'


def test_unavailable_provider_is_not_a_quote_document():
    assert quote_document(None, ['8058'], read_at=NOW) is None
    assert quote_document({'provider': 'OTHER'}, ['8058'], read_at=NOW) is None


def test_scope_cap_and_row_provenance():
    doc = document(); doc['symbols'] = {str(1000+i): {'provider': 'TACHIBANA'} for i in range(51)}
    doc['symbols']['1001']['provider'] = 'OTHER'
    out = quote_document(doc, list(doc['symbols']), read_at=NOW)
    assert len(out['quoteRequestedSymbols']) == 50
    assert len(out['symbols']) == 49 and '1001' not in out['symbols'] and '1050' not in out['symbols']


def test_actual_cached_watchlist_function_has_no_provider_or_ai_side_effect():
    tree = ast.parse(Path('scanner.py').read_text())
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'api_argus_japan_watchlist')
    fn.decorator_list = []
    calls = []
    base = {'status': 'delayed', 'stocks': [], 'asOf': '2026-10-13'}
    def core(symbols, allow_provider_fetch=True, record_requested_symbols=True):
        assert symbols == ['8058'] and allow_provider_fetch is False and record_requested_symbols is False
        calls.append('cached'); return base
    def forbidden(*a, **k):raise AssertionError('external or membership write')
    env = {'get_japan_watchlist_snapshot': core,
           '_sanitize_symbols': lambda s,*a:list(s), '_JP_SYM_RE': object(), '_JP_DYN_MAX': 50,
           '_note_jp_warm_hints': lambda s:calls.append('existing_eod_hint'),
           '_with_cap_truth': lambda s,*a:s, 'jsonify':lambda s:s,
           'request': SimpleNamespace(args={'symbols':'8058'}), '_tachibana_live_evidence': document,
           '_ai_now_iso': lambda: NOW, 'provider_fetch': forbidden, 'generate_ai': forbidden}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), '<actual-cached-quote-reader>', 'exec'), env)
    out = env['api_argus_japan_watchlist']()
    assert calls == ['cached', 'existing_eod_hint']
    assert out['japaneseLive']['symbols']['8058']['price'] == 123.4
    assert base == {'status': 'delayed', 'stocks': [], 'asOf': '2026-10-13'}


def test_actual_observation_preserves_minute_precision_as_a_separate_field():
    from argus_providers.tachibana.normalization import normalize_market_price
    from argus_providers.tachibana.models import MarketStatus
    from argus_tachibana_live import observation_evidence
    now = datetime(2026,10,14,1,47,45,tzinfo=timezone.utc)
    obs = normalize_market_price({'sIssueCode':'8058','pDPP':'123.4','tDPP:T':'10:47'},
        received_at=now,market_date=date(2026,10,14),market_status=MarketStatus.OPEN,
        market_date_verified=True)
    out = observation_evidence(obs, now=now)
    assert out['sourceTimestampPrecision'] == 'MINUTE'
    assert out['sourceTimestamp'].endswith('01:47:00+00:00')
    assert out['receivedAt'].endswith('01:47:45+00:00')
    assert out['freshness'] != 'FRESH'
