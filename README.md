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

1. Download this repository into a writable folder, for example `C:\Janani`.
2. Install Python with the Python launcher or **Add Python to PATH**, and install Chrome.
3. Run `setup_windows.bat`. It creates `.venv` and installs `requirements.txt`.
4. Check the webhook and WhatsApp group settings before running. The program contains defaults; override them as described below if needed.
5. Run `run_windows.bat --days 2`. Chrome opens; scan the WhatsApp QR code using your phone's **Linked devices** screen.
6. Check the console for collected records and webhook confirmations. Running this command sends real reports to the configured destination.

Keep the `whatsapp_session_janani` folder to retain the login. Keep `pushed_history.json` to prevent previously acknowledged bills from being uploaded again.

## Run manually

```bat
run_windows.bat --days 2
run_windows.bat --days 7 --debug-fuel
```

`--days` selects the scan period; the Python default is ten days; the daily launcher explicitly uses two days. `--group "Your Group Name"` selects a different group. `--debug-fuel` prints parsing diagnostics. Settings in `sheet_config.json` for `days` and `group_name` take precedence over those command-line options.

`--force` allows previously recorded fuel/text entries to be sent again. It still respects bill-image history. Avoid using it for routine scheduled runs. `--all` requests a much longer scan and can take considerable time. Image bills currently bypass the parsed-date cutoff, so older bills encountered during scrolling may also be considered; their known push history still applies.

## Run daily with Windows Task Scheduler

`run_daily.bat` runs the complete Python workflow: WhatsApp collection followed by webhook requests for the selected reports. It scans two days by default, appends output to `daily_log.txt`, and returns Python's exit code. The two-day scan provides overlap between daily runs; history and duplicate checks prevent acknowledged entries from being sent again.

Run `run_daily.bat` manually once before scheduling, complete the QR login if needed, and check the log. Then open **Task Scheduler → Create Task**:

| Setting | Value |
| --- | --- |
| General | Use your Windows account and select **Run only when user is logged on** |
| Trigger | **Daily**, at your chosen local time |
| Action: program | `C:\Windows\System32\cmd.exe` |
| Action: arguments | `/d /c ""C:\Janani\run_daily.bat""` |
| Action: Start in | `C:\Janani` |
| If the task is already running | **Do not start a new instance** |

Replace `C:\Janani` with your actual project folder. Keep the computer awake, connected to the Internet, and your account logged on. You may enable **Wake the computer to run this task** and **Run task as soon as possible after a scheduled start is missed** if suitable for your machine.

Use Task Scheduler's **Run** action to test the task. Check `daily_log.txt` for login, collection, and webhook results. A zero exit code or Task Scheduler success alone does not establish that reports were uploaded. An expired WhatsApp session requires another QR login. The current browser workflow is interactive and is not validated for **Run whether user is logged on or not**.

## Configuration

Optionally create `sheet_config.json` beside `janani-webhook.py`. Only include settings you want to override. For example:

```json
{
  "webhook_url": "https://script.google.com/macros/s/YOUR_DEPLOYMENT_ID/exec",
  "group_name": "Janani AI Reporting",
  "days": 2
}
```

Use your actual deployment URL in place of the example. Do not overwrite an existing configuration blindly. Keep configuration containing private deployment details out of public commits.

For offline or custom Chrome installations, add `chrome_binary` and `chromedriver_path` to this configuration, or set `JANANI_CHROME_BINARY` and `JANANI_CHROMEDRIVER` in the process environment. Environment settings take precedence for browser paths. ChromeDriver must match Chrome's major version. Modern systems without an explicitly supplied driver use Selenium Manager. See [WINDOWS.md](WINDOWS.md) for path examples and legacy-system limitations.

Configuration, history, the sync lock, and the WhatsApp profile resolve beside the Python file, even when launched from another working directory.

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

## Bill and odometer safeguards

- Bills are identified by decoded image bytes and stable WhatsApp message IDs. Repeated bills are filtered within a run and against saved history, including during forced runs. Compatible history from older versions is also recognized.
- A bill uses the date written in its caption, falling back to the WhatsApp message date. Dates use day/month/year. Missing or invalid dates cause the bill to be skipped rather than assigned today's folder.
- The payload includes `date_folder` as `DD-MM-YYYY`, `original_date`, `image_hash`, and an `idempotency_key`. The deployed Apps Script must honor the date and image identity when creating Drive files. Python does not create Drive folders directly.
- Odometer parsing reads one numeric value, supports comma-grouped readings, and avoids joining extra numbers into the reading. Invalid or suspicious pairs are skipped with a warning. An attached stray digit whose intended value is ambiguous is not guessed; correct the source message before retrying.
- History is saved atomically after an acknowledged success or duplicate response. A corrupt history file stops processing instead of silently treating every bill as new. A process lock prevents simultaneous syncs sharing the same history file.

Exactly-once uploads after a lost webhook response require server-side idempotency in Apps Script. Python cannot establish whether a timed-out request already created a Drive file. Different encodings of the same visual image may also need server-side handling when they come from different WhatsApp messages. Existing duplicate Drive files and incorrect spreadsheet rows are not automatically removed or repaired.

## Logs and troubleshooting

| Symptom | Check |
| --- | --- |
| Missing Python environment | Run `setup_windows.bat` and confirm `.venv\Scripts\python.exe` exists |
| Chrome cannot start | Check the browser/driver versions and configured paths; close other Chrome instances using the Janani profile |
| QR screen or group not found | Reconnect WhatsApp and check the exact group name |
| Bill skipped for its date | Add a valid date to the caption or check that WhatsApp message-date metadata is available |
| Suspicious odometer warning | Correct the source reading; use `--debug-fuel` to inspect parsing |
| Upload timeout or webhook error | Inspect the Apps Script deployment, access permissions, and execution logs before retrying |
| Another sync is running | Let the existing run finish; keep Task Scheduler's non-overlapping setting enabled |

Do not delete push history, remove browser profile locks, or use `--force` as a general repair. Confirm the cause first. `daily_log.txt` grows as runs append output; archive it periodically if needed.

## Development checks

```bat
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The regression suite covers parsing, bill deduplication, date-folder payloads, atomic history, locking, and mocked Windows browser selection. Native Windows scheduling and live WhatsApp/Google uploads have not been validated in the Linux development environment.
