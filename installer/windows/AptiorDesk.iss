#define MyAppName "AptiorDesk"
#define MyAppVersion "0.1.0"
#define MyAppPublisher "Oussama Hamida / Glidd.io"
#define MyAppURL "https://glidd.io"
#define MyAppExeName "AptiorDesk.exe"

[Setup]
AppId={{7F498F49-0569-49B4-9342-B6447028DC93}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
OutputDir=..\..\dist\installer
OutputBaseFilename=AptiorDesk-Windows-x64-Setup
SetupIconFile=..\..\packaging\icons\aptiordesk.ico
LicenseFile=..\..\LICENSE
InfoBeforeFile=privacy_before_install.txt
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName=AptiorDesk
VersionInfoCompany=Glidd.io
VersionInfoCopyright=Copyright (c) 2026 Oussama Hamida
VersionInfoDescription=AptiorDesk Windows installer
VersionInfoProductName=AptiorDesk
VersionInfoProductVersion={#MyAppVersion}
UsePreviousAppDir=yes
UsePreviousGroup=yes
CloseApplications=yes
RestartApplications=no
SetupLogging=yes
DisableProgramGroupPage=no
ChangesEnvironment=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Types]
Name: "full"; Description: "Full installation"
Name: "compact"; Description: "AptiorDesk without companion-extension guidance"
Name: "custom"; Description: "Custom installation"; Flags: iscustom

[Components]
Name: "core"; Description: "AptiorDesk core application"; Types: full compact custom; Flags: fixed
Name: "voice"; Description: "Kokoro neural voice and offline speech-to-text model (~460 MB)"; Types: full compact custom; Flags: fixed
Name: "extension"; Description: "Companion-extension setup guidance"; Types: full custom

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
; The PyInstaller directory is an immutable, self-contained runtime. Kokoro,
; ONNX Runtime, espeak-ng, the phonemizer, model and voice assets are already
; inside this tree before Setup starts.
Source: "..\..\dist\AptiorDesk\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Components: core
Source: "browser-extension-install.txt"; DestDir: "{app}\docs"; Flags: ignoreversion; Components: extension

[Dirs]
; User data is deliberately outside {app}. Upgrades and repair installs never
; delete the database, resumes, provider settings, models, or diagnostics.
Name: "{localappdata}\AptiorDesk"; Permissions: users-modify

[Icons]
Name: "{group}\AptiorDesk"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\AptiorDesk"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
Name: "{group}\Set up browser extension"; Filename: "{app}\docs\browser-extension-install.txt"; Components: extension
Name: "{group}\Uninstall AptiorDesk"; Filename: "{uninstallexe}"

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\App Paths\AptiorDesk.exe"; ValueType: string; ValueName: ""; ValueData: "{app}\{#MyAppExeName}"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Glidd.io\AptiorDesk"; ValueType: string; ValueName: "InstallLocation"; ValueData: "{app}"; Flags: uninsdeletekey

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch AptiorDesk"; Flags: nowait postinstall skipifsilent

[Code]
var
  LocalAIPage: TOutputMsgMemoWizardPage;
  ExtensionPage: TOutputMsgMemoWizardPage;

procedure InitializeWizard;
begin
  LocalAIPage := CreateOutputMsgMemoPage(
    wpSelectComponents,
    'Local AI and voice setup',
    'AptiorDesk installs its complete voice runtime before first launch.',
    'Review the included and optional local components.',
    'Kokoro and the default offline speech-to-text model are included and verified by Setup. No Python installation, first-run model download, or terminal command is required.' + #13#10 + #13#10 +
    'Ollama is optional. If you use it, install and start Ollama separately, then select an available model in AptiorDesk''s first-launch setup. You may instead connect a device AI CLI or cloud API.'
  );
  ExtensionPage := CreateOutputMsgMemoPage(
    LocalAIPage.ID,
    'Browser extension',
    'Job capture is optional and remains local to this computer.',
    'Install the separately distributed companion after AptiorDesk finishes.',
    'The proprietary companion extension is not bundled with this open-source desktop application. Install the official Chrome Web Store release when available, open its side panel once, and use Settings → System setup to verify the local connection.'
  );
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
begin
  if CurStep = ssPostInstall then
  begin
    if not Exec(
      ExpandConstant('{app}\{#MyAppExeName}'),
      '--verify-install "' + ExpandConstant('{tmp}\aptiordesk-install-check.json') + '"',
      '',
      SW_HIDE,
      ewWaitUntilTerminated,
      ResultCode
    ) or (ResultCode <> 0) then
    begin
      MsgBox(
        'AptiorDesk was installed, but voice or speech-model verification did not pass.' + #13#10 + #13#10 +
        'Rerun this installer to repair the application. Your local data and settings will be preserved.',
        mbError,
        MB_OK
      );
      RaiseException('Installed runtime verification failed.');
    end;
  end;
end;
