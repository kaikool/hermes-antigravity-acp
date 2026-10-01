@echo off
setlocal
set "EXTRA="
if /I "%~1"=="--verbose" set "EXTRA=-VerboseInstall"
if /I "%~1"=="--no-launch" set "EXTRA=-NoLaunch"
if /I "%~1"=="--verbose-no-launch" set "EXTRA=-VerboseInstall -NoLaunch"

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %EXTRA%
set "EC=%ERRORLEVEL%"
if not "%EC%"=="0" (
  echo.
  echo Installation failed with exit code %EC%.
  pause
)
exit /b %EC%
