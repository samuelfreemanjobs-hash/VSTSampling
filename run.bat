@echo off
REM Starts VST Sampling Factory. Double-click this file.
cd /d "%~dp0"

if not exist .venv (
    echo Please double-click setup.bat first - it only needs to run once.
    pause
    exit /b 1
)

call .venv\Scripts\activate.bat
python app.py
if errorlevel 1 (
    echo.
    echo  The app hit an error. Scroll up, copy the red text, and send it to
    echo  Claude to get it fixed.
    echo.
    pause
)
