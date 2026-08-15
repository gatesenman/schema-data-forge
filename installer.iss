#ifndef AppVersion
#define AppVersion "0.0.0"
#endif

[Setup]
AppId={{7A2B8F41-6C3D-4E5A-9B1C-2D8E4F6A7B9C}
AppName=Schema Data Forge
AppVersion={#AppVersion}
AppPublisher=gaosichun
DefaultDirName={autopf}\Schema Data Forge
DefaultGroupName=Schema Data Forge
DisableProgramGroupPage=yes
OutputDir=installer
OutputBaseFilename=SchemaDataForge-Setup
SetupIconFile=assets\icon.ico
UninstallDisplayIcon={app}\SchemaDataForge.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "dist\SchemaDataForge.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "MicrosoftEdgeWebView2Setup.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall; Check: WebView2Missing

[Icons]
Name: "{group}\Schema Data Forge"; Filename: "{app}\SchemaDataForge.exe"
Name: "{autodesktop}\Schema Data Forge"; Filename: "{app}\SchemaDataForge.exe"; Tasks: desktopicon

[Run]
Filename: "{tmp}\MicrosoftEdgeWebView2Setup.exe"; Parameters: "/silent /install"; StatusMsg: "Installing Microsoft Edge WebView2 Runtime..."; Check: WebView2Missing
Filename: "{app}\SchemaDataForge.exe"; Description: "{cm:LaunchProgram,Schema Data Forge}"; Flags: nowait postinstall skipifsilent

[Code]
function WebView2Missing: Boolean;
var
  Version: string;
begin
  Result := not (
    (RegQueryStringValue(HKLM, 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version) and (Version <> '') and (Version <> '0.0.0.0')) or
    (RegQueryStringValue(HKLM, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version) and (Version <> '') and (Version <> '0.0.0.0')) or
    (RegQueryStringValue(HKCU, 'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version) and (Version <> '') and (Version <> '0.0.0.0'))
  );
end;
