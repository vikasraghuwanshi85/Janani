import ast
import base64
import json
import unittest
from datetime import datetime
from unittest.mock import Mock, patch

import bill_classifier
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

    def run_pipeline(self, category, response=None, review=False):
        entry, history = bill(), set()
        namespace = dict(app.__dict__, __name__='__main__', FORCE_PUSH=False,
                         check_webhook=lambda: None,
                         read_last_n_days=lambda **kwargs: ([entry], history),
                         acquire_push_lock=lambda: Mock(), save_history=Mock())
        result = {'bill_category': category, 'reason': 'fixture image OCR',
                  'confidence': 92, 'ocr_engine': 'tesseract',
                  'review_required': review, 'classifier_version': 'fixture-v1'}
        target = 'Fuel' if category == 'FUEL' else 'Maintanence'
        response = response or {'success': True, 'driveLink': 'https://drive.google.com/file/d/file-id/view',
                                'fileId': 'file-id', 'folderId': 'folder-id',
                                'billCategory': category, 'billFolder': target, 'sheet': 'Bill log'}
        main = next(node for node in ast.parse(SOURCE.read_text()).body
                    if isinstance(node, ast.If) and isinstance(node.test, ast.Compare)
                    and any(isinstance(value, ast.Constant) and value.value == '__main__'
                            for value in node.test.comparators))
        exit_code = 0
        with patch.object(bill_classifier, 'classify_bill_image', return_value=result) as ocr, \
                patch.object(app.requests, 'post', return_value=Mock(text=json.dumps(response))) as post, \
                patch.object(app.time, 'sleep'), patch('builtins.print'):
            try:
                exec(compile(ast.Module(body=[main], type_ignores=[]), str(SOURCE), 'exec'), namespace)
            except SystemExit as error:
                exit_code = error.code
        return entry, history, namespace, post, ocr, exit_code

    def test_fuel_image_posts_category_without_inventing_fuel_report_numbers(self):
        entry, history, namespace, post, ocr, code = self.run_pipeline('FUEL')
        payload = post.call_args.kwargs['json']
        self.assertEqual(payload['bill_category'], 'FUEL')
        self.assertEqual(payload['bill_folder'], 'Fuel')
        self.assertEqual(payload['target_sheet'], 'Bill log')
        self.assertEqual(payload['date_folder'], '')
        self.assertEqual(payload['present_odo'], '')
        self.assertEqual(payload['diesel_liter'], '')
        self.assertEqual(code, 0)
        self.assertTrue(app.already_pushed(entry, history))
        namespace['save_history'].assert_called_once()
        self.assertEqual(ocr.call_args.args[0], payload['image_data'])

    def test_maintenance_image_posts_to_fixed_spelling_folder(self):
        _, _, _, post, _, code = self.run_pipeline('MAINTENANCE')
        self.assertEqual(post.call_args.kwargs['json']['bill_folder'], 'Maintanence')
        self.assertEqual(code, 0)

    def test_unknown_or_review_required_ocr_does_not_post_or_acknowledge(self):
        for category, review in [('UNKNOWN', True), ('FUEL', True)]:
            with self.subTest(category=category):
                _, history, namespace, post, _, code = self.run_pipeline(category, review=review)
                post.assert_not_called()
                namespace['save_history'].assert_not_called()
                self.assertEqual(history, set())
                self.assertEqual(code, 1)

    def test_success_without_correct_url_or_folder_is_not_acknowledged(self):
        for response in [{'success': True},
                         {'success': True, 'driveLink': 'url', 'fileId': 'id', 'folderId': 'folder',
                          'billCategory': 'FUEL', 'billFolder': '08-10-2026'}]:
            with self.subTest(response=response):
                _, history, namespace, post, _, code = self.run_pipeline('FUEL', response=response)
                post.assert_called_once()
                namespace['save_history'].assert_not_called()
                self.assertEqual(history, set())
                self.assertEqual(code, 1)

