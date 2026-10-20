# Download a specific official Inno Setup build and verify Windows Authenticode.
[CmdletBinding()]
param()
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$Root = Split-Path -Parent $PSScriptRoot
$Tools = Join-Path $Root "build/windows/tools"
New-Item $Tools -ItemType Directory -Force | Out-Null
$Installer = Join-Path $Tools "innosetup-6.4.3.exe"
Invoke-WebRequest "https://github.com/jrsoftware/issrc/releases/download/is-6_4_3/innosetup-6.4.3.exe" -OutFile $Installer
$Signature = Get-AuthenticodeSignature $Installer
if ($Signature.Status -ne "Valid" -or $Signature.SignerCertificate.Subject -notmatch "CN=Pyrsys B\.V\.(,|$)") {
    throw "Inno Setup installer has an invalid or unexpected Authenticode signature."
}
$Destination = Join-Path $Tools "InnoSetup"
$Process = Start-Process $Installer -ArgumentList @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-", "/DIR=`"$Destination`"") -Wait -PassThru
if ($Process.ExitCode -ne 0) { throw "Inno Setup installation failed: $($Process.ExitCode)" }
$Compiler = Join-Path $Destination "ISCC.exe"
if (-not (Test-Path $Compiler)) { throw "Inno Setup compiler is missing" }
Write-Output $Compiler
