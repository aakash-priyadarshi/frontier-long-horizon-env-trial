param(
    [int]$ApiPort = $(if ($env:FRONTIER_API_PORT) { [int]$env:FRONTIER_API_PORT } else { 8000 }),
    [int]$DashboardPort = $(if ($env:FRONTIER_DASHBOARD_PORT) { [int]$env:FRONTIER_DASHBOARD_PORT } else { 3000 }),
    [switch]$NoBrowser
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$Root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$Dashboard = Join-Path $Root "apps\dashboard"
$Runtime = Join-Path $Root ".frontier\launcher"
$Logs = Join-Path $Root ".frontier\logs"
$Venv = Join-Path $Root ".venv"
$VenvPython = Join-Path $Venv "Scripts\python.exe"
$ApiUrl = "http://localhost:$ApiPort"
$DashboardUrl = "http://localhost:$DashboardPort"
$OllamaUrl = "http://127.0.0.1:11434"

New-Item -ItemType Directory -Force -Path $Runtime, $Logs | Out-Null

function Write-Status {
    param(
        [ValidateSet("info", "ok", "warn", "error")][string]$Kind,
        [string]$Message
    )
    $settings = switch ($Kind) {
        "ok"    { @{ Prefix = "[OK]"; Color = "Green" } }
        "warn"  { @{ Prefix = "[WARNING]"; Color = "Yellow" } }
        "error" { @{ Prefix = "[ERROR]"; Color = "Red" } }
        default { @{ Prefix = "[INFO]"; Color = "Cyan" } }
    }
    Write-Host "$($settings.Prefix) $Message" -ForegroundColor $settings.Color
}

function Refresh-ProcessPath {
    $machine = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $user = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machine;$user"
}

function Install-WingetPackage {
    param([string]$Id, [string]$Label)
    Write-Status info "$Label is missing or unsupported. Installing it with Winget (Windows may request approval)."
    & winget.exe install --id $Id --exact --source winget --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) {
        Write-Status warn "Winget returned exit code $LASTEXITCODE while installing $Label; the dependency will be checked again."
    }
    Refresh-ProcessPath
}

function Test-Python312 {
    param([string]$Path, [string[]]$Prefix = @())
    try {
        $version = & $Path @Prefix -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
        return ($LASTEXITCODE -eq 0 -and $version.Trim() -eq "3.12")
    }
    catch { return $false }
}

function Find-Python312 {
    $candidates = @()
    if (Test-Path -LiteralPath $VenvPython) {
        $candidates += [pscustomobject]@{ Path = $VenvPython; Prefix = @() }
    }
    foreach ($name in @("python3.12.exe", "python.exe")) {
        $command = Get-Command $name -ErrorAction SilentlyContinue
        if ($null -ne $command) {
            $candidates += [pscustomobject]@{ Path = $command.Source; Prefix = @() }
        }
    }
    $localPython = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"
    if (Test-Path -LiteralPath $localPython) {
        $candidates += [pscustomobject]@{ Path = $localPython; Prefix = @() }
    }
    $launcher = Get-Command "py.exe" -ErrorAction SilentlyContinue
    if ($null -ne $launcher) {
        $candidates += [pscustomobject]@{ Path = $launcher.Source; Prefix = @("-3.12") }
    }
    foreach ($candidate in $candidates) {
        if (Test-Python312 -Path $candidate.Path -Prefix $candidate.Prefix) {
            return $candidate
        }
    }
    return $null
}

function Test-NodeVersion {
    try {
        $command = Get-Command "node.exe" -ErrorAction SilentlyContinue
        if ($null -eq $command) { return $false }
        $raw = (& $command.Source --version).Trim().TrimStart("v")
        return ([version]$raw -ge [version]"20.9.0")
    }
    catch { return $false }
}

function Assert-SystemDependencies {
    $needsGit = $null -eq (Get-Command "git.exe" -ErrorAction SilentlyContinue)
    $python = Find-Python312
    $needsPython = $null -eq $python
    $needsNode = -not (Test-NodeVersion)

    if ($needsGit -or $needsPython -or $needsNode) {
        if ($null -eq (Get-Command "winget.exe" -ErrorAction SilentlyContinue)) {
            throw "A required dependency is missing, and Winget is unavailable. Install App Installer from Microsoft, then run start-frontier.cmd again."
        }
        if ($needsGit) { Install-WingetPackage -Id "Git.Git" -Label "Git" }
        if ($needsPython) { Install-WingetPackage -Id "Python.Python.3.12" -Label "Python 3.12" }
        if ($needsNode) { Install-WingetPackage -Id "OpenJS.NodeJS.LTS" -Label "Node.js 20.9 or newer" }
    }

    $python = Find-Python312
    if ($null -eq $python) { throw "Python 3.12 is still unavailable after dependency setup." }
    if ($null -eq (Get-Command "git.exe" -ErrorAction SilentlyContinue)) { throw "Git is still unavailable after dependency setup." }
    if (-not (Test-NodeVersion)) { throw "Node.js 20.9 or newer is still unavailable after dependency setup." }
    if ($null -eq (Get-Command "npm.cmd" -ErrorAction SilentlyContinue)) { throw "npm is unavailable after Node.js setup." }
    return $python
}

function Get-FileDigest {
    param([string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Write-Stamp {
    param([string]$Path, [string]$Value)
    [IO.File]::WriteAllText($Path, "$Value`n", [Text.UTF8Encoding]::new($false))
}

function Install-ProjectDependencies {
    param($BootstrapPython)

    if (-not (Test-Path -LiteralPath $VenvPython) -or -not (Test-Python312 -Path $VenvPython)) {
        Write-Status info "Creating the repository Python 3.12 environment."
        $arguments = @($BootstrapPython.Prefix) + @("-m", "venv", $Venv)
        & $BootstrapPython.Path @arguments
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $VenvPython)) {
            throw "Python could not create $Venv."
        }
    }

    $pythonDigest = Get-FileDigest (Join-Path $Root "pyproject.toml")
    $pythonStamp = Join-Path $Runtime "python-dependencies.sha256"
    $importsReady = $false
    try {
        & $VenvPython -c "import fastapi, gymnasium, httpx, pytest, uvicorn, yaml" 2>$null
        $importsReady = $LASTEXITCODE -eq 0
    }
    catch { $importsReady = $false }
    $stampMatches = (Test-Path -LiteralPath $pythonStamp) -and ((Get-Content -Raw -LiteralPath $pythonStamp).Trim() -eq $pythonDigest)
    if (-not $importsReady -or -not $stampMatches) {
        Write-Status info "Installing Frontier Python dependencies into .venv."
        & $VenvPython -m pip install -e ".[test,adapters]"
        if ($LASTEXITCODE -ne 0) { throw "Python dependency installation failed." }
        Write-Stamp -Path $pythonStamp -Value $pythonDigest
    }
    & $VenvPython -m pip check
    if ($LASTEXITCODE -ne 0) { throw "The Python environment contains incompatible dependencies." }
    Write-Status ok "Python 3.12 and project dependencies are ready."

    $lockFile = Join-Path $Dashboard "package-lock.json"
    if (-not (Test-Path -LiteralPath $lockFile)) { throw "Dashboard package-lock.json is missing." }
    $nodeDigest = Get-FileDigest $lockFile
    $nodeStamp = Join-Path $Runtime "dashboard-dependencies.sha256"
    $modules = Join-Path $Dashboard "node_modules"
    $nodeStampMatches = (Test-Path -LiteralPath $nodeStamp) -and ((Get-Content -Raw -LiteralPath $nodeStamp).Trim() -eq $nodeDigest)
    if (-not (Test-Path -LiteralPath $modules) -or -not $nodeStampMatches) {
        Write-Status info "Installing deterministic dashboard dependencies with npm ci."
        & npm.cmd ci --prefix $Dashboard
        if ($LASTEXITCODE -ne 0) { throw "Dashboard dependency installation failed." }
        Write-Stamp -Path $nodeStamp -Value $nodeDigest
    }
    Write-Status ok "Node.js, npm, and dashboard dependencies are ready."
}

function Test-WebEndpoint {
    param([string]$Uri)
    try {
        $response = Invoke-WebRequest -Uri $Uri -Method Get -TimeoutSec 5 -UseBasicParsing
        return $response.StatusCode -ge 200 -and $response.StatusCode -lt 400
    }
    catch { return $false }
}

function Test-Api {
    try {
        $response = Invoke-RestMethod -Uri "http://127.0.0.1:$ApiPort/api/health" -Method Get -TimeoutSec 5
        return $response.status -eq "ok"
    }
    catch { return $false }
}

function Test-Ollama {
    return Test-WebEndpoint -Uri "$OllamaUrl/api/tags"
}

function Wait-ForEndpoint {
    param([scriptblock]$Probe, [int]$TimeoutSeconds = 60)
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    while ([DateTime]::UtcNow -lt $deadline) {
        if (& $Probe) { return $true }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

function Assert-PortAvailable {
    param([int]$Port, [string]$Service)
    if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
        throw "Port $Port is occupied by something other than the expected $Service. Stop that process or set FRONTIER_API_PORT / FRONTIER_DASHBOARD_PORT."
    }
}

function Start-FrontierServices {
    $env:FRONTIER_DASHBOARD_ORIGIN = $DashboardUrl
    $env:NEXT_PUBLIC_FRONTIER_API_URL = $ApiUrl

    if (Test-Api) {
        Write-Status ok "Frontier API is already healthy at $ApiUrl."
    }
    else {
        Assert-PortAvailable -Port $ApiPort -Service "Frontier API"
        Write-Status info "Starting the Frontier API."
        $process = Start-Process -FilePath $VenvPython `
            -ArgumentList @("-m", "uvicorn", "evaluation_service.app:app", "--host", "127.0.0.1", "--port", $ApiPort) `
            -WorkingDirectory $Root -WindowStyle Hidden -PassThru `
            -RedirectStandardOutput (Join-Path $Logs "api.out.log") `
            -RedirectStandardError (Join-Path $Logs "api.err.log")
        Write-Stamp -Path (Join-Path $Runtime "api.pid") -Value ([string]$process.Id)
        if (-not (Wait-ForEndpoint -Probe { Test-Api })) {
            throw "Frontier API did not become healthy. Review .frontier\logs\api.err.log."
        }
        Write-Status ok "Frontier API is healthy at $ApiUrl."
    }

    if (Test-WebEndpoint -Uri "http://127.0.0.1:$DashboardPort") {
        Write-Status ok "Dashboard is already available at $DashboardUrl."
    }
    else {
        Assert-PortAvailable -Port $DashboardPort -Service "Frontier dashboard"
        Write-Status info "Starting the Frontier dashboard."
        $process = Start-Process -FilePath "npm.cmd" `
            -ArgumentList @("run", "dev", "--", "--hostname", "127.0.0.1", "--port", $DashboardPort) `
            -WorkingDirectory $Dashboard -WindowStyle Hidden -PassThru `
            -RedirectStandardOutput (Join-Path $Logs "dashboard.out.log") `
            -RedirectStandardError (Join-Path $Logs "dashboard.err.log")
        Write-Stamp -Path (Join-Path $Runtime "dashboard.pid") -Value ([string]$process.Id)
        if (-not (Wait-ForEndpoint -Probe { Test-WebEndpoint -Uri "http://127.0.0.1:$DashboardPort" })) {
            throw "Frontier dashboard did not become ready. Review .frontier\logs\dashboard.err.log."
        }
        Write-Status ok "Dashboard is ready at $DashboardUrl."
    }
}

function Find-Ollama {
    $command = Get-Command "ollama.exe" -ErrorAction SilentlyContinue
    if ($null -ne $command) { return $command.Source }
    $candidate = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"
    if (Test-Path -LiteralPath $candidate) { return $candidate }
    return $null
}

function Start-OllamaIfAvailable {
    $ollama = Find-Ollama
    if ($null -eq $ollama) {
        Write-Status warn "Ollama is not installed. Hosted providers and scripted evaluations work, but local-model features will not. See Settings -> Tool compatibility for supported models and setup guidance."
        return
    }

    if (-not (Test-Ollama)) {
        Write-Status info "Ollama is installed; starting its local service."
        try {
            $process = Start-Process -FilePath $ollama -ArgumentList @("serve") -WorkingDirectory $Root `
                -WindowStyle Hidden -PassThru `
                -RedirectStandardOutput (Join-Path $Logs "ollama.out.log") `
                -RedirectStandardError (Join-Path $Logs "ollama.err.log")
            Write-Stamp -Path (Join-Path $Runtime "ollama.pid") -Value ([string]$process.Id)
            $null = Wait-ForEndpoint -Probe { Test-Ollama } -TimeoutSeconds 20
        }
        catch {
            Write-Status warn "Ollama was detected but its local service could not be started automatically. Open the Ollama app and retry."
        }
    }

    if (Test-Ollama) {
        Write-Status ok "Ollama is installed and running. Local-model features will work. See Settings -> Tool compatibility for model details."
    }
    else {
        Write-Status warn "Ollama is installed but its endpoint is not reachable. Open the Ollama app; local-model features will remain unavailable until it is running."
    }
}

try {
    Write-Host ""
    Write-Host "Frontier one-click launcher" -ForegroundColor White
    Write-Host "Repository: $Root" -ForegroundColor DarkGray
    $bootstrapPython = Assert-SystemDependencies
    Install-ProjectDependencies -BootstrapPython $bootstrapPython
    Start-OllamaIfAvailable
    Start-FrontierServices
    Write-Host ""
    Write-Status ok "Frontier is ready: $DashboardUrl"
    Write-Status info "API docs: $ApiUrl/docs"
    Write-Status info "Runtime logs: $Logs"
    if (-not $NoBrowser) { Start-Process $DashboardUrl }
    exit 0
}
catch {
    Write-Status error $_.Exception.Message
    Write-Status info "Runtime logs, when available: $Logs"
    exit 1
}
