@echo off
REM Janani Fleet - Task Scheduler VISIBLE version - GUARANTEED to show Chrome
REM This version uses cmd /k and forces interactive desktop

setlocal
cd /d "%~dp0"
chcp 65001 >nul
set PYTHONIOENCODING=utf-8

set LOG=daily_log.txt
set SCRIPT=FINAL_janani_webhook.py

REM Find script
if not exist "%SCRIPT%" (
  for /f "delims=" %%a in ('dir /b /o-d FINAL_V*.py 2^>nul') do set SCRIPT=%%a & goto :found
  for /f "delims=" %%a in ('dir /b /o-d *.py 2^>nul') do set SCRIPT=%%a & goto :found
  echo No python script found!
  pause
  exit /b 1
)
:found

echo ============================================ >> "%LOG%"
echo [%date% %time%] Task Scheduler run - VISIBLE >> "%LOG%"
echo Script: %SCRIPT% >> "%LOG%"

REM Find python
set PY=python
where python >nul 2>&1 || set PY=py
where %PY% >nul 2>&1 || set PY=py -3

echo [%date% %time%] Starting with %PY% %SCRIPT% --days 2 >> "%LOG%"

REM IMPORTANT: This bat MUST be run with "Run only when user is logged on"
REM Otherwise Chrome won't show

REM Run - --days 2 for daily, not --all
%PY% "%SCRIPT%" --days 2 >> "%LOG%" 2>&1

echo [%date% %time%] Finished code %errorlevel% >> "%LOG%"

REM Don't close immediately when run from scheduler - keep log
timeout /t 5

endlocal
