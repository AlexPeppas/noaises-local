; Inno Setup script for noaises — local-first AI companion
; Wraps the PyInstaller dist/noaises/ directory into a Windows installer.
;
; Build:
;   1. Run PyInstaller first:  uv run python packaging/build.py
;   2. Then compile this:      iscc packaging/windows/noaises.iss

#define MyAppName "noaises"
#define MyAppVersion "0.1.0"
#define MyAppPublisher "noaises"
#define MyAppExeName "noaises.exe"

[Setup]
AppId={{B8A2F1E3-5C4D-4E6F-9A8B-7C1D2E3F4A5B}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\..\dist\installer
OutputBaseFilename=noaises-{#MyAppVersion}-setup
Compression=lzma
SolidCompression=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
SetupIconFile=..\icons\noaises.ico
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Bundle the entire PyInstaller output directory
Source: "..\..\dist\noaises\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
