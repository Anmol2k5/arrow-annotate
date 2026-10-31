# Optional trusted Authenticode signing. Never fabricate a signing identity.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string[]]$Paths,
    [string]$TimestampServer = "https://timestamp.digicert.com"
)
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
if ($env:OS -ne "Windows_NT") { throw "Authenticode signing requires Windows." }
$HasPfx = -not [string]::IsNullOrWhiteSpace($env:ARROW_SIGN_PFX_BASE64)
$HasPassword = -not [string]::IsNullOrWhiteSpace($env:ARROW_SIGN_PFX_PASSWORD)
$HasIdentity = -not [string]::IsNullOrWhiteSpace($env:ARROW_SIGN_CERT_THUMBPRINT)
if (-not $HasPfx -and -not $HasPassword -and -not $HasIdentity) {
    Write-Host "No signing identity configured: producing explicitly unsigned artifacts."
    return
}
if (-not $HasPfx -or -not $HasPassword -or -not $HasIdentity) {
    throw "Signing configuration is incomplete. Supply PFX, password and expected certificate thumbprint, or leave all unset."
}
$ExpectedThumbprint = ($env:ARROW_SIGN_CERT_THUMBPRINT -replace '\s', '').ToUpperInvariant()
if ($ExpectedThumbprint -notmatch '^[A-F0-9]{40}$') { throw "Expected signing certificate thumbprint must be 40 hexadecimal characters." }
if (-not $TimestampServer.StartsWith("https://", [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "A HTTPS trusted timestamp server is required."
}
# Resolve the Windows SDK tool without placing the PFX password on a command line.
$SignTool = Get-Command signtool.exe -ErrorAction SilentlyContinue
if ($SignTool) {
    $SignToolPath = $SignTool.Source
} else {
    $SdkRoot = "${env:ProgramFiles(x86)}\Windows Kits\10\bin"
    $Candidates = @(Get-ChildItem "$SdkRoot\*\x64\signtool.exe" -ErrorAction SilentlyContinue | Sort-Object FullName -Descending)
    if ($Candidates.Count -eq 0) { throw "Install Windows SDK Signing Tools before configuring signing." }
    $SignToolPath = $Candidates[0].FullName
}
$CertificatePath = "Cert:\CurrentUser\My\$ExpectedThumbprint"
if (Test-Path $CertificatePath) {
    throw "The signing identity already exists in CurrentUser/My. Use a clean build account so imported credentials can be removed safely."
}
$TemporaryPfx = Join-Path ([System.IO.Path]::GetTempPath()) ("Arrow-signing-" + [guid]::NewGuid().ToString("N") + ".pfx")
$PfxCertificates = [System.Security.Cryptography.X509Certificates.X509Certificate2Collection]::new()
$CleanupCertificates = @()
$Password = $null
$PfxBytes = $null
try {
    $PfxBytes = [Convert]::FromBase64String($env:ARROW_SIGN_PFX_BASE64)
    # Preflight without persisting keys: reject a PFX with unexpected private
    # identities before importing anything into the build account's store.
    $PfxCertificates.Import($PfxBytes, $env:ARROW_SIGN_PFX_PASSWORD,
        [System.Security.Cryptography.X509Certificates.X509KeyStorageFlags]::EphemeralKeySet)
    $PrivateIdentities = @($PfxCertificates | Where-Object { $_.HasPrivateKey })
    if ($PrivateIdentities.Count -ne 1 -or $PrivateIdentities[0].Thumbprint -ne $ExpectedThumbprint) {
        throw "PFX must contain exactly the expected private signing identity."
    }
    foreach ($PfxCertificate in $PfxCertificates) {
        if (-not (Test-Path "Cert:\CurrentUser\My\$($PfxCertificate.Thumbprint)")) {
            $CleanupCertificates += $PfxCertificate.Thumbprint
        }
    }
    [System.IO.File]::WriteAllBytes($TemporaryPfx, $PfxBytes)
    $Password = ConvertTo-SecureString $env:ARROW_SIGN_PFX_PASSWORD -AsPlainText -Force
    Import-PfxCertificate -FilePath $TemporaryPfx -CertStoreLocation Cert:\CurrentUser\My -Password $Password | Out-Null
    $Certificate = Get-Item $CertificatePath -ErrorAction Stop
    if (-not $Certificate.HasPrivateKey) { throw "Configured certificate has no private key." }
    foreach ($Path in $Paths) {
        if (-not (Test-Path $Path -PathType Leaf)) { throw "A requested signing target is missing." }
        # signtool uses the imported private key; no password or PFX is in process arguments.
        & $SignToolPath sign /sha1 $ExpectedThumbprint /s My /fd SHA256 /tr $TimestampServer /td SHA256 $Path | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "Authenticode signing failed." }
        & $SignToolPath verify /pa /all /tw $Path | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "Authenticode trust verification failed." }
        $Signature = Get-AuthenticodeSignature $Path
        if ($Signature.Status -ne "Valid" -or $null -eq $Signature.SignerCertificate -or
            $Signature.SignerCertificate.Thumbprint -ne $ExpectedThumbprint -or $null -eq $Signature.TimeStamperCertificate) {
            throw "Signature must have a trusted chain, expected publisher identity and timestamp."
        }
    }
    Write-Host "Trusted Authenticode signatures and timestamps verified."
} catch {
    # Do not echo imported PFX data/passwords, tool diagnostics, or sensitive exception detail.
    throw "Trusted Windows signing failed. Check certificate identity, password, code-signing trust, SDK tools and timestamp connectivity."
} finally {
    if (Test-Path $TemporaryPfx) { Remove-Item $TemporaryPfx -Force }
    foreach ($Thumbprint in $CleanupCertificates) {
        $ImportedPath = "Cert:\CurrentUser\My\$Thumbprint"
        if ($Thumbprint -eq $ExpectedThumbprint) {
            Remove-Item $ImportedPath -DeleteKey -Force -ErrorAction SilentlyContinue
        } else {
            Remove-Item $ImportedPath -Force -ErrorAction SilentlyContinue
        }
    }
    foreach ($PfxCertificate in $PfxCertificates) { $PfxCertificate.Dispose() }
    if ($null -ne $Password) { $Password.Dispose() }
    if ($null -ne $PfxBytes) { [Array]::Clear($PfxBytes, 0, $PfxBytes.Length) }
}
