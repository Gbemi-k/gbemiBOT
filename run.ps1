# Smart Queue Bot — one-command launcher (Windows / PowerShell)
# Creates a virtual environment, installs dependencies, and starts the server.

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$venv = Join-Path $root ".venv"

if (-not (Test-Path $venv)) {
    Write-Host "Creating virtual environment..." -ForegroundColor Cyan
    python -m venv $venv
}

$py = Join-Path $venv "Scripts\python.exe"

Write-Host "Installing dependencies..." -ForegroundColor Cyan
& $py -m pip install --upgrade pip --quiet
& $py -m pip install -r (Join-Path $root "backend\requirements.txt") --quiet

Write-Host ""
Write-Host "Smart Queue Bot is starting at http://127.0.0.1:8000" -ForegroundColor Green
Write-Host "  Home / sign up :  http://127.0.0.1:8000/" -ForegroundColor Green
Write-Host "  Dashboard      :  http://127.0.0.1:8000/dashboard.html (after login)" -ForegroundColor Green
Write-Host "  Customer link  :  http://127.0.0.1:8000/q/<your-slug> (shown on your dashboard)" -ForegroundColor Green
Write-Host "  API docs       :  http://127.0.0.1:8000/docs" -ForegroundColor Green
Write-Host "Press Ctrl+C to stop." -ForegroundColor DarkGray
Write-Host ""

Set-Location (Join-Path $root "backend")
& $py -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
