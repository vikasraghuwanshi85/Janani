# Bill image recognition

Image OCR recognizes **Aadeshwar Fuels / आदेश्वर फ्यूल्स** and routes those bills to `Bills/Fuel`. Readable other bills go to `Bills/Maintanence`. Captions, pump names and generic diesel/fuel words cannot determine image classification. Dates never name Drive folders.

## Windows setup

1. Install Python packages in the interpreter used by the daily BAT: `py -3 -m pip install -r requirements.txt`, or `.venv\Scripts\python.exe -m pip install -r requirements.txt` for an existing venv. The BAT logs its chosen Python path.
2. Install Tesseract using the [Windows installation guidance](https://tesseract-ocr.github.io/tessdoc/Installation.html#windows), including **Hindi** and **English**. Run `"C:\Program Files\Tesseract-OCR\tesseract.exe" --list-langs`; it must list `hin` and `eng`.
3. If Hindi is missing, obtain `hin.traineddata` from the official [tessdata_best repository](https://github.com/tesseract-ocr/tessdata_best) and place it in the Tesseract `tessdata` directory. Best models prioritize accuracy; fast models trade some accuracy for speed.
4. If automatic detection fails, add these settings to the existing `sheet_config.json`, preserving its webhook/group settings:

```json
{
  "bill_ocr_engine": "tesseract",
  "bill_ocr_tesseract": "C:/Program Files/Tesseract-OCR/tesseract.exe",
  "bill_ocr_tessdata_dir": "C:/Program Files/Tesseract-OCR/tessdata",
  "whatsapp_date_order": "MDY",
  "days": 15
}
```

Deploy [apps_script/Janani.gs](apps_script/Janani.gs) as a **new version**, then run `run_daily.bat` manually once. The response must show `V84`; bill successes include `billCategory`, `billFolder`, `driveLink`, `fileId`, and `folderId`. Schedule this BAT with **Run only when user is logged on** and **Do not start a new instance**.

## Recognition logic

- Preserve native text first and apply EXIF orientation. Additional passes use grayscale, contrast/sharpness, a heading crop, and rotations when text remains unreadable. Native-size recognition matters for Hindi conjunct characters.
- Normalize Unicode, punctuation and directional marks while retaining Hindi vowel signs. Match common Hindi/English Aadeshwar spellings and an adjacent fuel word. Exact phrases need usable OCR confidence; a one-character fuzzy match needs higher confidence. A name alone or generic diesel/fuel is insufficient.
- Missing OCR/Hindi data, timeouts, unreadable text, and low-confidence possible merchant phrases produce `UNKNOWN`. These images are not uploaded or recorded successful; they can retry after setup or source correction. Readable other receipts become `MAINTENANCE`.
- Successful classification is cached by image SHA-256, classifier version and configured OCR paths in local `bill_ocr_cache.json`. Unknown results are never cached. Remove only this cache after changing trained data/models in place; retain push history.
- OCR categorizes images; it never fills odometers, amounts, liters, dates or vehicle IDs from image text. Fuel-message numeric validation remains separate. The log and Bill log notes retain classification reason/confidence, without the OCR body.

Poor photos and unfamiliar merchant spellings can still be misread. Automated tests use rendered Hindi, maintenance and rotated receipts; they do not establish accuracy on all your actual bills. Local Tesseract keeps OCR on your computer and requires no API key. Previously acknowledged images are not automatically reorganized; dated folders aren't deleted. A verified repeated request can move an existing matched file while preserving its URL.

## Optional Google Cloud Vision

For difficult photos, `bill_classifier.py` also supports Google Cloud Vision **DOCUMENT_TEXT_DETECTION** with Hindi/English hints. Enable the API and billing, set `JANANI_GOOGLE_VISION_API_KEY` in your Windows user's environment, and set `"bill_ocr_engine": "google_vision"` in the existing configuration. This option sends images to Google Cloud and may incur charges; it is used only when explicitly selected. Keys and full OCR text are not logged or copied to the Sheet. Local Tesseract remains the default.
