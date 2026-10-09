# Running Janani on Windows

Windows 10/11 (and comparable Windows Server versions) are the recommended targets. Install a supported Python 3 release and Google Chrome, then run `setup_windows.bat` once and `run_windows.bat --days 2` to sync. Scan the WhatsApp QR code on the first run. Only run syncing when you intend to post records to the configured Google Sheets webhook.

The launchers handle installation paths with spaces and switch to the script directory, including when invoked from Task Scheduler. Configuration, push history, the sync lock, and the WhatsApp profile are located beside `janani-webhook.py`, independent of the caller's working directory. Keep that directory writable. Preserve `pushed_history.json` and the WhatsApp profile to retain duplicate protection and login state. Close any other Chrome instance using that profile before running; profile lock files are never forcibly deleted.

Modern Windows uses Selenium Manager to obtain a driver matching installed Chrome. For offline use or a custom browser installation, provide a matching driver yourself using `JANANI_CHROMEDRIVER` and optionally `JANANI_CHROME_BINARY`. These can also be configured as `chromedriver_path` and `chrome_binary` in the existing `sheet_config.json`; environment settings take precedence. Relative paths resolve beside the script. Do not replace existing webhook/group/date settings when adding browser paths.

Example additions to an existing configuration:

```json
{
  "chrome_binary": "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
  "chromedriver_path": "C:\\Janani\\chromedriver.exe"
}
```

Windows 7/8/8.1 can only be attempted with Python compatible with that OS, Selenium 4 compatible with that Python, and a manually installed matching Chrome/ChromeDriver pair. Python 3.8 was the last Python release supporting Windows 7; Chrome 109 was the last Chrome release supporting Windows 7/8/8.1. These obsolete runtimes no longer receive security updates and WhatsApp Web may refuse their browser. The script never automatically downloads a modern incompatible browser/driver on these systems. Working live WhatsApp syncing on them cannot be guaranteed. Windows XP/Vista are unsupported by the required stack.

Run regression tests using `.venv\Scripts\python.exe -m unittest discover -s tests -v`. Windows-specific selection and locking have mocked regression coverage; actual Windows end-to-end execution has not been validated in this Linux development environment.

## Daily scheduling

Keep `run_daily.bat` beside `janani-webhook.py`. Run `setup_windows.bat` once, then run `run_daily.bat` manually and complete the WhatsApp QR login. The batch file scans the last two days, appends Python output and timestamps to `daily_log.txt`, and returns Python's exit code. Keep push history intact and do not add `--force` to the daily schedule. The Python exit code alone does not confirm successful uploads; inspect the log for login, collection, and webhook results.

In Windows Task Scheduler, create a task with these settings (replace `C:\Janani` with your actual folder):

- **General:** choose your Windows account and **Run only when user is logged on**. The current sync needs an interactive Chrome session.
- **Triggers:** add **Daily** and select your desired local time.
- **Actions:** start `C:\Windows\System32\cmd.exe` with arguments `/d /c ""C:\Janani\run_daily.bat""` and **Start in** `C:\Janani`.
- **Settings:** choose **Do not start a new instance** if the task is already running. Optionally enable **Run task as soon as possible after a scheduled start is missed**.
- Keep the PC awake, connected to the Internet, and your Windows account logged on at the selected time. Enable waking the computer in task conditions if appropriate.

Use Task Scheduler's **Run** action for a first scheduled test. Check `daily_log.txt` for confirmed webhook successes or already-present results. An expired WhatsApp login requires scanning the QR code again. This Windows task runs both WhatsApp collection and the configured Google Sheets webhook; it does not separately schedule or deploy Google Apps Script. Actual Drive folder creation and server-side duplicate protection still depend on that deployed script.
