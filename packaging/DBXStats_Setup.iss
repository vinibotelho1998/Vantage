; Instalador do DBX Stats.
;
; Compile por packaging/build.ps1 (ou BUILD.bat): e' de la' que vem a versao,
; lida de src/dbxstats/__init__.py, para nao existir numero repetido em dois
; lugares. Compilar este arquivo na mao tambem funciona, usando a reserva.

; Nome exibido no instalador, nos atalhos e em Programas e Recursos.
; O executavel e a pasta de dados continuam DBXStats/"DBX Stats": mexer
; neles quebraria a configuracao de quem ja' usa o app.
#define MyAppName "DBX STATUS"
#ifndef MyAppVersion
  #define MyAppVersion "3.0.0"
#endif
#define MyAppPublisher "DBX"
#define MyAppExeName "DBXStats.exe"
#define MyAppUrl "https://github.com/vinibotelho1998/DBX-Stats"

[Setup]
; AppId fixo e unico: e' por ele que o Windows reconhece uma atualizacao no
; lugar de uma segunda instalacao. Nunca mudar entre versoes.
AppId={{7C4B1E2A-9D53-4F86-B0A7-2F1D8C6E5A31}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppUrl}
AppSupportURL={#MyAppUrl}/issues
AppUpdatesURL={#MyAppUrl}/releases/latest
AppCopyright=Copyright (C) {#MyAppPublisher}
VersionInfoVersion={#MyAppVersion}
VersionInfoProductName={#MyAppName}
VersionInfoDescription=Instalador do {#MyAppName}
AppComments=Monitoramento de desempenho para jogos: FPS, 1% low, sensores e telas.
VersionInfoCompany={#MyAppPublisher}

DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
DisableDirPage=auto
LicenseFile=..\LICENSE
InfoAfterFile=

OutputDir=..\dist
OutputBaseFilename=DBXStats-Setup
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
WizardImageFile=assets\wizard.bmp,assets\wizard-1.bmp,assets\wizard-2.bmp,assets\wizard-3.bmp
WizardSmallImageFile=assets\wizard-small.bmp,assets\wizard-small-1.bmp,assets\wizard-small-2.bmp,assets\wizard-small-3.bmp
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName} {#MyAppVersion}

; Sensores de CPU/placa e captura de FPS exigem privilegio; sem isso o app sobe
; mas nao mede nada. Melhor barrar na instalacao do que decepcionar depois.
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
; Fecha o app antes de sobrescrever os arquivos, em vez de falhar no meio.
CloseApplications=yes
RestartApplications=no
SetupMutex=DBXStatsSetupMutex

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na area de trabalho"; GroupDescription: "Atalhos:"

[Files]
Source: "..\dist\DBXStats\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\prereqs\vc_redist.x64.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall
Source: "..\prereqs\windowsdesktop-runtime-8.0-x64.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall
Source: "..\prereqs\windowsdesktop-runtime-6.0-x64.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall
Source: "..\prereqs\PawnIO_setup.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{tmp}\vc_redist.x64.exe"; Parameters: "/install /quiet /norestart"; StatusMsg: "Instalando Visual C++ Redistributable..."; Flags: waituntilterminated; Check: not IsVCRedistInstalled
Filename: "{tmp}\windowsdesktop-runtime-8.0-x64.exe"; Parameters: "/install /quiet /norestart"; StatusMsg: "Instalando .NET Desktop Runtime 8..."; Flags: waituntilterminated; Check: not IsWindowsDesktopRuntimeInstalled('8.')
Filename: "{tmp}\windowsdesktop-runtime-6.0-x64.exe"; Parameters: "/install /quiet /norestart"; StatusMsg: "Instalando .NET Desktop Runtime 6..."; Flags: waituntilterminated; Check: not IsWindowsDesktopRuntimeInstalled('6.')
Filename: "{tmp}\PawnIO_setup.exe"; Parameters: "-install -silent"; StatusMsg: "Instalando PawnIO (driver de sensores da CPU)..."; Flags: waituntilterminated
Filename: "{app}\{#MyAppExeName}"; Description: "Abrir o {#MyAppName} agora"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\_internal\__pycache__"

[Code]
function IsVCRedistInstalled: Boolean;
var
  Installed: Cardinal;
begin
  Result := RegQueryDWordValue(HKLM64, 'SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64', 'Installed', Installed)
    and (Installed = 1);
end;

function ReadTextFileSafe(const FileName: string): string;
var
  S: AnsiString;
begin
  if LoadStringFromFile(FileName, S) then
    Result := S
  else
    Result := '';
end;

function IsWindowsDesktopRuntimeInstalled(const MajorPrefix: string): Boolean;
var
  ResultCode: Integer;
  DotnetExe: string;
  OutFile: string;
  Content: string;
begin
  Result := False;
  DotnetExe := ExpandConstant('{sys}\dotnet.exe');
  if not FileExists(DotnetExe) then
    Exit;

  OutFile := ExpandConstant('{tmp}\dotnet_runtimes.txt');
  if Exec(ExpandConstant('{cmd}'), '/C ""' + DotnetExe + '" --list-runtimes > "' + OutFile + '""', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
  begin
    Content := ReadTextFileSafe(OutFile);
    if Pos('Microsoft.WindowsDesktop.App ' + MajorPrefix, Content) > 0 then
      Result := True;
  end;
end;

// Configuracoes, perfis de tela e atalhos de jogo ficam em %APPDATA%. Apagar
// isso sem perguntar seria destruir o trabalho de quem so' queria desinstalar
// para reinstalar depois.
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Dados: string;
begin
  if CurUninstallStep <> usPostUninstall then
    Exit;
  Dados := ExpandConstant('{userappdata}\DBX Stats');
  if not DirExists(Dados) then
    Exit;
  if MsgBox('Apagar tambem as configuracoes, perfis de tela e historico de benchmark?'
            + #13#10 + #13#10 + Dados,
            mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
    DelTree(Dados, True, True, True);
end;
