#define MyAppName "Photo Guard"
#define MyAppExeName "PhotoGuard.exe"

; G5: the version comes from pyproject.toml via the release workflow
; (ISCC.exe /DMyAppVersion=<version> ...). A missing define must fail loudly instead of
; stamping an empty AppVersion; if this guard is not understood by the local ISPP build,
; the bare {#MyAppVersion} reference below still aborts the compile.
#ifndef MyAppVersion
  #error MyAppVersion is required: pass /DMyAppVersion=<version> to ISCC.exe
#endif

[Setup]
AppId={{A0DAED64-1B78-4B63-88CF-94604E7C9CE1}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
LicenseFile=..\LICENSE
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
