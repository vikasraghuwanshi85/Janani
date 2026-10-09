@echo off
setlocal
rem Windows 10/11. Task Scheduler: Run only when user is logged on.
chcp 65001 >nul
set "PYTHONIOENCODING=utf-8"
rem Copy the complete project; Python, packages and browser set up automatically.
rem Default scan covers 2 days. Do not use --force for the daily schedule.
pushd "%~dp0"
if errorlevel 1 exit /b 1
set "JANANI_LOG=%~dp0daily_log.txt"
echo Janani setup and sync: details are written to "%JANANI_LOG%".
>>"%JANANI_LOG%" echo.
>>"%JANANI_LOG%" echo [%DATE% %TIME%] Starting Janani daily sync
if not exist "janani-webhook.py" goto missing_files
if not exist "requirements.txt" goto missing_files
if not exist "scripts\bootstrap_windows.ps1" goto missing_files
powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "%~dp0scripts\bootstrap_windows.ps1" >>"%JANANI_LOG%" 2>&1
if errorlevel 1 goto setup_failed
set "JANANI_CHROME_BINARY=%~dp0.janani-runtime\current\browser\chrome-win32\chrome.exe"
set "JANANI_CHROMEDRIVER=%~dp0.janani-runtime\current\browser\chromedriver-win32\chromedriver.exe"
if not exist ".janani-runtime\current\browser\chrome-win64\chrome.exe" goto run_sync
set "JANANI_CHROME_BINARY=%~dp0.janani-runtime\current\browser\chrome-win64\chrome.exe"
set "JANANI_CHROMEDRIVER=%~dp0.janani-runtime\current\browser\chromedriver-win64\chromedriver.exe"
:run_sync
".janani-runtime\current\python\python.exe" -u "janani-webhook.py" --days 2 %* >>"%JANANI_LOG%" 2>&1
set "JANANI_EXIT=%errorlevel%"
goto finished
:missing_files
>>"%JANANI_LOG%" echo ERROR: Copy the complete project: Python script, requirements.txt and scripts\bootstrap_windows.ps1 are required.
set "JANANI_EXIT=2"
goto finished
:setup_failed
>>"%JANANI_LOG%" echo ERROR: Automatic runtime setup failed. Check SETUP ERROR above. No sync was started.
set "JANANI_EXIT=2"
:finished
>>"%JANANI_LOG%" echo [%DATE% %TIME%] Finished with exit code %JANANI_EXIT%
echo Janani finished with exit code %JANANI_EXIT%. See daily_log.txt for details.
popd
exit /b %JANANI_EXIT%
