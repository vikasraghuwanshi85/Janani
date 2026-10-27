import ast
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


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

    def collect(self, html, date_order='DMY'):
        self.driver.get('about:blank')
        self.driver.execute_script('document.body.innerHTML=arguments[0]', '<div id="main">' + html + '</div>')
        return self.driver.execute_script(type(self).collection_script, date_order)

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

    def test_text_only_chat_row_opens_exact_group_and_confirms_header(self):
        from test_webhook import app
        self.driver.get('about:blank')
        self.driver.execute_script('document.body.innerHTML=arguments[0]',
            '<input aria-label="search chats">'
            '<div data-testid="chat-list"><div role="listitem" id="group" '
            'onclick="document.querySelector(\'#title\').textContent=\'Janani AI Reporting\'">'
            'Janani AI Reporting<br>Latest report</div></div>'
            '<div id="main"><header><span data-testid="conversation-title" id="title">Other</span></header>'
            '<div role="row" title="Janani AI Reporting" id="body-match">Quoted group name</div></div>')
        with patch.object(app.time, 'sleep'), patch('builtins.print'):
            self.assertTrue(app.find_group(self.driver, 'Janani AI Reporting'))
        self.assertEqual(self.driver.find_element('id', 'title').text, 'Janani AI Reporting')

    def test_collection_ignores_more_numerous_sidebar_rows(self):
        self.driver.get('about:blank')
        self.driver.execute_script('document.body.innerHTML=arguments[0]',
            '<div id="side">' + ''.join('<div role="row">Vehicle no - 9999 Date - 08/10/26</div>' for _ in range(5)) + '</div>'
            '<div id="main"><div data-id="real-report">Vehicle no - 7412 Date - 08/10/26</div></div>')
        rows = self.driver.execute_script(type(self).collection_script)
        self.assertEqual([row['messageId'] for row in rows], ['real-report'])

    def test_text_report_does_not_absorb_quoted_odometer(self):
        rows = self.collect('<div data-id="a"><div data-testid="quoted-message">'
            '<span class="selectable-text copyable-text">Previous odo - 9999999</span></div>'
            '<span class="selectable-text copyable-text">Vehicle no - 7412\nPresent odo - 366754</span></div>')
        self.assertNotIn('9999999', rows[0]['text'])
        self.assertIn('366754', rows[0]['text'])

    def test_scrolls_real_viewport_with_overlapping_pages(self):
        from test_webhook import app
        self.driver.get('about:blank')
        self.driver.execute_script('document.body.innerHTML=arguments[0]',
            '<div id="main"><div id="viewport" style="height:200px;overflow-y:auto">'
            '<div data-testid="conversation-panel-messages" style="height:2000px">Messages</div>'
            '</div></div>')
        newest = app.move_whatsapp_history(self.driver, 'newest')
        older = app.move_whatsapp_history(self.driver)
        self.assertTrue(older['found'])
        self.assertGreater(older['top'], 0)
        self.assertGreater(newest['top'], older['top'])
        self.assertLess(newest['top'] - older['top'], older['viewport'])

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

    def test_mdy_metadata_means_october_second_and_third(self):
        rows = self.collect(self.bill('a', '<span data-pre-plain-text="[10:00, 10/02/2026] Sender:"></span>')
            + self.bill('b', '<span data-pre-plain-text="[10:30, 10/03/2026] Sender:"></span>'), date_order='MDY')
        self.assertEqual([row['messageDate'] for row in rows], ['02/10/2026', '03/10/2026'])

    def test_mdy_numeric_separator_and_tooltip(self):
        rows = self.collect('<div>10/02/2026</div>' + self.bill('a')
            + self.bill('b', '<span title="10/03/2026 10:00">10:00</span>'), date_order='MDY')
        self.assertEqual([row['messageDate'] for row in rows], ['02/10/2026', '03/10/2026'])

    def test_mdy_default_and_explicit_dmy_only_affect_whatsapp_metadata(self):
        html = self.bill('a', '<span data-pre-plain-text="[10:00, 10/02/2026] Sender:"></span>')
        self.assertEqual(self.collect(html, 'DMY')[0]['messageDate'], '10/02/2026')
        self.driver.get('about:blank')
        self.driver.execute_script('document.body.innerHTML=arguments[0]', '<div id="main">' + html + '</div>')
        rows = self.driver.execute_script(type(self).collection_script)
        self.assertEqual(rows[0]['messageDate'], '02/10/2026')

    def test_unambiguous_numeric_day_and_iso_named_dates_keep_calendar_day(self):
        for heading in ('13/10/2026', '2026-10-13', '13 October 2026'):
            for order in ('MDY', 'DMY'):
                with self.subTest(heading=heading, order=order):
                    rows = self.collect('<div>' + heading + '</div>' + self.bill('a'), order)
                    self.assertEqual(rows[0]['messageDate'], '13/10/2026')

    def test_report_caption_date_remains_dmy_with_mdy_whatsapp_metadata(self):
        from test_webhook import app, IMAGE
        rows = self.collect(self.bill('a', '<span data-pre-plain-text="[10:00, 10/08/2026] Sender:"></span>'
            '<span>Date - 06/10/2026</span>'), 'MDY')
        self.assertEqual(rows[0]['messageDate'], '08/10/2026')
        report = app.parse_message(rows[0]['text'], IMAGE, message_date=rows[0]['messageDate'])
        self.assertEqual(report['payload']['date'], '06/10/26')
        self.assertEqual(report['payload']['date_folder'], '')

    def media_fixture(self, inline=False, full=True):
        self.driver.get('about:blank')
        return self.driver.execute_async_script('''
            const done = arguments[arguments.length - 1];
            const inline = arguments[0], full = arguments[1];
            let c = document.createElement('canvas'); c.width = 1000; c.height = 600;
            let ctx = c.getContext('2d');
            for(let y=0;y<600;y+=4) for(let x=0;x<1000;x+=4) {
                ctx.fillStyle = `rgb(${(x*37+y*11)%256},${(x*13+y*31)%256},${(x*71+y*7)%256})`;
                ctx.fillRect(x,y,4,4);
            }
            window.originalBill = c.toDataURL('image/png');
            c.width=80;c.height=60;ctx=c.getContext('2d');ctx.fillStyle='gray';ctx.fillRect(0,0,80,60);
            document.body.innerHTML='<div id="main"><div data-id="photo"><img id="preview"></div></div>';
            window.clicked=false;
            let img=document.querySelector('#preview');
            img.onclick=()=>{
                window.clicked=true;
                let dialog=document.createElement('div');dialog.setAttribute('role','dialog');
                dialog.innerHTML='<button aria-label="Close">close</button>';
                dialog.querySelector('button').onclick=()=>dialog.remove();
                if(full){let big=document.createElement('img');big.src=window.originalBill;dialog.append(big);}
                document.body.append(dialog);
            };
            img.onload=()=>done(window.originalBill);
            img.src=inline ? window.originalBill : c.toDataURL('image/png');
        ''', inline, full)

    def read_full_media(self):
        source = ast.parse((Path(__file__).resolve().parents[1] / 'janani-webhook.py').read_text())
        script = next(n.args[0].value for n in ast.walk(source)
                      if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                      and n.func.attr == 'execute_async_script' and n.args
                      and isinstance(n.args[0], ast.Constant) and 'BILL_FULL_MEDIA' in str(n.args[0].value))
        return self.driver.execute_async_script(script, '', False, 'photo')

    def test_viewer_original_bytes_replace_inline_thumbnail(self):
        original = self.media_fixture()
        result = self.read_full_media()
        self.assertTrue(result['image_data'] == original, 'Original image bytes were changed')
        self.assertEqual((result['width'], result['height']), (1000, 600))
        self.assertGreater(result['bytes'], 8192)
        self.assertFalse(self.driver.find_elements('css selector', '[role="dialog"]'))

    def test_full_inline_photo_is_preserved_without_opening_viewer(self):
        original = self.media_fixture(inline=True)
        result = self.read_full_media()
        self.assertTrue(result['image_data'] == original)
        self.assertFalse(self.driver.execute_script('return window.clicked'))

    def test_small_unavailable_photo_is_not_enlarged_or_returned(self):
        self.media_fixture(full=False)
        result = self.read_full_media()
        self.assertEqual(result['image_data'], '')
        self.assertFalse(self.driver.find_elements('css selector', '[role="dialog"]'))

    def test_reverse_message_list_scrolls_negative_to_older_history(self):
        from test_webhook import app
        self.driver.get('about:blank')
        self.driver.execute_script('document.body.innerHTML=arguments[0]',
            '<div id="main"><div id="viewport" style="height:200px;overflow-y:auto;display:flex;flex-direction:column-reverse">'
            + ''.join('<div data-id="m%d" style="min-height:100px">Message %d</div>' % (i, i) for i in range(20))
            + '</div></div>')
        newest = app.move_whatsapp_history(self.driver, 'newest')
        older = app.move_whatsapp_history(self.driver)
        self.assertEqual(newest['top'], 0)
        self.assertTrue(older['reversed'])
        self.assertLess(older['top'], 0)
        self.assertFalse(older['atTop'])
        for _ in range(20):
            edge = app.move_whatsapp_history(self.driver)
        self.assertTrue(edge['atTop'])
        self.assertEqual(edge['top'], -(edge['height'] - edge['viewport']))

    def test_message_viewport_selected_over_scrollable_surrounding_panel(self):
        from test_webhook import app
        self.driver.get('about:blank')
        self.driver.execute_script('document.body.innerHTML=arguments[0]',
            '<div id="main" style="height:300px;overflow-y:auto">'
            '<div style="height:600px">Header</div>'
            '<div id="viewport" style="height:200px;overflow-y:auto">'
            '<div data-id="report" style="height:2000px">Date-27/10/26 Vehicle-7412</div>'
            '</div></div>')
        newest = app.move_whatsapp_history(self.driver, 'newest')
        self.assertEqual(newest['viewport'], 200)
        self.assertEqual(newest['top'], 1800)
        self.assertEqual(self.driver.execute_script("return document.querySelector('#main').scrollTop"), 0)

    def test_deleted_media_popup_is_dismissed_without_waiting_for_image(self):
        self.media_fixture(full=False)
        self.driver.execute_script("""
            document.querySelector('#main img').onclick = () => {
                const popup = document.createElement('div'); popup.setAttribute('role','alertdialog');
                popup.innerHTML = "Couldn't download image. Please ask that it be resent to you.<button>OK</button>";
                popup.querySelector('button').onclick = () => popup.remove();
                document.body.appendChild(popup);
            };
        """)
        result = self.read_full_media()
        self.assertTrue(result['unavailable'])
        self.assertEqual(result['image_data'], '')
        self.assertFalse(self.driver.find_elements('css selector', '[role="alertdialog"]'))
