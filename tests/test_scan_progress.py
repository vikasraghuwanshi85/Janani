from datetime import datetime
from unittest import TestCase
from unittest.mock import Mock, patch

from test_webhook import app


class FixedClock(datetime):
    @classmethod
    def now(cls):
        return cls(2026, 10, 24, 14, 0)


def message(identifier='bill-1', date='24/10/2026', image=True):
    return {'messageId': identifier, 'messageDate': date, 'hasImage': image,
            'text': 'Bill attachment' if image else 'Vehicle no - 7412\nPresent odo - 366754',
            'isForwarded': False}


class ScanProgressTests(TestCase):
    def collect(self, batches, image_results=('', '', ''), progress=None, days=15):
        driver = Mock()
        batch_index = 0

        def visible_messages(*_args):
            nonlocal batch_index
            result = batches[min(batch_index, len(batches) - 1)]
            batch_index += 1
            return result

        driver.execute_script.side_effect = visible_messages
        driver.execute_async_script.side_effect = image_results
        progress = progress or {'found': True, 'before': 0, 'top': 0, 'atTop': True}
        with patch.object(app, 'move_whatsapp_history', return_value=progress), \
                patch.object(app.time, 'sleep'), patch.object(app, 'datetime', FixedClock), \
                patch('builtins.print') as output:
            collected = app.scroll_and_collect_with_image_fix(driver, days=days)
        return collected, driver, output

    def test_missing_image_retries_do_not_count_as_new_messages_or_block_end(self):
        collected, driver, output = self.collect([[message()]])
        self.assertEqual(set(collected), {'bill-1'})
        self.assertEqual(driver.execute_async_script.call_count, 3)
        self.assertEqual(driver.execute_script.call_count, 5)
        self.assertTrue(collected.scan_incomplete)
        scroll_logs = [call.args[0] for call in output.call_args_list if call.args and str(call.args[0]).startswith('  Scroll ')]
        self.assertIn('Found 1 new messages', scroll_logs[0])
        self.assertTrue(all('Found 0 new messages' in text for text in scroll_logs[1:]))
        warnings = [str(call.args[0]) for call in output.call_args_list if call.args and 'deferred until the next run' in str(call.args[0])]
        self.assertEqual(len(warnings), 1)

    def test_retry_can_load_image_without_resetting_distinct_message_progress(self):
        collected, driver, output = self.collect([[message()]], ('', '', 'data:image/png;base64,cGljdHVyZQ=='))
        self.assertEqual(driver.execute_async_script.call_count, 3)
        self.assertEqual(driver.execute_script.call_count, 5)
        self.assertEqual(collected['bill-1']['image_data'], 'data:image/png;base64,cGljdHVyZQ==')
        self.assertTrue(any('Loaded 1 bill image' in str(call.args[0]) for call in output.call_args_list if call.args))

    def test_each_missing_image_has_its_own_attempt_limit(self):
        collected, driver, _ = self.collect([[message('a'), message('b')]], ('',) * 6)
        self.assertEqual(len(collected), 2)
        self.assertEqual(driver.execute_async_script.call_count, 6)
        identifiers = [call.args[3] for call in driver.execute_async_script.call_args_list]
        self.assertEqual(identifiers.count('a'), 3)
        self.assertEqual(identifiers.count('b'), 3)

    def test_new_message_after_empty_pass_still_extends_scan(self):
        a, b = message('a', image=False), message('b', image=False)
        collected, driver, _ = self.collect([[a], [a], [a, b]])
        self.assertEqual(set(collected), {'a', 'b'})
        self.assertEqual(driver.execute_script.call_count, 7)
        driver.execute_async_script.assert_not_called()

    def test_confirmed_older_batches_stop_at_fifteen_day_window(self):
        progress = {'found': True, 'before': 500, 'top': 300, 'atTop': False}
        collected, driver, output = self.collect([
            [message('new', '24/10/2026', False)],
            [message('old', '08/10/2026', False)],
            [message('older', '07/10/2026', False)],
        ], progress=progress)
        self.assertEqual(driver.execute_script.call_count, 3)
        self.assertFalse(collected.scan_incomplete)
        self.assertTrue(any('older than the requested scan window' in str(call.args[0]) for call in output.call_args_list if call.args))

    def test_mixed_or_unknown_dates_do_not_prove_window_complete(self):
        progress = {'found': True, 'before': 200, 'top': 200, 'atTop': False}
        for date in ('', '31/02/2026', '24/10/2026'):
            with self.subTest(date=date):
                collected, driver, _ = self.collect([[message('old', '07/10/2026', False), message('uncertain', date, False)]], progress=progress)
                self.assertTrue(collected.scan_incomplete)
                self.assertEqual(driver.execute_script.call_count, 5)

    def test_stalled_viewport_is_incomplete_instead_of_looping_to_limit(self):
        progress = {'found': True, 'before': 200, 'top': 200, 'atTop': False}
        collected, driver, _ = self.collect([[message(image=False)]], progress=progress)
        self.assertTrue(collected.scan_incomplete)
        self.assertEqual(driver.execute_script.call_count, 5)

    def test_missing_viewport_does_not_claim_complete_history(self):
        collected, driver, _ = self.collect([[message(image=False)]], progress={'found': False})
        self.assertTrue(collected.scan_incomplete)
        self.assertEqual(driver.execute_script.call_count, 5)

    def test_all_mode_does_not_stop_at_daily_window(self):
        collected, driver, output = self.collect([[message('old', '01/01/2020', False)]], days=3650)
        self.assertTrue(collected.scan_incomplete)
        self.assertEqual(driver.execute_script.call_count, 5)
        self.assertFalse(any('older than the requested scan window' in str(call.args[0]) for call in output.call_args_list if call.args))

    def test_negative_scroll_positions_count_as_older_movement(self):
        progress = {'found': True, 'before': 0, 'top': -160, 'atTop': False, 'reversed': True}
        collected, driver, _ = self.collect([
            [message('new', '24/10/2026', False)],
            [message('old', '08/10/2026', False)],
            [message('older', '07/10/2026', False)],
        ], progress=progress)
        self.assertEqual(driver.execute_script.call_count, 3)
        self.assertFalse(collected.scan_incomplete)

    def test_loaded_edge_never_claims_full_all_history(self):
        collected, driver, _ = self.collect([[message(image=False)]], days=3650)
        self.assertTrue(collected.scan_incomplete)
        self.assertTrue(any('edge of the loaded' in issue for issue in collected.scan_issues))
