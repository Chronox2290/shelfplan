<#
.SYNOPSIS
    Start, stop and look after Shelf Plan on Windows.

.EXAMPLE
    .\shelfplan.ps1 start
    .\shelfplan.ps1 status
    .\shelfplan.ps1 logs
#>
param(
    [Parameter(Position = 0)]
    [ValidateSet('start', 'stop', 'restart', 'status', 'logs', 'update', 'backup', 'help')]
    [string]$Command = 'help'
)

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

# Docker Desktop does not always put its CLI on PATH.
$dockerBin = "$env:ProgramFiles\Docker\Docker\resources\bin"
if (Test-Path $dockerBin) { $env:Path = "$dockerBin;$env:Path" }

function Test-Engine {
    try { & docker info --format '{{.ServerVersion}}' 2>$null | Out-Null; return $LASTEXITCODE -eq 0 }
    catch { return $false }
}

function Start-Engine {
    if (Test-Engine) { return $true }
    Write-Host "Docker isn't running. Starting Docker Desktop..." -ForegroundColor Yellow
    $exe = "$env:ProgramFiles\Docker\Docker\Docker Desktop.exe"
    if (-not (Test-Path $exe)) {
        Write-Host "Docker Desktop is not installed." -ForegroundColor Red
        return $false
    }
    Start-Process -FilePath $exe
    foreach ($i in 1..40) {
        Start-Sleep -Seconds 5
        if (Test-Engine) { Write-Host "Docker is ready." -ForegroundColor Green; return $true }
        Write-Host "  waiting for Docker... ($($i * 5)s)"
    }
    Write-Host "Docker did not start in time. Open Docker Desktop and try again." -ForegroundColor Red
    return $false
}

function Get-Address {
    $port = 8000
    if (Test-Path .env) {
        $line = Select-String -Path .env -Pattern '^SHELFPLAN_PORT=(\d+)' -ErrorAction SilentlyContinue
        if ($line) { $port = $line.Matches[0].Groups[1].Value }
    }
    return $port
}

switch ($Command) {
    'start' {
        if (-not (Start-Engine)) { exit 1 }
        & docker compose up -d
        Start-Sleep -Seconds 6
        $port = Get-Address
        Write-Host ""
        Write-Host "Shelf Plan is running." -ForegroundColor Green
        Write-Host "  On this PC:      http://localhost:$port"
        # Skip the virtual adapters Docker and WSL create -- their addresses
        # look real but are not reachable from anything else on the network.
        $ip = (Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
               Where-Object {
                   $_.IPAddress -notmatch '^(127\.|169\.254\.)' -and
                   $_.InterfaceAlias -notmatch 'vEthernet|WSL|Docker|Loopback|Tailscale'
               } | Sort-Object -Property InterfaceMetric |
               Select-Object -First 1).IPAddress
        if ($ip) { Write-Host "  On your network: http://${ip}:$port" }
        $ts = "$env:ProgramFiles\Tailscale\tailscale.exe"
        if (Test-Path $ts) {
            $name = (& $ts status --json 2>$null | ConvertFrom-Json).Self.DNSName
            if ($name) { Write-Host "  Over Tailscale:  http://$($name.TrimEnd('.')):$port" }
        }
    }
    'stop' {
        & docker compose down
        Write-Host "Stopped. Your data is kept." -ForegroundColor Green
    }
    'restart' { & docker compose restart; Write-Host "Restarted." -ForegroundColor Green }
    'status' {
        if (-not (Test-Engine)) { Write-Host "Docker is not running." -ForegroundColor Yellow; exit 0 }
        & docker compose ps
        $port = Get-Address
        try {
            $health = Invoke-RestMethod "http://127.0.0.1:$port/api/health" -TimeoutSec 5
            Write-Host "Responding: $($health.status)" -ForegroundColor Green
        } catch { Write-Host "Not responding yet." -ForegroundColor Yellow }
    }
    'logs' {
        Write-Host "Ctrl+C to stop watching. Reset links appear here when email is not set up." -ForegroundColor Cyan
        & docker compose logs -f --tail 60
    }
    'update' {
        if (-not (Start-Engine)) { exit 1 }
        & docker compose up -d --build
        Write-Host "Rebuilt and restarted." -ForegroundColor Green
    }
    'backup' {
        $stamp = Get-Date -Format 'yyyy-MM-dd-HHmm'
        $out = Join-Path $PSScriptRoot "backups"
        New-Item -ItemType Directory -Force -Path $out | Out-Null
        $file = Join-Path $out "shelfplan-$stamp.db"
        & docker compose cp shelfplan:/app/data/shelfplan.db $file
        Write-Host "Saved $file" -ForegroundColor Green
    }
    default {
        Write-Host @"
Shelf Plan

  .\shelfplan.ps1 start     start it (starts Docker first if needed)
  .\shelfplan.ps1 stop      stop it, keeping all data
  .\shelfplan.ps1 status    is it running?
  .\shelfplan.ps1 logs      watch the log, including password reset links
  .\shelfplan.ps1 update    rebuild after code changes
  .\shelfplan.ps1 backup    copy the database into .\backups\
"@
    }
}
