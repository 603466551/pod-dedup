[CmdletBinding()]
param(
    [switch]$SyncDependencies,
    [switch]$Restart,
    [switch]$NoPause
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root 'backend'
$frontend = Join-Path $root 'frontend'

function Wait-ForUser([string]$Prompt = 'Press Enter to close this startup status window') {
    if (-not $NoPause) {
        Read-Host $Prompt | Out-Null
    }
}

trap {
    Write-Host ''
    Write-Host "Startup failed: $($_.Exception.Message)" -ForegroundColor Red
    Wait-ForUser
    exit 1
}

if (-not (Test-Path (Join-Path $root '.env'))) {
    throw 'Missing root .env. Copy .env.example and configure the local MySQL connection first.'
}

function Test-ListeningPort([int]$Port) {
    return @(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue).Count -gt 0
}

function Test-WorkerRunning {
    return (Get-ProjectWorkerRoots).Count -gt 0
}

function Get-ProjectWorkerRoots {
    # `uv run python -m ...` has a short wrapper process plus the actual
    # Python child.  Treat that parent/child pair as one Worker instance.
    $allWorkers = @(
        Get-CimInstance Win32_Process |
        Where-Object { $_.Name -eq 'python.exe' -and $_.CommandLine -like '*app.workers.runner*' }
    )
    $workerIds = @($allWorkers | Select-Object -ExpandProperty ProcessId)
    return @($allWorkers | Where-Object { $_.ParentProcessId -notin $workerIds })
}

function Stop-ProjectWorkerTree([int]$ProcessId) {
    $children = @(Get-CimInstance Win32_Process -Filter "ParentProcessId = $ProcessId")
    foreach ($child in $children) {
        Stop-ProjectWorkerTree -ProcessId $child.ProcessId
    }
    Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
}

function Stop-ListeningPort([int]$Port, [string]$Name, [string]$CommandSignature) {
    $processIds = @(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique)
    if ($processIds.Count -gt 1) {
        throw "Expected at most one $Name listener on port $Port, found $($processIds.Count)."
    }
    if ($processIds.Count -eq 1) {
        $process = Get-CimInstance Win32_Process -Filter "ProcessId = $($processIds[0])"
        if (-not $process -or $process.CommandLine -notlike $CommandSignature) {
            throw "Port $Port is not owned by the expected POD $Name process; refusing to stop it."
        }
        Stop-Process -Id $processIds[0] -Force
        Write-Host "$Name stopped for restart."
    }
}

function Stop-ProjectWorker {
    $workers = @(Get-ProjectWorkerRoots)
    if ($workers.Count -gt 1) {
        throw "Expected at most one project Worker process, found $($workers.Count)."
    }
    if ($workers.Count -eq 1) {
        Stop-ProjectWorkerTree -ProcessId $workers[0].ProcessId
        Write-Host 'Worker stopped for restart.'
    }
}

function Start-ProjectProcess([string]$Name, [string]$ScriptName) {
    $scriptPath = Join-Path $root "scripts\$ScriptName"
    $process = Start-Process -FilePath 'powershell.exe' -ArgumentList @(
        '-NoExit', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $scriptPath
    ) -WindowStyle Normal -PassThru
    Write-Host "$Name is starting (log window PID: $($process.Id))."
}

function Wait-ForStartup([string]$Name, [scriptblock]$Ready) {
    $deadline = (Get-Date).AddSeconds(20)
    while ((Get-Date) -lt $deadline) {
        if (& $Ready) {
            Write-Host "$Name is ready." -ForegroundColor Green
            return $true
        }
        Start-Sleep -Milliseconds 500
    }
    Write-Host "$Name was not confirmed ready within 20 seconds. Check its log window." -ForegroundColor Yellow
    return $false
}

$mysql = Get-Service -Name 'MySQL57' -ErrorAction SilentlyContinue
if (-not $mysql) {
    throw 'MySQL57 Windows service was not found. Install/configure MySQL 5.7.40 or update the script with the actual service name.'
}
if ($mysql.Status -ne 'Running') {
    try {
        Start-Service -Name 'MySQL57' -ErrorAction Stop
    } catch {
        throw 'MySQL57 could not be started automatically. Open an administrator PowerShell window, run Start-Service MySQL57, then run this script again.'
    }
    $mysql = Get-Service -Name 'MySQL57'
}
if ($mysql.Status -ne 'Running') {
    throw 'MySQL57 is not running. Refusing to start the API, Worker, and frontend without a database.'
}
Write-Host 'MySQL57 is running.'

if ($SyncDependencies -or -not (Test-Path (Join-Path $backend '.venv'))) {
    & (Join-Path $root 'scripts\bootstrap.ps1')
}
if (-not (Test-Path (Join-Path $frontend 'node_modules'))) {
    Push-Location $frontend
    try {
        npm install
    } finally {
        Pop-Location
    }
}

if ($Restart) {
    Stop-ListeningPort 8000 'API' '*uvicorn*app.main:app*'
    Stop-ProjectWorker
    Stop-ListeningPort 5173 'Frontend' '*vite*--host*127.0.0.1*'
    Start-Sleep -Milliseconds 500
}

if (Test-ListeningPort 8000) {
    Write-Host 'API is already listening on http://127.0.0.1:8000.' -ForegroundColor Green
} else {
    Start-ProjectProcess 'API' 'start_api.ps1'
}
if (Test-WorkerRunning) {
    Write-Host 'Worker is already running.' -ForegroundColor Green
} else {
    Start-ProjectProcess 'Worker' 'start_worker.ps1'
}
if (Test-ListeningPort 5173) {
    Write-Host 'Frontend is already listening on http://127.0.0.1:5173.' -ForegroundColor Green
} else {
    Start-ProjectProcess 'Frontend' 'start_frontend.ps1'
}

$apiReady = Wait-ForStartup 'API' { Test-ListeningPort 8000 }
$workerReady = Wait-ForStartup 'Worker' { Test-WorkerRunning }
$frontendReady = Wait-ForStartup 'Frontend' { Test-ListeningPort 5173 }

Write-Host ''
if ($apiReady -and $workerReady -and $frontendReady) {
    Write-Host 'All services are ready. Open: http://127.0.0.1:5173' -ForegroundColor Green
} else {
    Write-Host 'Some services were not confirmed ready. Check the log windows that remain open.' -ForegroundColor Yellow
}
Wait-ForUser
