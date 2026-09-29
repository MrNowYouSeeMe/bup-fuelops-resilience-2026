#Requires -Version 5.1
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = "E:\bup-fuelops-resilience-2026"

function Wait-Http([string]$Url, [int]$Seconds = 30) {
    $Deadline = (Get-Date).AddSeconds($Seconds)
    do {
        try {
            $Response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 3
            if ($Response.StatusCode -ge 200 -and $Response.StatusCode -lt 500) {
                return $true
            }
        } catch {}
        Start-Sleep -Milliseconds 700
    } while ((Get-Date) -lt $Deadline)
    return $false
}

Set-Location $Root

Write-Host "[STEP] Starting official BUP simulator" -ForegroundColor Cyan
docker compose up -d simulator-api
if ($LASTEXITCODE -ne 0) { throw "Could not start simulator-api" }

if (-not (Wait-Http "http://127.0.0.1:8000/v1/health" 45)) {
    throw "Simulator did not become healthy on port 8000."
}
Write-Host "[PASS] Simulator healthy" -ForegroundColor Green

$BackendAlready = Wait-Http "http://127.0.0.1:8001/api/health" 2
if (-not $BackendAlready) {
    Write-Host "[STEP] Starting Phase 2 backend on http://127.0.0.1:8001" -ForegroundColor Cyan
    Start-Process powershell.exe -ArgumentList @(
        "-NoExit",
        "-NoProfile",
        "-Command",
        "Set-Location '$Root'; `$env:PYTHONPATH='$Root\backend'; & '$Root\.venv\Scripts\python.exe' -m uvicorn app.main:app --app-dir '$Root\backend' --host 127.0.0.1 --port 8001"
    )

    if (-not (Wait-Http "http://127.0.0.1:8001/api/health" 30)) {
        throw "Backend did not become healthy on port 8001."
    }
}
Write-Host "[PASS] Backend healthy" -ForegroundColor Green

$FrontendAlready = Wait-Http "http://127.0.0.1:5173" 2
if (-not $FrontendAlready) {
    Write-Host "[STEP] Starting frontend on http://127.0.0.1:5173" -ForegroundColor Cyan
    Start-Process powershell.exe -ArgumentList @(
        "-NoExit",
        "-NoProfile",
        "-Command",
        "Set-Location '$Root\frontend'; npm run dev -- --host 127.0.0.1"
    )

    if (-not (Wait-Http "http://127.0.0.1:5173" 30)) {
        throw "Frontend did not become available on port 5173."
    }
}
Write-Host "[PASS] Frontend available" -ForegroundColor Green

Write-Host ""
Write-Host "============================================================" -ForegroundColor DarkCyan
Write-Host " PHASE 2 JUDGE DEMO READY" -ForegroundColor White
Write-Host "============================================================" -ForegroundColor DarkCyan
Write-Host "Frontend         : http://127.0.0.1:5173"
Write-Host "Decision support : http://127.0.0.1:8001/api/decision-support"
Write-Host "API docs         : http://127.0.0.1:8001/docs"
Write-Host "Simulator admin  : http://127.0.0.1:8000/admin"
Write-Host "============================================================" -ForegroundColor DarkCyan

Start-Process "http://127.0.0.1:5173"
