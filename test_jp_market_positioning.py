from copy import deepcopy
import json

import pytest

import argus_market_ledger as ledger
import jp_market_positioning as positioning


REPORT = b'''<html><pre>
JAPANESE YEN - CHICAGO MERCANTILE EXCHANGE Code-097741
FUTURES ONLY POSITIONS AS OF 09/08/26 |
NON-COMMERCIAL | COMMERCIAL | TOTAL | NONREPORTABLE
LONG | SHORT | SPREADS | LONG | SHORT | LONG | SHORT | LONG | SHORT
(CONTRACTS OF JPY 12,500,000) OPEN INTEREST: 499,635
COMMITMENTS
178,791 167,995 28,735 249,469 263,510 456,995 460,240 42,640 39,395
CHANGES FROM 09/01/26 (CHANGE IN OPEN INTEREST: 87,753)
61,622 -41,401 -7,566 24,280 135,882 78,336 86,915 9,417 838
</pre></html>'''
RECEIVED = '2026-09-12T13:46:55+00:00'


def document(raw=REPORT, at=RECEIVED):
    return positioning.normalize_cftc_jpy_report(raw, received_at=at)


def imported(report, state=None):
    state = state or ledger.empty_state()
    result = ledger.import_rows(state, positioning.ledger_candidates(report, state),
                               now_iso=report['receivedAt'], dry_run=False)
    assert result['ok'], result
    return result['state']


def test_real_report_arithmetic_and_lag_do_not_invent_publication_or_empty_shorts():
    row = document()
    assert row['current'] == {'longContracts': 178791, 'shortContracts': 167995,
                             'spreadContracts': 28735, 'netContracts': 10796}
    assert row['change']['netContracts'] == 103023
    assert row['previous']['netContracts'] == -92227
    assert row['publishedAt'] is None and not row['publicationTimeVerified']
    assert row['availableFrom'] == RECEIVED
    assert row['positionAgeCalendarDays'] == 4
    assert not row['observesCurrentLivePositions'] and not row['actionAuthority']


@pytest.mark.parametrize('before,after', [
    (b'Code-097741', b'Code-099741'),
    (b'FUTURES ONLY', b'FUTURES AND OPTIONS'),
    (b'178,791', b'178,790'),
    (b'61,622', b'61,623'),
    (b'178,791', b'17,,8791'),
    (b'09/01/26', b'09/09/26'),
    (b'JPY 12,500,000', b'JPY 125,000'),
])
def test_reject_wrong_contract_definition_or_inconsistent_columns(before, after):
    with pytest.raises(ValueError):
        document(REPORT.replace(before, after))


def test_duplicate_future_and_unzoned_reports_are_rejected():
    for raw, at in [(REPORT + REPORT, RECEIVED), (REPORT, '2026-09-07T13:00:00Z'),
                    (REPORT, '2026-09-12T13:00:00')]:
        with pytest.raises(ValueError):
            document(raw, at)


def test_restore_preserves_receipt_cutoff_and_same_report_first_acquisition():
    original = document()
    state = imported(original)
    state = ledger.merge_restored_state(ledger.empty_state(), json.loads(json.dumps(state)))
    assert positioning.latest_from_ledger(state, cutoff='2026-09-12T13:46:54Z')['status'] == 'UNAVAILABLE'
    result = positioning.latest_from_ledger(state, cutoff=RECEIVED)
    assert result['current'] == original['current']
    assert result['receivedAt'] == original['receivedAt']
    repeated = document(REPORT.replace(b'<html>', b'<html>Updated site header'), at='2026-09-13T13:00:00Z')
    assert repeated['sourceResponseSha256'] != original['sourceResponseSha256']
    assert repeated['reportId'] == original['reportId']
    assert positioning.ledger_candidates(repeated, state) == []
    assert positioning.latest_from_ledger(state, cutoff='2026-09-25T13:00:00Z')['status'] == 'STALE'


def test_changed_report_keeps_old_vintage_and_changes_only_after_actual_receipt():
    state = imported(document())
    corrected_raw = REPORT.replace(b'178,791', b'178,792').replace(b'249,469', b'249,468')
    corrected_raw = corrected_raw.replace(b'61,622', b'61,623').replace(b'24,280', b'24,279')
    corrected = document(corrected_raw, at='2026-09-13T13:00:00Z')
    revised = imported(corrected, state)
    assert len(revised['observations']) == 8
    assert positioning.latest_from_ledger(revised, cutoff=RECEIVED)['current']['longContracts'] == 178791
    assert positioning.latest_from_ledger(revised, cutoff=corrected['receivedAt'])['current']['longContracts'] == 178792


def test_incomplete_tampered_and_rolled_back_vintages_are_not_used():
    state = imported(document())
    incomplete = deepcopy(state); incomplete['observations'].pop()
    assert positioning.latest_from_ledger(incomplete, cutoff=RECEIVED)['status'] == 'UNAVAILABLE'
    corrupt = deepcopy(state)
    for row in corrupt['observations']:
        row['metadata']['change']['netContracts'] = 999999
    assert positioning.latest_from_ledger(corrupt, cutoff=RECEIVED)['status'] == 'UNAVAILABLE'
    rolled = ledger.rollback_import(state, state['observations'][0]['importId'], RECEIVED)
    assert positioning.latest_from_ledger(rolled, cutoff=RECEIVED)['status'] == 'UNAVAILABLE'


def test_brief_uses_the_same_record_and_never_observes_live_orders():
    import argus_market_brief
    doc = document()
    brief = argus_market_brief.compose_brief(now_iso=RECEIVED, jpy_position=doc)
    facts = [row for row in brief['facts'] if row['source'] == 'official_weekly_position']
    assert len(facts) == 1
    assert '167995' in facts[0]['text'] and '現在の建玉は未観測' in facts[0]['text']
    assert facts[0]['provenance']['receivedAt'] == RECEIVED
    assert facts[0]['provenance']['publishedAt'] is None


def test_runtime_collect_reuses_ledger_and_retries_failed_persistence(monkeypatch):
    import scanner
    monkeypatch.setattr(scanner, '_MARKET_LEDGER', ledger.empty_state())
    monkeypatch.setattr(scanner, '_CFTC_JPY_STATE', {'lastAttemptAt': None,
        'lastSuccessfulAcquisitionAt': None, 'status': 'NOT_ACQUIRED', 'lastAttemptMonotonic': None})
    monkeypatch.setattr(scanner, '_ai_now_iso', lambda: RECEIVED)
    monkeypatch.setattr(scanner, '_journal', lambda *a, **k: None)
    responses = iter([{'verified': False}, {'verified': True}])
    monkeypatch.setattr(scanner, '_osint_persist', lambda: next(responses))
    class Response:
        status_code = 200
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def iter_content(self, size): yield REPORT
    calls = []
    def fetch(url, **kwargs):
        calls.append((url, kwargs))
        return Response()
    monkeypatch.setattr(scanner.requests, 'get', fetch)
    result = scanner._cftc_jpy_autorefresh()
    assert result['appendedRows'] == 4
    assert scanner._CFTC_JPY_STATE['persistenceStatus'] == 'NOT_VERIFIED'
    before = deepcopy(scanner._MARKET_LEDGER)
    public = scanner._cftc_jpy_document()
    assert public['current']['netContracts'] == 10796
    assert len(calls) == 1  # cached document does not fetch
    assert scanner._cftc_jpy_autorefresh()['status'] == 'NOT_DUE'
    scanner._CFTC_JPY_STATE['lastAttemptMonotonic'] = None
    assert scanner._cftc_jpy_autorefresh()['appendedRows'] == 0
    assert scanner._CFTC_JPY_STATE['persistenceStatus'] == 'VERIFIED'
    assert scanner._MARKET_LEDGER == before
    assert calls[0][1]['allow_redirects'] is False


def test_runtime_failed_refresh_retains_last_good_received_report(monkeypatch):
    import scanner
    state = imported(document())
    monkeypatch.setattr(scanner, '_MARKET_LEDGER', deepcopy(state))
    monkeypatch.setattr(scanner, '_CFTC_JPY_STATE', {'lastAttemptAt': None,
        'lastSuccessfulAcquisitionAt': RECEIVED, 'status': 'AVAILABLE', 'lastAttemptMonotonic': None})
    monkeypatch.setattr(scanner, '_ai_now_iso', lambda: RECEIVED)
    def failure(*args, **kwargs): raise RuntimeError('temporary failure')
    monkeypatch.setattr(scanner.requests, 'get', failure)
    assert scanner._cftc_jpy_autorefresh()['status'] == 'FAILED'
    result = scanner._cftc_jpy_document()
    assert result['current']['shortContracts'] == 167995
    assert result['acquisition']['status'] == 'FAILED'
    assert scanner._MARKET_LEDGER == state
