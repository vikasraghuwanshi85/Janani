import unittest
from unittest.mock import patch

from test_webhook import app, fuel


class ReportDiagnosticsTests(unittest.TestCase):
    def test_invalid_number_names_exact_field_without_logging_private_text(self):
        message = fuel('361260', '360541').replace('41.54', '41x54') + '\nPilot name-Private Name'
        result, errors = app.parse_message_debug(message)
        self.assertIsNone(result)
        self.assertIn("Diesel liter='41x54'", errors[0])
        self.assertNotIn('Diesel amount=', errors[0])
        self.assertNotIn('Private Name', errors[0])

    def test_missing_amount_and_optional_average_are_distinguished(self):
        result, errors = app.parse_message_debug(fuel('361260', '360541').replace('Diesel amount - 4197.2', ''))
        self.assertIsNone(result)
        self.assertIn('Diesel amount=<missing>', errors[0])
        self.assertNotIn('Average=', errors[0])

    def test_history_duplicate_and_conflict_counts_are_separate(self):
        old = app.parse_message(fuel('361260', '360541'))
        new = app.parse_message(fuel('362000', '361260'))
        conflicting = app.parse_message(fuel('363000', '362000'))
        edited = app.parse_message(fuel('363000', '362000').replace('4197.2', '4200'))
        with patch('builtins.print') as output:
            batch = app.select_entries_to_push([old, new, new, conflicting, edited], app.bill_history_keys(old))
        self.assertEqual(batch, [new])
        self.assertEqual(batch.selection_counts, {'history': 1, 'duplicates': 1, 'conflicts': 2})
        lines = [str(call.args[0]) for call in output.call_args_list if call.args]
        self.assertTrue(any(line.startswith('[HISTORY SKIP] ' + old['unique_key']) for line in lines))

    def test_user_six_reports_parse_without_number_changes(self):
        reports = [
            ('20/10/26', '2464', '453403', '452975', '3409.09', '33.74', '12.68'),
            ('23/10/26', '2464', '454189', '453403', '5250.04', '51.96', '15.12'),
            ('24/10/26', '2464', '454731', '454189', '3555.60', '35.19', '15.40'),
            ('27/10/26', '2464', '455515', '454731', '5600.65', '55.43', '14.14'),
            ('23/10/2026', '6072', '415087', '414665', '2853.37', '28.24', '14.94'),
            ('24/10/2026', '6072', '415527', '415087', '2663.41', '26.36', '16.69'),
        ]
        for date, vehicle, present, previous, amount, liters, average in reports:
            with self.subTest(date=date, vehicle=vehicle):
                message = (f'Fuel msg-\nDate-{date}\nLocation-karahi\nVehicle no-{vehicle}\n'
                           f'Present odo-{present}\nPrevious odo-{previous}\nDiseal amount-{amount}\n'
                           f'Diseal liter-{liters}\nAverage-{average}\nPilot name- विकास\nPump Name-adeshwar')
                result, errors = app.parse_message_debug(message)
                self.assertIsNotNone(result, errors)
                payload = result['payload']
                self.assertEqual(payload['vehicle'], vehicle)
                self.assertEqual(payload['diesel_amount'], amount)
                self.assertEqual(payload['diesel_liter'], liters)
                self.assertEqual(payload['average'], average)
                self.assertEqual(payload['total_km'], str(int(present) - int(previous)))
