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
$ModelCache = Join-Path $Root "build/windows/voice-model-home"
$SpeechWav = Join-Path $Temporary "synthetic-english.wav"
$BuildPython = Join-Path $Root "build/windows/venv/Scripts/python.exe"
$env:ARROW_HOME = $DataDir
Remove-Item Env:ARROW_DB_PATH -ErrorAction SilentlyContinue
$env:QT_QPA_PLATFORM = "offscreen"

function Invoke-Process {
    param([string]$File, [string[]]$Arguments)
    $Process = Start-Process $File -ArgumentList $Arguments -Wait -PassThru
    if ($Process.ExitCode -ne 0) { throw "$File failed with exit code $($Process.ExitCode)" }
}

function Write-SpeechFailure {
    param([string]$Report)
    if (Test-Path $Report) {
        $Details = (Get-Content $Report -Raw).Replace('%', '%25').Replace("`r", '%0D').Replace("`n", '%0A')
        # This report contains only the synthetic test instruction and runtime
        # errors, never a user's microphone recording or provider credentials.
        Write-Host "::error title=Offline synthetic speech validation::$Details"
    }
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
    $SpeechReport = Join-Path $Reports "$Label-offline-speech.json"
    try {
        Invoke-Process (Join-Path $Bundle "ArrowMCP.exe") @("--speech-smoke", "`"$SpeechWav`"", "`"$SpeechReport`"")
    } catch {
        Write-SpeechFailure $SpeechReport
        throw
    }
    $SpeechResult = Get-Content $SpeechReport -Raw | ConvertFrom-Json
    if (-not $SpeechResult.success) { throw "Frozen offline speech validation failed: $SpeechReport" }
}

try {
    # This explicit CI setup downloads public weights only. Inference runs with
    # network access disabled in fresh source/frozen smoke subprocesses.
    & (Join-Path $env:SystemRoot "System32/WindowsPowerShell/v1.0/powershell.exe") `
        -NoProfile -NonInteractive -File (Join-Path $Root "scripts/create-speech-fixture.ps1") -OutputPath $SpeechWav
    if ($LASTEXITCODE -ne 0) { throw "Windows synthetic speech fixture creation failed" }
    try {
        $env:ARROW_HOME = $ModelCache
        $ModelSetupCode = @'
from arrow.speech.offline import install_voice_model
try:
    install_voice_model()
except Exception as error:
    detail = f'{type(error).__name__}: {error}; cause: {error.__cause__}'
    print('::error title=Explicit offline test model setup::' + detail.replace('%', '%25').replace('\r', '%0D').replace('\n', '%0A'))
    raise SystemExit(1)
'@
        & $BuildPython -c $ModelSetupCode
        if ($LASTEXITCODE -ne 0) { throw "Explicit CI voice model setup failed" }
    } finally {
        $env:ARROW_HOME = $DataDir
    }
    Copy-Item (Join-Path $ModelCache "models") (Join-Path $DataDir "models") -Recurse -Force
    & $BuildPython (Join-Path $Root "main.py") --speech-smoke $SpeechWav (Join-Path $Reports "source-offline-speech.json")
    if ($LASTEXITCODE -ne 0) {
        Write-SpeechFailure (Join-Path $Reports "source-offline-speech.json")
        throw "Source offline speech validation failed"
    }
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
