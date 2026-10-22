@echo off
echo Installing Xiaomian pet autostart and starting the watchdog...
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\install_autostart.ps1"
echo.
pause
