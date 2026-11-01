#requires -Version 5.1
<#
.SYNOPSIS
Create the opt-in speech smoke fixture using an installed Windows English voice.
Run with Windows PowerShell 5.1 (powershell.exe), which provides System.Speech.
No voice, model, or audio is downloaded.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$OutputPath
)

$ErrorActionPreference = 'Stop'
$synthesizer = $null
try {
    Add-Type -AssemblyName System.Speech
    $synthesizer = New-Object System.Speech.Synthesis.SpeechSynthesizer
    $voice = $synthesizer.GetInstalledVoices() |
        Where-Object { $_.Enabled -and $_.VoiceInfo.Culture.TwoLetterISOLanguageName -eq 'en' } |
        Sort-Object { if ($_.VoiceInfo.Culture.Name -eq 'en-US') { 0 } else { 1 } } |
        Select-Object -First 1
    if ($null -eq $voice) {
        throw 'No enabled English Windows speech voice is installed. Install an English voice before running this check.'
    }
    $destination = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($OutputPath)
    $parent = [System.IO.Path]::GetDirectoryName($destination)
    [System.IO.Directory]::CreateDirectory($parent) | Out-Null
    $synthesizer.SelectVoice($voice.VoiceInfo.Name)
    $synthesizer.Rate = 0
    $synthesizer.Volume = 100
    $format = New-Object -TypeName System.Speech.AudioFormat.SpeechAudioFormatInfo -ArgumentList @(
        16000,
        [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen,
        [System.Speech.AudioFormat.AudioChannel]::Mono
    )
    $synthesizer.SetOutputToWaveFile($destination, $format)
    $synthesizer.Speak('Move the blue button below the heading and keep sixteen pixels of spacing.')
    $synthesizer.SetOutputToNull()
    if (-not [System.IO.File]::Exists($destination) -or (Get-Item -LiteralPath $destination).Length -le 44) {
        throw 'Windows speech synthesis did not produce a nonempty PCM WAV.'
    }
    Write-Output ('Synthetic English WAV created with {0}: {1}' -f $voice.VoiceInfo.Name, $destination)
} finally {
    if ($null -ne $synthesizer) {
        $synthesizer.Dispose()
    }
}
