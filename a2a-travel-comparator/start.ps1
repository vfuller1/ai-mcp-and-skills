# start.ps1 — Launch all 3 A2A components in order.
# Weather Agent and Travel Agent start in background windows.
# Coordinator runs interactively in this terminal once both agents are ready.

$dir = Split-Path -Parent $MyInvocation.MyCommand.Path

function Kill-Port($port) {
    $pid_ = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue |
            Select-Object -ExpandProperty OwningProcess -First 1
    if ($pid_) {
        Stop-Process -Id $pid_ -Force -ErrorAction SilentlyContinue
        Write-Host "  Cleared port $port (PID $pid_)" -ForegroundColor Yellow
    }
}

function Wait-ForPort($port, $label, $timeoutSec = 40) {
    $elapsed = 0
    Write-Host -NoNewline "  Waiting for $label on port $port "
    while ($elapsed -lt $timeoutSec) {
        $listening = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
        if ($listening) {
            Write-Host "READY" -ForegroundColor Green
            return $true
        }
        Start-Sleep -Milliseconds 500
        $elapsed += 0.5
        Write-Host -NoNewline "."
    }
    Write-Host "TIMEOUT" -ForegroundColor Red
    return $false
}

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "   Travel Weather Comparator — Startup" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan

# --- Clean up any stale processes ---
Write-Host "`n[1/4] Cleaning up stale processes..." -ForegroundColor Yellow
Kill-Port 5001
Kill-Port 5003

# --- Start Weather Agent in a new window ---
Write-Host "`n[2/4] Starting Weather Agent (port 5001)..." -ForegroundColor Yellow
Start-Process pwsh -ArgumentList "-NoExit", "-NoLogo", "-Command",
    "Write-Host 'Weather Agent' -ForegroundColor Cyan; cd '$dir'; uv run python weather_agent.py"

if (-not (Wait-ForPort 5001 "Weather Agent")) {
    Write-Host "`nWeather Agent failed to start. Check the agent window for errors." -ForegroundColor Red
    exit 1
}

# --- Start Travel Agent in a new window ---
Write-Host "`n[3/4] Starting Travel Agent (port 5003)..." -ForegroundColor Yellow
Start-Process pwsh -ArgumentList "-NoExit", "-NoLogo", "-Command",
    "Write-Host 'Travel Agent' -ForegroundColor Cyan; cd '$dir'; uv run python travel_agent.py"

if (-not (Wait-ForPort 5003 "Travel Agent")) {
    Write-Host "`nTravel Agent failed to start. Check the agent window for errors." -ForegroundColor Red
    exit 1
}

# --- All agents up — launch coordinator here ---
Write-Host "`n[4/4] Both agents ready. Launching coordinator..." -ForegroundColor Green
Write-Host "============================================`n" -ForegroundColor Cyan

Set-Location $dir
uv run python travel_coordinator.py
