# keystroke-auth - Start All Services
# Run from the project root: .\start.ps1

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "   keystroke-auth - Starting Services  " -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Start Auth Service
Write-Host "[..] Starting Auth Service (port 5001)..." -ForegroundColor Yellow
$authJob = Start-Job -ScriptBlock {
    Set-Location $using:PWD\auth-service
    python app.py 2>&1
}
Start-Sleep -Seconds 2
Write-Host "[OK] Auth Service started" -ForegroundColor Green

# Start Dummy App
Write-Host "[..] Starting Dummy WebApp (port 3000)..." -ForegroundColor Yellow
$appJob = Start-Job -ScriptBlock {
    Set-Location $using:PWD\dummy-app
    python server.py 2>&1
}
Start-Sleep -Seconds 2
Write-Host "[OK] Dummy WebApp started" -ForegroundColor Green

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "         Services Running!             " -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Auth Service:  http://localhost:5001" -ForegroundColor White
Write-Host "  Dummy WebApp:  http://localhost:3000" -ForegroundColor White
Write-Host ""
Write-Host "Press Ctrl+C to stop all services" -ForegroundColor Gray
Write-Host ""

# Keep script running and show logs
try {
    while ($true) {
        Receive-Job $authJob -ErrorAction SilentlyContinue
        Receive-Job $appJob -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 1
    }
} finally {
    Write-Host ""
    Write-Host "Stopping services..." -ForegroundColor Yellow
    Stop-Job $authJob -ErrorAction SilentlyContinue
    Stop-Job $appJob -ErrorAction SilentlyContinue
    Remove-Job $authJob -ErrorAction SilentlyContinue
    Remove-Job $appJob -ErrorAction SilentlyContinue
    Write-Host "[OK] Services stopped" -ForegroundColor Green
}
