# Janani Fleet Reporting

Janani reads fleet reports and bill images from a WhatsApp group using Chrome and Selenium, then sends them to a Google Apps Script webhook for Google Sheets and Google Drive processing.

The main program is `janani-webhook.py`. Files under `Backup/` are historical copies and are not used by the current program.

## Requirements

- Windows 10 or 11 is recommended, with a supported Python 3 release (Python 3.8 or later is required by the setup launcher).
- Google Chrome, an Internet connection, and a writable project folder.
- A WhatsApp account with access to the reporting group.
- A deployed Google Apps Script webhook that accepts the program's reporting payloads and has access to the intended spreadsheet and Drive folders.

Windows 7/8/8.1 require older Python/browser versions and a matching driver installed manually. WhatsApp Web may reject these obsolete browsers. Windows XP/Vista are unsupported. See [Windows compatibility details](WINDOWS.md).

## First-time Windows setup

1. Copy the complete repository into a writable local folder, for example `C:\Janani`.
2. Install Python 3 with its launcher and Google Chrome. Install Tesseract with Hindi and English trained data as described in [BILL_OCR.md](BILL_OCR.md). In that folder, install packages once: `py -3 -m pip install -r requirements.txt`. An existing `.venv` is also supported; install its packages with `.venv\Scripts\python.exe -m pip install -r requirements.txt`.
3. Deploy the complete [Apps Script](apps_script/Janani.gs) using the [deployment instructions](apps_script/DEPLOY_COMPLETE.md). Add its `/exec` URL and the exact WhatsApp group name to `sheet_config.json` if the defaults differ.
4. Run `run_daily.bat` manually. Scan the QR code in the Chrome window opened by Janani, then check `daily_log.txt` for the matched group, validation warnings, and confirmed sheet/Drive responses.

Keep `whatsapp_session_janani` to retain login and `pushed_history.json` to retain duplicate protection. The daily BAT runs Python directly; it does not call a setup/start/run BAT or download dependencies.

## Run daily with Windows Task Scheduler

`run_daily.bat` uses `.venv\Scripts\python.exe` when present, otherwise discovers Python through `py -3`, then `python`. This avoids relying only on the Microsoft Store `python` shortcut. It checks required imports, runs `janani-webhook.py --days 15 --debug --debug-fuel`, appends stdout/stderr and timestamps to `daily_log.txt`, and preserves the sync's failure code.

After completing a manual run, open **Task Scheduler → Create Task**:

| Setting | Value |
| --- | --- |
| General | Your Windows account; **Run only when user is logged on** |
| Trigger | **Daily**, at your chosen local time |
| Action: program | `C:\Windows\System32\cmd.exe` |
| Action: arguments | `/d /c ""C:\Janani\run_daily.bat""` |
| Action: Start in | `C:\Janani` |
| Already running | **Do not start a new instance** |

Replace `C:\Janani` with your actual folder. Keep the computer awake, online, and logged in. Use Task Scheduler's **Run** action for the first scheduled test; check `daily_log.txt` for the Python path, successful WhatsApp login, exact matched group, and `[RESULT]` confirmations. A zero code can mean all valid reports were already in history, not that a new row was inserted. An expired WhatsApp login needs QR login again.

The 15-day scan overlaps successive daily runs. After a longer interruption, run `run_daily.bat --days 30` (or the number of days missed plus overlap) to retry the relevant window. Explicit `--days`/`--group` options take precedence over configuration. `--all` requests a much longer scan and can take considerable time. History protects acknowledged records during catch-up.

For an intentional longer scan, use `run_daily.bat --days 30`. `--force` can replay fuel/text entries but still respects bill history; do not use it for the daily schedule or as a general repair. The launcher returns code 2 for missing Python/packages or deployment failure, and code 1 for failed collection/uploads. Windows Task Scheduler and live WhatsApp/Drive execution still require verification on your computer; this repository's automated checks run in a Linux environment.

## Configuration

Optionally create `sheet_config.json` beside `janani-webhook.py`. Only include settings you want to override. For example:

```json
{
  "webhook_url": "https://script.google.com/macros/s/YOUR_DEPLOYMENT_ID/exec",
  "group_name": "Janani AI Reporting",
  "days": 15,
  "whatsapp_date_order": "MDY",
  "bill_ocr_engine": "tesseract"
}
```

Use your actual deployment URL in place of the example. Do not overwrite an existing configuration blindly. Keep configuration containing private deployment details out of public commits.

For offline or custom Chrome installations, add `chrome_binary` and `chromedriver_path` to this configuration, or set `JANANI_CHROME_BINARY` and `JANANI_CHROMEDRIVER` in the process environment. Environment settings take precedence for browser paths. ChromeDriver must match Chrome's major version. Modern systems without an explicitly supplied driver use Selenium Manager. See [WINDOWS.md](WINDOWS.md) for path examples and legacy-system limitations.

Configuration, history, the sync lock, and the WhatsApp profile resolve beside the Python file, even when launched from another working directory.

## Complete Google Apps Script

Use [apps_script/Janani.gs](apps_script/Janani.gs) as a single-file replacement containing the vehicle, fuel validation, fixed bill-category routing, duplicate/retry, and dashboard fixes. Follow the [deployment instructions](apps_script/DEPLOY_COMPLETE.md); do not keep duplicate helper definitions alongside the bundle. Live deployment is performed through Apps Script.

## Vehicle IDs from WhatsApp

Vehicle IDs come from the WhatsApp report itself, not from a location-to-vehicle mapping. Supported labels include `Vehicle no`, `Vehicle No.`, `Vehicle No (Full)`, `Vehicle Number`, `Vehicle ID`, `Veh No`, and `Registration No`. For example:

```text
Date - 08/10/2026
Location - Barud
Vehicle no - 5998
Present odo - 361260
Previous odo - 360541
Diesel amount - 4197.2
Diesel liter - 41.54
```

This message sends `vehicle`, `vehicle_id`, and `vehicle_no` as `5998` in the webhook JSON. A full registration such as `CG 04 NW 7485` is sent as `CG04NW7485`; a four-digit ID is preserved without inventing a registration prefix. Fuel/text reports with missing, invalid, or conflicting vehicle IDs are skipped with a warning. An image-only bill can retain a synthetic bill reference in `vehicle` for compatibility; its source vehicle ID fields remain blank when the image caption has no vehicle ID.

The supplied V79 Apps Script only maps a header called `Vehicle`, while October uses **Vehicle No (Full)**. This makes the October cell blank even when Python sends `vehicle`. Apply the [Apps Script fuel-column fix](apps_script/README.md) to the deployed project; it supports both headers, writes timestamps, and finds duplicate-check columns by name. Renaming a sheet column does not by itself change a JSON key. Existing blank October rows are not automatically filled or replayed by this fix; do not use `--force` to backfill them indiscriminately because that can create additional fuel duplicates.

## Bill classification and fuel safeguards

Bill images go to **Janani Reporting → Bills → Fuel** or **Janani Reporting → Bills → Maintanence**. Apps Script creates only these fixed category folders when missing; it creates no date subfolders. The spelling `Maintanence` matches the requested folder name.

[Hindi/English image OCR](BILL_OCR.md) recognizes the merchant phrase **Aadeshwar Fuels**, including `आदेश्वर फ्यूल्स`, directly in image pixels. Captions, pump names, and generic words such as diesel do not determine classification. Recognized fuel bills get `Bill Category = FUEL`; readable other bills get `MAINTENANCE`. OCR errors, missing Hindi data, and uncertain/unreadable images stay unacknowledged for review/retry. OCR does not fill odometers, amounts, liters, or dates from image text.

Dates in captions remain DD/MM/YYYY. Numeric WhatsApp message dates default to MM/DD/YYYY for this Windows account; set `whatsapp_date_order` to `DMY` if your WhatsApp uses DD/MM. The scan covers 15 calendar dates, including today, using received dates when available; captions can describe older reports. A bill with no date can upload with a blank date because its folder is category-based. Invalid supplied dates are flagged, never replaced with today. Unknown received-date context is logged for review rather than treated as a guessed date.

Image bytes are hashed with SHA-256; local history protects repeated images and old acknowledged images. Apps Script verifies bytes, serializes writes, and journals incomplete uploads so retries reuse a file and log row. A successful bill response must contain `driveLink`, `fileId`, `folderId`, `billCategory`, and the selected `billFolder` before Python saves history. In an uncertain interrupted creation, another copy is blocked until the reserved outcome is checked. Different encodings of a visually identical picture are not proven identical solely by hashes.

Previously acknowledged images and existing dated folders are not automatically migrated or deleted. A verified repeated request for an existing matched image can move that same file into its category folder, preserving the URL. Keep push history; do not clear it to reorganize old folders. Historical migration needs a separate review.

Fuel text reports use complete numeric values and validate dates, both odometers, money, liters, supplied distance, rate, and mileage. Ambiguous extra digits and inconsistent calculations are flagged rather than guessed. Source typos that remain numerically plausible cannot always be detected. Fuel content fingerprints preserve exact retries and surface conflicting source edits; legacy history without fingerprints is respected with a review warning. Scan limits and rejected/conflicting fuel reports produce a nonzero result after valid records are sent.

## Logs and troubleshooting

Run `run_daily.bat --check-webhook` to test the configured URL without opening WhatsApp or sending any fuel reports or bill images. It requires the complete V84 or newer Apps Script and verifies its fixed Fuel/Maintanence folder response. Every normal run performs this check first. See [complete deployment instructions](apps_script/DEPLOY_COMPLETE.md) for replacing the script and publishing a new deployment version. The check verifies the HTTP handler, not spreadsheet/Drive permissions; successful uploads verify those separately.

| Symptom | Check |
| --- | --- |
| Missing Python/packages | Check the Python path in the log and install `requirements.txt` with that interpreter |
| Chrome cannot start | Check the browser/driver versions and configured paths; close other Chrome instances using the Janani profile |
| Chrome disconnects during scrolling / invalid session ID | The scan stops on a closed/crashed session, retains valid collected reports, and returns failure for the incomplete scan. Rerun the same BAT with Chrome's Janani window left open; retain push history. Missing images get at most three attempts per run and retry on a later run. |
| WhatsApp login did not complete | Scan QR in the Chrome window opened by Janani, and allow chats to load within the 180-second wait. Login in another browser profile does not log in this one. Group search is skipped on timeout. |
| Group not found after login | Confirm the logged-in account belongs to the group. Set `group_name` in `sheet_config.json` to the exact visible name, including any emoji. Search supports editable fields and text inputs, waits up to 30 seconds for them to load, excludes the message composer, and matches exact chat names. |
| Bill OCR needs review | Install Hindi/English Tesseract data or inspect the unreadable image; see [BILL_OCR.md](BILL_OCR.md) |
| Suspicious odometer warning | Correct the source reading; use `--debug-fuel` to inspect parsing |
| Upload timeout or webhook error | Inspect the Apps Script deployment, access permissions, and execution logs before retrying |
| `Script function not found: doGet` or `doPost` | Paste the entire `apps_script/Janani.gs`, save, and deploy a **new version** of the web app; verify the `/exec` URL in `sheet_config.json` |
| Google returns HTML or a login page | Use the deployed `/exec` URL with **Execute as: Me** and **Who has access: Anyone**, as required by the current Python client |
| Another sync is running | Let the existing run finish; keep Task Scheduler's non-overlapping setting enabled |

Do not delete push history, remove browser profile locks, or use `--force` as a general repair. Confirm the cause first. `daily_log.txt` grows as runs append output; archive it periodically if needed.

The collector counts distinct messages separately from image retries, uses the requested 15-day received-message window when reliable dates establish its boundary, and stops stalled scrolling with a review status. A Chrome disconnection or cleanup failure does not erase the valid snapshot already collected; confirmed records can still be posted, while the run remains incomplete. An unavailable image is not acknowledged. The script cannot prevent Windows or a user from closing Chrome; keep the Janani browser window open and prevent overlapping scheduled/manual runs.

## Development checks

```bat
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The regression suite covers parsing, bill deduplication, fixed-category payloads, atomic history, locking, and mocked Windows browser selection. Native Windows scheduling and live WhatsApp/Google uploads have not been validated in the Linux development environment.

The portable runtime's setup flow has a PowerShell smoke test using fake downloads and Linux executables:

```text
pwsh -NoProfile -File tests/test_bootstrap_windows.ps1
```

It checks PowerShell parsing, first-time setup, cached reuse, embedded module paths, and failed-download handling. It does not execute Windows binaries or validate the BAT on Windows. The official Python and paired Windows browser/driver download URLs were also checked for availability.
