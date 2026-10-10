[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
trap {
    Write-Host ''
    Write-Host "Frontend startup failed: $($_.Exception.Message)" -ForegroundColor Red
    Read-Host 'Press Enter after reading this message' | Out-Null
    exit 1
}
Push-Location (Join-Path $root 'frontend')
try {
    Write-Host 'Starting frontend development server. This window will keep showing logs.' -ForegroundColor Cyan
    npm run dev
} finally {
    Pop-Location
}

