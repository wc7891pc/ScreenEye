@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
echo Installing PyInstaller (first run only)...
runtime\python\python.exe -m pip install --disable-pip-version-check --no-warn-script-location pyinstaller
echo Building EXE, this takes a few minutes...
runtime\python\python.exe -m PyInstaller --noconfirm --clean --windowed --name ScreenEye ^
  --icon "assets\icon.ico" ^
  --add-data "assets;assets" ^
  --collect-all rapidocr_onnxruntime ^
  --hidden-import mss.windows ^
  --exclude-module tkinter ^
  --exclude-module PySide6.QtWebEngineCore ^
  --exclude-module PySide6.QtQuick ^
  --workpath "build\pyi" --specpath "build" --distpath "dist" ^
  "app\main.py"
if errorlevel 1 (
    echo Build failed.
    pause
    exit /b 1
)
echo Done: dist\ScreenEye\ScreenEye.exe
pause
endlocal
