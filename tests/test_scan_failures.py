import ast
import unittest
from unittest.mock import Mock, patch

from selenium.common.exceptions import InvalidSessionIdException, NoSuchWindowException, WebDriverException, TimeoutException
from test_webhook import SOURCE, app


def message():
    date = app.datetime.now().strftime('%d/%m/%Y')
    return {'messageId': 'fuel-message', 'messageDate': date, 'hasImage': False,
            'text': f'Date-{date}\nVehicle no-7412\nPresent odo-100123\n'
                    'Previous odo-100000\nDiesel amount-1000\nDiesel liter-10'}


class BrowserFailureTests(unittest.TestCase):
    def test_closed_session_markers_are_fatal_but_timeout_is_retryable(self):
        for error in (InvalidSessionIdException('closed'), NoSuchWindowException('closed'),
                      WebDriverException('disconnected: unable to receive message from renderer'),
                      WebDriverException('tab crashed')):
            with self.subTest(error=type(error).__name__):
                self.assertTrue(app.browser_session_lost(error))
        self.assertFalse(app.browser_session_lost(TimeoutException('script timed out')))

    def test_fatal_scan_stops_without_reusing_dead_session_and_keeps_messages(self):
        driver = Mock()
        driver.execute_script.side_effect = [[message()], InvalidSessionIdException('session deleted as browser closed')]
        with patch.object(app, 'move_whatsapp_history', return_value={'found': True, 'before': 400, 'top': 200}), \
                patch.object(app.time, 'sleep'), patch('builtins.print'):
            collected = app.scroll_and_collect_with_image_fix(driver, days=15)
        self.assertEqual(driver.execute_script.call_count, 2)
        self.assertIn('fuel-message', collected)
        self.assertTrue(collected.scan_incomplete)
        self.assertEqual(len(collected.scan_issues), 1)
        self.assertIn('Chrome closed or disconnected', collected.scan_issues[0])

    def test_initial_position_failure_returns_an_incomplete_empty_collection(self):
        driver = Mock()
        with patch.object(app, 'move_whatsapp_history', side_effect=InvalidSessionIdException('closed')), \
                patch('builtins.print'):
            collected = app.scroll_and_collect_with_image_fix(driver, days=15)
        driver.execute_script.assert_not_called()
        self.assertEqual(collected, {})
        self.assertTrue(collected.scan_incomplete)
        self.assertIn('position', collected.scan_issues[0])

    def test_repeated_transient_errors_are_bounded(self):
        driver = Mock()
        driver.execute_script.side_effect = TimeoutException('script timed out')
        with patch.object(app, 'move_whatsapp_history', return_value={'found': True}), \
                patch.object(app.time, 'sleep'), patch('builtins.print'):
            collected = app.scroll_and_collect_with_image_fix(driver, days=15)
        self.assertEqual(driver.execute_script.call_count, 3)
        self.assertTrue(collected.scan_incomplete)
        self.assertIn('three consecutive', collected.scan_issues[0])

    def test_browser_dies_while_reading_image_stops_instead_of_swallowing_error(self):
        driver = Mock()
        driver.execute_script.return_value = [dict(message(), hasImage=True)]
        driver.execute_async_script.side_effect = InvalidSessionIdException('browser closed')
        with patch.object(app, 'move_whatsapp_history', return_value={'found': True}), \
                patch.object(app.time, 'sleep'), patch('builtins.print'):
            collected = app.scroll_and_collect_with_image_fix(driver, days=15)
        driver.execute_script.assert_called_once()
        driver.execute_async_script.assert_called_once()
        self.assertTrue(collected.scan_incomplete)

    def test_failed_quit_does_not_erase_collected_reports_or_existing_history(self):
        item = message()
        collected = app.ScanCollection({'fuel-message': {'text': item['text'], 'image_data': '',
                                                        'message_id': 'fuel-message', 'message_date': item['messageDate']}})
        app.stop_whatsapp_scan(collected, 'Fixture: browser disconnected')
        driver = Mock()
        driver.quit.side_effect = InvalidSessionIdException('already closed')
        history = {'previous-acknowledgment'}
        with patch.object(app, 'create_driver_universal', return_value=driver), \
                patch.object(app, 'wait_for_whatsapp_login', return_value=True), \
                patch.object(app, 'find_group', return_value=True), \
                patch.object(app, 'scroll_and_collect_with_image_fix', return_value=collected), \
                patch.object(app, 'load_history', return_value=history), \
                patch.object(app.time, 'sleep'), patch('builtins.print'):
            reports, saved_history = app.read_last_n_days(days=15)
        self.assertEqual(len(reports), 1)
        self.assertEqual(reports[0]['payload']['vehicle'], '7412')
        self.assertEqual(reports.scan_issues, ['Fixture: browser disconnected'])
        self.assertIs(saved_history, history)
        driver.quit.assert_called_once()

    def test_partial_reports_can_be_acknowledged_but_scheduler_gets_failure(self):
        entry = app.parse_message(message()['text'])
        reports = app.ReportBatch([entry], issues=['Fixture: browser disconnected'])
        history = set()
        namespace = dict(app.__dict__, __name__='__main__', FORCE_PUSH=False,
                         check_webhook=lambda: None, read_last_n_days=lambda **kwargs: (reports, history),
                         acquire_push_lock=lambda: Mock(), save_history=Mock())
        main = next(node for node in ast.parse(SOURCE.read_text()).body
                    if isinstance(node, ast.If) and isinstance(node.test, ast.Compare)
                    and any(isinstance(value, ast.Constant) and value.value == '__main__'
                            for value in node.test.comparators))
        with patch.object(app.requests, 'post', return_value=Mock(text='{"success":true,"sheet":"Oct"}')) as post, \
                patch.object(app.time, 'sleep'), patch('builtins.print'), self.assertRaises(SystemExit) as failure:
            exec(compile(ast.Module(body=[main], type_ignores=[]), str(SOURCE), 'exec'), namespace)
        post.assert_called_once()
        namespace['save_history'].assert_called_once()
        self.assertTrue(app.already_pushed(entry, history))
        self.assertEqual(failure.exception.code, 1)

