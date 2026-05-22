# test_mcp.ps1 — Run MCP demo integration tests from the terminal
# Usage: .\test_mcp.ps1

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

function Write-Header($text) {
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host "  $text" -ForegroundColor Cyan
    Write-Host "========================================" -ForegroundColor Cyan
}

function Run-Test($label, $dir, $script) {
    Write-Header $label
    Push-Location "$root\$dir"
    try {
        uv run python $script
        if ($LASTEXITCODE -ne 0) {
            Write-Host "[FAILED] $label exited with code $LASTEXITCODE" -ForegroundColor Red
        }
    } catch {
        Write-Host "[ERROR] $_" -ForegroundColor Red
    } finally {
        Pop-Location
    }
}

# --- Sync dependencies ---
Write-Header "Installing dependencies"

foreach ($dir in @("weather", "weather-skills", "mcp-client", "skills-client")) {
    Write-Host "  uv sync: $dir" -ForegroundColor Yellow
    Push-Location "$root\$dir"
    uv sync --quiet
    Pop-Location
}

# --- Run tests ---
Run-Test "Basic Weather Server (tools only)" "weather" "test_server.py"
Run-Test "Advanced Weather Server (tools + resources + skills)" "weather-skills" "test_server.py"

# --- OpenAI smoke test (optional, needs OPENAI_API_KEY) ---
Write-Header "OpenAI connectivity (optional)"
if (Test-Path "$root\.env") {
    Push-Location $root
    uv run python test_openai.py
    Pop-Location
} else {
    Write-Host "  Skipped — no .env file found at repo root" -ForegroundColor Yellow
    Write-Host "  Create .env with OPENAI_API_KEY=sk-... to enable this test"
}

Write-Host ""
Write-Host "Done." -ForegroundColor Green
