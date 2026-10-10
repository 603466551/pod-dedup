[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path (Join-Path $root '.env'))) {
    throw 'Missing root .env. Copy .env.example and configure the local MySQL connection first.'
}
Push-Location (Join-Path $root 'backend')
try {
    uv sync --all-groups
    Write-Host 'Backend dependencies match uv.lock; .env found. Confirm MySQL 5.7.40 is running.'
} finally {
    Pop-Location
}
