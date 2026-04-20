@echo off
rem =============================================================
rem  Commodity Sentiment Monitor - one-click launcher (Windows)
rem
rem  Double-click this file to:
rem    1. Create a .venv the first time (Python 3.11+ required on PATH)
rem    2. Install dependencies from pyproject.toml
rem    3. Start the dashboard and open your browser
rem
rem  For the cross-platform equivalent, see run.sh.
rem  Docker users can instead run: docker compose up --build
rem =============================================================
setlocal EnableDelayedExpansion

rem Work from the directory this script lives in, even if invoked from
rem elsewhere (double-click passes the Desktop or Explorer CWD otherwise).
cd /d "%~dp0"

rem --- Locate a Python interpreter ---------------------------------
rem  Prefer the `py` launcher (ships with Python.org installers on Win)
rem  because it resolves version constraints (py -3.11) reliably. Fall
rem  back to `python` on PATH for environments that only have that.
set "PY_CMD="
where py >nul 2>&1 && set "PY_CMD=py -3"
if "%PY_CMD%"=="" (
  where python >nul 2>&1 && set "PY_CMD=python"
)
if "%PY_CMD%"=="" (
  echo.
  echo   [ERROR] Python 3.11+ not found on PATH.
  echo   Install from https://www.python.org/downloads/ and retry.
  echo.
  pause
  exit /b 1
)

rem --- First-run setup: create venv + install deps ----------------
if not exist ".venv\Scripts\python.exe" (
  echo.
  echo   [setup] Creating virtual environment in .venv ...
  %PY_CMD% -m venv .venv
  if errorlevel 1 goto :setup_failed

  echo   [setup] Upgrading pip ...
  ".venv\Scripts\python.exe" -m pip install --upgrade pip >nul

  echo   [setup] Installing project dependencies ^(this takes a few minutes the first time^) ...
  ".venv\Scripts\python.exe" -m pip install -e ".[dev]"
  if errorlevel 1 goto :setup_failed
  echo   [setup] Done.
  echo.
)

rem --- Launch the app ---------------------------------------------
rem  src.main auto-opens the dashboard in your default browser
rem  (commit b07864c); --no-browser would disable that if needed.
echo   Starting Commodity Sentiment Monitor on http://localhost:8000
echo   (Ctrl+C to stop)
echo.
".venv\Scripts\python.exe" -m src.main %*
exit /b %errorlevel%

:setup_failed
echo.
echo   [ERROR] Setup failed. Scroll up for details.
echo   Tip: make sure you have internet access and a recent Python 3.11+.
echo.
pause
exit /b 1
