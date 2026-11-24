# SIMPL Agent compile task. Installed to C:\Program Files\SimplAgent\ (admin-only) and run by
# the "SIMPL Agent\Compile" scheduled task with highest privileges, because SIMPL Windows
# runs as administrator and smpc has to drive it.
#
# It does exactly one thing: compile one .smw under an allowed folder (config.json, admin-only)
# with smpc.exe, and write the result. The request comes from a user-writable file, so every
# field is validated here.
$ErrorActionPreference = 'Stop'
$base = Join-Path $env:LOCALAPPDATA 'SimplAgent\compile'
$requestPath = Join-Path $base 'request.json'
$resultPath = Join-Path $base 'result.json'
$id = $null

function Write-Result($obj) {
    $tmp = "$resultPath.tmp"
    $obj | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $tmp -Encoding utf8
    Move-Item -LiteralPath $tmp -Destination $resultPath -Force
}

try {
    $config = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'config.json') -Raw | ConvertFrom-Json
    $request = Get-Content -LiteralPath $requestPath -Raw | ConvertFrom-Json
    $id = [string]$request.id
    if ($id -notmatch '^[A-Za-z0-9-]{8,64}$') { throw 'bad request id' }
    $path = [System.IO.Path]::GetFullPath([string]$request.path)
    if (-not $path.EndsWith('.smw', [StringComparison]::OrdinalIgnoreCase)) { throw 'only .smw files can be compiled' }
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "no such file: $path" }
    $item = Get-Item -LiteralPath $path
    # OneDrive marks synced files as reparse points too, so check the link type, not the attribute.
    if ($item.LinkType) { throw "links are not allowed ($($item.LinkType))" }
    $allowed = $false
    foreach ($root in $config.allowed_roots) {
        $prefix = [System.IO.Path]::GetFullPath([string]$root).TrimEnd('\') + '\'
        if ($path.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) { $allowed = $true }
    }
    if (-not $allowed) { throw "not under an allowed folder: $($config.allowed_roots -join '; ')" }
    $timeout = [int]$config.timeout_minutes
    if ($timeout -lt 1 -or $timeout -gt 60) { $timeout = 20 }

    Write-Result @{ id = $id; state = 'running'; path = $path; started = (Get-Date).ToString('o') }
    # Run smpc with .NET directly: in Windows PowerShell, a native program writing to stderr
    # under ErrorActionPreference=Stop would be treated as a crash. The path was validated above
    # and can't contain quotes (Windows file names can't).
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = Join-Path $PSScriptRoot 'smpc.exe'
    $psi.Arguments = "--compile-timeout $($timeout)m `"$path`""
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.CreateNoWindow = $true
    $proc = [System.Diagnostics.Process]::Start($psi)
    $stdout = $proc.StandardOutput.ReadToEndAsync()
    $stderr = $proc.StandardError.ReadToEndAsync()
    $proc.WaitForExit()
    $output = $stdout.Result + "`n" + $stderr.Result
    Write-Result @{ id = $id; state = 'done'; path = $path; exit_code = $proc.ExitCode; output = $output;
                    finished = (Get-Date).ToString('o') }
}
catch {
    Write-Result @{ id = $id; state = 'refused'; error = $_.Exception.Message }
}
