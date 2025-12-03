Write-Host "Stopping all python and node processes..."
Stop-Process -Name "python" -ErrorAction SilentlyContinue
Stop-Process -Name "node" -ErrorAction SilentlyContinue
Write-Host "Shutdown complete."
