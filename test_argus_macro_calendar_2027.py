"""公表済み予定だけを年越し・夏冬時間を保って既存カレンダーへ渡す。"""
from datetime import date
import scanner


def collect_2027():
    events = {}
    for month in range(1, 13):
        for row in scanner._build_curated_events(date(2027, month, 1)):
            if row['eventDate'].startswith('2027-'):
                events[row['id']] = row
    return events


def test_published_bls_and_bea_types_keep_all_twelve_dated_releases():
    events = collect_2027()
    for kind in ('cpi', 'ppi', 'nfp', 'pce', 'gdp'):
        rows = [row for row in events.values() if row['kind'] == kind]
        assert len(rows) == 12
        assert {row['eventDate'][5:7] for row in rows} == {f'{m:02}' for m in range(1, 13)}
    # GDPとPCEは同日でも異なる予定として残す。
    assert events['us-gdp-2027-01-28']['eventTimeUtc'] == events['us-pce-2027-01-28']['eventTimeUtc']
    assert events['us-cpi-2027-01-13']['eventTimeUtc'] == '2027-01-13T13:30:00Z'
    assert events['us-ppi-2027-08-10']['eventTimeUtc'] == '2027-08-10T12:30:00Z'
    assert events['us-gdp-2027-06-25']['eventTimeUtc'] == '2027-06-25T12:30:00Z'
    assert events['us-pce-2027-12-22']['eventTimeUtc'] == '2027-12-22T13:30:00Z'


def test_published_schedule_provenance_does_not_become_actual_result_or_receipt():
    events = collect_2027()
    for row in events.values():
        if row['kind'] not in ('cpi', 'ppi', 'nfp', 'pce', 'gdp'):
            continue
        assert row['sourceScheduleCheckedAt'].endswith(('+00:00', 'Z'))
        assert not any(key in row for key in ('releasedAt', 'publishedAt', 'actual', 'officialResult'))
        if row['kind'] in ('cpi', 'ppi', 'nfp'):
            assert row['sourceScheduleRef'] == 'https://www.bls.gov/schedule/2027/home.htm'
            assert row['sourceScheduleEvidence'] == 'OFFICIAL_PAGE_WEB_READ'
            assert 'sourceScheduleResponseSha256' not in row
        else:
            assert row['sourceScheduleRef'] == 'https://www.bea.gov/news/schedule/next-year'
            assert row['sourceScheduleEvidence'] == 'OFFICIAL_HTTP_RETAINED'
            assert len(row['sourceScheduleResponseSha256']) == 64
    assert not [row for row in events.values() if row['kind'] == 'jolts']


def test_summer_winter_boundary_and_existing_horizon_are_retained():
    events = collect_2027()
    assert events['us-nfp-2027-11-05']['localTimeJst'] == '2027-11-05 21:30 JST'
    assert events['us-cpi-2027-11-10']['localTimeJst'] == '2027-11-10 22:30 JST'
    assert events['us-cpi-2027-03-10']['localTimeJst'] == '2027-03-10 22:30 JST'
    assert events['us-cpi-2027-04-13']['localTimeJst'] == '2027-04-13 21:30 JST'
    for row in scanner._build_curated_events(date(2027, 1, 1)):
        assert -scanner._EVENT_RELEASED_KEEP_DAYS <= row['daysUntil'] <= scanner._EVENT_HORIZON_DAYS
    assert not [row for row in scanner._build_curated_events(date(2027, 1, 17))
                if row['id'] == 'us-cpi-2027-01-13']


def test_existing_2026_and_date_only_central_bank_schedule_are_not_rewritten():
    rows = scanner._build_curated_events(date(2026, 10, 31))
    before = next(row for row in rows if row['id'] == 'us-nfp-2026-11-06')
    assert before['eventTimeUtc'] == '2026-11-06T13:30:00Z'
    assert 'sourceScheduleCheckedAt' not in before
    january = scanner._build_curated_events(date(2027, 1, 1))
    boj = next(row for row in january if row['id'] == 'jp-boj-2027-01-22')
    assert boj['eventTimeUtc'] is None and boj['localTimeJst'] is None
    assert 'sourceScheduleCheckedAt' not in boj
