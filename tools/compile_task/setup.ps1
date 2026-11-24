# One-time setup for SIMPL Agent's compile task. Run elevated (one UAC prompt).
#
#   powershell -ExecutionPolicy Bypass -File setup.ps1 -SmpcExe <verified smpc.exe> -AllowedRoots <folder>,<folder> -User <DOMAIN\user>
#
# Installs smpc.exe, compile.ps1 and config.json into C:\Program Files\SimplAgent (admin-only,
# so nothing unelevated can change what the task runs), then registers the on-demand task
# "\SIMPL Agent\Compile": runs as the user, interactive (smpc needs the desktop), highest
# privileges, one instance at a time, stopped after 65 minutes.
param(
    [Parameter(Mandatory)] [string] $SmpcExe,
    [Parameter(Mandatory)] [string[]] $AllowedRoots,
    [Parameter(Mandatory)] [string] $User,
    [int] $TimeoutMinutes = 20
)
$ErrorActionPreference = 'Stop'
$dest = Join-Path $env:ProgramFiles 'SimplAgent'
New-Item -ItemType Directory -Force -Path $dest | Out-Null
Copy-Item -LiteralPath $SmpcExe -Destination (Join-Path $dest 'smpc.exe') -Force
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'compile.ps1') -Destination (Join-Path $dest 'compile.ps1') -Force
@{ allowed_roots = $AllowedRoots; timeout_minutes = $TimeoutMinutes } | ConvertTo-Json |
    Set-Content -LiteralPath (Join-Path $dest 'config.json') -Encoding utf8

$action = New-ScheduledTaskAction -Execute 'powershell.exe' `
    -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$dest\compile.ps1`""
$principal = New-ScheduledTaskPrincipal -UserId $User -LogonType Interactive -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 65) -StartWhenAvailable
Register-ScheduledTask -TaskPath '\SIMPL Agent\' -TaskName 'Compile' -Action $action -Principal $principal `
    -Settings $settings -Force | Out-Null
"installed to $dest and registered \SIMPL Agent\Compile for $User"
