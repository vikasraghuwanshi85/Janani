from datetime import datetime
from unittest import TestCase
from unittest.mock import Mock, patch

from test_webhook import app, IMAGE


class FixedClock(datetime):
    @classmethod
    def now(cls):
        return cls(2026, 10, 24, 14, 0)


def fuel_item(identifier, report_date='24/10/2026', received_date='24/10/2026', invalid=False):
    present, previous = ('408780', '409308') if invalid else ('366754', '366205')
    text = (f'Date - {report_date}\nVehicle no - 7412\nPresent odo - {present}\n'
            f'Previous odo - {previous}\nDiesel amount - 3441.45\nDiesel liter - 35.05')
    return {'text': text, 'message_date': received_date, 'message_id': identifier}


def bill_item(identifier, received_date, report_date='', downloaded=False):
    return {'text': 'Date - ' + report_date if report_date else 'Bill attachment',
            'message_date': received_date, 'message_id': identifier, 'has_image': True,
            'image_data': IMAGE if downloaded else ''}


class ScanWindowTests(TestCase):
    def scan(self, items, days=15):
        collected = app.ScanCollection({item['message_id']: item for item in items})
        with patch.object(app, 'datetime', FixedClock), \
                patch.object(app, 'create_driver_universal', return_value=Mock()), \
                patch.object(app, 'wait_for_whatsapp_login', return_value=True), \
                patch.object(app, 'find_group', return_value=True), \
                patch.object(app, 'scroll_and_collect_with_image_fix', return_value=collected), \
                patch.object(app, 'load_history', return_value=set()), \
                patch.object(app, 'parse_message_debug', wraps=app.parse_message_debug) as parse, \
                patch.object(app.time, 'sleep'), patch('builtins.print'):
            batch, _history = app.read_last_n_days(days)
        return batch, parse

    def test_known_old_invalid_reports_and_unread_bills_do_not_fail_current_run(self):
        batch, parse = self.scan([
            fuel_item('old-bad', '24/09/2026', '24/09/2026', invalid=True),
            bill_item('old-unread', '24/09/2026'),
            fuel_item('current'),
        ])
        self.assertEqual([entry['message_id'] for entry in batch], ['current'])
        self.assertEqual(batch.scan_issues, [])
        self.assertEqual(parse.call_count, 1)

    def test_recent_arrival_with_historical_caption_still_requires_validation(self):
        batch, parse = self.scan([fuel_item('recent-bad', '24/09/2026', '24/10/2026', invalid=True)])
        self.assertEqual(batch, [])
        self.assertEqual(parse.call_count, 1)
        self.assertTrue(any('Suspicious odometer' in issue for issue in batch.scan_issues))

    def test_current_caption_is_kept_when_fuel_metadata_is_old(self):
        batch, _ = self.scan([fuel_item('current-caption', '24/10/2026', '24/09/2026')])
        self.assertEqual([entry['message_id'] for entry in batch], ['current-caption'])
        self.assertEqual(batch.scan_issues, [])

    def test_unknown_or_invalid_dates_are_not_assumed_outside_window(self):
        for date in ('', '31/02/2026', 'unavailable'):
            with self.subTest(date=date):
                batch, parse = self.scan([fuel_item('unknown', date, date, invalid=True)])
                self.assertEqual(parse.call_count, 1)
                self.assertTrue(batch.scan_issues)

    def test_unread_bill_uses_known_arrival_date_before_caption_date(self):
        batch, parse = self.scan([bill_item('old-arrival', '24/09/2026', '24/10/2026')])
        self.assertEqual(batch, [])
        self.assertEqual(batch.scan_issues, [])
        parse.assert_not_called()

    def test_recent_unread_bill_is_reported_and_not_marked_uploaded(self):
        batch, parse = self.scan([bill_item('recent-unread', '24/10/2026', '24/09/2026')])
        self.assertEqual(batch, [])
        self.assertTrue(any('could not be downloaded' in issue for issue in batch.scan_issues))
        parse.assert_not_called()

    def test_bill_unknown_arrival_and_caption_remains_eligible(self):
        batch, parse = self.scan([bill_item('unknown-unread', '')])
        self.assertEqual(batch, [])
        self.assertTrue(any('could not be downloaded' in issue for issue in batch.scan_issues))
        parse.assert_not_called()

    def test_downloaded_bill_keeps_recent_arrival_despite_old_caption(self):
        batch, _ = self.scan([bill_item('recent-bill', '24/10/2026', '24/09/2026', downloaded=True)])
        self.assertEqual([entry['message_id'] for entry in batch], ['recent-bill'])
        self.assertEqual(batch.scan_issues, [])

    def test_fifteen_day_scan_includes_october_tenth_and_excludes_ninth(self):
        batch, parse = self.scan([
            fuel_item('cutoff', '10/10/2026', '10/10/2026'),
            fuel_item('before-cutoff', '09/10/2026', '09/10/2026', invalid=True),
        ])
        self.assertEqual([entry['message_id'] for entry in batch], ['cutoff'])
        self.assertEqual(parse.call_count, 1)
        self.assertEqual(batch.scan_issues, [])

    def test_all_mode_keeps_older_invalid_reports_for_review(self):
        batch, parse = self.scan([
            fuel_item('old-bad', '24/09/2026', '24/09/2026', invalid=True),
            bill_item('old-unread', '24/09/2026'),
        ], days=3650)
        self.assertEqual(batch, [])
        self.assertEqual(parse.call_count, 1)
        self.assertEqual(len(batch.scan_issues), 2)
