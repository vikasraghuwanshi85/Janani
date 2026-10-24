import base64
import ast
import sys
from types import SimpleNamespace
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock

SOURCE = Path(__file__).resolve().parents[1] / 'janani-webhook.py'
spec = importlib.util.spec_from_file_location('janani', SOURCE)
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)
IMAGE = 'data:image/jpeg;base64,' + base64.b64encode(b'original bill image bytes').decode()


def fuel(present, previous):
    return ('Date - 08/10/2026\nVehicle no - MP04AB1234\n'
            f'Present odo - {present}\nPrevious odo - {previous}\n'
            'Diesel amount - 4197.2\nDiesel liter - 41.54')


def bill(date='08/10/2026', image=IMAGE):
    return app.parse_message(f'Date - {date}\nVehicle no - MP04AB1234', image)


class ParsingTests(unittest.TestCase):
    def test_separate_digit_not_concatenated(self):
        result, errors = app.parse_message_debug(fuel('361260', '360541 4'))
        self.assertIsNone(result)
        self.assertIn('Invalid odometer', errors[0])

    def test_screenshot_bad_readings_skipped(self):
        for present, previous in [('361260', '3605414'), ('360541', '3598913')]:
            with self.subTest(previous=previous):
                result, errors = app.parse_message_debug(fuel(present, previous))
                self.assertIsNone(result)
                self.assertIn('Suspicious odometer', errors[0])

    def test_valid_screenshot_reading(self):
        self.assertEqual(app.parse_message(fuel('366754', '366205'))['payload']['total_km'], '549')

    def test_comma_readings(self):
        self.assertEqual(app.parse_message(fuel('361,260', '360,541'))['payload']['total_km'], '719')

    def test_grouped_odometer_formats_from_skip_log(self):
        for value in ['447,194', '447, 194', '4,47,194', '447.194', '447 194', '447\u202f194']:
            with self.subTest(value=value):
                payload = app.parse_message(fuel(value, '446611'))['payload']
                self.assertEqual(payload['present_odo'], '447194')
                self.assertEqual(payload['total_km'], '583')

    def test_decimal_or_malformed_odometer_not_truncated(self):
        for value in ['447.19', '447,19', '447.1944']:
            with self.subTest(value=value):
                self.assertEqual(app.parse_odometer(value), '')

    def test_reporting_footer_does_not_truncate_message_at_comma(self):
        message = fuel('447,194', '446,611') + '\nJanani Reporting, footer, metadata, more, data'
        self.assertEqual(app.parse_message(message)['payload']['total_km'], '583')

    def test_long_alias(self):
        text = fuel('361260', '360541').replace('Present odo -', 'Present Odo Reading -')
        self.assertEqual(app.parse_message(text)['payload']['present_odo'], '361260')

    def test_numeric_label_touching_value_from_actual_export(self):
        text = ('Fuel msg-\nDate-7/10/26\nLocation-SEGAON\nVehicle no-6073\n'
                'Present odo-331956\nPrevious odo331215\nDiseal amount-4541.75\n'
                'Diseal liter-44.95\nAverage-16.48\nPilot name-Test Driver\nPump Name-Sample Pump')
        result = app.parse_message(text)
        self.assertEqual(result['payload']['previous_odo'], '331215')
        self.assertEqual(result['payload']['total_km'], '741')

    def test_touching_label_does_not_consume_other_words_or_extra_digits(self):
        self.assertEqual(app.get_field('Previous odo', 'Previous odometer331215', strict=True), '')
        self.assertIsNone(app.parse_message(fuel('331956', '331215 4').replace('Previous odo - ', 'Previous odo')))

    def test_no_silent_truncation(self):
        self.assertIsNone(app.parse_message(fuel('12345678', '12345000')))

    def test_normal_digit_rollover(self):
        self.assertEqual(app.parse_message(fuel('100001', '99999'))['payload']['total_km'], '2')

    def test_bill_date_is_metadata_only(self):
        p = bill()['payload']
        self.assertEqual(p['date_folder'], '')
        self.assertEqual(p['original_date'], '08/10/26')
        self.assertEqual(p['target_sheet'], 'Bill log')

    def test_image_only_message_date(self):
        p = app.parse_message('[IMAGE_ONLY_BILL]', IMAGE, message_date='06/10/2026')['payload']
        self.assertEqual(p['date'], '06/10/26')
        self.assertEqual(p['date_folder'], '')

    def test_missing_bill_date_is_blank_and_invalid_date_is_rejected(self):
        p = app.parse_message('[IMAGE_ONLY_BILL]', IMAGE)['payload']
        self.assertEqual(p['date'], '')
        self.assertEqual(p['original_date'], '')
        self.assertEqual(bill('31/02/2026')['payload']['date'], '')

    def test_bill_caption_date_with_display_time(self):
        payload = app.parse_message('Date - 08/10/2026 10:30 AM\nVehicle no - 7412', IMAGE)['payload']
        self.assertEqual(payload['date'], '08/10/26')

    def test_caption_date_overrides_message_date(self):
        p = app.parse_message('Date - 06/10/2026', IMAGE, message_date='08/10/2026')['payload']
        self.assertEqual(p['date'], '06/10/26')

    def test_invalid_image_skipped(self):
        self.assertIsNone(bill(image='not base64!'))

    def test_fuel_numbers_with_currency_units_and_grouping(self):
        message = fuel('361260 km', '360541 kms').replace('4197.2', '₹4,197.20').replace('41.54', '41.54 liters')
        payload = app.parse_message(message)['payload']
        self.assertEqual(payload['diesel_amount'], '4197.20')
        self.assertEqual(payload['diesel_liter'], '41.54')
        self.assertEqual(payload['total_km'], '719')

    def test_extra_numeric_text_is_not_concatenated_or_truncated(self):
        for value in ('4197.2 5', '4,19,7.2', '4197x2', '-4197.2', '4197.2.5', '9' * 400):
            with self.subTest(value=value):
                self.assertIsNone(app.parse_message(fuel('361260', '360541').replace('4197.2', value)))

    def test_zero_or_missing_fuel_values_are_rejected(self):
        message = fuel('361260', '360541')
        for text in (message.replace('41.54', '0'), message.replace('4197.2', '0'),
                     message.replace('Previous odo - 360541\n', ''),
                     message.replace('Diesel liter - 41.54', '')):
            with self.subTest(text=text):
                self.assertIsNone(app.parse_message(text))

    def test_source_calculation_conflicts_are_rejected(self):
        message = fuel('361260', '360541')
        for extra, error in (('Total KM - 718', 'Total KM'), ('Average - 3.3', 'Average'), ('Rate/L - 5', 'Rate')):
            with self.subTest(extra=extra):
                result, errors = app.parse_message_debug(message + '\n' + extra)
                self.assertIsNone(result)
                self.assertIn(error, errors[0])

    def test_matching_source_calculations_and_markdown_are_preserved(self):
        message = fuel('361260', '360541') + '\nTotal KM - 719\nAverage - 17.31 km/ltr\nRate/L - 101.04'
        message = message.replace('Diesel amount', '*Diesel amount*')
        payload = app.parse_message(message)['payload']
        self.assertEqual(payload['average'], '17.31')
        self.assertEqual(payload['rate'], '101.04')

    def test_invalid_fuel_date_is_not_substituted_with_today(self):
        for value in ('31/02/2026', '08/10/20260', 'not known'):
            with self.subTest(value=value):
                result, errors = app.parse_message_debug(fuel('361260', '360541').replace('08/10/2026', value), message_date='08/10/2026')
                self.assertIsNone(result)
                self.assertIn('report date', errors[0])

    def test_undated_fuel_requires_actual_whatsapp_date(self):
        message = fuel('361260', '360541').replace('Date - 08/10/2026\n', '')
        self.assertIsNone(app.parse_message(message))
        self.assertEqual(app.parse_message(message, message_date='08/10/2026')['payload']['date'], '08/10/26')


class DedupTests(unittest.TestCase):
    def test_same_bill_once_across_dates_and_force(self):
        a, b = bill(), bill('06/10/2026')
        self.assertEqual(a['unique_key'], b['unique_key'])
        self.assertEqual(len(app.select_entries_to_push([a, b], set(), force=True)), 1)
        self.assertEqual(app.select_entries_to_push([b], app.bill_history_keys(a), force=True), [])

    def test_base64_prefix_does_not_change_identity(self):
        self.assertEqual(bill()['unique_key'], bill(image=IMAGE.split(',')[1])['unique_key'])

    def test_legacy_history_respected_across_dates(self):
        import hashlib
        old = hashlib.md5(IMAGE.encode()).hexdigest()[:20]
        self.assertTrue(app.already_pushed(bill(), {f'01/10/26_{old}_bill'}))

    def test_old_canvas_history_respected_with_original_bytes(self):
        entry = bill()
        entry['legacy_image_hash'] = '1234567890abcdef1234'
        self.assertTrue(app.already_pushed(entry, {'01/10/26_1234567890abcdef1234_bill'}))

    def test_same_message_not_repeated_if_thumbnail_changes(self):
        a, b = bill(), bill(image=base64.b64encode(b'new thumbnail').decode())
        a['message_id'] = b['message_id'] = 'stable-whatsapp-id'
        self.assertEqual(len(app.select_entries_to_push([a, b], set())), 1)
        self.assertEqual(app.select_entries_to_push([b], app.bill_history_keys(a), force=True), [])

    def test_different_images_not_collapsed(self):
        other = 'data:image/jpeg;base64,' + base64.b64encode(b'another bill').decode()
        self.assertEqual(len(app.select_entries_to_push([bill(), bill(image=other)], set())), 2)

    def test_force_still_works_for_fuel(self):
        entry = app.parse_message(fuel('361260', '360541'))
        self.assertEqual(app.select_entries_to_push([entry], {entry['unique_key']}, force=True), [entry])

    def test_fuel_content_changes_are_not_hidden_by_same_odometer_history(self):
        original = app.parse_message(fuel('361260', '360541'))
        edited = app.parse_message(fuel('361260', '360541').replace('4197.2', '4297.2'))
        history = app.bill_history_keys(original)
        self.assertTrue(app.already_pushed(original, history))
        self.assertFalse(app.already_pushed(edited, history))
        self.assertEqual(app.select_entries_to_push([edited], history), [edited])

    def test_conflicting_same_reading_messages_are_held_before_posting(self):
        original = app.parse_message(fuel('361260', '360541'))
        edited = app.parse_message(fuel('361260', '360541').replace('4197.2', '4297.2'))
        with patch('builtins.print'):
            pending = app.select_entries_to_push([original, edited], set())
        self.assertEqual(pending, [])
        self.assertIn('Conflicting fuel', pending.scan_issues[0])

    def test_legacy_fuel_history_is_preserved_with_explicit_diagnostic(self):
        entry = app.parse_message(fuel('361260', '360541'))
        with patch('builtins.print') as output:
            self.assertEqual(app.select_entries_to_push([entry], {entry['unique_key']}), [])
        self.assertIn('Legacy fuel record', output.call_args.args[0])

    def test_history_roundtrip_and_corruption(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(app, 'HISTORY_FILE', str(Path(directory) / 'history.json')):
            app.save_history(app.bill_history_keys(bill()))
            self.assertTrue(app.already_pushed(bill(), app.load_history()))
            Path(app.HISTORY_FILE).write_text('{broken')
            with self.assertRaises(RuntimeError):
                app.load_history()

    @unittest.skipIf(os.name == 'nt', 'Unix locking exercised on cloud host')
    def test_concurrent_run_refused(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(app, 'HISTORY_FILE', str(Path(directory) / 'history.json')):
            lock = app.acquire_push_lock()
            try:
                with self.assertRaises(RuntimeError):
                    app.acquire_push_lock()
            finally:
                lock.close()

    def test_failed_atomic_write_preserves_existing_history(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(app, 'HISTORY_FILE', str(Path(directory) / 'history.json')):
            app.save_history({'previous'})
            with patch.object(app.os, 'replace', side_effect=OSError('disk error')):
                with self.assertRaises(OSError):
                    app.save_history({'new'})
            self.assertEqual(app.load_history(), {'previous'})
            self.assertEqual(len(list(Path(directory).iterdir())), 1)


class VehicleIdTests(unittest.TestCase):
    def test_actual_whatsapp_message_is_posted_with_7412(self):
        message = ("Fuel msg-\n\nDate-8/10/26\nLocation-khargone DH\nVehicle no-7412\n"
                   "Present odo-366754\nPrevious odo-366205\nDiseal amount-3441.45\n"
                   "Diseal liter-35.05\nAverage-15.66\nPilot name-Raja\nPump Name- Aadeswar")
        entry = app.parse_message(message)
        self.assertEqual(entry['payload']['vehicle'], '7412')
        self.assertEqual(entry['payload']['total_km'], '549')
        main = next(node for node in ast.parse(SOURCE.read_text()).body
                    if isinstance(node, ast.If) and isinstance(node.test, ast.Compare) and any(isinstance(value, ast.Constant) and value.value == '__main__' for value in node.test.comparators))
        namespace = dict(app.__dict__, __name__='__main__', FORCE_PUSH=False,
                         read_last_n_days=lambda **kwargs: ([entry], set()),
                         acquire_push_lock=lambda: Mock(), save_history=Mock(),
                         check_webhook=lambda: None)
        response = Mock(text='{"success":true}')
        with patch.object(app.requests, 'post', return_value=response) as post, patch.object(app.time, 'sleep'), patch('builtins.print'):
            exec(compile(ast.Module(body=[main], type_ignores=[]), str(SOURCE), 'exec'), namespace)
        post.assert_called_once()
        sent = post.call_args.kwargs['json']
        for field in ['vehicle', 'vehicle_id', 'vehicle_no']:
            self.assertEqual(sent[field], '7412')
        self.assertEqual(sent['month'], 'Oct')
        namespace['save_history'].assert_called_once()


class WebhookDeploymentTests(unittest.TestCase):
    def response(self, text, url='https://script.google.com/macros/s/example/exec'):
        return Mock(text=text, url=url)

    def run_main(self, namespace):
        main = next(node for node in ast.parse(SOURCE.read_text()).body
                    if isinstance(node, ast.If) and isinstance(node.test, ast.Compare)
                    and any(isinstance(value, ast.Constant) and value.value == '__main__'
                            for value in node.test.comparators))
        exec(compile(ast.Module(body=[main], type_ignores=[]), str(SOURCE), 'exec'), namespace)

    def test_html_google_error_is_reported_without_script_noise(self):
        response = self.response('\ufeff <!doctype html><title>Error</title><script>private javascript</script>'
                                 '<style>body{}</style><div>Script function not found: doGet</div>')
        with self.assertRaises(app.WebhookProtocolError) as error:
            app.webhook_json(response)
        self.assertIn('Script function not found: doGet', str(error.exception))
        self.assertNotIn('private javascript', str(error.exception))
        self.assertNotIn('body{}', str(error.exception))

    def test_login_page_is_reported(self):
        response = self.response('<html><body>Sign in to continue</body></html>', 'https://accounts.google.com/')
        with self.assertRaisesRegex(app.WebhookProtocolError, 'accounts.google.com.*Sign in'):
            app.webhook_json(response)

    def test_invalid_json_and_array_are_not_confirmations(self):
        for body in ['upstream error', '[{"success":true}]', 'null']:
            with self.subTest(body=body), self.assertRaises(app.WebhookProtocolError):
                app.webhook_json(self.response(body))

    def test_read_only_preflight_checks_version_and_folder(self):
        response = self.response('{"success":true,"v":"V86","billUploadMode":"FUEL_FOLDER","billOcrRequired":false}')
        with patch.object(app.requests, 'get', return_value=response) as get, patch.object(app.requests, 'post') as post, patch('builtins.print'):
            self.assertEqual(app.check_webhook()['v'], 'V86')
        self.assertEqual(get.call_args.kwargs['params'], {'action': 'test_date', 'date': '09/10/26'})
        post.assert_not_called()

    def test_old_wrong_or_failed_deployment_is_rejected(self):
        for body in ['{"v":"V79 FIXED COL SHIFT","folderFull":"09-10-2026"}',
                     '{"v":"V83","folderFull":"09-10-2026"}',
                     '{"v":"V84","billFolders":{"fuel":"Fuel","maintenance":"Maintenance"}}',
                     '{"v":"V82","folderFull":"09-10-2026"}',
                     '{"v":"V82","folderFull":"09-10-26"}',
                     '{"success":false,"error":"Drive access denied","v":"V82"}']:
            with self.subTest(body=body), patch.object(app.requests, 'get', return_value=self.response(body)), self.assertRaises(app.WebhookProtocolError):
                app.check_webhook()

    def test_dev_url_is_rejected_without_network(self):
        with patch.object(app, 'WEBHOOK_URL', 'https://script.google.com/macros/s/example/dev'), patch.object(app.requests, 'get') as get:
            with self.assertRaisesRegex(app.WebhookProtocolError, '/exec'):
                app.check_webhook()
        get.assert_not_called()

    def test_failed_preflight_stops_before_browser_or_uploads(self):
        namespace = dict(app.__dict__, __name__='__main__',
                         check_webhook=Mock(side_effect=app.WebhookProtocolError('Script function not found: doGet')),
                         read_last_n_days=Mock(), acquire_push_lock=Mock(), save_history=Mock())
        with patch.object(app.requests, 'post') as post, patch('builtins.print'), self.assertRaises(SystemExit) as error:
            self.run_main(namespace)
        self.assertEqual(error.exception.code, 2)
        namespace['read_last_n_days'].assert_not_called()
        namespace['acquire_push_lock'].assert_not_called()
        namespace['save_history'].assert_not_called()
        post.assert_not_called()

    def test_check_only_skips_browser(self):
        namespace = dict(app.__dict__, __name__='__main__', check_webhook=Mock(), read_last_n_days=Mock())
        with patch.object(sys, 'argv', ['janani-webhook.py', '--check-webhook']), self.assertRaises(SystemExit) as error:
            self.run_main(namespace)
        self.assertEqual(error.exception.code, 0)
        namespace['check_webhook'].assert_called_once()
        namespace['read_last_n_days'].assert_not_called()

    def test_html_upload_stops_batch_preserves_history_and_fails_schedule(self):
        entry = bill()
        history = set()
        namespace = dict(app.__dict__, __name__='__main__', FORCE_PUSH=False,
                         check_webhook=lambda: None, read_last_n_days=lambda **kwargs: ([entry, entry], history),
                         acquire_push_lock=lambda: Mock(), save_history=Mock(),
                         select_entries_to_push=lambda *args, **kwargs: [entry, entry])
        with patch.object(app.requests, 'post', return_value=self.response('<html>Script function not found: doPost</html>')) as post, patch('builtins.print'), self.assertRaises(SystemExit) as error:
            self.run_main(namespace)
        self.assertEqual(error.exception.code, 1)
        post.assert_called_once()
        self.assertEqual(history, set())
        namespace['save_history'].assert_not_called()

    def test_json_rejection_does_not_update_history(self):
        entry = bill()
        history = set()
        namespace = dict(app.__dict__, __name__='__main__', FORCE_PUSH=False,
                         check_webhook=lambda: None, read_last_n_days=lambda **kwargs: ([entry], history),
                         acquire_push_lock=lambda: Mock(), save_history=Mock())
        with patch.object(app.requests, 'post', return_value=self.response('{"success":false,"error":"Drive access denied"}')), patch.object(app.time, 'sleep'), patch('builtins.print'), self.assertRaises(SystemExit) as error:
            self.run_main(namespace)
        self.assertEqual(error.exception.code, 1)
        self.assertEqual(history, set())
        namespace['save_history'].assert_not_called()

    def test_http_error_is_not_confirmation(self):
        response = self.response('{"success":true}')
        response.raise_for_status.side_effect = app.requests.HTTPError('503 unavailable')
        with self.assertRaises(app.requests.HTTPError):
            app.webhook_json(response)


class VehicleLabelTests(unittest.TestCase):

    def test_supported_labels_send_vehicle_to_webhook(self):
        labels = ['Vehicle no', 'Vehicle No.', 'Vehicle No (Full)', 'Vehicle Number',
                  'Vehicle ID', 'Veh No', 'Veh.No', 'V No', 'Registration No']
        for label in labels:
            with self.subTest(label=label):
                message = fuel('361260', '360541').replace('Vehicle no - MP04AB1234', label + ' : 5998')
                payload = app.parse_message(message)['payload']
                self.assertEqual(payload['vehicle'], '5998')
                self.assertEqual(payload['vehicle_id'], '5998')
                self.assertEqual(payload['vehicle_no'], '5998')

    def test_full_registration_and_whatsapp_formatting(self):
        for text in ['Vehicle no - CG04NW7485', 'Vehicle No (Full): CG 04 NW 7485',
                     '*Vehicle no* - *cg-04-nw-7485*', '‎Vehicle no : CG04NW7485‏']:
            with self.subTest(text=text):
                self.assertEqual(app.extract_vehicle_id(text), 'CG04NW7485')

    def test_single_line_report_does_not_absorb_odometer(self):
        message = ('Date - 08/10/26 Location - Barud Vehicle no - 5998 '
                   'Present odo - 361260 Previous odo - 360541 Diesel amount - 4197.2 Diesel liter - 41.54')
        p = app.parse_message(message)['payload']
        self.assertEqual(p['vehicle'], '5998')
        self.assertEqual(p['total_km'], '719')

    def test_unseparated_single_line_vehicle_field(self):
        self.assertEqual(app.extract_vehicle_id('Vehicle no 5998 Present odo 361260'), '5998')

    def test_missing_id_is_not_guessed_from_location_or_odometer(self):
        message = fuel('361260', '360541').replace('Vehicle no - MP04AB1234\n', '').replace('Date -', 'Location - Barud\nDate -')
        result, warnings = app.parse_message_debug(message)
        self.assertIsNone(result)
        self.assertIn('vehicle ID', warnings[0])

    def test_invalid_field_does_not_turn_into_a_vehicle(self):
        for value in ['null', 'unknown', '599812', '5998 1234', '']:
            with self.subTest(value=value):
                self.assertIsNone(app.parse_message(fuel('361260', '360541').replace('MP04AB1234', value)))

    def test_conflicting_vehicles_are_rejected(self):
        self.assertEqual(app.extract_vehicle_id('Vehicle no - 5998\nVehicle ID - 6047'), '')

    def test_bare_registration_supported_but_bare_numeric_id_not_guessed(self):
        self.assertEqual(app.extract_vehicle_id('Report for CG04NW7485\nPresent odo - 360760'), 'CG04NW7485')
        self.assertEqual(app.extract_vehicle_id('Location - Barud\nOdometer - 5998'), '')

    def test_bill_placeholder_not_presented_as_source_vehicle(self):
        payload = app.parse_message('[IMAGE_ONLY_BILL]', IMAGE, message_date='08/10/26')['payload']
        self.assertEqual(payload['vehicle_id'], '')
        self.assertEqual(payload['vehicle_no'], '')
        self.assertTrue(payload['vehicle'].startswith('BILL_'))

    def test_history_identity_keeps_different_vehicles_separate(self):
        a = app.parse_message(fuel('361260', '360541').replace('MP04AB1234', '5998'))
        b = app.parse_message(fuel('361260', '360541').replace('MP04AB1234', '6047'))
        self.assertNotEqual(a['unique_key'], b['unique_key'])


class WindowsCompatibilityTests(unittest.TestCase):
    def test_cli_days_and_group_override_saved_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, 'sheet_config.json').write_text('{"days":3650,"group_name":"Saved Group"}')
            namespace = {'__name__': 'janani_config_probe', '__file__': str(Path(directory, SOURCE.name))}
            with patch.object(sys, 'argv', [SOURCE.name, '--days', '2', '--group', 'Exact Group']):
                exec(compile(SOURCE.read_text(), str(SOURCE), 'exec'), namespace)
            self.assertEqual(namespace['DAYS_TO_SCAN'], 2)
            self.assertEqual(namespace['GROUP_NAME'], 'Exact Group')

    def test_windows_versions(self):
        for major, minor, legacy, unsupported in [(5, 1, True, True), (6, 0, True, True),
                (6, 1, True, False), (6, 2, True, False), (6, 3, True, False), (10, 0, False, False)]:
            with self.subTest(version=(major, minor)), patch.object(app.platform, 'system', return_value='Windows'), patch.object(
                    app.sys, 'getwindowsversion', return_value=SimpleNamespace(major=major, minor=minor), create=True):
                info = app.detect_windows()
                self.assertEqual(info['is_legacy'], legacy)
                self.assertEqual(info['is_unsupported'], unsupported)
                self.assertEqual(info['is_win8_family'], (major, minor) in [(6, 2), (6, 3)])

    def test_paths_independent_of_working_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            old = os.getcwd()
            try:
                os.chdir(directory)
                self.assertEqual(app.local_path('pushed_history.json'), str(SOURCE.parent / 'pushed_history.json'))
            finally:
                os.chdir(old)

    def test_windows_browser_options_preserve_profile_locks(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(app, 'CHAT_DB_PATH', directory), patch.object(
                app, 'BROWSER_BINARY', ''), patch.object(app.platform, 'system', return_value='Windows'):
            lock = Path(directory) / 'SingletonLock'
            lock.write_text('owned by browser')
            options = app.get_chrome_options_universal()
            self.assertEqual(lock.read_text(), 'owned by browser')
            self.assertNotIn('--no-sandbox', options.arguments)
            self.assertNotIn('--disable-dev-shm-usage', options.arguments)
            self.assertIn('--user-data-dir=' + directory, options.arguments)

    def test_legacy_requires_explicit_driver(self):
        with patch.object(app, 'detect_windows', return_value={'is_legacy': True, 'is_unsupported': False}), patch.object(
                app, 'get_chrome_options_universal', return_value=Mock()), patch.object(app, 'DRIVER_PATH', ''), patch.object(
                app.shutil, 'which', return_value=None), patch('selenium.webdriver.Chrome') as chrome:
            with self.assertRaisesRegex(RuntimeError, 'manually installed'):
                app.create_driver_universal()
            chrome.assert_not_called()

    def test_custom_driver_paths_with_spaces(self):
        with tempfile.TemporaryDirectory(prefix='janani space ') as directory:
            driver = Path(directory) / 'chromedriver.exe'
            driver.touch()
            with patch.object(app, 'detect_windows', return_value={'is_legacy': True, 'is_unsupported': False}), patch.object(
                    app, 'get_chrome_options_universal', return_value=Mock()), patch.object(app, 'DRIVER_PATH', str(driver)), patch(
                    'selenium.webdriver.Chrome') as chrome:
                app.create_driver_universal()
                self.assertEqual(chrome.call_args.kwargs['service'].path, str(driver))
                chrome.return_value.set_script_timeout.assert_called_once_with(30)

    def test_modern_windows_uses_selenium_manager(self):
        with patch.object(app, 'detect_windows', return_value={'is_legacy': False, 'is_unsupported': False}), patch.object(
                app, 'get_chrome_options_universal', return_value=Mock()), patch.object(app, 'DRIVER_PATH', ''), patch.object(
                app.shutil, 'which', return_value=None), patch('selenium.webdriver.Chrome') as chrome:
            app.create_driver_universal()
            service = chrome.call_args.kwargs['service']
            self.assertFalse(service.path)
            self.assertIn('--log-level=WARNING', service.service_args)

    def test_missing_configured_driver_reports_path(self):
        with patch.object(app, 'detect_windows', return_value={'is_legacy': False, 'is_unsupported': False}), patch.object(
                app, 'get_chrome_options_universal', return_value=Mock()), patch.object(app, 'DRIVER_PATH', 'missing-driver.exe'):
            with self.assertRaisesRegex(RuntimeError, 'does not exist'):
                app.create_driver_universal()

    def test_windows_lock_uses_nonblocking_byte_lock(self):
        msvcrt = Mock(LK_NBLCK=1)
        with tempfile.TemporaryDirectory() as directory, patch.object(app, 'HISTORY_FILE', str(Path(directory) / 'history.json')), patch.object(
                app.os, 'name', 'nt'), patch.dict(sys.modules, {'msvcrt': msvcrt}):
            lock = app.acquire_push_lock()
            try:
                msvcrt.locking.assert_called_once_with(lock.fileno(), 1, 1)
            finally:
                lock.close()

    def test_python38_syntax(self):
        ast.parse(SOURCE.read_text(), feature_version=(3, 8))


class WhatsAppLoginTests(unittest.TestCase):
    def test_login_timeout_never_searches_or_collects(self):
        driver = Mock()
        driver.find_elements.return_value = []
        with patch.object(app, 'create_driver_universal', return_value=driver), patch.object(app, 'find_group') as search, patch.object(app, 'wait_for_whatsapp_login', side_effect=lambda d: app_wait(d, timeout=2)), patch.object(app.time, 'sleep'), patch('builtins.print'):
            self.assertEqual(app.read_last_n_days(1), ([], set()))
        search.assert_not_called()
        driver.quit.assert_called_once()

    def test_hidden_sidebar_does_not_confirm_login(self):
        driver = Mock()
        driver.find_elements.return_value = [Mock(is_displayed=Mock(return_value=False))]
        with patch.object(app.time, 'sleep'), patch('builtins.print'):
            self.assertFalse(app.wait_for_whatsapp_login(driver, timeout=2))

    def test_visible_sidebar_confirms_login_without_wait(self):
        driver = Mock()
        driver.find_elements.return_value = [Mock(is_displayed=Mock(return_value=True))]
        with patch.object(app.time, 'sleep') as sleep, patch('builtins.print'):
            self.assertTrue(app.wait_for_whatsapp_login(driver, timeout=2))
        sleep.assert_not_called()

    def test_group_search_only_clicks_exact_sidebar_match(self):
        driver = Mock()
        driver.execute_script.return_value = False
        box = Mock(is_displayed=Mock(return_value=True))
        wrong = Mock(is_displayed=Mock(return_value=True))
        wrong.get_attribute.return_value = 'Janani Other Group'
        right = Mock(is_displayed=Mock(return_value=True))
        right.get_attribute.return_value = 'Janani AI Reporting'
        driver.find_elements.side_effect = [[box], [wrong, right], [right]]
        with patch.object(app.time, 'sleep'), patch('builtins.print'):
            self.assertTrue(app.find_group(driver, app.GROUP_NAME))
        wrong.click.assert_not_called()
        right.click.assert_called_once()
        for call in driver.find_elements.call_args_list[:2]:
            self.assertIn('#side', call.args[1])
        box.send_keys.assert_any_call(app.GROUP_NAME)

    def test_shorter_query_does_not_open_a_different_alias_group(self):
        driver = Mock()
        driver.execute_script.return_value = False
        box = Mock(is_displayed=Mock(return_value=True))
        alias = Mock(is_displayed=Mock(return_value=True))
        alias.get_attribute.return_value = 'Janani'
        driver.find_elements.side_effect = lambda _by, selector: [box] if 'contenteditable' in selector else [alias]
        with patch.object(app.time, 'sleep'), patch('builtins.print'):
            self.assertFalse(app.find_group(driver, app.GROUP_NAME))
        alias.click.assert_not_called()

    def test_group_name_ignores_directional_marks_but_keeps_emoji(self):
        self.assertEqual(app.normalize_chat_name('\u200eJanani  AI Reporting\u200f'), app.normalize_chat_name('Janani AI Reporting'))
        self.assertNotEqual(app.normalize_chat_name('Janani 🚚'), app.normalize_chat_name('Janani'))

    def test_missing_sidebar_search_does_not_use_message_composer(self):
        driver = Mock()
        driver.find_elements.return_value = []
        with patch.object(app.time, 'sleep'), patch('builtins.print'):
            self.assertFalse(app.find_group(driver, app.GROUP_NAME))
        driver.find_element.assert_not_called()
        driver.execute_script.assert_not_called()

    def test_search_waits_for_field_to_appear(self):
        driver = Mock()
        driver.execute_script.return_value = False
        box = Mock()
        driver.find_elements.side_effect = [[], [], [box]]
        with patch.object(app.time, 'sleep') as sleep, patch('builtins.print'):
            self.assertIs(app.find_whatsapp_search(driver, timeout=3), box)
        self.assertEqual(sleep.call_count, 2)


app_wait = app.wait_for_whatsapp_login

if __name__ == '__main__':
    unittest.main()
