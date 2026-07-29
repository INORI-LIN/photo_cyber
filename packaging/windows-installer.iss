#define MyAppName "Photo Guard"
#define MyAppVersion "0.1.0"
#define MyAppExeName "PhotoGuard.exe"

[Setup]
AppId={{A0DAED64-1B78-4B63-88CF-94604E7C9CE1}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
DefaultDirName={autopf}\Photo Guard
DefaultGroupName=Photo Guard
OutputDir=..\release
OutputBaseFilename=PhotoGuard-Windows-x64-Setup
Compression=lzma2/ultra64
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern

[Files]
Source: "..\dist\desktop_entry.dist\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Photo Guard"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\Photo Guard"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch Photo Guard"; Flags: nowait postinstall skipifsilent
