import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

from jp_market_events import sq_calendar

SOURCE = json.loads((Path(__file__).parent / 'ops/calendar/jp_index_sq_2026.json').read_text())


def fixture():
    # Simulated early publication is a test input, not the real source receipt.
    return {**SOURCE, 'knownAt': '2025-12-01T00:00:00Z', 'sourceRef': 'test:official-calendar'}


def at(value):
    return datetime.fromisoformat(value)


class SqCalendarTest(unittest.TestCase):
    def test_actual_official_dates_and_thirty_day_horizon(self):
        result = sq_calendar(now=at('2026-09-12T09:00:00+09:00'), schedule=SOURCE)
        self.assertEqual([(e['sqDate'], e['lastTradingDate']) for e in result['events']],
                         [('2026-10-09', '2026-10-08')])
        self.assertEqual(result['events'][0]['kind'], 'MONTHLY_SQ')
        self.assertEqual(result['events'][0]['tradingSessionsUntil'], 17)
        self.assertFalse(result['dependsOnAi'])
        self.assertEqual(result['notificationProposals'], [])

    def test_major_week_previous_session_and_today_are_distinct(self):
        for value, stage, phase in [('2026-09-07T08:00:00+09:00', 'EVENT_WEEK', 'WEEK'),
                                     ('2026-09-10T08:00:00+09:00', 'LAST_TRADING_DAY', 'PREVIOUS_SESSION'),
                                     ('2026-09-11T08:00:00+09:00', 'TODAY', 'DAY')]:
            result = sq_calendar(now=at(value), schedule=fixture())
            event = result['events'][0]
            self.assertEqual(event['kind'], 'MAJOR_SQ')
            self.assertEqual(event['stage'], stage)
            self.assertIsNone(event['directionalSignal'])
            notice = result['notificationProposals'][0]
            self.assertEqual(notice['phase'], phase)
            self.assertEqual(notice['deliveryStatus'], 'NOT_SENT')
            self.assertEqual(notice['deduplicationKey'], event['eventId'] + ':' + phase)

    def test_jst_date_and_notice_expiry_are_independent_of_host_timezone(self):
        early = sq_calendar(now=at('2026-09-10T22:59:00+00:00'), schedule=fixture())
        due = sq_calendar(now=at('2026-09-10T23:00:00+00:00'), schedule=fixture())
        late = sq_calendar(now=at('2026-09-11T07:00:00+00:00'), schedule=fixture())
        self.assertEqual(early['notificationProposals'], [])
        self.assertEqual(due['events'][0]['stage'], 'TODAY')
        self.assertEqual(len(due['notificationProposals']), 1)
        self.assertEqual(late['notificationProposals'], [])

    def test_unpublished_and_uncovered_schedules_are_not_invented(self):
        past = sq_calendar(now=at('2026-03-01T08:00:00+09:00'), schedule=SOURCE)
        self.assertEqual(past['status'], 'UNAVAILABLE')
        future = sq_calendar(now=at('2026-12-20T08:00:00+09:00'), schedule=SOURCE)
        self.assertEqual(future['status'], 'PARTIAL')
        self.assertIn('official_schedule_does_not_cover_full_horizon', future['gaps'])
        self.assertEqual(future['events'], [])

    def test_missing_month_is_not_reported_as_complete_calendar(self):
        missing = {**SOURCE, 'rows': [row for row in SOURCE['rows'] if row['sqDate'] != '2026-10-09']}
        result = sq_calendar(now=at('2026-09-12T09:00:00+09:00'), schedule=missing)
        self.assertEqual(result['status'], 'PARTIAL')
        self.assertIn('missing_official_monthly_schedule', result['gaps'])

    def test_conflicting_calendar_does_not_silently_move_official_date(self):
        result = sq_calendar(now=at('2026-10-08T08:00:00+09:00'), schedule=SOURCE,
                             trading_day=lambda day: day.weekday() < 5 and day.isoformat() != '2026-10-09')
        event = result['events'][0]
        self.assertEqual(event['sqDate'], '2026-10-09')
        self.assertEqual(event['calendarStatus'], 'UNAVAILABLE_OR_CONFLICT')
        self.assertIsNone(event['tradingSessionsUntil'])
        self.assertEqual(result['notificationProposals'], [])


if __name__ == '__main__':
    unittest.main()
