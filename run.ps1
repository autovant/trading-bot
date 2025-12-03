Write-Host "Starting Trading Bot System..." -ForegroundColor Green

# 1. Setup Python Virtual Environment
if (-not (Test-Path "venv")) {
    Write-Host "Creating virtual environment..."
    python -m venv venv
}

# 2. Install requirements
Write-Host "Installing dependencies..."
.\venv\Scripts\python.exe -m pip install -r requirements.txt

# 3. Start Backend Server
Write-Host "Starting Backend API..."
# Launch in a new window so logs are visible
Start-Process -FilePath "cmd.exe" -ArgumentList "/k .\venv\Scripts\uvicorn.exe main:app --reload --port 8000" -WorkingDirectory "$PSScriptRoot"

# 4. Start Frontend Dev Server
Write-Host "Starting Frontend..."
# Launch in a new window so logs are visible
Start-Process -FilePath "cmd.exe" -ArgumentList "/k npm run dev" -WorkingDirectory "$PSScriptRoot\frontend"

Write-Host "Services started in separate windows." -ForegroundColor Green
