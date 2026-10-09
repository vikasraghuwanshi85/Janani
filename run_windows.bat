@echo off
setlocal
cd /d "%~dp0"
if errorlevel 1 exit /b 1
if not exist ".venv\Scripts\python.exe" (
  echo Run setup_windows.bat first.
  exit /b 1
)
".venv\Scripts\python.exe" janani-webhook.py %*
exit /b %errorlevel%
