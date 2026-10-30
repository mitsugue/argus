"""合成の政策文で、日付・金利・公表と受領・転送拒否を確認する。"""
from copy import deepcopy
from io import BytesIO

import pytest

import argus_boj_policy_result as boj
import argus_macro_event_analysis as analysis
import argus_macro_results as results

DAY = '2026-10-30'
URL = 'https://www.boj.or.jp/mopo/mpmdeci/mpr_2026/k261030a.pdf'
RECEIVED = '2026-10-30T14:00:00Z'
# 合成例。実際の政策値や公式原文の代用にはしない。
TEXT = '''２０２６年１０月３０日 日本銀行 当面の金融政策運営について
１．金融市場調節方針
無担保コールレート（オーバーナイト物）を、０．５０％程度で推移するよ
う促す。
２．ＥＴＦの売却 本年までの年間の売却ペースを3,000億円程度としていた。
本日の金融政策決定会合において、ＥＴＦの売却について、市場の規模を踏まえ、
年間の売却ペースを8,000億円程度とする。以上
（注）反対議案は、無担保コールレート（オーバーナイト物）を、０．７５％程度で推移するよう促す。
2027年1月から実施。
公表日時 当面の金融政策運営について――10月30日（金）12:02
他の資料――11月2日（月）14:00予定'''


def parse(text=TEXT, **kwargs):
    return boj.parse_document(text, event_date=kwargs.pop('event_date', DAY),
        received_at=kwargs.pop('received_at', RECEIVED),
        source_url=kwargs.pop('source_url', URL),
        document_sha256=kwargs.pop('document_sha256', 'a' * 64), **kwargs)


def index(href=URL, day='2026年10月30日', title='当面の金融政策運営について'):
    return f'<table><tr><td>{day}</td><td><a href="{href}">{title}</a></td></tr></table>'


def test_main_policy_not_dissent_or_previous_etf_pace_and_times_separate():
    out = parse()
    assert out['metrics'] == {'policyRatePct': 0.5, 'etfAnnualSalesOkuYen': 8000,
                              'etfAnnualSalesEffectiveMonth': '2027-01'}
    assert out['releasedAt'] == '2026-10-30T03:02:00Z'
    assert out['receivedAt'] == out['availableFrom'] == RECEIVED
    assert '2027/1から' in out['headline']
    assert out['publicationTimeEvidence']['precision'] == 'MINUTE'
    assert '0.75' not in out['headline'] and '3,000' not in out['headline']


@pytest.mark.parametrize('changes', [
    {'event_date': '2026-10-29'}, {'received_at': '2026-10-30T03:01:59Z'},
    {'received_at': '2026-10-30T14:00:00'}, {'source_url': 'https://example.test/result.pdf'},
    {'source_url': URL + '?override=1'}, {'document_sha256': 'not-a-digest'},
])
def test_wrong_date_time_or_source_never_becomes_official_result(changes):
    with pytest.raises(ValueError):
        parse(**changes)


def test_ambiguous_main_target_and_planned_publication_fail_closed():
    with pytest.raises(ValueError):
        parse(TEXT.replace('以上', '無担保コールレート（オーバーナイト物）を、1.00%程度で推移するよう促す。以上'))
    with pytest.raises(ValueError):
        parse(TEXT.replace('12:02', '12:02予定'))


def test_missing_publication_notice_does_not_use_receipt_as_release():
    out = parse(TEXT.split('公表日時')[0])
    assert out['available'] and out['releasedAt'] is None
    assert 'publicationTimeEvidence' not in out
    assert out['availableFrom'] == RECEIVED


@pytest.mark.parametrize('rate', ['0', '-0.1'])
def test_zero_and_negative_policy_rates_are_real_values_not_missing(rate):
    out = parse(TEXT.replace('０．５０', rate))
    assert out['metrics']['policyRatePct'] == float(rate)


def test_reference_is_same_date_primary_document_on_official_host_only():
    assert boj.policy_reference(index('/mopo/mpmdeci/mpr_2026/k261030a.pdf'), event_date=DAY) == URL
    for value in (index('https://example.test/result.pdf'), index(day='2026年9月18日'),
                  index(title='（参考）当面の金融政策運営について'),
                  index() + index('/mopo/mpmdeci/mpr_2026/k261030b.pdf')):
        with pytest.raises(ValueError):
            boj.policy_reference(value, event_date=DAY)


class Response:
    def __init__(self, url, raw, code=200):
        self.url, self.raw, self.status_code = url, raw, code
        self.history, self.closed = [], False
    def iter_content(self, size):
        for offset in range(0, len(self.raw), size):
            yield self.raw[offset:offset + size]
    def close(self):
        self.closed = True


def test_fetch_only_index_then_linked_document_and_receipt_after_io(monkeypatch):
    calls, responses = [], []
    def get(url, **kwargs):
        calls.append((url, kwargs))
        response = Response(url, index().encode() if len(calls) == 1 else b'%PDF-fixture')
        responses.append(response)
        return response
    monkeypatch.setattr(boj, 'extract_document', lambda _raw: TEXT)
    out = boj.fetch(get, {'date': DAY}, now_iso='2026-10-30T02:00:00Z', clock=lambda: RECEIVED)
    assert len(calls) == 2 and all(r.closed for r in responses)
    assert all(k['allow_redirects'] is False and k['stream'] is True for _, k in calls)
    assert out['receivedAt'] == RECEIVED
    assert out['releasedAt'] == '2026-10-30T03:02:00Z'


def test_future_event_sends_nothing_and_failed_http_response_is_closed():
    def forbidden(*args, **kwargs):
        pytest.fail('future event must not fetch')
    with pytest.raises(ValueError):
        boj.fetch(forbidden, {'eventDate': '2026-11-02'}, now_iso=RECEIVED)
    for raw, code in ((b'x', 302), (b'x' * 20, 200)):
        response = Response(URL, raw, code)
        with pytest.raises(ValueError):
            boj._read(lambda *args, **kwargs: response, URL, 10)
        assert response.closed


def test_pdf_structure_bounds_are_checked_without_using_a_real_original():
    from pypdf import PdfWriter
    for page_count in (0, 9):
        writer = PdfWriter()
        for _ in range(page_count):
            writer.add_blank_page(width=72, height=72)
        stream = BytesIO()
        writer.write(stream)
        with pytest.raises(ValueError):
            boj.extract_document(stream.getvalue())


def test_after_release_pre_is_not_scored_or_relabelled_and_original_unchanged():
    actual = parse()
    pre = {'generatedAt': '2026-10-30T04:00:00Z', 'argusScenarioJa': '合成の記録'}
    record = {'eventCode': 'BOJ', 'pre': pre, 'actual': actual,
              'post': {'verdict': 'hit', 'answerCheckJa': '合成の答え合わせ'}}
    before = deepcopy(record)
    projected = results.project_macro_result_record(record)
    assert projected['pre'] == {}
    assert projected['post']['verdict'] == 'not_scoreable'
    assert projected['preTimingStatus'] == 'NOT_BEFORE_RELEASE'
    assert record == before
    valid = {**pre, 'generatedAt': '2026-10-30T03:01:59Z'}
    assert analysis.pre_before_release(valid, actual['releasedAt']) == valid
    assert analysis.pre_before_release({**valid, 'generatedAt': '2026-10-30T03:01:59'}, actual['releasedAt']) == {}
    assert analysis.resolve_macro_event_phase(None, RECEIVED, actual_available=True, event_date=DAY) == 'post_result'


def _scanner_event():
    return {'id': 'jp-boj-2026-10-30', 'eventId': 'jp-boj-2026-10-30',
            'eventCode': 'BOJ', 'eventDate': DAY, 'eventTimeUtc': None,
            'displayImpact': 'high', 'daysUntil': 0, 'title': '日銀金融政策'}


def test_release_day_refresh_uses_received_document_and_keeps_original_pre(monkeypatch):
    import scanner
    event = _scanner_event()
    record = analysis.new_record(event, now_iso=RECEIVED)
    record['pre'] = {'generatedAt': '2026-10-30T04:00:00Z', 'argusScenarioJa': '合成の記録'}
    original_pre = deepcopy(record['pre'])
    monkeypatch.setattr(scanner, '_MACRO_ANALYSIS', {event['eventId']: record})
    monkeypatch.setattr(scanner, '_MACRO_ANALYSIS_STATE', {'restored': True})
    monkeypatch.setattr(scanner, '_MACRO_RESULT_STATE', {'BOJ': {}})
    monkeypatch.setattr(scanner, '_macro_analysis_persist', lambda: None)
    monkeypatch.setattr(scanner, '_macro_important_events', lambda _limit: [event])
    monkeypatch.setattr(scanner, '_ai_now_iso', lambda: RECEIVED)
    calls = []
    def fetch(_event):
        calls.append(1)
        return parse()
    monkeypatch.setattr(scanner, '_macro_result_fetch', fetch)
    assert scanner._refresh_macro_results()['resultsFetched'] == 1
    stored = scanner._MACRO_ANALYSIS[event['eventId']]
    assert stored['eventTimeUtc'] == '2026-10-30T03:02:00Z'
    assert stored['phase'] == 'post_result'
    assert stored['pre'] == original_pre
    assert len(stored['resultRevisions']) == 1
    assert scanner._refresh_macro_results()['resultsFetched'] == 0
    assert len(calls) == 1
    from argus_dashboard_event_summary import build_summary
    out = build_summary(important_events=[event], macro_records=[stored], now_iso=RECEIVED)
    row = out['items'][0]
    assert row['caos']['verdict'] == 'not_scoreable'
    assert row['caos']['preScenarioJa'] == ''


def test_release_day_no_document_keeps_pre_phase_and_waits_existing_retry(monkeypatch):
    import scanner
    event = _scanner_event()
    record = analysis.new_record(event, now_iso=RECEIVED)
    monkeypatch.setattr(scanner, '_MACRO_ANALYSIS', {event['eventId']: record})
    monkeypatch.setattr(scanner, '_MACRO_ANALYSIS_STATE', {'restored': True})
    monkeypatch.setattr(scanner, '_MACRO_RESULT_STATE', {'BOJ': {}})
    monkeypatch.setattr(scanner, '_macro_analysis_persist', lambda: None)
    monkeypatch.setattr(scanner, '_macro_important_events', lambda _limit: [event])
    monkeypatch.setattr(scanner, '_ai_now_iso', lambda: RECEIVED)
    calls = []
    def fetch(_event):
        calls.append(1)
        return results.boj_partial(_event, RECEIVED)
    monkeypatch.setattr(scanner, '_macro_result_fetch', fetch)
    assert scanner._refresh_macro_results()['resultsFetched'] == 0
    assert scanner._refresh_macro_results()['resultsFetched'] == 0
    assert len(calls) == 1
    assert scanner._MACRO_ANALYSIS[event['eventId']]['phase'] == 'imminent'
    assert not scanner._MACRO_ANALYSIS[event['eventId']]['actual']['available']


def test_received_result_reaches_existing_material_path_only_after_receipt():
    import argus_macro_material as material
    actual = parse()
    record = {**_scanner_event(), 'eventTimeUtc': actual['releasedAt'], 'actual': actual}
    assert material.released_materials([record], now_iso='2026-10-30T13:59:59Z') == []
    rows = material.released_materials([record], now_iso=RECEIVED)
    assert len(rows) == 1
    assert rows[0]['materialOrigin'] == 'OFFICIAL_MACRO_RESULT'
    assert rows[0]['sourceReceivedAt'] == RECEIVED
    assert '政策金利' in rows[0]['headlineJa'] and '2027/1' in rows[0]['headlineJa']


def test_missing_publication_clock_cannot_make_a_pre_receipt_view_scoreable():
    actual = parse(TEXT.split('公表日時')[0])
    record = {'eventCode': 'BOJ', 'actual': actual,
              'pre': {'generatedAt': '2026-10-30T02:00:00Z', 'argusScenarioJa': '合成の記録'},
              'post': {'verdict': 'hit'}}
    projected = results.project_macro_result_record(record)
    assert projected['pre'] == {} and projected['post']['verdict'] == 'not_scoreable'


def test_unscoreable_post_is_not_regenerated_for_unchanged_received_result(monkeypatch):
    import scanner
    import argus_macro_event_store as store
    event = _scanner_event()
    actual = parse()
    record = {**analysis.new_record(event, now_iso=RECEIVED),
        'eventTimeUtc': actual['releasedAt'], 'actual': actual,
        'pre': {'generatedAt': '2026-10-30T04:00:00Z', 'summaryJa': '合成の発表後記録'},
        'post': {'verdict': 'not_scoreable', 'generatedAt': RECEIVED,
                 'actualRevisionId': store.actual_revision_id(actual)}}
    monkeypatch.setattr(scanner, '_MACRO_ANALYSIS', {event['eventId']: record})
    monkeypatch.setattr(scanner, '_MACRO_ANALYSIS_STATE', {'restored': True})
    monkeypatch.setattr(scanner, '_macro_analysis_persist', lambda: None)
    monkeypatch.setattr(scanner, '_macro_important_events', lambda _limit: [event])
    monkeypatch.setattr(scanner, '_macro_market_context_ja', lambda: '')
    monkeypatch.setattr(scanner, '_event_news_context_cached', lambda *a, **k: {})
    monkeypatch.setattr(scanner, '_ai_now_iso', lambda: RECEIVED)
    def forbidden(*args, **kwargs):
        pytest.fail('unchanged result must not generate again merely because no pre exists')
    monkeypatch.setattr(scanner, '_openai_prose', forbidden)
    assert scanner._generate_macro_event_analysis_locked()['post'] == 0


def test_new_result_is_explained_once_without_scoring_after_release_pre(monkeypatch):
    import scanner
    event = _scanner_event()
    actual = parse()
    record = {**analysis.new_record(event, now_iso=RECEIVED),
        'eventTimeUtc': actual['releasedAt'], 'actual': actual,
        'pre': {'generatedAt': '2026-10-30T04:00:00Z', 'summaryJa': '合成の発表後記録'},
        'post': {'verdict': 'not_scoreable', 'generatedAt': RECEIVED, 'actualRevisionId': None}}
    monkeypatch.setattr(scanner, '_MACRO_ANALYSIS', {event['eventId']: record})
    monkeypatch.setattr(scanner, '_MACRO_ANALYSIS_STATE', {'restored': True})
    monkeypatch.setattr(scanner, '_macro_analysis_persist', lambda: None)
    monkeypatch.setattr(scanner, '_macro_important_events', lambda _limit: [event])
    monkeypatch.setattr(scanner, '_macro_market_context_ja', lambda: '')
    monkeypatch.setattr(scanner, '_event_news_context_cached', lambda *a, **k: {})
    monkeypatch.setattr(scanner, '_ai_now_iso', lambda: RECEIVED)
    calls = []
    def generate(prompt, **kwargs):
        calls.append(prompt)
        assert '合成の発表後記録' not in prompt
        return {'verdict': 'hit', 'answerCheckJa': '合成の結果説明'}
    monkeypatch.setattr(scanner, '_openai_prose', generate)
    assert scanner._generate_macro_event_analysis_locked()['post'] == 1
    assert scanner._generate_macro_event_analysis_locked()['post'] == 0
    assert len(calls) == 1
    assert scanner._MACRO_ANALYSIS[event['eventId']]['post']['verdict'] == 'not_scoreable'
