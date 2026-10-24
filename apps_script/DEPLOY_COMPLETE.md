# Deploy Janani V85 — image uploads without OCR

1. Back up the current Apps Script outside the active project. Replace all of Code.gs with [Janani.gs](Janani.gs). Remove other files defining the same functions; the bundle already contains every module.
2. Verify SHEET_ID, BILL_IMAGES_FOLDER_ID (your existing Bills folder), and BILL_LOG_SHEET_NAME. Set the project timezone to Asia/Kolkata. There are no Fuel/Maintanence folder IDs or OCR requirements.
3. Save, then **Deploy → Manage deployments → Edit → New version → Deploy**. Use the account with Sheet/Drive access under **Execute as: Me**, and **Who has access: Anyone** for this Python client. Retain the deployment URL or update webhook_url in the existing sheet_config.json if it changes.
4. Update the complete Python project on Windows. Only requests and Selenium are required; run_daily.bat calls Python directly and defaults to 15 days. Keep its WhatsApp login and push history.
5. Run `run_daily.bat --check-webhook`. It must report V85 and **direct bill upload check passed**. This check reads configuration without uploading images or proving Drive permissions.
6. Run `run_daily.bat --days 45` once to include the older September/October photos that were held for OCR (retain history and omit --force), then schedule it under the same Windows account with **Run only when user is logged on** and **Do not start a new instance**.

Images go directly to Bills. A confirmed response contains driveLink, fileId, folderId and billUploadMode DIRECT. The image checksum, script lock, and unfinished-upload journal protect retries. No OCR/Pillow/Tesseract/Google Vision is needed, and image contents never populate text-report amounts or readings. Existing folders and acknowledged history are not bulk migrated/deleted.

Maintenance text writes MAINTENANCE to the report-date month with Date, Vehicle, Location, Bill Amount, Work Details, Pilot, Pump and optional Present ODO. Fuel fields are not required. Source IDs and complete business fields deduplicate maintenance writes; conflicting edits are flagged. An attached image and valid maintenance caption create independent image/log and monthly-report records.

Pending uploads use janani_bill_v84_pending_<SHA256> for backward-compatible recovery. If the previous create outcome is unknown, inspect the reserved folder/name before removing that specific property. Do not clear all history or all script properties.

GET endpoints retain dashboard compatibility: get_fuel/get_dashboard provide monthly records, get_all_data provides Bill log, get_both/get_combined provide both, search filters records, list_folders reads existing children, and test_date returns compatibility date fields plus billUploadMode DIRECT / billOcrRequired false. Unsafe old cleanup/header-rewrite actions remain non-destructive previews/errors.

Build with `python scripts/build_apps_script.py`. Verify with `node --test tests/test_full_script.cjs tests/test_bill_folders.cjs tests/test_apps_script.cjs`. Google tests use mocks; Windows scheduling and live permissions still require the authorized manual run after deployment.
