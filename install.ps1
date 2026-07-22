# VST Sampling Factory — one-click install + build
$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot

Write-Host ""
Write-Host "=== VST Sampling Factory — Install ===" -ForegroundColor Cyan
Write-Host ""

# Python
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host "Python not found. Install Python 3.11+ and check 'Add Python to PATH':" -ForegroundColor Red
    Write-Host "  https://www.python.org/downloads/" -ForegroundColor Yellow
    exit 1
}

Set-Location $Root

# Virtual environment
if (-not (Test-Path ".venv\Scripts\Activate.ps1")) {
    Write-Host "[1/4] Creating virtual environment..." -ForegroundColor Green
    python -m venv .venv
} else {
    Write-Host "[1/4] Virtual environment already exists." -ForegroundColor DarkGray
}

Write-Host "[2/4] Installing dependencies..." -ForegroundColor Green
& .\.venv\Scripts\python.exe -m pip install --upgrade pip -q
& .\.venv\Scripts\pip.exe install -r requirements.txt -q

Write-Host "[3/4] Building standalone app (first time may take a few minutes)..." -ForegroundColor Green
& .\.venv\Scripts\pyinstaller.exe app.spec --noconfirm

$Exe = Join-Path $Root "dist\VSTSamplingFactory\VSTSamplingFactory.exe"
if (-not (Test-Path $Exe)) {
    Write-Host "Build failed — exe not found." -ForegroundColor Red
    exit 1
}

Write-Host "[4/4] Done!" -ForegroundColor Green
Write-Host ""
Write-Host "App location:" -ForegroundColor Cyan
Write-Host "  $Exe" -ForegroundColor White
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "  1. Double-click 'Run VST Sampling Factory.bat' in this folder" -ForegroundColor White
Write-Host "  2. In the app: Settings -> set reaper_path to your reaper.exe" -ForegroundColor White
Write-Host "  3. Queue tab -> Add Job -> Start Queue" -ForegroundColor White
Write-Host ""

$launch = Read-Host "Launch the app now? (Y/n)"
if ($launch -eq "" -or $launch -match "^[Yy]") {
    Start-Process $Exe
}
