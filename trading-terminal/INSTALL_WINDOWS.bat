@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo TUI Trading Terminal - Windows setup
echo ============================================================
py -3.12 --version >nul 2>&1
if errorlevel 1 (
  echo ERROR: Python 3.12 is required. Install Python 3.12 x64 and enable the Python launcher.
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  py -3.12 -m venv .venv
  if errorlevel 1 goto :failed
)

".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :failed

".venv\Scripts\python.exe" -m pip install -e ".[dev,mt5,telegram]"
if errorlevel 1 goto :failed

if not exist ".env" (
  copy ".env.example" ".env" >nul
  if errorlevel 1 goto :failed
  echo Created .env with safe defaults.
)

echo.
echo Setup complete.
echo Defaults: MT5 disabled, trading mode PAPER, kill switch ON, Telegram disabled.
echo This application does not send orders to MT5. Paper proposals are not fills.
echo Configure MT5_ENABLED=true only after the local MT5 terminal is installed and logged in.
echo Run RUN_WINDOWS.bat to start the dashboard.
exit /b 0

:failed
echo.
echo ERROR: Setup failed. Review the error above and check Python/network/package access.
exit /b 1
