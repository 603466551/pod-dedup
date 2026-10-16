[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot

function Assert-ApiPortAvailable {
    $processIds = @(Get-NetTCPConnection -State Listen -LocalPort 8000 -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique)
    if ($processIds.Count -eq 0) {
        return
    }
    $owners = @($processIds | ForEach-Object { Get-CimInstance Win32_Process -Filter "ProcessId = $_" })
    $details = $owners | ForEach-Object { "PID $($_.ProcessId) ($($_.Name)): $($_.CommandLine)" }
    throw "Port 8000 is already occupied. POD API was not started.`n$($details -join "`n")"
}

trap {
    Write-Host ''
    Write-Host "API startup failed: $($_.Exception.Message)" -ForegroundColor Red
    Read-Host 'Press Enter after reading this message' | Out-Null
    exit 1
}
Assert-ApiPortAvailable
Push-Location (Join-Path $root 'backend')
try {
    Write-Host 'Applying database migrations and starting API: http://127.0.0.1:8000' -ForegroundColor Cyan
    uv run alembic upgrade head
    uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
} finally {
    Pop-Location
}

