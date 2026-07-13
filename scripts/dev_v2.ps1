param(
    [int]$ApiPort = $(if ($env:FRONTIER_API_PORT) { [int]$env:FRONTIER_API_PORT } else { 8000 }),
    [int]$DashboardPort = $(if ($env:FRONTIER_DASHBOARD_PORT) { [int]$env:FRONTIER_DASHBOARD_PORT } else { 3000 })
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$Dashboard = Join-Path $Root "apps\dashboard"

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Python 3.12 environment missing. Create .venv and install -e '.[test,adapters]'."
}
if (-not (Test-Path -LiteralPath (Join-Path $Dashboard "node_modules"))) {
    throw "Dashboard dependencies missing. Run npm install in apps\dashboard."
}

$Version = & $Python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
if ($Version -ne "3.12") { throw "V2 requires Python 3.12; found $Version." }
if (-not (Get-Command node -ErrorAction SilentlyContinue)) { throw "Node.js is not installed." }

foreach ($Port in @($ApiPort, $DashboardPort)) {
    if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
        throw "Port $Port is already in use. Pass -ApiPort/-DashboardPort or set FRONTIER_API_PORT/FRONTIER_DASHBOARD_PORT."
    }
}

$env:FRONTIER_DASHBOARD_ORIGIN = "http://localhost:$DashboardPort"
$env:NEXT_PUBLIC_FRONTIER_API_URL = "http://localhost:$ApiPort"
$Api = $null
$Ui = $null
try {
    $Api = Start-Process -FilePath $Python -ArgumentList @("-m", "uvicorn", "evaluation_service.app:app", "--host", "127.0.0.1", "--port", $ApiPort) -WorkingDirectory $Root -WindowStyle Hidden -PassThru
    $Ui = Start-Process -FilePath "npm.cmd" -ArgumentList @("run", "dev", "--", "--hostname", "127.0.0.1", "--port", $DashboardPort) -WorkingDirectory $Dashboard -WindowStyle Hidden -PassThru
    Write-Host "Frontier V2 is starting."
    Write-Host "Dashboard: http://localhost:$DashboardPort"
    Write-Host "API:       http://localhost:$ApiPort"
    Write-Host "Press Ctrl+C to stop both processes."
    while (-not $Api.HasExited -and -not $Ui.HasExited) { Start-Sleep -Milliseconds 500 }
    if ($Api.HasExited) { throw "API process exited with code $($Api.ExitCode)." }
    if ($Ui.HasExited) { throw "Dashboard process exited with code $($Ui.ExitCode)." }
}
finally {
    foreach ($Process in @($Ui, $Api)) {
        if ($null -ne $Process -and -not $Process.HasExited) {
            Stop-Process -Id $Process.Id -ErrorAction SilentlyContinue
        }
    }
}
