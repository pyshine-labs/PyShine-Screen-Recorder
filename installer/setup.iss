; ---------------------------------------------------------------------------
; Inno Setup installer script for Screen Recorder
; ---------------------------------------------------------------------------
; Build the PyInstaller distribution first, then run:
;   ISCC installer\setup.iss
; ---------------------------------------------------------------------------

#define MyAppId "{{com.screenrecorder.app}}"
#define MyAppName "Screen Recorder"
#define MyAppVersion "1.0.3"
#define MyAppPublisher "Screen Recorder Project"
#define MyAppURL "https://github.com/pyshine-labs/PyShine-Screen-Recorder"
#define MyAppExeName "ScreenRecorder.exe"

[Setup]
; Application metadata
AppId={#MyAppId}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues

; Installation directories
DefaultDirName={{autop}\Screen Recorder
DefaultGroupName={#MyAppName}

; Output settings
OutputDir=output
OutputBaseFilename=ScreenRecorder-{#MyAppVersion}-setup

; Compression
Compression=lzma2/ultra64
SolidCompression=yes

; Icons
; SetupIconFile=..\resources\icons\app.ico  ; Uncomment when app.ico is added
UninstallDisplayIcon={app}\{#MyAppExeName}

; Privileges — no admin elevation needed
PrivilegesRequired=lowest

; Architecture
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

; License
LicenseFile=..\LICENSE

; Misc
DisableProgramGroupPage=yes
DisableWelcomePage=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
; Include the single PyInstaller onefile executable
Source: "..\dist\ScreenRecorder.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
; Start Menu shortcuts
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"

; Desktop shortcut (optional, via task selection)
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; Offer to launch the application after installation
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Clean up application data directory on uninstall
Type: filesandordirs; Name: "{autopf}\{#MyAppName}"
