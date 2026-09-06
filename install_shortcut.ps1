<#!
.SYNOPSIS
    Set up Personal Tracker and place a click-to-open shortcut on the desktop.

This script is intentionally user-scoped: it does not need administrator rights.
#>

[CmdletBinding()]
param(
    [string]$VaultPath
)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $MyInvocation.MyCommand.Path

function Find-CommandPath([string[]]$Names) {
    foreach ($name in $Names) {
        $command = Get-Command $name -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($command -and $command.Source) {
            return $command.Source
        }
    }
    return $null
}

$python = Find-CommandPath @('python.exe', 'py.exe', 'python')
if (-not $python) {
    throw 'Python was not found. Install Python 3 and make sure it is available on PATH.'
}

$pythonw = Find-CommandPath @('pythonw.exe', 'pyw.exe', 'pythonw')
if (-not $pythonw) {
    # Standard Python installs ship pythonw.exe beside python.exe.
    $candidate = Join-Path (Split-Path -Parent $python) 'pythonw.exe'
    if (Test-Path $candidate) { $pythonw = $candidate }
}
if (-not $pythonw) {
    throw 'pythonw.exe was not found. Reinstall Python with the standard Windows installation options.'
}

if (-not $VaultPath) { $VaultPath = $env:VAULT_PATH }
if (-not $VaultPath) {
    $VaultPath = Read-Host 'Enter the full path to your Obsidian vault'
}
$VaultPath = [Environment]::ExpandEnvironmentVariables($VaultPath.Trim().Trim('"'))
if (-not $VaultPath) { throw 'A vault path is required.' }
$VaultPath = [IO.Path]::GetFullPath($VaultPath)

if (-not (Test-Path $VaultPath -PathType Container)) {
    New-Item -ItemType Directory -Path $VaultPath -Force | Out-Null
}

Write-Host 'Preparing the vault...'
# Explorer-launched apps do not load a PowerShell profile, so setup persists
# VAULT_PATH for the Windows user. `t setup` owns that write; this script does
# not repeat it.
& $python (Join-Path $repo 'tracker.py') setup $VaultPath --persist-env
if ($LASTEXITCODE -ne 0) { throw 'Vault setup failed.' }

$env:VAULT_PATH = $VaultPath

$desktop = [Environment]::GetFolderPath('Desktop')
$shortcutPath = Join-Path $desktop 'Personal Tracker.lnk'
$quickadd = Join-Path $repo 'quickadd.py'
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $pythonw
$shortcut.Arguments = '"' + $quickadd + '"'
$shortcut.WorkingDirectory = $repo
$shortcut.Description = 'Open Personal Tracker'
$shortcut.IconLocation = "$env:SystemRoot\System32\SHELL32.dll,13"
$shortcut.Save()

Write-Host ""
Write-Host "Done. Double-click '$shortcutPath' to open Personal Tracker."
Write-Host 'The shortcut uses the saved vault path:' $VaultPath
