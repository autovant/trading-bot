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

$ThisScript = $MyInvocation.MyCommand.Path

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
$ActiveModeFile = Join-Path $RunDir "active-mode.txt"
$Global:Services = @()
$Global:LocalEnv = @{}

function Get-DefaultEnvLines {
    return @(
        "APP_MODE=paper",
        "NATS_URL=nats://127.0.0.1:4222",
        "DB_URL=sqlite+aiosqlite:///./dev.db",
        "API_PORT=8080",
        "UI_PORT=8501",
        "EXEC_PORT=8082",
        "FEED_PORT=8081",
        "RISK_PORT=8083",
        "REPORTER_PORT=8084",
        "REPLAY_PORT=8085",
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

    throw "No suitable Python interpreter found. Install Python 3.11+ (or the highest 3.x) and retry."
}

function Ensure-Venv {
    param([string]$PythonPath)

    if (-not (Test-Path $VenvPython)) {
        Write-Log "Creating virtual environment at $VenvDir"
        & $PythonPath -m venv $VenvDir
    }

    Write-Log "Upgrading pip inside the virtual environment"
    & $VenvPython -m pip install --upgrade pip | Write-Host

    $requirements = Join-Path $RepoRoot "requirements.txt"
    if (Test-Path $requirements) {
        Write-Log "Installing dependencies from requirements.txt"
        & $VenvPython -m pip install -r $requirements | Write-Host
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
    if (-not (Test-Path $EnvExample)) {
        Write-Log "Creating .env.example with safe defaults"
        Set-Content -Path $EnvExample -Value ((Get-DefaultEnvLines) -join [Environment]::NewLine)
    }
}

function Load-Env {
    param([string]$Path)
    if (-not (Test-Path $Path)) { return }
    Write-Log "Loading environment variables from $Path"
    $Global:LocalEnv.Clear()
    $lines = Get-Content $Path
    foreach ($line in $lines) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith("#") -or -not $trimmed.Contains("=")) {
            continue
        }
        $pair = $trimmed.Split("=", 2)
        $key = $pair[0].Trim()
        $value = $pair[1].Trim().Trim('"').Trim("'")
        if ($key) {
            $Global:LocalEnv[$key] = $value
        }
    }
}

function Get-LocalEnvValue {
    param(
        [string]$Key,
        [string]$Default
    )
    if ($Global:LocalEnv.ContainsKey($Key) -and $Global:LocalEnv[$Key]) {
        return $Global:LocalEnv[$Key]
    }
    return $Default
}

function Set-LocalEnvDefault {
    param(
        [string]$Key,
        [string]$Value
    )
    if (-not $Global:LocalEnv.ContainsKey($Key) -or -not $Global:LocalEnv[$Key]) {
        $Global:LocalEnv[$Key] = $Value
    }
}

function Ensure-DerivedEnv {
    Set-LocalEnvDefault "NATS_URL" "nats://127.0.0.1:4222"
    Set-LocalEnvDefault "DB_URL" "sqlite+aiosqlite:///./dev.db"
    Set-LocalEnvDefault "API_PORT" "8080"
    Set-LocalEnvDefault "UI_PORT" "8501"
    Set-LocalEnvDefault "EXEC_PORT" "8082"
    Set-LocalEnvDefault "FEED_PORT" "8081"
    Set-LocalEnvDefault "RISK_PORT" "8083"
    Set-LocalEnvDefault "REPORTER_PORT" "8084"
    Set-LocalEnvDefault "REPLAY_PORT" "8085"
    Set-LocalEnvDefault "OPS_PORT" "8080"
    $currentApiPort = Get-LocalEnvValue "API_PORT" "8080"
    $currentReplayPort = Get-LocalEnvValue "REPLAY_PORT" "8085"
    Set-LocalEnvDefault "OPS_API_URL" "http://127.0.0.1:$currentApiPort"
    Set-LocalEnvDefault "REPLAY_URL" "http://127.0.0.1:$currentReplayPort"
}

function Export-LocalEnv {
    foreach ($entry in $Global:LocalEnv.GetEnumerator()) {
        $key = $entry.Key
        $value = $entry.Value
        if ($null -ne $value) {
            Set-Item -Path ("Env:{0}" -f $key) -Value $value
        }
    }
}

function Get-Ports {
    return @{
        api      = Get-LocalEnvValue "API_PORT" "8080"
        ui       = Get-LocalEnvValue "UI_PORT" "8501"
        exec     = Get-LocalEnvValue "EXEC_PORT" "8082"
        feed     = Get-LocalEnvValue "FEED_PORT" "8081"
        risk     = Get-LocalEnvValue "RISK_PORT" "8083"
        reporter = Get-LocalEnvValue "REPORTER_PORT" "8084"
        replay   = Get-LocalEnvValue "REPLAY_PORT" "8085"
    }
}

# Edit the map below to tweak service commands, ports, or health checks.
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
            Port = $null
            Modes = @("paper", "live", "replay")
        },
        [pscustomobject]@{
            Name = "ops-api"
            FilePath = $PythonPath
            Arguments = @(
                "-m", "uvicorn", "src.ops_api_service:app",
                "--host", "127.0.0.1",
                "--port", $ports.api
            )
            WorkingDirectory = $RepoRoot
            LogPath = Join-Path $LogDir "ops-api.log"
            PidPath = Join-Path $RunDir "ops-api.pid"
            HealthUrl = "http://127.0.0.1:$($ports.api)/health"
            Port = $ports.api
            Modes = @("paper", "live", "replay")
        },
        [pscustomobject]@{
            Name = "feed"
            FilePath = $PythonPath
            Arguments = @(
                "-m", "uvicorn", "src.services.feed:app",
                "--host", "127.0.0.1",
                "--port", $ports.feed
            )
            WorkingDirectory = $RepoRoot
            LogPath = Join-Path $LogDir "feed.log"
            PidPath = Join-Path $RunDir "feed.pid"
            HealthUrl = "http://127.0.0.1:$($ports.feed)/health"
            Port = $ports.feed
            Modes = @("paper", "live")
        },
        [pscustomobject]@{
            Name = "execution"
            FilePath = $PythonPath
            Arguments = @(
                "-m", "uvicorn", "src.services.execution:app",
                "--host", "127.0.0.1",
                "--port", $ports.exec
            )
            WorkingDirectory = $RepoRoot
            LogPath = Join-Path $LogDir "execution.log"
            PidPath = Join-Path $RunDir "execution.pid"
            HealthUrl = "http://127.0.0.1:$($ports.exec)/health"
            Port = $ports.exec
            Modes = @("paper", "live", "replay")
        },
        [pscustomobject]@{
            Name = "risk"
            FilePath = $PythonPath
            Arguments = @(
                "-m", "uvicorn", "src.services.risk:app",
                "--host", "127.0.0.1",
                "--port", $ports.risk
            )
            WorkingDirectory = $RepoRoot
            LogPath = Join-Path $LogDir "risk.log"
            PidPath = Join-Path $RunDir "risk.pid"
            HealthUrl = "http://127.0.0.1:$($ports.risk)/health"
            Port = $ports.risk
            Modes = @("paper", "live", "replay")
        },
        [pscustomobject]@{
            Name = "reporter"
            FilePath = $PythonPath
            Arguments = @(
                "-m", "uvicorn", "src.services.reporter:app",
                "--host", "127.0.0.1",
                "--port", $ports.reporter
            )
            WorkingDirectory = $RepoRoot
            LogPath = Join-Path $LogDir "reporter.log"
            PidPath = Join-Path $RunDir "reporter.pid"
            HealthUrl = "http://127.0.0.1:$($ports.reporter)/health"
            Port = $ports.reporter
            Modes = @("paper", "live", "replay")
        },
        [pscustomobject]@{
            Name = "replay"
            FilePath = $PythonPath
            Arguments = @(
                "-m", "uvicorn", "src.services.replay:app",
                "--host", "127.0.0.1",
                "--port", $ports.replay
            )
            WorkingDirectory = $RepoRoot
            LogPath = Join-Path $LogDir "replay.log"
            PidPath = Join-Path $RunDir "replay.pid"
            HealthUrl = "http://127.0.0.1:$($ports.replay)/health"
            Port = $ports.replay
            Modes = @("replay")
        },
        [pscustomobject]@{
            Name = "dashboard"
            FilePath = $PythonPath
            Arguments = @(
                "-m", "streamlit", "run", "dashboard/app.py",
                "--server.port", $ports.ui,
                "--server.headless", "true",
                "--browser.gatherUsageStats", "false"
            )
            WorkingDirectory = $RepoRoot
            LogPath = Join-Path $LogDir "dashboard.log"
            PidPath = Join-Path $RunDir "dashboard.pid"
            HealthUrl = "http://127.0.0.1:$($ports.ui)/_stcore/health"
            Port = $ports.ui
            Modes = @("paper", "live", "replay")
        }
    )

    return $Global:Services
}

function Should-RunService {
    param(
        $Service,
        [string]$Mode
    )
    if (-not $Service.Modes -or $Service.Modes.Count -eq 0) {
        return $true
    }
    return $Service.Modes -contains $Mode
}

function Test-ProcessAlive {
    param([string]$PidPath)
    if (-not (Test-Path $PidPath)) { return $null }
    $pidValue = (Get-Content $PidPath | Select-Object -First 1).Trim()
    if (-not $pidValue) { return $null }
    $pidCandidate = 0
    if (-not [int]::TryParse($pidValue, [ref]$pidCandidate)) {
        Remove-Item $PidPath -ErrorAction SilentlyContinue
        return $null
    }
    $proc = Get-Process -Id $pidCandidate -ErrorAction SilentlyContinue
    if ($null -ne $proc) {
        return $proc
    }
    Remove-Item $PidPath -ErrorAction SilentlyContinue
    return $null
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
    $process = Start-Process `
        -FilePath $Service.FilePath `
        -ArgumentList $arguments `
        -WorkingDirectory $Service.WorkingDirectory `
        -PassThru `
        -RedirectStandardOutput $Service.LogPath `
        -RedirectStandardError $stdErrLog
    Set-Content -Path $Service.PidPath -Value $process.Id
}

function Test-ServiceHealth {
    param(
        $Service,
        [switch]$Quiet
    )
    if (-not $Service.HealthUrl) {
        return $true
    }
    try {
        $response = Invoke-WebRequest -Uri $Service.HealthUrl -UseBasicParsing -TimeoutSec 5
        return ($response.StatusCode -ge 200 -and $response.StatusCode -lt 300)
    }
    catch {
        if (-not $Quiet) {
            Write-Log "$($Service.Name) health probe failed: $($_.Exception.Message)" "WARN"
        }
        return $false
    }
}

function Wait-ForServiceHealth {
    param(
        $Service,
        [int]$TimeoutSec = 45
    )
    if (-not $Service.HealthUrl) {
        return $true
    }
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        if (Test-ServiceHealth -Service $Service -Quiet) {
            Write-Log "$($Service.Name) passed warmup health check"
            return $true
        }
        Start-Sleep -Seconds 2
    }
    return $false
}

function Ensure-ServiceRunning {
    param(
        $Service,
        [string]$Mode
    )
    if (-not (Should-RunService -Service $Service -Mode $Mode)) {
        Write-Log "$($Service.Name) skipped for mode $Mode"
        return
    }

    $maxAttempts = 2
    for ($attempt = 1; $attempt -le $maxAttempts; $attempt++) {
        $existing = Test-ProcessAlive -PidPath $Service.PidPath
        if ($existing -and (Test-ServiceHealth -Service $Service -Quiet)) {
            Write-Log "$($Service.Name) already running (PID $($existing.Id))"
            return
        }
        if ($existing) {
            Write-Log "$($Service.Name) running but unhealthy; restarting (attempt $attempt/$maxAttempts)" "WARN"
            Stop-ServiceProcess -Service $Service
            Start-Sleep -Seconds 2
        }

        Start-ServiceProcess -Service $Service
        if (Wait-ForServiceHealth -Service $Service -TimeoutSec 45) {
            return
        }

        Write-Log "$($Service.Name) failed warmup health (attempt $attempt/$maxAttempts). Restarting..." "WARN"
        Stop-ServiceProcess -Service $Service
        Start-Sleep -Seconds 2
    }

    throw "$($Service.Name) failed to become healthy after $maxAttempts attempts. Check $($Service.LogPath) and $($Service.LogPath).err"
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
        if (-not $process.HasExited) {
            Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        }
    }
    if (Test-Path $Service.PidPath) {
        Remove-Item $Service.PidPath -ErrorAction SilentlyContinue
    }
}

function Start-AllServices {
    param([string]$Mode)
    foreach ($service in $Global:Services) {
        Ensure-ServiceRunning -Service $service -Mode $Mode
    }
}

function Stop-AllServices {
    foreach ($service in $Global:Services) {
        Stop-ServiceProcess -Service $service
    }
}

function Show-ServiceStatus {
    param([string]$Mode)
    $rows = @()
    foreach ($service in $Global:Services) {
        $expected = Should-RunService -Service $service -Mode $Mode
        $process = Test-ProcessAlive -PidPath $service.PidPath
        if (-not $expected) {
            $rows += [pscustomobject]@{
                Name = $service.Name
                PID = "-"
                Port = if ($service.Port) { $service.Port } else { "-" }
                Status = "SKIPPED ($Mode)"
                Log = $service.LogPath
            }
            continue
        }
        if ($process) {
            $rows += [pscustomobject]@{
                Name = $service.Name
                PID = $process.Id
                Port = if ($service.Port) { $service.Port } else { "-" }
                Status = "RUNNING"
                Log = $service.LogPath
            }
        }
        else {
            $rows += [pscustomobject]@{
                Name = $service.Name
                PID = "-"
                Port = if ($service.Port) { $service.Port } else { "-" }
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
    param(
        [int]$TimeoutSec = 60,
        [string]$Mode
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    $results = @{}

    foreach ($service in $Global:Services) {
        if (-not (Should-RunService -Service $service -Mode $Mode)) {
            $results[$service.Name] = $true
            continue
        }
        if ($service.HealthUrl) {
            $results[$service.Name] = $false
        }
        else {
            $results[$service.Name] = $true
        }
    }

    while ((Get-Date) -lt $deadline) {
        foreach ($service in $Global:Services) {
            if (-not (Should-RunService -Service $service -Mode $Mode)) { continue }
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
        if (-not (Should-RunService -Service $service -Mode $Mode)) {
            Write-Log "$($service.Name) skipped for mode $Mode"
            continue
        }
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
        Write-Log "All requested services healthy. READY"
    }
}

function Ensure-NatsBinary {
    if (Test-Path $NatsExe) {
        return
    }

    Write-Log "NATS binary not found. Downloading latest Windows release"
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
        Write-Log "Failed to query GitHub releases. Falling back to pinned NATS v2.10.14" "WARN"
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
        throw "NATS setup failed. Ensure internet connectivity or manually place nats-server.exe under tools\nats."
    }
}

function Start-Nats {
    Ensure-NatsBinary
    $maxAttempts = 3
    $arguments = @("--addr", "127.0.0.1", "--http_port", "8222")
    for ($attempt = 1; $attempt -le $maxAttempts; $attempt++) {
        $existing = Test-ProcessAlive -PidPath $NatsPidFile
        if ($existing) {
            if (Test-NatsHealth -Quiet) {
                Write-Log "NATS already running (PID $($existing.Id))"
                return
            }
            Write-Log "NATS process $($existing.Id) unhealthy; restarting" "WARN"
            Stop-Nats
            Start-Sleep -Seconds 2
        }

        Write-Log "Starting NATS server (attempt $attempt/$maxAttempts)"
        $stdErrLog = "$NatsLog.err"
        $process = Start-Process `
            -FilePath $NatsExe `
            -ArgumentList $arguments `
            -WorkingDirectory $NatsDir `
            -PassThru `
            -RedirectStandardOutput $NatsLog `
            -RedirectStandardError $stdErrLog
        Set-Content -Path $NatsPidFile -Value $process.Id

        if (Wait-ForNatsHealthy -TimeoutSec 20) {
            Write-Log "NATS ready (PID $($process.Id))"
            return
        }

        Write-Log "NATS failed to report healthy (attempt $attempt/$maxAttempts). Retrying..." "WARN"
        Write-Log "If Windows prompts for network access, click 'Allow' to let nats-server bind to localhost." "WARN"
        Stop-Nats
        Start-Sleep -Seconds 2
    }

    $tail = ""
    if (Test-Path "$NatsLog.err") {
        $tail = (Get-Content "$NatsLog.err" -Tail 15) -join [Environment]::NewLine
    }
    throw "NATS could not start after $maxAttempts attempts. Check logs/nats.log.err for details.`n$tail"
}

function Wait-ForNatsHealthy {
    param([int]$TimeoutSec = 20)
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        if (Test-NatsHealth -Quiet) {
            return $true
        }
        Start-Sleep -Seconds 2
    }
    return $false
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
        if (-not $process.HasExited) {
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
    param([switch]$Quiet)
    try {
        $response = Invoke-WebRequest -Uri "http://127.0.0.1:8222/healthz" -UseBasicParsing -TimeoutSec 5
        if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 300) {
            if (-not $Quiet) {
                Write-Log "NATS HEALTHY"
            }
            return $true
        }
    }
    catch {}
    if (-not $Quiet) {
        Write-Log "NATS health check failed" "ERROR"
    }
    return $false
}

function Perform-Clean {
    Stop-Nats
    Stop-AllServices
    if (Test-Path $RunDir) {
        Write-Log "Clearing run directory"
        Get-ChildItem $RunDir -Filter *.pid -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue
        if (Test-Path $ActiveModeFile) {
            Remove-Item $ActiveModeFile -ErrorAction SilentlyContinue
        }
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
        if (Test-Path $ActiveModeFile) {
            Remove-Item $ActiveModeFile -ErrorAction SilentlyContinue
        }
        exit 1
    } | Out-Null
}

try {
    Ensure-Dirs
    Ensure-Env
    Load-Env -Path $EnvFile
    Ensure-DerivedEnv
    Export-LocalEnv

    $ModeWasExplicit = $PSBoundParameters.ContainsKey("Mode")
    $EffectiveMode = $Mode
    if ($Action -ne "start" -and -not $ModeWasExplicit -and (Test-Path $ActiveModeFile)) {
        $stored = (Get-Content $ActiveModeFile -ErrorAction SilentlyContinue | Select-Object -First 1).Trim()
        if ($stored) {
            $EffectiveMode = $stored
            Write-Log "Mode argument not provided; using stored mode '$stored'."
        }
    }
    $Global:ActiveMode = $EffectiveMode
    $env:APP_MODE = $Global:ActiveMode

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
            Start-AllServices -Mode $Global:ActiveMode
            Start-Sleep -Seconds 3
            Invoke-HealthChecks -TimeoutSec 60 -Mode $Global:ActiveMode
            Set-Content -Path $ActiveModeFile -Value $Global:ActiveMode
        }
        "stop" {
            $pythonPath = if (Test-Path $VenvPython) { $VenvPython } elseif ($Python) { Resolve-Python -Requested $Python } else { "python" }
            Get-ServiceDefinitions -PythonPath $pythonPath | Out-Null
            Stop-AllServices
            Stop-Nats
            if (Test-Path $ActiveModeFile) {
                Remove-Item $ActiveModeFile -ErrorAction SilentlyContinue
            }
        }
        "restart" {
            & $ThisScript -Action stop -Mode $Mode -Python $Python
            & $ThisScript -Action start -Mode $Mode -Python $Python
            return
        }
        "status" {
            $pythonPath = if (Test-Path $VenvPython) { $VenvPython } elseif ($Python) { Resolve-Python -Requested $Python } else { "python" }
            Get-ServiceDefinitions -PythonPath $pythonPath | Out-Null
            Show-NatsStatus
            Show-ServiceStatus -Mode $Global:ActiveMode
        }
        "health" {
            $pythonPath = if (Test-Path $VenvPython) { $VenvPython } elseif ($Python) { Resolve-Python -Requested $Python } else { "python" }
            Get-ServiceDefinitions -PythonPath $pythonPath | Out-Null
            $natsHealthy = Test-NatsHealth
            try {
                Invoke-HealthChecks -TimeoutSec 5 -Mode $Global:ActiveMode
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
