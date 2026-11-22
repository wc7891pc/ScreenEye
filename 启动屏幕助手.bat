@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
if not exist "runtime\python\pythonw.exe" (
    echo [ERROR] Portable runtime not found. Please use the EXE build instead.
    pause
    exit /b 1
)
start "" "runtime\python\pythonw.exe" "app\main.py"
endlocal
