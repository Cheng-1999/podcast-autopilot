@echo off
setlocal

rem Double-click this file to set up and open the Podcast Autopilot dashboard.
rem Port 8766 avoids the agentboard dashboard's usual port (8765).
set "SCRIPT_DIR=%~dp0"

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%dashboard.ps1" -Port 8766
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
    echo.
    echo Dashboard stopped with exit code %EXIT_CODE%.
    pause
)

exit /b %EXIT_CODE%
