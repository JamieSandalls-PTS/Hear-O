@echo off
REM ==== Build Hear-O into a standalone Windows app ====
REM Produces dist\Hear-O\Hear-O.exe (a self-contained folder you can zip and
REM share - the target PC does NOT need Python installed).
REM Run this after Hear-O.bat has created the .venv at least once.

setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Creating environment first...
    py -3 -m venv .venv || python -m venv .venv
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
)

".venv\Scripts\python.exe" -m pip install pyinstaller

".venv\Scripts\pyinstaller.exe" --noconfirm --clean --windowed ^
    --name Hear-O --icon icon.ico ^
    --add-data "app/models;app/models" ^
    --collect-all ai_edge_litert ^
    --collect-all ctranslate2 ^
    --collect-all faster_whisper ^
    --collect-all tokenizers ^
    --collect-all onnxruntime ^
    run_app.py

if errorlevel 1 (
    echo BUILD FAILED - see messages above.
    pause
    exit /b 1
)

REM Remove PyInstaller's scratch folder. It contains a NON-WORKING copy of
REM Hear-O.exe that fails with "python313.dll not found" if run by mistake -
REM deleting it leaves only the real app in dist\.
if exist "build" rmdir /s /q "build"

echo.
echo ============================================================
echo  DONE.  Run the app here:
echo     dist\Hear-O\Hear-O.exe
echo  (Zip the whole dist\Hear-O folder to share it.)
echo ============================================================
start "" explorer "dist\Hear-O"
pause
endlocal
