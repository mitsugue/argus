from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import pytest
from argus_providers.tachibana.models import TachibanaError, ErrorClass, Freshness
from argus_providers.tachibana.usage_policy import UsagePolicy, initialize_blocked_policy
from argus_providers.tachibana.price_runtime import GuardedTransport, TachibanaPriceRuntime, COLUMNS
from test_argus_tachibana_sensor import _session, _encrypted_session_response, _success, NOW


def test_quiet_hours_send_nothing_including_login_and_logout(tmp_path):
    for hour in (3, 4, 5):
        clock = lambda: datetime(2026, 10, 5, hour, tzinfo=__import__('zoneinfo').ZoneInfo('Asia/Tokyo'))
        policy = UsagePolicy(tmp_path / 'policy.json', clock)
        class NoNetwork:
            def post_json(self, *args): pytest.fail('quiet_hours_network')
        guarded = GuardedTransport(NoNetwork(), policy)
        guarded.session_day = clock().date()
        for operation in ('CLMAuthLoginRequest', 'CLMMfdsGetMarketPrice', 'CLMAuthLogoutRequest'):
            with pytest.raises(TachibanaError) as exc:
                guarded.post_json('synthetic', {'sCLMID': operation}, 2)
            assert exc.value.classification == ErrorClass.MAINTENANCE


def test_restart_preserves_six_login_limit_and_first_error_stop(tmp_path):
    now = [NOW]; path = tmp_path / 'policy.json'
    path.write_text(json.dumps({'day': NOW.astimezone(__import__('zoneinfo').ZoneInfo('Asia/Tokyo')).date().isoformat(), 'count': 0, 'blocked': False}))
    for i in range(6):
        policy = UsagePolicy(path, lambda: now[0]); policy.acquire()
        policy.before_send(login=True); policy.release()
        assert json.loads(path.read_text())['count'] == i + 1
    policy = UsagePolicy(path, lambda: now[0]); policy.acquire()
    with pytest.raises(TachibanaError): policy.before_send(login=True)
    now[0] += timedelta(days=1)
    policy.before_send(login=True); policy.block(); policy.release()
    restored = UsagePolicy(path, lambda: now[0]); restored.acquire()
    try:
        with pytest.raises(TachibanaError): restored.before_send()
        assert restored.count == 1 and restored.blocked
    finally: restored.release()


def test_corrupt_policy_and_duplicate_process_fail_closed(tmp_path):
    path = tmp_path / 'policy.json'; path.write_text('invalid')
    with pytest.raises(TachibanaError): UsagePolicy(path, lambda: NOW).acquire()
    path.unlink()
    initialize_blocked_policy(path, lambda: NOW)
    first = UsagePolicy(path, lambda: NOW); first.acquire()
    try:
        with pytest.raises(RuntimeError): UsagePolicy(path, lambda: NOW).acquire()
    finally: first.release()
    path.unlink()
    path.symlink_to(tmp_path / 'absent')
    with pytest.raises(TachibanaError): UsagePolicy(path, lambda: NOW).acquire()


def test_network_error_and_yesterday_session_never_retry(tmp_path):
    now = [NOW]; path = tmp_path / 'policy.json'
    path.write_text(json.dumps({'day': NOW.date().isoformat(), 'count': 0, 'blocked': False}))
    policy = UsagePolicy(path, lambda: now[0]); policy.acquire()
    class Broken:
        calls = 0
        def post_json(self, *args):
            self.calls += 1
            raise OSError('synthetic')
    raw = Broken(); guarded = GuardedTransport(raw, policy)
    with pytest.raises(OSError): guarded.post_json('synthetic', {'sCLMID': 'CLMAuthLoginRequest'}, 2)
    with pytest.raises(TachibanaError): guarded.post_json('synthetic', {'sCLMID': 'CLMAuthLoginRequest'}, 2)
    assert raw.calls == 1
    now[0] += timedelta(days=1)
    with pytest.raises(TachibanaError): guarded.post_json('synthetic', {'sCLMID': 'CLMMfdsGetMarketPrice'}, 2)
    assert raw.calls == 1
    policy.release()


def price_response(symbols, sequence, *, traded='15:00:10', errno='0'):
    rows = [{'sIssueCode': symbol, 'pDPP': '2000', 'pPRP': '1980', 'pDYWP': '20',
             'pDYRP': '1.01', 'tDPP:T': traded, 'pDOP': '1990', 'pDHP': '2010', 'pDLP': '1985'} for symbol in symbols]
    return {**_success('CLMMfdsGetMarketPrice', 'aCLMMfdsMarketPrice', rows, p_no=str(sequence)),
            'p_rv_date': '2026.09.01-15:00:10.000', 'p_errno': errno}


def runtime_fixture(tmp_path, symbols=('101', '6501'), supplier=None):
    (tmp_path / 'policy.json').write_text(json.dumps({'day': NOW.date().isoformat(), 'count': 0, 'blocked': False}))
    session, transport, key = _session(tmp_path, [])
    login, _ = _encrypted_session_response(key.public_key())
    date = _success('CLMDateZyouhou', 'aCLMDateZyouhou', [{'sDayKey': '001', 'sTheDay': '20260901'}])
    transport.responses.extend([login, date, price_response(symbols, 3)])
    runtime = TachibanaPriceRuntime(session.config, symbols=symbols, policy_path=tmp_path / 'policy.json',
                                   clock=lambda: NOW, transport=transport, symbols_supplier=supplier)
    return runtime, transport


def test_price_only_runtime_index_stocks_membership_and_no_relogin(tmp_path):
    members = [('101', '6501')]
    runtime, transport = runtime_fixture(tmp_path, supplier=lambda: members[0])
    try:
        runtime.start()
        assert set(runtime._price_observations) == set(members[0])
        assert all(row.freshness == Freshness.FRESH for row in runtime._price_observations.values())
        members[0] = ('101', '7203')
        transport.responses.append(price_response(members[0], 4))
        runtime.refresh()
        assert set(runtime._price_observations) == set(members[0])
        operations = [call[1]['sCLMID'] for call in transport.calls]
        assert operations == ['CLMAuthLoginRequest', 'CLMStkGetDateZyouhou', 'CLMMfdsGetMarketPrice', 'CLMMfdsGetMarketPrice']
        transport.responses.append({'p_no': '5', 'p_errno': '0', 'sCLMID': 'CLMAuthLogoutAck', 'sResultCode': '0'})
    finally: runtime.stop()


def test_provider_error_stops_day_and_old_trade_never_refreshes(tmp_path):
    runtime, transport = runtime_fixture(tmp_path)
    try:
        runtime.start()
        transport.responses.append(price_response(runtime.symbols, 4, traded='14:00:00'))
        runtime.refresh()
        assert all(row.freshness != Freshness.FRESH for row in runtime._price_observations.values())
        transport.responses.append(price_response(runtime.symbols, 5, errno='-1'))
        with pytest.raises(TachibanaError): runtime.refresh()
        calls = len(transport.calls)
        with pytest.raises(TachibanaError): runtime.refresh()
        assert len(transport.calls) == calls and runtime._price_observations == {}
    finally: runtime.stop()
    assert len(transport.calls) == calls  # No logout after the error either.


def test_default_client_rejects_index_and_unknown_indices(tmp_path):
    runtime, transport = runtime_fixture(tmp_path)
    for symbol in ('101', '102'):
        with pytest.raises(TachibanaError): runtime.client.market_price((symbol,), COLUMNS)
    with pytest.raises(TachibanaError): runtime.client.market_price(('101', '102'), COLUMNS, allow_nikkei=True)
    assert transport.calls == []


def test_index_display_requires_approval_and_fresh_trade_and_receipt(monkeypatch):
    import argus_index_live as index
    import argus_tachibana_live as live
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None): return NOW
    monkeypatch.setattr(index, 'datetime', Clock)
    monkeypatch.setattr(index, '_state', {'quote': {'price': 1900, 'realtime': False}, 'error': None})
    doc = {'displayApproved': True, 'symbols': {'101': {'provider': 'TACHIBANA', 'price': 2000,
        'freshness': 'FRESH', 'marketStatus': 'OPEN', 'sourceTimestamp': NOW.isoformat(), 'receivedAt': NOW.isoformat()}}}
    monkeypatch.setattr(live, 'current_evidence_safe', lambda: doc)
    assert index.current_quote_safe()['quote']['realtime'] is True
    doc['displayApproved'] = False
    assert index.current_quote_safe()['quote']['price'] == 1900
    doc['displayApproved'] = True
    doc['symbols']['101']['receivedAt'] = (NOW - timedelta(seconds=16)).isoformat()
    assert index.current_quote_safe()['quote']['price'] == 1900
    doc['symbols']['101']['receivedAt'] = NOW.isoformat()
    doc['symbols']['101']['sourceTimestamp'] = (NOW + timedelta(seconds=1)).isoformat()
    assert index.current_quote_safe()['quote']['price'] == 1900


def test_shadow_measure_default_never_loads_credentials_or_connects(monkeypatch, capsys):
    from scripts import tachibana_price_measure as measure
    monkeypatch.setattr(measure, 'TachibanaPriceRuntime', lambda *a, **k: pytest.fail('unexpected_runtime'))
    monkeypatch.setattr(measure.sys, 'argv', ['measure'])
    assert measure.main() == 0
    assert json.loads(capsys.readouterr().out)['networkCalls'] == 0


def test_missing_policy_is_not_assumed_to_have_zero_logins(tmp_path):
    path = tmp_path / 'absent.json'
    policy = UsagePolicy(path, lambda: NOW)
    with pytest.raises(TachibanaError) as failure: policy.acquire()
    assert failure.value.classification == ErrorClass.CONFIGURATION
    assert not path.exists()
    with pytest.raises(TachibanaError): policy.before_send(login=True)


def test_unknown_day_bootstrap_stays_blocked_and_does_not_overwrite(tmp_path):
    path = tmp_path / 'policy.json'; now = [NOW]
    result = initialize_blocked_policy(path, lambda: now[0])
    assert result['networkCalls'] == 0 and result['initialUsageUnknown'] is True
    old = path.read_bytes()
    with pytest.raises(TachibanaError): initialize_blocked_policy(path, lambda: now[0])
    assert path.read_bytes() == old
    policy = UsagePolicy(path, lambda: now[0]); policy.acquire()
    try:
        with pytest.raises(TachibanaError): policy.before_send(login=True)
        assert path.read_bytes() == old
        now[0] += timedelta(days=1)
        policy.before_send(login=True)
        saved = json.loads(path.read_text())
        assert saved['count'] == 1 and saved['blocked'] is False
    finally: policy.release()
    assert path.stat().st_mode & 0o777 == 0o600


def test_unknown_usage_cannot_be_written_as_unblocked(tmp_path):
    path=tmp_path/'policy.json'
    path.write_text(json.dumps({'day': NOW.date().isoformat(), 'count': 0,
                                'blocked': False, 'initialUsageUnknown': True}))
    with pytest.raises(TachibanaError): UsagePolicy(path, lambda: NOW).acquire()


def test_policy_bootstrap_cli_never_loads_credentials_or_connects(monkeypatch,tmp_path,capsys):
    from scripts import tachibana_price_measure as measure
    monkeypatch.setattr(measure, 'TachibanaPriceRuntime', lambda *a, **k: pytest.fail('unexpected_runtime'))
    monkeypatch.setattr(measure.sys, 'argv', ['measure','--initialize-blocked-policy',
        '--exclusive-owner-session','--policy-path', str(tmp_path/'policy.json')])
    assert measure.main() == 0
    result=json.loads(capsys.readouterr().out)
    assert result['networkCalls']==0 and result['enabledChanged'] is False
