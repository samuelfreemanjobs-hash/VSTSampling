@echo off
REM One-time setup for VST Sampling Factory. Double-click this file.
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo.
    echo  Python was not found on this computer.
    echo.
    echo  1. Go to  https://www.python.org/downloads/
    echo  2. Download and run the installer
    echo  3. IMPORTANT: tick the box "Add Python to PATH" on the first screen
    echo  4. Then double-click this setup.bat again
    echo.
    pause
    exit /b 1
)

echo Creating private Python environment (one-time)...
python -m venv .venv
call .venv\Scripts\activate.bat

echo Installing libraries (this takes a few minutes)...
python -m pip install --upgrade pip
pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo  Something went wrong installing libraries. Scroll up for the red error
    echo  text and send it to Claude to get it fixed.
    echo.
    pause
    exit /b 1
)

echo.
echo  ============================================
echo   Setup complete!
echo   Double-click  run.bat  to start the app.
echo  ============================================
echo.
pause
