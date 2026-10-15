@echo off
rem Double-click launcher for Inspect-MaddenIso.ps1 (Madden NFL 06 PS2 research utility).
rem Runs the script with Windows PowerShell without changing the system execution policy.
rem Any arguments are passed through, e.g.:  Run-Inspector.cmd -Extract "UIS_*.DAT"
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Inspect-MaddenIso.ps1" %*
echo.
echo Press any key to close this window.
pause >nul
endlocal
