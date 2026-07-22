@echo off
title VST Sampling Factory
cd /d "%~dp0"

set "EXE=%~dp0dist\VSTSamplingFactory\VSTSamplingFactory.exe"

if exist "%EXE%" (
    start "" "%EXE%"
    exit /b 0
)

echo App not built yet.
echo.
echo Double-click install.bat first, or run:
echo   powershell -ExecutionPolicy Bypass -File install.ps1
echo.
pause
