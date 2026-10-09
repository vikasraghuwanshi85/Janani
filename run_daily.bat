@echo off
setlocal
rem Chrome requires Task Scheduler: Run only when user is logged on.
chcp 65001 >nul
set "PYTHONIOENCODING=utf-8"
rem Keep this file beside janani-webhook.py. Run setup_windows.bat once first.
rem Default scan covers 2 days. Do not use --force for the daily schedule.
pushd "%~dp0"
if errorlevel 1 exit /b 1
set "JANANI_LOG=%~dp0daily_log.txt"
>>"%JANANI_LOG%" echo.
>>"%JANANI_LOG%" echo [%DATE% %TIME%] Starting Janani daily sync
if not exist ".venv\Scripts\python.exe" (
  >>"%JANANI_LOG%" echo ERROR: Python environment missing. Run setup_windows.bat first.
  popd
  exit /b 2
)
if not exist "janani-webhook.py" (
  >>"%JANANI_LOG%" echo ERROR: janani-webhook.py is missing beside this batch file.
  popd
  exit /b 2
)
".venv\Scripts\python.exe" -u "janani-webhook.py" --days 2 %* >>"%JANANI_LOG%" 2>&1
set "JANANI_EXIT=%errorlevel%"
>>"%JANANI_LOG%" echo [%DATE% %TIME%] Finished with Python exit code %JANANI_EXIT%
popd
exit /b %JANANI_EXIT%
