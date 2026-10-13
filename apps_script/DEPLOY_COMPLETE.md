# Deploy the complete Janani V84 Apps Script

[Janani.gs](Janani.gs) contains all handlers, dashboard compatibility, fuel validation/uniqueness, and OCR-category bill routing. The spreadsheet and Bills parent IDs from your supplied script are retained. Local code is prepared and tested; live deployment must be performed in your Apps Script account.

## Deploy

1. Back up the current Apps Script outside the active project. Replace **all** of `Code.gs` with `Janani.gs`.
2. Remove old source files defining duplicate functions. The bundle already contains the modules; do not paste the bundle and modular files together.
3. Verify `SHEET_ID`, `BILL_IMAGES_FOLDER_ID` (the existing **Bills** folder), and `BILL_LOG_SHEET_NAME`. Optional `BILL_FUEL_FOLDER_ID` / `BILL_MAINTENANCE_FOLDER_ID` can target pre-existing direct child folders with exact names **Fuel** / **Maintanence**. Set the project timezone to **Asia/Kolkata**.
4. Save, then **Deploy → Manage deployments → Edit → New version → Deploy**. Use **Execute as: Me** with an account that can write the Sheet and Bills folder, and **Who has access: Anyone** for the current Python client, which does not sign into Google. Complete authorization prompts. Updating the same deployment preserves its URL.
5. If the URL changes, update `webhook_url` in the existing Windows `sheet_config.json`. Keep its group/browser settings.
6. Install the Python requirements and Hindi/English OCR using [BILL_OCR.md](../BILL_OCR.md). Run `run_daily.bat --check-webhook`. It must report **V84: JSON response and Fuel/Maintanence routing check passed**. This check uploads nothing and verifies handlers/routing configuration; it does not prove Drive write permissions.
7. Run `run_daily.bat` manually and complete QR login if needed. A confirmed bill response must include `billCategory`, `billFolder`, `driveLink`, `fileId`, and `folderId`. Then schedule that same BAT daily with the same Windows account and **Run only when user is logged on**.

## Bill behavior

- `FUEL` OCR category goes directly to **Bills/Fuel**; `MAINTENANCE` goes directly to **Bills/Maintanence**. Only these fixed folders are created when missing. There are no date subfolders, no new Bills parent, and no My Drive fallback.
- Unknown/missing/failed/review-required classification is rejected before upload. The server accepts the category validated by Python's image OCR; it does not perform OCR itself. Dates are optional Sheet metadata; missing dates stay blank, and supplied dates validate. Old `date_folder` fields do not route files.
- Bill log stores the category, confirmed Drive URL, image hash and classification note. It reuses recognized category headers or appends **Bill Category** safely. OCR reason/engine/confidence are recorded; full OCR text and keys are not.
- SHA-256, a script lock and a pending journal handle retries/partial writes. A matching file is reused; its log row is recovered or updated. A verified repeated request can move an existing matched image to its selected category, keeping the same URL.
- A pending `janani_bill_v84_pending_<SHA256>` property reserves folder/name before creation, adds file ID after creation, and is cleared only after the Sheet flush. If an upload outcome is unconfirmed, inspect that reserved folder/name first; only after confirming no file exists should an operator clear that specific property. A second file is blocked while outcome is uncertain.

Keep `pushed_history.json`. Old acknowledged bills and dated folders are not automatically replayed, migrated or deleted. Different encodings of the same-looking image cannot be proven identical solely by hashes. Existing conflicting copies, broken links, or duplicate category-folder names require review; no historical cleanup is automatic.

## Fuel and read endpoints

Fuel rows map real headers including Vehicle No (Full), preserve IDs as text, validate numbers/calculations, and detect duplicate or conflicting date/vehicle/odometer records. Fuel source message IDs are stored in row notes. Existing rows with blank vehicle IDs require separate review before historical replay. Malformed source readings are flagged, not guessed.

| Read action | Response |
| --- | --- |
| get_dashboard / get_fuel / empty GET | Fuel records, recent records and counts |
| get_all_data | Bill log records, preserving the supplied V79 dashboard contract |
| get_both / get_combined | Combined data with separate fuel and bill arrays |
| search | Combined records matching q/query |
| list_folders | Direct child folder metadata under Bills |
| test_date | Date-format compatibility fields and fixed billFolders proof |

JSONP callback names validate. fix_headers refuses unsafe relabeling; cleanupBillLogDuplicates previews without deletion; fixFuelShiftForExistingData leaves old data for review. If Google returns an HTML/login/function-not-found error, deploy the entire bundle as a new version and check URL/access settings. Python prints the readable error and preserves failure status/history.

## Build and checks

```text
python scripts/build_apps_script.py
node --test tests/test_full_script.cjs tests/test_bill_folders.cjs tests/test_apps_script.cjs
```

Automated Apps Script tests use mocked Google services. Python OCR tests include rendered Hindi, maintenance and rotated receipts. They do not establish live Windows scheduling, Drive permissions, WhatsApp layout or accuracy across all actual bill photos; verify those in the authorized manual run after deployment.
