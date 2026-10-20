; Compile with /DAppVersion=<pyproject version> /DSourceDir=<absolute bundle> /DOutputDir=<absolute artifacts>
#ifndef AppVersion
  #error AppVersion must come from pyproject.toml
#endif
#ifndef SourceDir
  #error SourceDir must name the frozen bundle
#endif
#ifndef OutputDir
  #define OutputDir "..\dist\artifacts"
#endif

[Setup]
AppId={{B7568862-50CB-49A5-BC77-B663D4AF2091}
AppName=Arrow Annotate
AppVersion={#AppVersion}
AppVerName=Arrow Annotate {#AppVersion}
DefaultDirName={localappdata}\Programs\ArrowAnnotate
DefaultGroupName=Arrow Annotate
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
OutputDir={#OutputDir}
OutputBaseFilename=Arrow-Annotate-Setup-{#AppVersion}-x64
SetupIconFile=..\arrow\ui\assets\arrow.ico
UninstallDisplayIcon={app}\ArrowAnnotate.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
; Restart Manager checks full paths of installed executables; never kill by process name.
CloseApplicationsFilter=ArrowAnnotate.exe,ArrowMCP.exe
SetupLogging=yes

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Arrow Annotate"; Filename: "{app}\ArrowAnnotate.exe"; WorkingDir: "{app}"
Name: "{group}\Uninstall Arrow Annotate"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Arrow Annotate"; Filename: "{app}\ArrowAnnotate.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\ArrowAnnotate.exe"; Description: "Launch Arrow Annotate"; Flags: nowait postinstall skipifsilent

; No [UninstallDelete]: settings, captures and databases in the user's ~/.arrow survive uninstall.
