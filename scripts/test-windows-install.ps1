[CmdletBinding()]
param()
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$Reports = Join-Path $Root "dist/smoke-reports"
New-Item $Reports -ItemType Directory -Force | Out-Null
$Temporary = Join-Path ([System.IO.Path]::GetTempPath()) ("ArrowAnnotate-test-" + [guid]::NewGuid().ToString("N"))
$InstallDir = Join-Path $Temporary "Installed Application"
$DataDir = Join-Path $Temporary "User Data"
New-Item $DataDir -ItemType Directory -Force | Out-Null
$PreviousArrowHome = $env:ARROW_HOME
$PreviousArrowDbPath = $env:ARROW_DB_PATH
$env:ARROW_HOME = $DataDir
Remove-Item Env:ARROW_DB_PATH -ErrorAction SilentlyContinue
$env:QT_QPA_PLATFORM = "offscreen"

function Invoke-Process {
    param([string]$File, [string[]]$Arguments)
    $Process = Start-Process $File -ArgumentList $Arguments -Wait -PassThru
    if ($Process.ExitCode -ne 0) { throw "$File failed with exit code $($Process.ExitCode)" }
}

function Test-FrozenApp {
    param([string]$Bundle, [string]$Label)
    foreach ($Exe in @("ArrowAnnotate.exe", "ArrowMCP.exe")) {
        $Report = Join-Path $Reports "$Label-$Exe.json"
        if (Test-Path $Report) { Remove-Item $Report -Force }
        Invoke-Process (Join-Path $Bundle $Exe) @("--smoke-test", "`"$Report`"")
        if (-not (Test-Path $Report)) { throw "$Exe did not write a smoke report" }
        $Result = Get-Content $Report -Raw | ConvertFrom-Json
        if (-not $Result.success) { throw "$Exe smoke report indicates failure: $Report" }
    }
    $Version = & (Join-Path $Bundle "ArrowMCP.exe") --version
    if ($LASTEXITCODE -ne 0 -or -not $Version) { throw "Frozen --version failed" }
    & (Join-Path $Root "build/windows/venv/Scripts/python.exe") `
        (Join-Path $Root "scripts/windows_mcp_smoke.py") `
        (Join-Path $Bundle "ArrowMCP.exe") (Join-Path $Reports "$Label-mcp-protocol.json")
    if ($LASTEXITCODE -ne 0) { throw "Frozen MCP stdio protocol smoke failed" }
}

try {
    # A different cwd proves resource and data paths do not depend on the source checkout.
    Set-Location $Temporary
    Test-FrozenApp (Join-Path $Root "dist/ArrowAnnotate") "portable"
    $Setups = @(Get-ChildItem (Join-Path $Root "dist/artifacts/Arrow-Annotate-Setup-*-x64.exe"))
    if ($Setups.Count -ne 1) { throw "Expected exactly one installer, found $($Setups.Count)" }
    Invoke-Process $Setups[0].FullName @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-", "/DIR=`"$InstallDir`"", "/LOG=`"$(Join-Path $Reports 'install.log')`"")
    Test-FrozenApp $InstallDir "installed"
    $Sentinel = Join-Path $DataDir "uninstall-preserves-data.txt"
    Set-Content $Sentinel "User data must survive uninstall" -Encoding utf8
    Invoke-Process (Join-Path $InstallDir "unins000.exe") @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/LOG=`"$(Join-Path $Reports 'uninstall.log')`"")
    if (-not (Test-Path $Sentinel)) { throw "Uninstall removed user data" }
    if (Test-Path (Join-Path $InstallDir "ArrowAnnotate.exe")) { throw "Uninstall left the application executable" }
} finally {
    Set-Location $Root
    $env:ARROW_HOME = $PreviousArrowHome
    $env:ARROW_DB_PATH = $PreviousArrowDbPath
    # Keep reports for CI; remove only this script's isolated temporary tree.
    if (Test-Path $Temporary) { Remove-Item $Temporary -Recurse -Force }
}
