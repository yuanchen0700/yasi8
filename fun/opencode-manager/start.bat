@echo off
setlocal
cd /d "%~dp0"

rem ============================================================
rem  opencode session manager launcher
rem  Double-click this file to start the local web UI.
rem  Requires Node.js 22+ available in PATH.
rem ============================================================

where node >nul 2>nul
if errorlevel 1 (
  echo [ERROR] node.js was not found in PATH.
  echo Please install Node.js (v22 or newer) or add it to PATH, then try again.
  pause
  exit /b 1
)

set "PORT=4123"

echo Starting opencode session manager at http://127.0.0.1:%PORT%
echo Close this window to stop the server.

start "opencode-manager" cmd /c "node server.js %PORT%"
timeout /t 2 /nobreak >nul
start "" "http://127.0.0.1:%PORT%"

pause
