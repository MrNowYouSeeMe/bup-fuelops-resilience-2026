#Requires -Version 5.1
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = "E:\bup-fuelops-resilience-2026"
Set-Location $Root

Write-Host "[STEP] Starting official BUP simulator" -ForegroundColor Cyan
docker compose up -d simulator-api
if ($LASTEXITCODE -ne 0) { throw "Could not start simulator-api" }

Write-Host "[STEP] Starting backend on http://127.0.0.1:8001" -ForegroundColor Cyan
Start-Process powershell.exe -ArgumentList @(
    "-NoExit",
    "-NoProfile",
    "-Command",
    "Set-Location '$Root'; `$env:PYTHONPATH='$Root\backend'; & '$Root\.venv\Scripts\python.exe' -m uvicorn app.main:app --app-dir '$Root\backend' --host 127.0.0.1 --port 8001"
)

Write-Host "[STEP] Starting frontend on http://127.0.0.1:5173" -ForegroundColor Cyan
Start-Process powershell.exe -ArgumentList @(
    "-NoExit",
    "-NoProfile",
    "-Command",
    "Set-Location '$Root\frontend'; npm run dev -- --host 127.0.0.1"
)

Write-Host ""
Write-Host "[PASS] Phase 1 services launched" -ForegroundColor Green
Write-Host "Simulator : http://127.0.0.1:8000"
Write-Host "Admin     : http://127.0.0.1:8000/admin"
Write-Host "Backend   : http://127.0.0.1:8001/api/health"
Write-Host "Frontend  : http://127.0.0.1:5173"
