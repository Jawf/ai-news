# ai-news service control: start | stop | restart | status
param([ValidateSet("start","stop","restart","status")][string]$Action = "start")

$ProjectDir = Split-Path -Parent $PSScriptRoot
$Port = 8000

function Get-ServerPid {
    $line = netstat -ano | Select-String ":$Port\s.*LISTENING" | Select-Object -First 1
    if ($line) { return ($line -split '\s+')[-1] }
    return $null
}

function Start-Server {
    if (Get-ServerPid) { Write-Host "[OK] already running: http://localhost:$Port"; return }
    Write-Host "starting ai-news service on port $Port ..."
    Start-Process -FilePath "uv" `
        -ArgumentList "run","python","-m","ainews.cli","serve","--host","0.0.0.0","--port","$Port" `
        -WorkingDirectory $ProjectDir -WindowStyle Hidden
    for ($i = 0; $i -lt 15; $i++) {
        Start-Sleep -Seconds 1
        if (Get-ServerPid) {
            Write-Host "[OK] started: http://localhost:$Port (LAN: http://<your-ip>:$Port)"
            Write-Host "     schedule: hourly fetch+patrol / 08:00 12:00 analyze+trade / 03:30 purge"
            return
        }
    }
    Write-Host "[!] port not detected after 15s - check manually: http://localhost:$Port"
}

function Stop-Server {
    $procId = Get-ServerPid
    if (-not $procId) { Write-Host "[-] not running"; return }
    Write-Host "stopping PID $procId ..."
    taskkill /F /PID $procId | Out-Null
    Start-Sleep -Seconds 1
    if (Get-ServerPid) { Write-Host "[!] still listening - stop manually" } else { Write-Host "[OK] stopped" }
}

switch ($Action) {
    "start"   { Start-Server }
    "stop"    { Stop-Server }
    "restart" { Stop-Server; Start-Sleep -Seconds 1; Start-Server }
    "status"  {
        $procId = Get-ServerPid
        if ($procId) { Write-Host "[OK] running (PID $procId): http://localhost:$Port" }
        else { Write-Host "[-] not running" }
    }
}
