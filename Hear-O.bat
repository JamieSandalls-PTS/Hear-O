@echo off
REM ==== Hear-O launcher ====
REM Double-click this file to run the app. The first run creates a private
REM Python environment and installs everything it needs (this takes a few
REM minutes and only happens once). Later runs start immediately.

setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo.
    echo First-time setup - installing Hear-O. This can take a few minutes...
    echo.
    py -3 -m venv .venv 2>nul || python -m venv .venv
    if not exist ".venv\Scripts\python.exe" (
        echo.
        echo ERROR: Could not create the Python environment.
        echo Make sure Python 3.10+ is installed from https://www.python.org/downloads/
        echo and that "Add Python to PATH" was ticked during install.
        echo.
        pause
        exit /b 1
    )
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo.
        echo ERROR: Dependency install failed. See the messages above.
        echo.
        pause
        exit /b 1
    )
)

echo Starting Hear-O...
".venv\Scripts\python.exe" -m app.main
if errorlevel 1 (
    echo.
    echo Hear-O exited with an error. See the messages above.
    pause
)
endlocal
