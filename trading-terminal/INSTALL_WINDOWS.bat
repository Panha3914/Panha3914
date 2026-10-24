@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title TUI Trading Terminal - Windows Setup

echo ============================================================
echo TUI Trading Terminal - Windows setup
echo ============================================================
echo.
echo Installer folder:
echo %CD%
echo.

REM Support tested runtimes 3.12/3.13. Prefer the py launcher, then PATH python.
REM Keep this console open on every success/failure path.
set "PYTHON_CMD="
py -3.13 --version >nul 2>&1
if not errorlevel 1 set "PYTHON_CMD=py -3.13"

if not defined PYTHON_CMD (
  py -3.12 --version >nul 2>&1
  if not errorlevel 1 set "PYTHON_CMD=py -3.12"
)

if not defined PYTHON_CMD (
  python -c "import sys; raise SystemExit(0 if (3, 12) <= sys.version_info[:2] < (3, 14) else 1)" >nul 2>&1
  if not errorlevel 1 set "PYTHON_CMD=python"
)

if not defined PYTHON_CMD goto :python_missing

echo Detected Python command:
%PYTHON_CMD% --version
if errorlevel 1 goto :python_missing

if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -c "import sys; raise SystemExit(0 if (3, 12) <= sys.version_info[:2] < (3, 14) else 1)" >nul 2>&1
  if errorlevel 1 goto :venv_incompatible
  echo.
  echo Existing compatible virtual environment found.
) else (
  echo.
  echo [1/3] Creating Python virtual environment...
  %PYTHON_CMD% -m venv .venv
  if errorlevel 1 goto :failed
)

echo.
echo [2/3] Updating pip...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :failed

echo.
echo [3/3] Installing Trading Terminal and optional integrations...
".venv\Scripts\python.exe" -m pip install -e ".[dev,mt5,telegram]"
if errorlevel 1 goto :failed

if not exist ".env" (
  echo.
  echo Creating local .env from .env.example...
  if not exist ".env.example" (
    echo ERROR: .env.example was not found in this folder.
    goto :failed
  )
  copy ".env.example" ".env"
  if errorlevel 1 goto :failed
)

echo.
echo ============================================================
echo SETUP SUCCESSFUL
echo ============================================================
echo Defaults: MT5 disabled, PAPER mode, kill switch ON, Telegram disabled.
echo No broker orders can be sent by this build.
echo.
echo Next step: double-click RUN_WINDOWS.bat to open the terminal.
echo.
pause
exit /b 0

:python_missing
echo.
echo ============================================================
echo ERROR: Python 3.12 or 3.13 could not be found.
echo ============================================================
echo.
echo This project installer supports Python 3.12 and 3.13.
echo Your "python" command may point to a different installation than "py".
echo Run these commands in CMD to inspect installed versions:
echo     python --version
echo     py -0p
echo.
echo Install Python 3.12/3.13 x64 or repair the launcher, then retry.
echo.
pause
exit /b 1

:venv_incompatible
echo.
echo ============================================================
echo ERROR: The existing .venv uses an unsupported Python version.
echo ============================================================
echo.
echo Close the terminal, delete only this project's .venv folder,
echo then run INSTALL_WINDOWS.bat again.
echo Your .env and SQLite paper history are separate and will not be deleted.
echo.
pause
exit /b 1

:failed
echo.
echo ============================================================
echo SETUP FAILED
echo ============================================================
echo The command above reported an error. Read that message before closing.
echo Common causes: network/package download failure, insufficient disk space,
echo or a damaged/incomplete extracted folder.
echo.
pause
exit /b 1
