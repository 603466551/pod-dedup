[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
trap {
    Write-Host ''
    Write-Host "API startup failed: $($_.Exception.Message)" -ForegroundColor Red
    Read-Host 'Press Enter after reading this message' | Out-Null
    exit 1
}
Push-Location (Join-Path $root 'backend')
try {
    Write-Host 'Applying database migrations and starting API: http://127.0.0.1:8000' -ForegroundColor Cyan
    uv run alembic upgrade head
    uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
} finally {
    Pop-Location
}

