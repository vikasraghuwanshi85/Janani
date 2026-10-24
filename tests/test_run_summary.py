import ast
import base64
import unittest
from unittest.mock import Mock, patch

from test_webhook import SOURCE, app, bill, fuel


class RunSummaryTests(unittest.TestCase):
    def run_main(self, entries, responses):
        namespace = dict(app.__dict__, __name__='__main__', FORCE_PUSH=False,
                         print_startup_context=Mock(), check_webhook=lambda: None,
                         read_last_n_days=lambda **kwargs: (entries, set()),
                         acquire_push_lock=lambda: Mock(), save_history=Mock())
        main = next(node for node in ast.parse(SOURCE.read_text()).body
                    if isinstance(node, ast.If) and isinstance(node.test, ast.Compare)
                    and any(isinstance(value, ast.Constant) and value.value == '__main__'
                            for value in node.test.comparators))
        with patch.object(app.requests, 'post', side_effect=[Mock(text=text, url='https://script.google.com/macros/s/example/exec') for text in responses]) as post, \
                patch.object(app.time, 'sleep'), patch('builtins.print') as output:
            try:
                exec(compile(ast.Module(body=[main], type_ignores=[]), str(SOURCE), 'exec'), namespace)
                exit_code = 0
            except SystemExit as error:
                exit_code = error.code
        summary = next(call.args[0].strip() for call in output.call_args_list
                       if call.args and str(call.args[0]).strip().startswith('[RESULT]'))
        return summary, exit_code, post

    def test_image_upload_failure_is_separate_from_unprocessed_records(self):
        entries = [app.parse_message(fuel('361260', '360541')), bill()]
        summary, code, post = self.run_main(entries, ['{"success":true}', '{"success":false,"error":"Drive permission"}'])
        self.assertEqual(summary, '[RESULT] Confirmed: 1; upload unconfirmed: 1; not processed: 0')
        self.assertEqual(post.call_count, 2)
        self.assertEqual(code, 1)

    def test_protocol_stop_counts_only_remaining_entries_as_not_processed(self):
        entries = [app.parse_message(fuel('361260', '360541')), bill()]
        summary, code, post = self.run_main(entries, ['<html>Script function not found: doPost</html>'])
        self.assertEqual(summary, '[RESULT] Confirmed: 0; upload unconfirmed: 1; not processed: 1')
        post.assert_called_once()
        self.assertEqual(code, 1)

    def test_rejection_reference_identifies_source_without_full_message(self):
        item = {'message_id': 'id\nwith-newline', 'message_date': '24/10/2026',
                'text': 'Date-24/10/2026\nVehicle no-7412\nPilot name-Private Example\nPresent odo-408780'}
        reference = app.message_reference(item)
        self.assertIn('date=24/10/2026', reference)
        self.assertIn('vehicle=7412', reference)
        self.assertIn('message=id with-newline', reference)
        self.assertNotIn('Private Example', reference)
        self.assertNotIn('\n', reference)

