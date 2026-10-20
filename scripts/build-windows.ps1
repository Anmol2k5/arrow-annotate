[CmdletBinding()]
param(
    [string]$Python = "python",
    [string]$InnoCompiler = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
)
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
if ($env:OS -ne "Windows_NT") { throw "Build on Windows x64; PyInstaller cannot cross-compile." }
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Invoke-Checked {
    param([string]$Command, [string[]]$Arguments)
    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Command failed with exit code $LASTEXITCODE" }
}

if (-not (Test-Path $InnoCompiler)) { throw "Install Inno Setup 6.4.3 or supply -InnoCompiler." }
# Clear only known generated outputs so a failed/repeated build cannot upload old installers.
foreach ($Generated in @("dist/artifacts", "dist/smoke-reports", "dist/ArrowAnnotate")) {
    $GeneratedPath = Join-Path $Root $Generated
    if (Test-Path $GeneratedPath) { Remove-Item $GeneratedPath -Recurse -Force }
}
Invoke-Checked $Python @("-c", "import sys,struct; assert sys.version_info[:2] == (3,12), 'Use Python 3.12'; assert struct.calcsize('P') == 8, 'Use x64 Python'")
Invoke-Checked $Python @("-m", "venv", "build/windows/venv")
$BuildPython = Join-Path $Root "build/windows/venv/Scripts/python.exe"
$env:PYTHONNOUSERSITE = "1"
$env:QT_QPA_PLATFORM = "offscreen"
Invoke-Checked $BuildPython @("-m", "pip", "install", "--disable-pip-version-check", "-r", "packaging/requirements-build.txt", ".", "pytest")
$PreviousArrowHome = $env:ARROW_HOME
$PreviousArrowDbPath = $env:ARROW_DB_PATH
$TestHome = Join-Path ([System.IO.Path]::GetTempPath()) ("ArrowAnnotate-source-tests-" + [guid]::NewGuid().ToString("N"))
try {
    $env:ARROW_HOME = $TestHome
    Remove-Item Env:ARROW_DB_PATH -ErrorAction SilentlyContinue
    Invoke-Checked $BuildPython @("-m", "pytest", "-q")
} finally {
    $env:ARROW_HOME = $PreviousArrowHome
    $env:ARROW_DB_PATH = $PreviousArrowDbPath
    if (Test-Path $TestHome) { Remove-Item $TestHome -Recurse -Force }
}
$Version = & $BuildPython scripts/windows_build_metadata.py --version
if ($LASTEXITCODE -ne 0) { throw "Could not read project version" }
$Version = $Version.Trim()
if ($env:GITHUB_REF_TYPE -eq "tag" -and $env:GITHUB_REF_NAME -ne "v$Version") {
    throw "Tag $env:GITHUB_REF_NAME does not match project version v$Version"
}
$Resources = Join-Path $Root "build/windows/resources"
if (Test-Path $Resources) { Remove-Item $Resources -Recurse -Force }
Invoke-Checked $BuildPython @("scripts/windows_build_metadata.py", "--output", $Resources)
Invoke-Checked $BuildPython @("-m", "PyInstaller", "--clean", "--noconfirm", "--workpath", "build/windows/pyinstaller", "packaging/windows.spec")
$Bundle = Join-Path $Root "dist/ArrowAnnotate"
$Artifacts = Join-Path $Root "dist/artifacts"
New-Item $Artifacts -ItemType Directory -Force | Out-Null
# Record the exact dependency resolution for each build, alongside license provenance.
$Freeze = & $BuildPython -m pip freeze --all
if ($LASTEXITCODE -ne 0) { throw "pip freeze failed" }
$Freeze | Set-Content (Join-Path $Artifacts "build-requirements.txt") -Encoding utf8
Copy-Item (Join-Path $Resources "THIRD-PARTY-NOTICES/manifest.json") (Join-Path $Artifacts "third-party-manifest.json")
Invoke-Checked $InnoCompiler @("/DAppVersion=$Version", "/DSourceDir=$Bundle", "/DOutputDir=$Artifacts", "packaging/windows-installer.iss")
$Portable = Join-Path $Artifacts "Arrow-Annotate-Portable-$Version-x64.zip"
if (Test-Path $Portable) { Remove-Item $Portable -Force }
Compress-Archive -Path $Bundle -DestinationPath $Portable -CompressionLevel Optimal
$ReleaseFiles = @(
    (Join-Path $Artifacts "Arrow-Annotate-Setup-$Version-x64.exe"),
    $Portable
)
$Sums = foreach ($File in $ReleaseFiles) {
    $Hash = (Get-FileHash $File -Algorithm SHA256).Hash.ToLowerInvariant()
    "$Hash  $([System.IO.Path]::GetFileName($File))"
}
$Sums | Set-Content (Join-Path $Artifacts "SHA256SUMS.txt") -Encoding ascii
Write-Host "Built Arrow Annotate $Version in $Artifacts"
