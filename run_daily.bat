@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul
pushd "%~dp0"
if errorlevel 1 exit /b 1
set "PYTHONIOENCODING=utf-8"
set "JANANI_EXIT=2"
set "JANANI_PYTHON="
type nul >>"daily_log.txt" 2>nul
if errorlevel 1 (
  echo ERROR: Cannot write daily_log.txt. Use a writable project folder. 1>&2
  popd
  exit /b 2
)
>>"daily_log.txt" echo.
>>"daily_log.txt" echo [%DATE% %TIME%] Starting Janani daily sync
if not exist "janani-webhook.py" goto missing_script
if exist ".venv\Scripts\python.exe" set "JANANI_PYTHON=%~dp0.venv\Scripts\python.exe"
if defined JANANI_PYTHON goto run_python
for /f "delims=" %%P in ('py -3 -c "import sys; print(sys.executable)" 2^>nul') do if exist "%%P" set "JANANI_PYTHON=%%P"
if defined JANANI_PYTHON goto run_python
for /f "delims=" %%P in ('python -c "import sys; print(sys.executable)" 2^>nul') do if exist "%%P" set "JANANI_PYTHON=%%P"
if defined JANANI_PYTHON goto run_python
>>"daily_log.txt" echo ERROR: Python 3 was not found. Install Python with the launcher, or add it to PATH.
goto finished
:run_python
>>"daily_log.txt" echo Using Python: "%JANANI_PYTHON%"
"%JANANI_PYTHON%" -c "import sys, requests, selenium; sys.exit(0 if sys.version_info >= (3,8) else 1)" >>"daily_log.txt" 2>&1
if errorlevel 1 goto missing_packages
"%JANANI_PYTHON%" -u "janani-webhook.py" --debug --debug-fuel %* >>"daily_log.txt" 2>&1
set "JANANI_EXIT=%errorlevel%"
goto finished
:missing_packages
>>"daily_log.txt" echo ERROR: Python 3.8+ and requests/Selenium are required. Install requirements.txt with the Python shown above.
goto finished
:missing_script
>>"daily_log.txt" echo ERROR: Keep run_daily.bat beside janani-webhook.py.
:finished
>>"daily_log.txt" echo [%DATE% %TIME%] Finished with exit code %JANANI_EXIT%
popd
exit /b %JANANI_EXIT%
