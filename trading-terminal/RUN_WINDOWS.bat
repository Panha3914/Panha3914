@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo ERROR: Environment not installed. Run INSTALL_WINDOWS.bat first.
  exit /b 1
)

if not exist ".env" (
  echo ERROR: .env was not found. Run INSTALL_WINDOWS.bat to create safe defaults.
  exit /b 1
)

".venv\Scripts\python.exe" -m trading_terminal.app
set EXIT_CODE=%ERRORLEVEL%
if not "%EXIT_CODE%"=="0" (
  echo.
  echo Terminal exited with code %EXIT_CODE%.
  pause
)
exit /b %EXIT_CODE%
