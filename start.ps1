<#
    NexaDesk AI - start both servers.

        .\start.ps1

    Opens two PowerShell windows: the FastAPI backend on port 8000 and the
    React frontend on port 5173, then opens your browser.

    Close those two windows to stop the servers.
#>

$ErrorActionPreference = "Stop"
$root     = $PSScriptRoot
$backend  = Join-Path $root "backend"
$frontend = Join-Path $root "frontend"
$venvPy   = Join-Path $backend ".venv\Scripts\python.exe"

Write-Host "NexaDesk AI" -ForegroundColor Cyan
Write-Host "-----------"

# --- checks, with a useful message rather than a stack trace -------------
if (-not (Test-Path $venvPy)) {
    Write-Host "No virtual environment at backend\.venv" -ForegroundColor Red
    Write-Host "Run .\setup.ps1 first."
    exit 1
}
if (-not (Test-Path (Join-Path $backend ".env"))) {
    Write-Host "No backend\.env file." -ForegroundColor Red
    Write-Host "Run .\setup.ps1 first."
    exit 1
}
if (-not (Test-Path (Join-Path $frontend "node_modules"))) {
    Write-Host "Frontend dependencies are not installed." -ForegroundColor Red
    Write-Host "Run .\setup.ps1 first."
    exit 1
}

# --- backend --------------------------------------------------------------
Write-Host "Starting backend on http://127.0.0.1:8000 ..."
Start-Process powershell -ArgumentList @(
    "-NoExit", "-Command",
    "Set-Location '$backend'; & '.\.venv\Scripts\Activate.ps1'; " +
    "Write-Host 'BACKEND - leave this window open' -ForegroundColor Cyan; " +
    "uvicorn app.main:app --reload"
)

Start-Sleep -Seconds 4

# --- frontend -------------------------------------------------------------
Write-Host "Starting frontend on http://localhost:5173 ..."
Start-Process powershell -ArgumentList @(
    "-NoExit", "-Command",
    "Set-Location '$frontend'; " +
    "Write-Host 'FRONTEND - leave this window open' -ForegroundColor Cyan; " +
    "npm run dev"
)

Start-Sleep -Seconds 6
Start-Process "http://localhost:5173"

Write-Host ""
Write-Host "Customer chat : http://localhost:5173"        -ForegroundColor Green
Write-Host "Staff console : http://localhost:5173/login"  -ForegroundColor Green
Write-Host "API docs      : http://127.0.0.1:8000/docs"   -ForegroundColor Green
Write-Host ""
Write-Host "Stop the servers by closing the two new windows."
