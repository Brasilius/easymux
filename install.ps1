# Install a Windows PATH launcher backed by one WSL distribution.
[CmdletBinding()]
param(
    [string]$Distro,
    [switch]$InstallDeps
)
$ErrorActionPreference = 'Stop'

if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
    throw 'WSL is required. Run "wsl --install" from an administrator PowerShell, restart if prompted, finish Linux user setup, then rerun this installer.'
}

$wslArgs = @()
if ($Distro) { $wslArgs = @('--distribution', $Distro) }
# Pin the current default distribution so later default changes do not lose sessions.
$probe = & wsl.exe @wslArgs --exec printenv WSL_DISTRO_NAME
if ($LASTEXITCODE -ne 0 -or -not $probe) {
    throw 'No ready WSL distribution. Run "wsl --install", finish Linux user setup, then rerun. Use -Distro NAME to select an installed distribution.'
}
$Distro = ($probe -join '').Trim()
# Distribution names become a literal argument in a .cmd launcher.
if ($Distro -notmatch '^[A-Za-z0-9_. -]+$') {
    throw 'Unsupported distribution name. Use a WSL distribution name containing letters, digits, spaces, dots, underscores, or hyphens.'
}
$wslArgs = @('--distribution', $Distro)
$linuxSource = & wsl.exe @wslArgs --exec wslpath -a -u $PSScriptRoot
if ($LASTEXITCODE -ne 0) { throw 'Cannot access the checkout from WSL.' }
$linuxSource = ($linuxSource -join '').Trim()
$installArgs = @('--exec', 'bash', "$linuxSource/install.sh")
if ($InstallDeps) { $installArgs += '--install-deps' }
& wsl.exe @wslArgs @installArgs
if ($LASTEXITCODE -ne 0) { throw 'Linux installation failed. Resolve the error above, then rerun.' }

$binDir = Join-Path $env:LOCALAPPDATA 'EasyMux\bin'
New-Item -ItemType Directory -Force -Path $binDir | Out-Null
$linuxHome = & wsl.exe @wslArgs --exec printenv HOME
if ($LASTEXITCODE -ne 0 -or -not $linuxHome) { throw 'Cannot determine the WSL home directory.' }
$linuxLauncher = ($linuxHome -join '').TrimEnd('/') + '/.local/bin/easymux-wsl'
if ($linuxLauncher -match '[%"\r\n]') { throw 'Unsupported characters in the WSL home directory.' }
$launcher = @"
@echo off
wsl.exe --distribution "$Distro" --exec "$linuxLauncher" %*
exit /b %errorlevel%
"@
Set-Content -LiteralPath (Join-Path $binDir 'easymux.cmd') -Value $launcher -Encoding Ascii

$userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
if (($userPath -split ';') -notcontains $binDir) {
    $newPath = if ([string]::IsNullOrEmpty($userPath)) { $binDir } else { "$($userPath.TrimEnd(';'));$binDir" }
    [Environment]::SetEnvironmentVariable('Path', $newPath, 'User')
}
if (($env:Path -split ';') -notcontains $binDir) { $env:Path = "$binDir;$env:Path" }
Write-Host "Installed $binDir\easymux.cmd (WSL: $Distro)."
Write-Host 'Run easymux in this PowerShell or a newly opened terminal.'
Write-Host 'Claude and Codex must be installed and signed in inside the selected WSL distribution.'
