; Inno Setup script for HoverDeck.
;
; Build (after `python build.py onedir` has produced dist\HoverDeck\):
;   iscc /DMyAppVersion=0.1.0 installer\hoverdeck.iss
; Output: dist\HoverDeck-Setup-<version>.exe  (per-user install, no admin needed)

#define MyAppName "HoverDeck"
#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif
#define MyAppPublisher "HoverDeck"
#define MyAppExeName "HoverDeck.exe"

[Setup]
; Keep this AppId stable forever — it ties upgrades/uninstalls together.
AppId={{A1F4C2E7-8B3D-4E6A-9C21-7F0E5D9B2A34}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
; Per-user install: no UAC prompt, lands in %LOCALAPPDATA%\Programs.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\dist
OutputBaseFilename=HoverDeck-Setup-{#MyAppVersion}
SetupIconFile=..\assets\icons\hoverdeck.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"

[Files]
; The whole one-dir PyInstaller output.
Source: "..\dist\HoverDeck\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{userdesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent
