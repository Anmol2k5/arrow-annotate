[CmdletBinding()]
param(
    [string]$Executable = (Join-Path $env:LOCALAPPDATA "Programs\ArrowAnnotate\ArrowMCP.exe"),
    [string]$ReportPath = (Join-Path (Get-Location) "arrow-windows-diagnostics.json"),
    [switch]$Interactive
)
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    throw "Run this harness on the target Windows desktop. Linux CI cannot validate Windows hardware."
}
if ($env:QT_QPA_PLATFORM -in @("offscreen", "minimal")) {
    throw "Remove QT_QPA_PLATFORM for this interactive desktop test; offscreen tests cannot validate real monitors."
}
if (-not (Test-Path -LiteralPath $Executable -PathType Leaf)) {
    throw "ArrowMCP.exe was not found. Pass -Executable with the installed or portable console executable."
}
if ([System.IO.Path]::GetFileName($Executable) -ne "ArrowMCP.exe") {
    throw "Use the console ArrowMCP.exe executable; ArrowAnnotate.exe has no interactive stdin."
}

$Arguments = @("--diagnostics", $ReportPath)
if ($Interactive) { $Arguments += "--interactive" }
Write-Host "Collecting read-only device and client status. No audio is recorded and no agent task is submitted."
if ($Interactive) {
    Write-Host "Use docs/windows-interactive-testing.md. Perform each real test before entering p, f or n."
}
& $Executable @Arguments
$ResultCode = $LASTEXITCODE
if (-not (Test-Path -LiteralPath $ReportPath -PathType Leaf)) {
    throw "The diagnostic command did not produce a report (exit $ResultCode)."
}
$Report = Get-Content -LiteralPath $ReportPath -Raw | ConvertFrom-Json
Write-Host "Overall: $($Report.overall). Exit zero can still mean manual tests are pending."
$Report.checks.PSObject.Properties | ForEach-Object {
    [pscustomobject]@{ Check = $_.Name; Status = $_.Value.status; Evidence = $_.Value.evidence }
} | Format-Table -AutoSize
exit $ResultCode
