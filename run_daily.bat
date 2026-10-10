@echo off
setlocal
cd /d "%~dp0"
if errorlevel 1 exit /b 1

set "PYTHONIOENCODING=utf-8"

>>"daily_log.txt" echo.
>>"daily_log.txt" echo [%DATE% %TIME%] Starting Janani

python -u "janani_webhook.py" --debug --debug-fuel >>"daily_log.txt" 2>&1
set "JANANI_EXIT=%errorlevel%"

>>"daily_log.txt" echo [%DATE% %TIME%] Finished with exit code %JANANI_EXIT%
exit /b %JANANI_EXIT%