[CmdletBinding()]
param(
    [ValidateSet("start", "stop", "restart", "status", "health", "clean")]
    [string]$Action = "start",

    [ValidateSet("paper", "replay", "live")]
    [string]$Mode = "paper",

    [string]$Python
)

$ErrorActionPreference = "Stop"

$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = (Resolve-Path (Join-Path $ScriptRoot "..")).Path
Set-Location $RepoRoot

$RunDir = Join-Path $RepoRoot "run"
$LogDir = Join-Path $RepoRoot "logs"
$ToolsDir = Join-Path $RepoRoot "tools"
$NatsDir = Join-Path $ToolsDir "nats"
$NatsExe = Join-Path $NatsDir "nats-server.exe"
$VenvDir = Join-Path $RepoRoot ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$EnvFile = Join-Path $RepoRoot ".env"
$EnvExample = Join-Path $RepoRoot ".env.example"
$NatsPidFile = Join-Path $RunDir "nats.pid"
$NatsLog = Join-Path $LogDir "nats.log"
$Global:Services = @()

function Get-DefaultEnvLines {
    return @(
        "APP_MODE=paper",
        "NATS_URL=nats://127.0.0.1:4222",
        "DB_URL=sqlite+aiosqlite:///./dev.db",
        "API_PORT=8080",
        "UI_PORT=8501",
        "OPS_API_URL=http://127.0.0.1:8080",
        "REPLAY_URL=http://127.0.0.1:8085",
        "EXEC_PORT=8082",
        "FEED_PORT=8081",
        "RISK_PORT=8083",
        "REPORTER_PORT=8084",
        "REPLAY_PORT=8085",
        "OPS_PORT=8080",
        "LOG_LEVEL=INFO"
    )
}

function Write-Log {
    param(
        [string]$Message,
        [ValidateSet("INFO", "WARN", "ERROR")]
        [string]$Level = "INFO"
    )
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Write-Host "[$timestamp][$Level] $Message"
}

function Ensure-Dirs {
    foreach ($dir in @($RunDir, $LogDir, $ToolsDir, $NatsDir)) {
        if (-not (Test-Path $dir)) {
            Write-Log "Creating directory $dir"
            New-Item -ItemType Directory -Path $dir | Out-Null
        }
    }
}

function Get-PythonFromCandidate {
    param([string[]]$CommandParts)
    try {
        $args = @()
        if ($CommandParts.Length -gt 1) {
            $args = $CommandParts[1..($CommandParts.Length - 1)]
        }
        $args += @("-c", "import sys; print(sys.executable)")
        $output = & $CommandParts[0] @args 2>$null
        if ($LASTEXITCODE -eq 0 -and $output) {
            $candidate = $output.Trim()
            if (Test-Path $candidate) {
                return $candidate
            }
        }
    }
    catch {
        return $null
    }
    return $null
}

function Resolve-Python {
    param([string]$Requested)

    if ($Requested) {
        if (Test-Path $Requested) {
            return (Resolve-Path $Requested).Path
        }
        else {
            throw "Provided Python path '$Requested' does not exist."
        }
    }

    $candidates = @(
        @("py", "-3.11"),
        @("py", "-3"),
        @("python")
    )

    foreach ($candidate in $candidates) {
        $path = Get-PythonFromCandidate -CommandParts $candidate
        if ($path) {
            return $path
        }
    }

    throw "No suitable Python interpreter found. Install Python 3.9+ and retry."
}

function Ensure-Venv {
    param([string]$PythonPath)

    if (-not (Test-Path $VenvPython)) {
        Write-Log "Creating virtual environment at $VenvDir"
        & $PythonPath -m venv $VenvDir
    }

    Write-Log "Upgrading pip"
    & $VenvPython -m pip install --upgrade pip | Write-Host

    if (Test-Path (Join-Path $RepoRoot "requirements.txt")) {
        Write-Log "Installing dependencies from requirements.txt"
        & $VenvPython -m pip install -r (Join-Path $RepoRoot "requirements.txt") | Write-Host
    }
    else {
        $defaultPackages = @(
            "fastapi",
            "uvicorn[standard]",
            "pydantic",
            "requests",
            "python-dotenv",
            "streamlit",
            "nats-py",
            "prometheus-client"
        )
        Write-Log "Installing baseline dependencies"
        & $VenvPython -m pip install @defaultPackages | Write-Host
    }
}

function New-DefaultEnv {
    $defaults = Get-DefaultEnvLines
    Write-Log "Generating default .env"
    Set-Content -Path $EnvFile -Value ($defaults -join [Environment]::NewLine)
}

function Ensure-Env {
    if (-not (Test-Path $EnvFile)) {
        New-DefaultEnv
    }
    $defaults = Get-DefaultEnvLines
    Write-Log "Ensuring .env.example with default values"
    Set-Content -Path $EnvExample -Value ($defaults -join [Environment]::NewLine)
}

function Load-Env {
    param([string]$Path)
    Write-Log "Loading environment variables from $Path"
    $lines = Get-Content $Path
    foreach ($line in $lines) {
        if ($line.Trim().StartsWith("#") -or -not $line.Contains("=")) {
            continue
        }
        $pair = $line.Split("=", 2)
        $key = $pair[0].Trim()
        $value = $pair[1].Trim().Trim('"').Trim("'")
        if ($key) {
            Set-Item -Path "env:$key" -Value $value
        }
    }
}

function Get-Ports {
    return @{
        api = if ($env:API_PORT) { $env:API_PORT } else { "8080" }
        ui = if ($env:UI_PORT) { $env:UI_PORT } else { "8501" }
        exec = if ($env:EXEC_PORT) { $env:EXEC_PORT } else { "8082" }
        feed = if ($env:FEED_PORT) { $env:FEED_PORT } else { "8081" }
        risk = if ($env:RISK_PORT) { $env:RISK_PORT } else { "8083" }
        reporter = if ($env:REPORTER_PORT) { $env:REPORTER_PORT } else { "8084" }
        replay = if ($env:REPLAY_PORT) { $env:REPLAY_PORT } else { "8085" }
        ops = if ($env:OPS_PORT) { $env:OPS_PORT } else { "8080" }
    }
}

function Get-ServiceDefinitions {
    param([string]$PythonPath)

    if (-not $PythonPath) {
        if (Test-Path $VenvPython) {
            $PythonPath = $VenvPython
        }
        else {
            $PythonPath = "python"
        }
    }

    $ports = Get-Ports

    $Global:Services = @(
        [pscustomobject]@{
            Name = "engine"
            FilePath = $PythonPath
            Arguments = @("-m", "src.main")
            WorkingDirectory = $RepoRoot
            LogPath = Join-Path $LogDir "engine.log"
            PidPath = Join-Path $RunDir "engine.pid"
            HealthUrl = $null
        },
        [pscustomobject]@{
            Name = "ops-api"
            FilePath = $PythonPath
            Arguments = @("-m", "uvicorn", "src.ops_api_service:app", "--host", "127.0.0.1", "--port", $ports.ops, "--reload")
            WorkingDirectory = $RepoRoot
            LogPath = Join-Path $LogDir "ops-api.log"
            PidPath = Join-Path $RunDir "ops-api.pid"
            HealthUrl = "http://127.0.0.1:$($ports.ops)/health"
        },
        [pscustomobject]@{
            Name = "feed"
            FilePath = $PythonPath
            Arguments = @("-m", "uvicorn", "src.services.feed:app", "--host", "127.0.0.1", "--port", $ports.feed, "--reload")
            WorkingDirectory = $RepoRoot
            LogPath = Join-Path $LogDir "feed.log"
            PidPath = Join-Path $RunDir "feed.pid"
            HealthUrl = "http://127.0.0.1:$($ports.feed)/health"
        },
        [pscustomobject]@{
            Name = "execution"
            FilePath = $PythonPath
            Arguments = @("-m", "uvicorn", "src.services.execution:app", "--host", "127.0.0.1", "--port", $ports.exec, "--reload")
            WorkingDirectory = $RepoRoot
            LogPath = Join-Path $LogDir "execution.log"
            PidPath = Join-Path $RunDir "execution.pid"
            HealthUrl = "http://127.0.0.1:$($ports.exec)/health"
        },
        [pscustomobject]@{
            Name = "risk"
            FilePath = $PythonPath
            Arguments = @("-m", "uvicorn", "src.services.risk:app", "--host", "127.0.0.1", "--port", $ports.risk, "--reload")
            WorkingDirectory = $RepoRoot
            LogPath = Join-Path $LogDir "risk.log"
            PidPath = Join-Path $RunDir "risk.pid"
            HealthUrl = "http://127.0.0.1:$($ports.risk)/health"
        },
        [pscustomobject]@{
            Name = "reporter"
            FilePath = $PythonPath
            Arguments = @("-m", "uvicorn", "src.services.reporter:app", "--host", "127.0.0.1", "--port", $ports.reporter, "--reload")
            WorkingDirectory = $RepoRoot
            LogPath = Join-Path $LogDir "reporter.log"
            PidPath = Join-Path $RunDir "reporter.pid"
            HealthUrl = "http://127.0.0.1:$($ports.reporter)/health"
        },
        [pscustomobject]@{
            Name = "replay"
            FilePath = $PythonPath
            Arguments = @("-m", "uvicorn", "src.services.replay:app", "--host", "127.0.0.1", "--port", $ports.replay, "--reload")
            WorkingDirectory = $RepoRoot
            LogPath = Join-Path $LogDir "replay.log"
            PidPath = Join-Path $RunDir "replay.pid"
            HealthUrl = "http://127.0.0.1:$($ports.replay)/health"
        },
        [pscustomobject]@{
            Name = "dashboard"
            FilePath = $PythonPath
            Arguments = @("-m", "streamlit", "run", "dashboard/app.py", "--server.port", $ports.ui, "--server.headless", "true", "--browser.gatherUsageStats", "false")
            WorkingDirectory = $RepoRoot
            LogPath = Join-Path $LogDir "dashboard.log"
            PidPath = Join-Path $RunDir "dashboard.pid"
            HealthUrl = "http://127.0.0.1:$($ports.ui)/_stcore/health"
        }
    )

    return $Global:Services
}

function Test-ProcessAlive {
    param([string]$PidPath)
    if (-not (Test-Path $PidPath)) { return $null }
    $pid = (Get-Content $PidPath | Select-Object -First 1).Trim()
    if (-not $pid) { return $null }
    $proc = Get-Process -Id $pid -ErrorAction SilentlyContinue
    if ($null -ne $proc) {
        return $proc
    }
    else {
        Remove-Item $PidPath -ErrorAction SilentlyContinue
        return $null
    }
}

function Start-ServiceProcess {
    param($Service)

    $existing = Test-ProcessAlive -PidPath $Service.PidPath
    if ($existing) {
        Write-Log "$($Service.Name) already running (PID $($existing.Id))"
        return
    }

    $arguments = $Service.Arguments
    Write-Log "Starting $($Service.Name): $($Service.FilePath) $($arguments -join ' ')"
    $stdErrLog = "$($Service.LogPath).err"
    $process = Start-Process -FilePath $Service.FilePath -ArgumentList $arguments -WorkingDirectory $Service.WorkingDirectory -PassThru -RedirectStandardOutput $Service.LogPath -RedirectStandardError $stdErrLog
    Set-Content -Path $Service.PidPath -Value $process.Id
}

function Stop-ServiceProcess {
    param($Service)
    $process = Test-ProcessAlive -PidPath $Service.PidPath
    if ($process) {
        Write-Log "Stopping $($Service.Name) (PID $($process.Id))"
        try {
            $process.CloseMainWindow() | Out-Null
        }
        catch {}
        Start-Sleep -Seconds 2
        if (!$process.HasExited) {
            Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        }
    }
    if (Test-Path $Service.PidPath) {
        Remove-Item $Service.PidPath -ErrorAction SilentlyContinue
    }
}

function Start-AllServices {
    foreach ($service in $Global:Services) {
        Start-ServiceProcess -Service $service
    }
}

function Stop-AllServices {
    foreach ($service in $Global:Services) {
        Stop-ServiceProcess -Service $service
    }
}

function Show-ServiceStatus {
    $rows = @()
    foreach ($service in $Global:Services) {
        $process = Test-ProcessAlive -PidPath $service.PidPath
        if ($process) {
            $rows += [pscustomobject]@{
                Name = $service.Name
                PID = $process.Id
                Status = "RUNNING"
                Log = $service.LogPath
            }
        }
        else {
            $rows += [pscustomobject]@{
                Name = $service.Name
                PID = "-"
                Status = "STOPPED"
                Log = $service.LogPath
            }
        }
    }
    if ($rows.Count -gt 0) {
        $rows | Format-Table -AutoSize
    }
    else {
        Write-Log "No services defined" "WARN"
    }
}

function Invoke-HealthChecks {
    param([int]$TimeoutSec = 60)

    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    $results = @{}
    foreach ($service in $Global:Services) {
        if ($service.HealthUrl) {
            $results[$service.Name] = $false
        }
        else {
            $results[$service.Name] = $true
        }
    }

    while ((Get-Date) -lt $deadline) {
        foreach ($service in $Global:Services) {
            if (-not $service.HealthUrl) { continue }
            if ($results[$service.Name]) { continue }
            try {
                $response = Invoke-WebRequest -Uri $service.HealthUrl -UseBasicParsing -TimeoutSec 5
                if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 300) {
                    $results[$service.Name] = $true
                    Write-Log "$($service.Name) passed health check"
                }
            }
            catch {
                Start-Sleep -Seconds 2
            }
        }
        if (-not ($results.Values | Where-Object { -not $_ })) {
            break
        }
        Start-Sleep -Seconds 2
    }

    foreach ($service in $Global:Services) {
        if ($results[$service.Name]) {
            Write-Log "$($service.Name) HEALTHY"
        }
        else {
            Write-Log "$($service.Name) FAILED health check ($($service.HealthUrl))" "ERROR"
        }
    }

    if ($results.Values | Where-Object { -not $_ }) {
        throw "One or more services failed health checks."
    }
    else {
        Write-Log "All services healthy. READY"
    }
}

function Ensure-NatsBinary {
    if (Test-Path $NatsExe) {
        return
    }

    Write-Log "NATS binary not found. Downloading latest release"
    $releaseUrl = "https://api.github.com/repos/nats-io/nats-server/releases/latest"
    $zipPath = Join-Path $NatsDir "nats-server.zip"
    try {
        $release = Invoke-RestMethod -Uri $releaseUrl -Headers @{"User-Agent" = "trading-bot-local-deployer"}
        $asset = $release.assets | Where-Object { $_.name -like "*windows-amd64.zip" } | Select-Object -First 1
        if (-not $asset) {
            throw "Suitable Windows AMD64 asset not found in latest release."
        }
        $downloadUrl = $asset.browser_download_url
    }
    catch {
        Write-Log "Failed to query GitHub releases. Falling back to pinned version" "WARN"
        $downloadUrl = "https://github.com/nats-io/nats-server/releases/download/v2.10.14/nats-server-v2.10.14-windows-amd64.zip"
    }

    try {
        Write-Log "Downloading NATS from $downloadUrl"
        Invoke-WebRequest -Uri $downloadUrl -OutFile $zipPath -UseBasicParsing
        Write-Log "Extracting NATS archive"
        Expand-Archive -Path $zipPath -DestinationPath $NatsDir -Force
        Remove-Item $zipPath -ErrorAction SilentlyContinue
        $extracted = Get-ChildItem $NatsDir -Directory | Where-Object { $_.Name -like "nats-server*" } | Select-Object -First 1
        if ($null -eq $extracted) {
            throw "Failed to locate extracted NATS directory."
        }
        $sourceExe = Join-Path $extracted.FullName "nats-server.exe"
        Copy-Item $sourceExe $NatsExe -Force
        try {
            Remove-Item $extracted.FullName -Recurse -Force -ErrorAction SilentlyContinue
        }
        catch {}
    }
    catch {
        Write-Log "Unable to download or extract NATS: $_" "ERROR"
        throw "NATS setup failed. Ensure internet connectivity or manually place nats-server.exe under tools\\nats."
    }
}

function Start-Nats {
    Ensure-NatsBinary

    $existing = Test-ProcessAlive -PidPath $NatsPidFile
    if ($existing) {
        Write-Log "NATS already running (PID $($existing.Id))"
        return
    }

    $arguments = @("-p", "4222", "--http_port", "8222")
    Write-Log "Starting NATS server"
    $stdErrLog = "$NatsLog.err"
    $process = Start-Process -FilePath $NatsExe -ArgumentList $arguments -WorkingDirectory $NatsDir -PassThru -RedirectStandardOutput $NatsLog -RedirectStandardError $stdErrLog
    Set-Content -Path $NatsPidFile -Value $process.Id
    if (-not $env:NATS_URL) {
        $env:NATS_URL = "nats://127.0.0.1:4222"
    }
}

function Stop-Nats {
    $process = Test-ProcessAlive -PidPath $NatsPidFile
    if ($process) {
        Write-Log "Stopping NATS (PID $($process.Id))"
        try {
            $process.CloseMainWindow() | Out-Null
        }
        catch {}
        Start-Sleep -Seconds 2
        if (!$process.HasExited) {
            Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        }
    }
    if (Test-Path $NatsPidFile) {
        Remove-Item $NatsPidFile -ErrorAction SilentlyContinue
    }
}

function Show-NatsStatus {
    $process = Test-ProcessAlive -PidPath $NatsPidFile
    if ($process) {
        Write-Log "NATS RUNNING (PID $($process.Id))"
    }
    else {
        Write-Log "NATS STOPPED" "WARN"
    }
}

function Test-NatsHealth {
    try {
        $response = Invoke-WebRequest -Uri "http://127.0.0.1:8222/healthz" -UseBasicParsing -TimeoutSec 5
        if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 300) {
            Write-Log "NATS HEALTHY"
            return $true
        }
    }
    catch {}
    Write-Log "NATS health check failed" "ERROR"
    return $false
}

function Perform-Clean {
    Stop-Nats
    Stop-AllServices
    if (Test-Path $RunDir) {
        Write-Log "Clearing run directory"
        Get-ChildItem $RunDir -Filter *.pid -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue
    }
    if (Test-Path $LogDir) {
        Write-Log "Clearing logs directory"
        Get-ChildItem $LogDir -Filter *.log -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue
    }
    if (Test-Path $VenvDir) {
        $confirm = Read-Host "Delete virtual environment at $VenvDir? (y/N)"
        if ($confirm -match '^[Yy]$') {
            Write-Log "Removing virtual environment"
            Remove-Item $VenvDir -Recurse -Force
        }
    }
}

function Register-CtrlCHandler {
    Register-EngineEvent -SourceIdentifier ConsoleCancelEvent -Action {
        Write-Host "`nCtrl+C detected. Stopping services..."
        Stop-Nats
        Stop-AllServices
        exit 1
    } | Out-Null
}

try {
    Ensure-Dirs
    Ensure-Env
    Load-Env -Path $EnvFile
    $env:APP_MODE = $Mode

    switch ($Action) {
        "start" {
            $pythonPath = Resolve-Python -Requested $Python
            Write-Log "Using Python interpreter at $pythonPath"
            Ensure-Venv -PythonPath $pythonPath
            if (-not (Test-Path $VenvPython)) {
                throw "Virtual environment python not found at $VenvPython"
            }
            Register-CtrlCHandler
            $servicePython = $VenvPython
            Get-ServiceDefinitions -PythonPath $servicePython | Out-Null
            Start-Nats
            Start-AllServices
            Start-Sleep -Seconds 3
            Invoke-HealthChecks -TimeoutSec 60
        }
        "stop" {
            $pythonPath = if (Test-Path $VenvPython) { $VenvPython } elseif ($Python) { Resolve-Python -Requested $Python } else { "python" }
            Get-ServiceDefinitions -PythonPath $pythonPath | Out-Null
            Stop-AllServices
            Stop-Nats
        }
        "restart" {
            & $MyInvocation.MyCommand.Path -Action stop -Mode $Mode -Python $Python
            & $MyInvocation.MyCommand.Path -Action start -Mode $Mode -Python $Python
            return
        }
        "status" {
            $pythonPath = if (Test-Path $VenvPython) { $VenvPython } elseif ($Python) { Resolve-Python -Requested $Python } else { "python" }
            Get-ServiceDefinitions -PythonPath $pythonPath | Out-Null
            Show-NatsStatus
            Show-ServiceStatus
        }
        "health" {
            $pythonPath = if (Test-Path $VenvPython) { $VenvPython } elseif ($Python) { Resolve-Python -Requested $Python } else { "python" }
            Get-ServiceDefinitions -PythonPath $pythonPath | Out-Null
            $natsHealthy = Test-NatsHealth
            try {
                Invoke-HealthChecks -TimeoutSec 5
                if (-not $natsHealthy) { exit 1 }
            }
            catch {
                exit 1
            }
        }
        "clean" {
            $pythonPath = if (Test-Path $VenvPython) { $VenvPython } elseif ($Python) { Resolve-Python -Requested $Python } else { "python" }
            Get-ServiceDefinitions -PythonPath $pythonPath | Out-Null
            Perform-Clean
        }
    }
}
catch {
    Write-Log $_.Exception.Message "ERROR"
    exit 1
}
finally {
    Get-EventSubscriber -SourceIdentifier ConsoleCancelEvent -ErrorAction SilentlyContinue | Unregister-Event -ErrorAction SilentlyContinue
}
