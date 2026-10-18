<#
.SYNOPSIS
  Start / stop / check the local PostgreSQL 16 server used for development.

.EXAMPLE
  .\scripts\db.ps1 start
  .\scripts\db.ps1 status
  .\scripts\db.ps1 stop

  Override locations with $env:PG_BIN / $env:PG_DATA if your install lives elsewhere.
#>
param([ValidateSet("start", "stop", "status", "restart")][string]$Action = "status")

$bin  = if ($env:PG_BIN)  { $env:PG_BIN }  else { Join-Path $env:LOCALAPPDATA "Programs\PostgreSQL\16\bin" }
$data = if ($env:PG_DATA) { $env:PG_DATA } else { Join-Path $env:LOCALAPPDATA "PostgreSQL\16\data" }
$log  = Join-Path (Split-Path $data) "server.log"
$pgCtl = Join-Path $bin "pg_ctl.exe"

if (-not (Test-Path $pgCtl)) { Write-Error "pg_ctl not found at $pgCtl (set `$env:PG_BIN)"; exit 1 }
if (-not (Test-Path (Join-Path $data "PG_VERSION"))) { Write-Error "No cluster at $data (set `$env:PG_DATA)"; exit 1 }

# Start the server detached: if postgres inherits this console's handles, the caller
# (and anything piping its output) would hang until the server exits.
function Invoke-Detached([string[]]$PgArgs) {
  # Not -Wait: in Windows PowerShell that also waits for child processes (the server itself).
  $p = Start-Process -FilePath $pgCtl -ArgumentList $PgArgs -WindowStyle Hidden -PassThru
  $p.WaitForExit()
  return $p.ExitCode
}

switch ($Action) {
  "start"   { $code = Invoke-Detached @("-D", "`"$data`"", "-l", "`"$log`"", "-w", "start") }
  "restart" { $code = Invoke-Detached @("-D", "`"$data`"", "-l", "`"$log`"", "-m", "fast", "-w", "restart") }
  "stop"    { & $pgCtl -D $data -m fast -w stop; $code = $LASTEXITCODE }
  "status"  { & $pgCtl -D $data status; $code = $LASTEXITCODE }
}
if ($Action -in "start", "restart") {
  if ($code -eq 0) { Write-Host "PostgreSQL is running (log: $log)" } else { Write-Error "pg_ctl failed (exit $code); see $log" }
}
exit $code
