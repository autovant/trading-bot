# start_dev.ps1
# Robust startup script for Trading Bot Frontend

Write-Host "🚀 Starting Trading Bot Frontend Dev Environment..." -ForegroundColor Cyan

function Kill-PortProcess {
    param([int]$Port)
    
    $connections = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue
    if ($connections) {
        foreach ($conn in $connections) {
            $pid_to_kill = $conn.OwningProcess
            if ($pid_to_kill -ne 0) {
                try {
                    $process = Get-Process -Id $pid_to_kill -ErrorAction SilentlyContinue
                    if ($process) {
                        Write-Host "   ⚠️  Port $Port is in use by PID $pid_to_kill ($($process.ProcessName)). Killing it..." -ForegroundColor Yellow
                        Stop-Process -Id $pid_to_kill -Force -ErrorAction SilentlyContinue
                        Write-Host "      ✅ Process terminated." -ForegroundColor Green
                    }
                } catch {
                    Write-Host "      ❌ Failed to kill process $pid_to_kill on port $Port." -ForegroundColor Red
                }
            }
        }
    } else {
        Write-Host "   ✅ Port $Port is free." -ForegroundColor DarkGray
    }
}

# 1. Clean up ports
Write-Host "`n1️⃣  Checking ports..." -ForegroundColor White
Kill-PortProcess -Port 3000
Kill-PortProcess -Port 3001
Kill-PortProcess -Port 8000

# 2. Clean up lock file
Write-Host "`n2️⃣  Checking for stale lock files..." -ForegroundColor White
$lockFile = "frontend\.next\dev\lock"
if (Test-Path $lockFile) {
    Write-Host "   ⚠️  Found stale lock file at $lockFile. Removing..." -ForegroundColor Yellow
    Remove-Item $lockFile -Force -ErrorAction SilentlyContinue
    Write-Host "      ✅ Lock file removed." -ForegroundColor Green
} else {
    Write-Host "   ✅ No lock file found." -ForegroundColor DarkGray
}

# 3. Start Backend (API)
Write-Host "`n3️⃣  Starting Backend API (Port 8000)..." -ForegroundColor White
$backendProcess = Start-Process -FilePath "python" -ArgumentList "-m uvicorn src.api_server:app --reload --port 8000" -PassThru -NoNewWindow
Write-Host "   ✅ Backend started (PID: $($backendProcess.Id))." -ForegroundColor Green

# 4. Start Frontend
Write-Host "`n4️⃣  Starting Next.js..." -ForegroundColor White
Set-Location frontend
npm run dev
