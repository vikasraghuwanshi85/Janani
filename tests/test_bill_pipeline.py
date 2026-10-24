import ast
import base64
import json
import unittest
from datetime import datetime
from unittest.mock import Mock, patch

from test_webhook import SOURCE, app, bill


class BillPipelineTests(unittest.TestCase):
    def read_fixture(self, rows):
        class FixedDate(datetime):
            @classmethod
            def now(cls):
                return cls(2026, 10, 13, 14, 0)
        with patch.object(app, 'datetime', FixedDate), \
                patch.object(app, 'create_driver_universal', return_value=Mock()), \
                patch.object(app, 'wait_for_whatsapp_login', return_value=True), \
                patch.object(app, 'find_group', return_value=True), \
                patch.object(app, 'scroll_and_collect_with_image_fix', return_value=rows), \
                patch.object(app, 'load_history', return_value=set()), \
                patch.object(app.time, 'sleep'), patch('builtins.print'):
            return app.read_last_n_days(days=15)[0]

    def test_fifteen_calendar_dates_use_received_date_for_image_window(self):
        rows = {}
        for name, received, caption in [('too-old', '28/09/2026', ''),
                                        ('boundary', '29/09/2026', ''),
                                        ('new-old-report', '13/10/2026', 'Date-01/09/2026')]:
            rows[name] = {'text': caption or '[IMAGE_ONLY_BILL]', 'has_image': True,
                          'image_data': 'data:image/jpeg;base64,' + base64.b64encode(name.encode()).decode(),
                          'message_date': received, 'message_id': name}
        reports = self.read_fixture(rows)
        self.assertEqual({report['message_id'] for report in reports}, {'boundary', 'new-old-report'})
        historical = next(report for report in reports if report['message_id'] == 'new-old-report')
        self.assertEqual(historical['payload']['date'], '01/09/26')

    def test_unread_image_is_reported_and_not_downgraded_to_text_report(self):
        reports = self.read_fixture({'missing': {'text': 'Fuel report with unread image',
                                                'has_image': True, 'image_data': '',
                                                'message_date': '13/10/2026', 'message_id': 'missing-photo'}})
        self.assertEqual(reports, [])
        self.assertTrue(any('missing-photo' in issue for issue in reports.scan_issues))

    def run_pipeline(self, response=None):
        entry, history = bill(), set()
        namespace = dict(app.__dict__, __name__='__main__', FORCE_PUSH=False,
                         check_webhook=lambda: None, read_last_n_days=lambda **kwargs: ([entry], history),
                         acquire_push_lock=lambda: Mock(), save_history=Mock())
        response = response or {'success': True, 'driveLink': 'https://drive.google.com/file/d/id/view',
                                'fileId': 'id', 'folderId': 'bills-root', 'billUploadMode': 'FUEL_FOLDER', 'billFolder': 'Fuel', 'sheet': 'Bill log'}
        main = next(node for node in ast.parse(SOURCE.read_text()).body
                    if isinstance(node, ast.If) and isinstance(node.test, ast.Compare)
                    and any(isinstance(value, ast.Constant) and value.value == '__main__' for value in node.test.comparators))
        code = 0
        with patch.object(app.requests, 'post', return_value=Mock(text=json.dumps(response))) as post, \
                patch.object(app.time, 'sleep'), patch('builtins.print'), \
                patch.dict('sys.modules', {'PIL': None, 'bill_classifier': None}):
            try:
                exec(compile(ast.Module(body=[main], type_ignores=[]), str(SOURCE), 'exec'), namespace)
            except SystemExit as error:
                code = error.code
        return entry, history, namespace, post, code

    def test_image_upload_succeeds_with_no_pillow_or_ocr_module(self):
        entry, history, namespace, post, code = self.run_pipeline()
        payload = post.call_args.kwargs['json']
        self.assertEqual(payload['target_sheet'], 'Bill log')
        self.assertNotIn('bill_category', payload)
        self.assertNotIn('ocr_status', payload)
        self.assertEqual(code, 0)
        namespace['save_history'].assert_called_once()
        self.assertTrue(app.already_pushed(entry, history))

    def test_incomplete_bill_confirmation_keeps_history_unacknowledged(self):
        for response in [{'success': True}, {'success': True, 'driveLink': 'url', 'fileId': 'id', 'folderId': 'folder', 'billUploadMode': 'OCR'}]:
            with self.subTest(response=response):
                _, history, namespace, post, code = self.run_pipeline(response)
                namespace['save_history'].assert_not_called()
                self.assertEqual(history, set())
                self.assertEqual(code, 1)

    def test_mntc_with_blank_present_odo_is_not_a_fuel_report(self):
        text = 'Mntc MSG-\nDate-17/9/26\nLocation-Test\nVehicle no-7485\nPresent odo-\nBill amount-1,250\nWork details-Electric work\nPilot name-Test Driver\nPump Name-Workshop'
        report = app.parse_message(text)
        self.assertEqual(report['type'], 'MAINTENANCE')
        self.assertEqual(report['payload']['bill_amount'], '1250')
        self.assertEqual(report['payload']['work_details'], 'Electric work')
        self.assertEqual(report['payload']['present_odo'], '')
        self.assertEqual(report['payload']['diesel_amount'], '')
        self.assertEqual(report['payload']['target_sheet'], 'Sep')

    def test_malformed_maintenance_amount_is_not_silently_shortened(self):
        text = 'Mntc MSG-\nDate-17/9/26\nVehicle no-7485\nBill amount-12x50\nWork details-Electric work'
        self.assertIsNone(app.parse_message(text))

    def test_maintenance_preserves_hindi_names_and_multiline_work(self):
        text = 'Mntc MSG-\nDate-13/10/26\nLocation-खरगोन\nVehicle no-7485\nPresent odo400138\nBill amount600\nWork details-टायर की मरम्मत\nट्यूब बदली\nPilot name-राजा\nPump Name-वर्कशॉप'
        report = app.parse_message(text)['payload']
        self.assertEqual(report['type'], 'MAINTENANCE')
        self.assertEqual(report['present_odo'], '400138')
        self.assertEqual(report['bill_amount'], '600')
        self.assertEqual(report['work_details'], 'टायर की मरम्मत\nट्यूब बदली')
        self.assertEqual(report['pilot'], 'राजा')
        self.assertEqual(report['location'], 'खरगोन')

    def test_maintenance_caption_and_its_image_produce_separate_records(self):
        text = 'Mntc MSG-\nDate-13/10/26\nVehicle no-7485\nBill amount-350\nWork details-Electric work'
        reports = self.read_fixture({'attached': {'text': text, 'has_image': True,
                                                 'image_data': 'data:image/jpeg;base64,' + base64.b64encode(b'image').decode(),
                                                 'message_date': '13/10/2026', 'message_id': 'attached'}})
        self.assertEqual(len(reports), 2)
        self.assertEqual({r['payload']['target_sheet'] for r in reports}, {'Bill log', 'Oct'})

    def test_full_maintenance_work_details_are_part_of_duplicate_identity(self):
        prefix = 'Mntc MSG-\nDate-13/10/26\nVehicle no-7485\nBill amount-600\nWork details-'
        shared = 'Replace the damaged component and '
        first = app.parse_message(prefix + shared + 'repair wiring')
        second = app.parse_message(prefix + shared + 'replace fuse')
        self.assertNotEqual(first['unique_key'], second['unique_key'])
        self.assertFalse(app.already_pushed(second, app.bill_history_keys(first)))
        self.assertTrue(app.already_pushed(first, app.bill_history_keys(first)))
        self.assertTrue(app.already_pushed(first, {first['legacy_maintenance_key']}))
