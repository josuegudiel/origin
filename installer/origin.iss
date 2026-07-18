; Inno Setup script — empaqueta el bundle PyInstaller en un instalador .exe.
; Requiere Inno Setup 6 instalado: https://jrsoftware.org/isinfo.php
; Compilar:
;   "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer\origin.iss

#define AppName "Origin"
#define AppVersion "0.3.0"
#define AppPublisher "Origin"
#define AppExeName "Origin.exe"

[Setup]
AppId={{8C7F0A1F-2A5A-4D6D-9C2F-7B5E2A0C9F00}}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\dist
OutputBaseFilename=OriginSetup-{#AppVersion}-small-v3
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon";  Description: "Crear acceso directo en el escritorio"; GroupDescription: "Atajos:"
Name: "autostart";    Description: "Iniciar Origin con Windows (al system tray)"; GroupDescription: "Inicio:"; Flags: unchecked

[Files]
Source: "..\dist\Origin\Origin.exe";    DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\Origin\*";             DestDir: "{app}"; Excludes: "Origin.exe"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}";               Filename: "{app}\{#AppExeName}"
Name: "{group}\Uninstall {#AppName}";     Filename: "{uninstallexe}"
Name: "{commondesktop}\{#AppName}";       Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "Origin"; ValueData: """{app}\{#AppExeName}"" --tray"; Flags: uninsdeletevalue; Tasks: autostart

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Lanzar {#AppName}"; Flags: nowait postinstall skipifsilent
