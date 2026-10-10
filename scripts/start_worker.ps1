[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
trap {
    Write-Host ''
    Write-Host "Worker startup failed: $($_.Exception.Message)" -ForegroundColor Red
    Read-Host 'Press Enter after reading this message' | Out-Null
    exit 1
}
Push-Location (Join-Path $root 'backend')
try {
    Write-Host 'Starting Worker. This window will keep showing runtime logs.' -ForegroundColor Cyan
    uv run python -m app.workers.runner
} finally {
    Pop-Location
}

