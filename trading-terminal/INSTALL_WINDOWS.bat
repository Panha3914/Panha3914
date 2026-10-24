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

REM Keep this console open on every success/failure path so errors remain visible.
py -3.12 --version
if errorlevel 1 goto :python_missing

if not exist ".venv\Scripts\python.exe" (
  echo.
  echo [1/3] Creating Python virtual environment...
  py -3.12 -m venv .venv
  if errorlevel 1 goto :failed
) else (
  echo.
  echo [1/3] Existing virtual environment found.
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
echo ERROR: Python 3.12 was not found by the Windows Python launcher.
echo ============================================================
echo.
echo Install Python 3.12 (64-bit), enable the Python launcher, and then
echo close this window and run INSTALL_WINDOWS.bat again.
echo.
echo You can check the installation by running this command in CMD:
echo     py -0p
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
