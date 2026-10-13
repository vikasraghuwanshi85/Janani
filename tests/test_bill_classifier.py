"""Bill routing uses image OCR evidence, never captions or guessed financial values."""
import base64
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bill_classifier as classifier


def tokens(text, confidence=93, **fields):
    return [dict(text=word, confidence=confidence, **fields) for word in text.split()]


class MerchantMatcherTests(unittest.TestCase):
    def test_hindi_merchants_and_fuel_spelling_variations(self):
        for merchant in ("आदेश्वर", "आदेशवर", "आदेश्वार", "आदेस्वर", "आदीश्वर"):
            for fuel in ("फ्यूल्स", "फ्यूल", "फ्यूलस", "फ्युल्स"):
                with self.subTest(merchant=merchant, fuel=fuel):
                    result = classifier.match_bill_tokens(tokens(merchant + " " + fuel))
                    self.assertEqual(result["bill_category"], "FUEL")
                    self.assertFalse(result["review_required"])

    def test_english_and_joined_heading(self):
        for heading in ("Aadeshwar Fuels", "Aadeswar Fuels", "आदेश्वरफ्यूल्स", "आदेश्वर\u200d फ्यूल्स"):
            self.assertEqual(classifier.match_bill_tokens(tokens(heading))["bill_category"], "FUEL")

    def test_name_alone_and_generic_diesel_do_not_mean_fuel(self):
        for body in ("Aadeshwar workshop genuine spare parts invoice", "Diesel fuel pump replacement labour charges invoice"):
            self.assertEqual(classifier.match_bill_tokens(tokens(body))["bill_category"], "MAINTENANCE")

    def test_recognized_invoice_with_other_details_is_maintenance(self):
        body = "श्री गणेश ऑटोमोबाइल इंजन मरम्मत बिल क्रमांक"
        self.assertEqual(classifier.match_bill_tokens(tokens(body))["bill_category"], "MAINTENANCE")

    def test_low_confidence_merchant_is_unknown_not_maintenance(self):
        result = classifier.match_bill_tokens(tokens("Aadeshwar Fuels", confidence=28) + tokens("Invoice genuine items quantity total"))
        self.assertEqual(result["bill_category"], "UNKNOWN")

    def test_nonfinite_confidence_cannot_confirm_merchant(self):
        for confidence in (float('nan'), float('inf'), float('-inf')):
            with self.subTest(confidence=confidence):
                result = classifier.match_bill_tokens(tokens('Aadeshwar Fuels', confidence=confidence))
                self.assertEqual(result['bill_category'], 'UNKNOWN')
        self.assertTrue(result["review_required"])

    def test_fuzzy_match_requires_high_confidence(self):
        self.assertEqual(classifier.match_bill_tokens(tokens("Aadeahwar Fuels", 89))["bill_category"], "FUEL")
        self.assertEqual(classifier.match_bill_tokens(tokens("Aadeahwar Fuels", 65))["bill_category"], "UNKNOWN")
        self.assertEqual(classifier.match_bill_tokens(tokens("Aanexhwar Fuels workshop spare parts invoice"))["bill_category"], "MAINTENANCE")

    def test_unrelated_paragraphs_do_not_form_a_merchant_heading(self):
        records = tokens("Aadeshwar", block=1) + tokens("spare engine parts invoice Fuels", block=2)
        self.assertEqual(classifier.match_bill_tokens(records)["bill_category"], "MAINTENANCE")

    def test_unreadable_text_is_unknown(self):
        for records in ([], tokens("xx", 90), tokens("random ambiguous blurred text", 25)):
            self.assertEqual(classifier.match_bill_tokens(records)["bill_category"], "UNKNOWN")

    def test_exact_word_does_not_match_unrelated_superstring(self):
        records = tokens("NotAadeshwar diesel fuels service parts invoice")
        self.assertEqual(classifier.match_bill_tokens(records)["bill_category"], "MAINTENANCE")


class ClassificationApiTests(unittest.TestCase):
    def test_cache_uses_decoded_content_and_never_rescans_success(self):
        positive = classifier.match_bill_tokens(tokens("आदेश्वर फ्यूल्स"))
        with tempfile.TemporaryDirectory() as directory, patch.object(classifier, "_tesseract_image", return_value=positive) as engine:
            path = str(Path(directory) / "ocr.json")
            one = classifier.classify_bill_image(b"same-image", cache_path=path)
            encoded = "data:image/jpeg;base64," + base64.b64encode(b"same-image").decode()
            two = classifier.classify_bill_image(encoded, cache_path=path)
            self.assertEqual(one["bill_category"], "FUEL")
            self.assertEqual(one["image_hash"], two["image_hash"])
            self.assertFalse(one["cache_hit"])
            self.assertTrue(two["cache_hit"])
            engine.assert_called_once()
            stored = json.loads(Path(path).read_text())
            self.assertNotIn("आदेश्वर", json.dumps(stored))

    def test_unknown_and_engine_errors_are_retryable(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(classifier, "_tesseract_image", side_effect=RuntimeError("Hindi language missing")) as engine:
            path = str(Path(directory) / "ocr.json")
            for _ in range(2):
                result = classifier.classify_bill_image(b"image", cache_path=path)
                self.assertEqual(result["bill_category"], "UNKNOWN")
                self.assertIn("Hindi language", result["reason"])
            self.assertEqual(engine.call_count, 2)
            self.assertFalse(Path(path).exists())

    def test_classifier_does_not_use_caption_or_cloud_by_default(self):
        with patch.object(classifier, "_tesseract_image", return_value=classifier.match_bill_tokens(tokens("Workshop genuine parts labour invoice"))), patch.object(classifier, "_google_vision_image") as cloud:
            result = classifier.classify_bill_image(b"image", config={"caption": "आदेश्वर फ्यूल्स"})
            self.assertEqual(result["bill_category"], "MAINTENANCE")
            cloud.assert_not_called()

    def test_configuration_change_invalidates_cache(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(classifier, "_tesseract_image", return_value=classifier.match_bill_tokens(tokens("आदेश्वर फ्यूल्स"))) as local, patch.object(classifier, "_google_vision_image", return_value=classifier.match_bill_tokens(tokens("Workshop genuine parts labour invoice"))) as cloud:
            path = str(Path(directory) / "ocr.json")
            classifier.classify_bill_image(b"image", cache_path=path)
            result = classifier.classify_bill_image(b"image", config={"bill_ocr_engine": "google_vision"}, cache_path=path)
            self.assertEqual(result["bill_category"], "MAINTENANCE")
            self.assertEqual(local.call_count, 1)
            self.assertEqual(cloud.call_count, 1)

    def test_invalid_or_empty_base64_returns_unknown(self):
        for value in ("", "data:image/jpeg;base64,notvalid##", "data:image/jpeg,hello"):
            self.assertEqual(classifier.classify_bill_image(value)["bill_category"], "UNKNOWN")

    def test_cloud_setup_requires_explicit_credentials(self):
        with patch.dict(os.environ, {}, clear=True):
            result = classifier.classify_bill_image(b"image", config={"bill_ocr_engine": "google_vision"})
        self.assertEqual(result["bill_category"], "UNKNOWN")
        self.assertIn("no bill_ocr_google_api_key", result["reason"])

    def test_cloud_adapter_uses_image_ocr_confidence(self):
        words = [{"symbols": [{"text": name}], "confidence": .96} for name in ("आदेश्वर", "फ्यूल्स")]
        response = Mock(status_code=200)
        response.json.return_value = {"responses": [{"fullTextAnnotation": {"pages": [{"blocks": [{"paragraphs": [{"words": words}]}]}]}}]}
        with patch("requests.post", return_value=response) as request:
            result = classifier.classify_bill_image(b"image", config={"bill_ocr_engine": "google_vision", "bill_ocr_google_api_key": "test-secret"})
        self.assertEqual(result["bill_category"], "FUEL")
        self.assertEqual(result["confidence"], 96)
        self.assertNotIn("test-secret", json.dumps(result))
        call = request.call_args.kwargs
        self.assertEqual(call["json"]["requests"][0]["imageContext"]["languageHints"], ["hi", "en"])

    def test_cloud_http_error_does_not_expose_credentials(self):
        response = Mock(status_code=403)
        with patch("requests.post", return_value=response):
            result = classifier.classify_bill_image(b"image", config={"bill_ocr_engine": "google_vision", "bill_ocr_google_api_key": "very-secret"})
        self.assertEqual(result["bill_category"], "UNKNOWN")
        self.assertNotIn("very-secret", json.dumps(result))

    def test_tesseract_missing_hindi_never_treats_english_ocr_as_maintenance(self):
        languages = Mock(returncode=0, stdout="List of languages:\neng\nosd\n")
        with patch.object(classifier, "_tesseract_executable", return_value="tesseract"), patch.object(classifier.subprocess, "run", return_value=languages):
            result = classifier.classify_bill_image(b"image")
        self.assertEqual(result["bill_category"], "UNKNOWN")
        self.assertIn("hin.traineddata", result["reason"])

    def test_bad_image_is_not_a_maintenance_receipt(self):
        languages = Mock(returncode=0, stdout="List of languages:\neng\nhin\nosd\n")
        with patch.object(classifier, "_tesseract_executable", return_value="tesseract"), patch.object(classifier.subprocess, "run", return_value=languages):
            result = classifier.classify_bill_image(b"not-an-image")
        self.assertEqual(result["bill_category"], "UNKNOWN")
        self.assertIn("not a readable image", result["reason"])


class RealHindiOcrTests(unittest.TestCase):
    """Synthetic fixture validates the installed engine; real photos still need review."""
    @classmethod
    def setUpClass(cls):
        cls.font = Path("/usr/share/fonts/truetype/noto/NotoSansDevanagari-Bold.ttf")
        cls.executable = shutil.which("tesseract")
        if not cls.executable or not cls.font.exists():
            raise unittest.SkipTest("Real Hindi OCR requires Tesseract and the Noto Devanagari font")
        config = {"bill_ocr_tessdata_dir": os.environ.get("JANANI_TEST_TESSDATA", "")} if os.environ.get("JANANI_TEST_TESSDATA") else {}
        languages = subprocess.run([cls.executable, "--list-langs"], env=classifier._tesseract_environment(config), capture_output=True, text=True, timeout=10)
        if "hin" not in languages.stdout.splitlines():
            raise unittest.SkipTest("Real Hindi OCR requires hin.traineddata; set JANANI_TEST_TESSDATA")
        cls.config = config

    def fixture(self, heading, rotate=0):
        from PIL import Image, ImageDraw, ImageFont
        image = Image.new("RGB", (1600, 1000), "white")
        drawing = ImageDraw.Draw(image)
        heading_font = ImageFont.truetype(str(self.font), 85)
        body_font = ImageFont.truetype(str(self.font), 46)
        latin_path = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
        latin_font = ImageFont.truetype(str(latin_path), 46) if latin_path.exists() else body_font
        drawing.text((85, 80), heading, fill="black", font=heading_font)
        for y, line in enumerate(("पता खरगोन मध्य प्रदेश", "Invoice number 12345", "Quantity amount total bill", "धन्यवाद आपका स्वागत है"), start=1):
            font = latin_font if line.isascii() else body_font
            drawing.text((85, 130 + y * 140), line, fill="black", font=font)
        if rotate:
            image = image.rotate(rotate, expand=True)
        output = io.BytesIO()
        image.save(output, format="PNG")
        return output.getvalue()

    def test_rendered_hindi_fuel_heading(self):
        result = classifier.classify_bill_image(self.fixture("आदेश्वर फ्यूल्स"), config=self.config)
        self.assertEqual(result["bill_category"], "FUEL", result)

    def test_rendered_maintenance_heading(self):
        result = classifier.classify_bill_image(self.fixture("गणेश ऑटो पार्ट्स"), config=self.config)
        self.assertEqual(result["bill_category"], "MAINTENANCE", result)

    def test_rotated_hindi_fuel_heading(self):
        result = classifier.classify_bill_image(self.fixture("आदेश्वर फ्यूल्स", rotate=90), config=self.config)
        self.assertEqual(result["bill_category"], "FUEL", result)


if __name__ == "__main__":
    unittest.main()
