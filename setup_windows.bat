@echo off
setlocal
cd /d "%~dp0"
if errorlevel 1 exit /b 1
where py >nul 2>&1
if errorlevel 1 (set "JANANI_PYTHON=python") else (set "JANANI_PYTHON=py -3")
%JANANI_PYTHON% -c "import sys; sys.exit(0 if sys.version_info >= (3,8) else 1)"
if errorlevel 1 (
  echo Install Python 3.8 or later and enable the Python launcher or Add Python to PATH.
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
  %JANANI_PYTHON% -m venv .venv
  if errorlevel 1 exit /b 1
)
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" -m pip check
if errorlevel 1 exit /b 1
echo Setup complete. Install Chrome, then use run_windows.bat.
exit /b 0
