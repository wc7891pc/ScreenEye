@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
echo Starting ScreenEye in debug mode (console will show errors)...
"runtime\python\python.exe" "app\main.py"
if errorlevel 1 pause
endlocal
