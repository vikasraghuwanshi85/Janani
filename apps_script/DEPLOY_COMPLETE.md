# Deploy the full Janani V82 Apps Script

[Janani.gs](Janani.gs) is the complete, standalone script. It contains the web-app handlers, dashboard endpoints, fuel-column mapping, validation, and Drive bill-folder code. It already includes the spreadsheet and bill-parent folder IDs from the V79 script you supplied.

## Replace the existing deployment code

1. Save a copy of the current Apps Script project outside the active project's source files.
2. Open **Extensions → Apps Script** from the spreadsheet. Replace the contents of `Code.gs` with **all** of `Janani.gs`.
3. Remove the old `fuel_header_fix.gs`, `bill_folder_fix.gs`, or other source files defining the same functions from the active project. Their contents are already bundled. Keep unrelated project files only if they do not duplicate these functions. Do not paste all the modular files alongside the bundle.
4. Confirm the three configuration values at the top: `SHEET_ID`, `BILL_IMAGES_FOLDER_ID`, and `BILL_LOG_SHEET_NAME`. Set the project's timezone to **Asia/Kolkata** in Project Settings so spreadsheet Date cells display consistently.
5. Save. Select **Deploy → Manage deployments → Edit → New version → Deploy** for the existing web-app deployment. Retain its current execution/access settings and confirm that its execution account has access to both the spreadsheet and parent Drive folder. Updating the existing deployment preserves its URL.
6. If you create a different deployment instead, put its `/exec` URL in `sheet_config.json` as `webhook_url` before running Python.
7. Update the Python checkout on Windows, then run the normal daily batch file. Confirm a real authorized response says `v: "V82"`, contains the vehicle ID for fuel, or contains `driveLink`, `fileId`, `folderId`, and the correct `dateFolder` for a bill.

Do not manually run `doPost` as an editor test for a production insert. Local tests use mocked Google services; a real daily run sends real reports.

## Included behavior

- Existing `Vehicle` and `Vehicle No (Full)` columns both receive the WhatsApp vehicle ID. Writes and duplicate checks follow header names, including reordered columns. Numeric-looking IDs are written as text; timestamps are populated where present.
- Calendar dates and month targets are validated. No missing date is replaced by today's date. Fuel reports require the source vehicle, both odometers, a positive amount and positive liters. Grouped odometers are normalized without concatenating arbitrary extra digits; negative distance, malformed numeric values, mismatched distance/rate/mileage are rejected. Missing calculated distance/rate/mileage is computed from valid inputs.
- Bills are uploaded into **configured parent → DD-MM-YYYY**. Drive access failures propagate instead of falling back to the root/parent. A successful response requires the actual file to be in that folder with a Drive URL.
- Bill bytes are hashed with SHA-256. Repeated requests reuse the file and log row; an interrupted log write can be recovered without creating another file. Matching referenced images in the wrong folder can be moved to the requested folder on a retry, keeping the same URL. Permission failures, invalid existing links, conflicting file content, or multiple same-name date folders require reconciliation.
- Fuel and bill writes use the same script lock. Existing records with blank IDs cannot match a new vehicle-aware request, so they must be reconciled before replaying historical fuel reports.
- JSON and validated JSONP responses work with the dashboard. The current payload and legacy `upload_bill` keys (`filedata`, `filename`, `date_folder`) are accepted.

## Read endpoints and compatibility

| Action | Result |
| --- | --- |
| `get_dashboard`, `get_fuel`, or empty GET action | Fuel records, `recent`, and counts |
| `get_all_data` | Bill records, matching the supplied V79 bill dashboard contract |
| `get_both`, `get_combined` | Combined data plus separate fuel and bill arrays |
| `search` with `q` or `query` | Matching combined records |
| `list_folders` | Date-folder names, IDs, and URLs under the configured parent |
| `test_date` with `date=08/10/26` | Calendar validation and full-year folder `08-10-2026` |

Dashboard results retain original sheet headers and add canonical fuel aliases such as `Vehicle` and `Present ODO`. Timestamps remain ISO timestamps rather than losing their time component.

`fix_headers` returns an explicit error instead of changing labels over existing data. `cleanupBillLogDuplicates()` now calls `previewBillLogDuplicates()` and performs no deletion. `fixFuelShiftForExistingData()` leaves data untouched. These prevent accidental historical changes while showing what needs separate review.

## Limits and historical data

The script cannot infer a missing bill date from image pixels. Python must provide a caption date or reliable WhatsApp message/date-separator context; keep the updated Python date collector. Unrecognized localized date labels may still require an explicit caption such as `Date-08/10/2026`.

Previously acknowledged bills in local push history do not automatically replay, and existing blank October IDs/duplicate rows are not automatically cleaned. Do not delete the full history or force a bulk replay to repair old rows. Different image encodings are not considered identical solely because they look alike. Moving a file may change inherited folder access. New files retain V79's link-sharing request when Drive policy permits it; this is not required for upload success.

The bundled code is tested locally but has not been deployed or verified against your live spreadsheet/Drive account by this task.

## Rebuild and test

The modular source files remain for maintenance. After changing them, rebuild the standalone file:

```text
python scripts/build_apps_script.py
node --test tests/test_full_script.cjs tests/test_bill_folders.cjs tests/test_apps_script.cjs
```

Activate the project Python environment before the tests; `test_apps_script.cjs` also exercises the Python parser. `JANANI_TEST_PYTHON` can select a specific interpreter. The complete-script tests exercise `doPost` and `doGet` with mocked Google services, including the actual WhatsApp report supplied in chat.
