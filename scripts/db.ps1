<#
.SYNOPSIS
  Manage the local PostgreSQL 16 Windows service used by ShopSync, and take backups.

.DESCRIPTION
  status   (default) Service state plus a pg_isready connection check.
  start    Start the service      (needs an elevated "Run as administrator" PowerShell).
  stop     Stop the service       (needs an elevated PowerShell).
  restart  Restart the service    (needs an elevated PowerShell).
  backup   pg_dump (custom format) of the database in DATABASE_URL into a new, timestamped
           file under %USERPROFILE%\ShopSync-backups. Never overwrites an existing file.

  The service starts automatically with Windows, so start/stop/restart are rarely needed.
  Only the service "postgresql-x64-16" is ever managed; an older per-user PostgreSQL copy
  (under AppData) is never started or stopped by this script.

.EXAMPLE
  .\scripts\db.ps1
  .\scripts\db.ps1 backup

  Overrides: $env:PG_BIN (PostgreSQL bin folder), $env:SHOPSYNC_BACKUP_DIR (backup folder).
  DATABASE_URL is read from the environment, else from the repository's .env file.
#>
param([ValidateSet("status", "start", "stop", "restart", "backup")][string]$Action = "status")

Set-StrictMode -Version 3

$ServiceName = "postgresql-x64-16"  # fixed on purpose: never the old per-user installation
$PgBin = if ($env:PG_BIN) { $env:PG_BIN } else { "C:\Program Files\PostgreSQL\16\bin" }
$RepoRoot = Split-Path -Parent $PSScriptRoot

function Get-PgService {
  $svc = Get-CimInstance Win32_Service -Filter "Name='$ServiceName'" -ErrorAction SilentlyContinue
  if (-not $svc) { throw "Windows service '$ServiceName' not found. Install PostgreSQL 16 (see README)." }
  # Defence in depth: refuse to manage a service that runs a per-user (AppData) copy of PostgreSQL.
  if ($svc.PathName -like "*\AppData\*") { throw "Service '$ServiceName' runs from a per-user folder; refusing to manage it." }
  return $svc
}

function Assert-Administrator {
  $principal = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
  if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "'$Action' needs an elevated PowerShell (right-click > Run as administrator)."
  }
}

function Show-Status {
  $null = Get-PgService
  $svc = Get-Service -Name $ServiceName
  Write-Host ("Service {0}: {1} (startup: {2})" -f $ServiceName, $svc.Status, $svc.StartType)
  $isReady = Join-Path $PgBin "pg_isready.exe"
  if (-not (Test-Path -LiteralPath $isReady)) {
    Write-Warning "pg_isready not found in $PgBin (set `$env:PG_BIN)."
    return 1
  }
  & $isReady -h localhost -p 5432 | Out-Host  # Out-Host: keep its text out of the return value
  return $LASTEXITCODE
}

function Get-DatabaseUrl {
  if ($env:DATABASE_URL) { return $env:DATABASE_URL }
  $envFile = Join-Path $RepoRoot ".env"
  if (Test-Path -LiteralPath $envFile) {
    foreach ($line in Get-Content -LiteralPath $envFile) {
      if ($line -match '^\s*DATABASE_URL\s*=\s*(.*?)\s*$') {
        $value = $Matches[1]
        if ($value.Length -ge 2 -and (($value[0] -eq '"' -and $value[-1] -eq '"') -or ($value[0] -eq "'" -and $value[-1] -eq "'"))) {
          $value = $value.Substring(1, $value.Length - 2)
        }
        return $value
      }
    }
  }
  throw "DATABASE_URL is not set (environment or .env)."
}

function ConvertFrom-DatabaseUrl([string]$Url) {
  # postgresql[+driver]://user:password@host[:port]/database[?options]
  # User and password may be percent-encoded (decoded like SQLAlchemy: %xx only, '+' stays '+').
  # The URL itself is never printed, because it contains the password.
  $pattern = '^postgres(?:ql)?(?:\+[A-Za-z0-9_]+)?://(?<userinfo>.*)@(?<hostport>[^@/?#]+)/(?<db>[^/?#]+)'
  if ($Url -notmatch $pattern) { throw "DATABASE_URL is not a postgresql:// URL with user, host and database." }
  $userInfo, $hostPort, $db = $Matches['userinfo'], $Matches['hostport'], $Matches['db']

  $sep = $userInfo.IndexOf(':')
  if ($sep -lt 0) { $user, $password = $userInfo, "" }
  else { $user, $password = $userInfo.Substring(0, $sep), $userInfo.Substring($sep + 1) }

  if ($hostPort -match '^\[(?<h>[^\]]+)\](?::(?<p>\d+))?$' -or $hostPort -match '^(?<h>[^:]+)(?::(?<p>\d+))?$') {
    $dbHost = $Matches['h']
    $port = if ($Matches.ContainsKey('p') -and $Matches['p']) { [int]$Matches['p'] } else { 5432 }
  } else { throw "DATABASE_URL has an invalid host/port." }

  return [pscustomobject]@{
    User     = [Uri]::UnescapeDataString($user)
    Password = [Uri]::UnescapeDataString($password)
    Host     = $dbHost
    Port     = $port
    Database = [Uri]::UnescapeDataString($db)
  }
}

function Invoke-Backup {
  $pgDump = Join-Path $PgBin "pg_dump.exe"
  $pgRestore = Join-Path $PgBin "pg_restore.exe"
  foreach ($tool in $pgDump, $pgRestore) {
    if (-not (Test-Path -LiteralPath $tool)) { throw "$tool not found (set `$env:PG_BIN)." }
  }

  $conn = ConvertFrom-DatabaseUrl (Get-DatabaseUrl)
  $dir = if ($env:SHOPSYNC_BACKUP_DIR) { $env:SHOPSYNC_BACKUP_DIR } else { Join-Path $env:USERPROFILE "ShopSync-backups" }
  New-Item -ItemType Directory -Force -Path $dir | Out-Null
  $safeDb = $conn.Database -replace '[^A-Za-z0-9_-]', '_'
  $target = Join-Path $dir ("{0}_{1}.dump" -f $safeDb, (Get-Date -Format "yyyyMMdd_HHmmss"))
  if (Test-Path -LiteralPath $target) { throw "Refusing to overwrite existing backup: $target" }

  Write-Host ("Backing up database '{0}' on {1}:{2} as '{3}'..." -f $conn.Database, $conn.Host, $conn.Port, $conn.User)
  $env:PGPASSWORD = $conn.Password  # process-scoped; removed below; never printed
  try {
    $dumpOutput = & $pgDump -h $conn.Host -p $conn.Port -U $conn.User -d $conn.Database `
      --format=custom --no-owner --no-password --file $target 2>&1 | ForEach-Object { "$_" }
    $dumpExit = $LASTEXITCODE
  } finally {
    Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
  }

  if ($dumpExit -ne 0) {
    $detail = ($dumpOutput | Select-Object -First 5) -join " "
    if (Test-Path -LiteralPath $target) { $detail += " (incomplete file left at $target)" }
    throw "pg_dump failed (exit $dumpExit): $detail"
  }
  if (-not (Test-Path -LiteralPath $target)) { throw "pg_dump reported success but $target was not created." }
  $size = (Get-Item -LiteralPath $target).Length
  if ($size -le 0) { throw "Backup file $target is empty." }

  # Verify the archive is readable (lists its contents; restores nothing).
  $toc = & $pgRestore --list $target 2>&1 | ForEach-Object { "$_" }
  if ($LASTEXITCODE -ne 0) { throw "pg_restore --list could not read $target (exit $LASTEXITCODE)." }
  $tables = @($toc | Where-Object { $_ -match ' TABLE DATA ' }).Count

  Write-Host ("Backup OK: {0} ({1:N0} bytes, {2} tables with data)" -f $target, $size, $tables)
  return 0
}

try {
  switch ($Action) {
    "status"  { $code = Show-Status }
    "start"   { Assert-Administrator; $null = Get-PgService; Start-Service -Name $ServiceName -ErrorAction Stop; $code = Show-Status }
    "stop"    { Assert-Administrator; $null = Get-PgService; Stop-Service -Name $ServiceName -ErrorAction Stop; $null = Show-Status; $code = 0 }
    "restart" { Assert-Administrator; $null = Get-PgService; Restart-Service -Name $ServiceName -ErrorAction Stop; $code = Show-Status }
    "backup"  { $code = Invoke-Backup }
  }
  exit $code
} catch {
  Write-Host ("ERROR: " + $_.Exception.Message) -ForegroundColor Red
  exit 1
}
