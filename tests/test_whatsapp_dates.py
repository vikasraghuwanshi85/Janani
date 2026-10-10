import ast
import os
from pathlib import Path
import tempfile
import unittest


@unittest.skipUnless(os.environ.get('JANANI_TEST_BROWSER') and os.environ.get('JANANI_TEST_DRIVER'),
                     'Set JANANI_TEST_BROWSER and JANANI_TEST_DRIVER for browser date tests')
class WhatsAppDateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from selenium import webdriver
        from selenium.webdriver.chrome.service import Service
        cls.profile = tempfile.TemporaryDirectory()
        options = webdriver.ChromeOptions()
        options.binary_location = os.environ['JANANI_TEST_BROWSER']
        options.add_argument('--headless=new')
        options.add_argument('--user-data-dir=' + cls.profile.name)
        if os.name != 'nt':
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
        cls.driver = webdriver.Chrome(service=Service(os.environ['JANANI_TEST_DRIVER']), options=options)
        source = ast.parse((Path(__file__).resolve().parents[1] / 'janani-webhook.py').read_text())
        fn = next(node for node in source.body if isinstance(node, ast.FunctionDef)
                  and node.name == 'scroll_and_collect_with_image_fix')
        cls.collection_script = next(node.args[0].value for node in ast.walk(fn)
                           if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                           and node.func.attr == 'execute_script' and isinstance(node.args[0], ast.Constant)
                           and 'let result' in node.args[0].value)

    @classmethod
    def tearDownClass(cls):
        cls.driver.quit()
        cls.profile.cleanup()

    def collect(self, html):
        self.driver.get('about:blank')
        self.driver.execute_script('document.body.innerHTML=arguments[0]', '<div id="main">' + html + '</div>')
        return self.driver.execute_script(type(self).collection_script)

    @staticmethod
    def bill(identifier, extra=''):
        return '<div data-id="' + identifier + '">Bill<img src="blob:http://example/bill">' + extra + '</div>'

    def test_chat_search_supports_input_outside_side_and_excludes_composer(self):
        from test_webhook import app
        self.driver.get('about:blank')
        self.driver.execute_script('document.body.innerHTML=arguments[0]',
            '<div id="main"><input aria-label="Search" id="composer"></div>'
            '<input aria-label="Search chats" id="chat-search">')
        field = app.find_whatsapp_search(self.driver, timeout=1)
        self.assertEqual(field.get_attribute('id'), 'chat-search')

    def test_chat_search_supports_editable_data_tab_outside_side(self):
        from test_webhook import app
        self.driver.get('about:blank')
        self.driver.execute_script('document.body.innerHTML=arguments[0]',
            '<div contenteditable="true" data-tab="3" id="chat-search"></div>')
        field = app.find_whatsapp_search(self.driver, timeout=1)
        self.assertEqual(field.get_attribute('id'), 'chat-search')

    def test_image_only_uses_preceding_date_separator(self):
        rows = self.collect('<div>06/10/2026</div>' + self.bill('a') + '<div>08/10/2026</div>' + self.bill('b'))
        self.assertEqual([r['messageDate'] for r in rows], ['06/10/2026', '08/10/2026'])

    def test_caption_in_other_message_not_used_as_date_separator(self):
        rows = self.collect(self.bill('a', '<span>Date - 06/10/2026</span>') + self.bill('b'))
        self.assertEqual(rows[1]['messageDate'], '')

    def test_future_separator_not_used_for_earlier_bill(self):
        rows = self.collect(self.bill('a') + '<div>08/10/2026</div>')
        self.assertEqual(rows[0]['messageDate'], '')

    def test_metadata_takes_priority_over_separator(self):
        rows = self.collect('<div>08/10/2026</div>' + self.bill('a', '<span data-pre-plain-text="[10:00, 06/10/2026] Sender:"></span>'))
        self.assertEqual(rows[0]['messageDate'], '06/10/2026')

    def test_timestamp_tooltip_fallback(self):
        rows = self.collect(self.bill('a', '<span title="08/10/2026 10:00">10:00</span>'))
        self.assertEqual(rows[0]['messageDate'], '08/10/2026')

    def test_named_month_separator(self):
        rows = self.collect('<span>8 October 2026</span>' + self.bill('a'))
        self.assertEqual(rows[0]['messageDate'], '08/10/2026')

    def test_yesterday_uses_browser_local_calendar(self):
        expected = self.driver.execute_script("let d=new Date();d.setDate(d.getDate()-1);return String(d.getDate()).padStart(2,'0')+'/'+String(d.getMonth()+1).padStart(2,'0')+'/'+d.getFullYear()")
        rows = self.collect('<div>Yesterday</div>' + self.bill('a'))
        self.assertEqual(rows[0]['messageDate'], expected)

    def test_invalid_calendar_date_remains_unknown(self):
        rows = self.collect('<div>31/02/2026</div>' + self.bill('a'))
        self.assertEqual(rows[0]['messageDate'], '')
