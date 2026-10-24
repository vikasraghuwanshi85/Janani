import ast
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from selenium.common.exceptions import WebDriverException
from test_webhook import SOURCE, app


class BrowserDiagnosticTests(unittest.TestCase):
    def test_startup_context_identifies_script_even_from_another_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            previous = os.getcwd()
            try:
                os.chdir(directory)
                with patch('builtins.print') as output:
                    app.print_startup_context()
            finally:
                os.chdir(previous)
        lines = [call.args[0] for call in output.call_args_list]
        self.assertIn('[SCRIPT] ' + str(SOURCE.resolve()), lines)
        self.assertIn('[BUILD] ' + app.PYTHON_BUILD, lines)
        self.assertIn('[PYTHON] ' + sys.executable, lines)

    def test_existing_profile_check_opens_no_website_and_posts_nothing(self):
        driver = Mock()
        with patch.object(app, 'create_driver_universal', return_value=driver) as factory, \
                patch.object(app.requests, 'get') as get, patch.object(app.requests, 'post') as post, \
                patch('builtins.print'):
            app.check_browser_startup()
        factory.assert_called_once_with()
        driver.get.assert_not_called()
        driver.quit.assert_called_once()
        get.assert_not_called()
        post.assert_not_called()

    def test_fresh_check_uses_separate_temporary_profile_and_preserves_login(self):
        with tempfile.TemporaryDirectory() as real_profile:
            login = Path(real_profile) / 'login-marker'
            login.write_text('preserve this login')
            observed = []
            driver = Mock()
            def create(profile_path=None):
                observed.append(profile_path)
                self.assertNotEqual(profile_path, real_profile)
                self.assertTrue(Path(profile_path).is_dir())
                return driver
            with patch.object(app, 'CHAT_DB_PATH', real_profile), \
                    patch.object(app, 'create_driver_universal', side_effect=create), patch('builtins.print'):
                app.check_browser_startup(fresh_profile=True)
            self.assertEqual(login.read_text(), 'preserve this login')
            self.assertFalse(Path(observed[0]).exists())
            driver.quit.assert_called_once()

    def test_failed_fresh_start_cleans_only_its_diagnostic_directory(self):
        observed = []
        def fail(profile_path=None):
            observed.append(profile_path)
            raise RuntimeError('fixture startup error')
        with patch.object(app, 'create_driver_universal', side_effect=fail), patch('builtins.print'):
            with self.assertRaisesRegex(RuntimeError, 'fixture startup error'):
                app.check_browser_startup(fresh_profile=True)
        self.assertFalse(Path(observed[0]).exists())

    def run_main(self, namespace):
        main = next(node for node in ast.parse(SOURCE.read_text()).body
                    if isinstance(node, ast.If) and isinstance(node.test, ast.Compare)
                    and any(isinstance(value, ast.Constant) and value.value == '__main__'
                            for value in node.test.comparators))
        exec(compile(ast.Module(body=[main], type_ignores=[]), str(SOURCE), 'exec'), namespace)

    def test_diagnostic_command_skips_webhook_and_full_workflow(self):
        namespace = dict(app.__dict__, __name__='__main__', print_startup_context=Mock(),
                         check_webhook=Mock(), check_browser_startup=Mock(),
                         acquire_push_lock=Mock(), read_last_n_days=Mock())
        with patch.object(sys, 'argv', ['janani-webhook.py', '--check-browser', '--fresh-profile']), \
                self.assertRaises(SystemExit) as exit_status:
            self.run_main(namespace)
        self.assertEqual(exit_status.exception.code, 0)
        namespace['check_browser_startup'].assert_called_once_with(fresh_profile=True)
        namespace['check_webhook'].assert_not_called()
        namespace['read_last_n_days'].assert_not_called()

    def test_fresh_flag_alone_does_not_start_a_sync(self):
        namespace = dict(app.__dict__, __name__='__main__', print_startup_context=Mock(),
                         check_webhook=Mock(), read_last_n_days=Mock())
        with patch.object(sys, 'argv', ['janani-webhook.py', '--fresh-profile']), \
                patch('builtins.print'), self.assertRaises(SystemExit) as exit_status:
            self.run_main(namespace)
        self.assertEqual(exit_status.exception.code, 2)
        namespace['check_webhook'].assert_not_called()
        namespace['read_last_n_days'].assert_not_called()

    def test_startup_failure_stops_driver_service_and_reports_short_error(self):
        service = Mock()
        with patch.object(app, 'detect_windows', return_value={'is_legacy': False, 'is_unsupported': False}), \
                patch.object(app, 'get_chrome_options_universal', return_value=Mock()), \
                patch.object(app, 'DRIVER_PATH', ''), patch.object(app.shutil, 'which', return_value=None), \
                patch('selenium.webdriver.chrome.service.Service', return_value=service) as make_service, \
                patch('selenium.webdriver.Chrome', side_effect=WebDriverException('Chrome instance exited\nNOISY_NATIVE_STACK')), \
                patch('builtins.print'), self.assertRaises(RuntimeError) as failure:
            app.create_driver_universal()
        self.assertEqual(make_service.call_args.kwargs['log_output'], app.CHROMEDRIVER_LOG)
        self.assertEqual(make_service.call_args.kwargs['service_args'], ['--log-level=WARNING'])
        service.stop.assert_called_once()
        self.assertIn('Chrome instance exited', str(failure.exception))
        self.assertNotIn('NOISY_NATIVE_STACK', str(failure.exception))
        self.assertIn(app.CHROMEDRIVER_LOG, str(failure.exception))

