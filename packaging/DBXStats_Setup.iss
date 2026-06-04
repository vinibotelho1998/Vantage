#define MyAppName "DBX Stats"
#define MyAppVersion "2.0.0"
#define MyAppPublisher "DBX"
#define MyAppExeName "DBXStats.exe"

[Setup]
AppId=DBXStats
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=DBXStats-Setup
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Files]
Source: "..\dist\DBXStats\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\prereqs\vc_redist.x64.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall
Source: "..\prereqs\windowsdesktop-runtime-8.0-x64.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall
Source: "..\prereqs\windowsdesktop-runtime-6.0-x64.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"

[Run]
Filename: "{tmp}\vc_redist.x64.exe"; Parameters: "/install /quiet /norestart"; StatusMsg: "Instalando VC++ Redistributable..."; Flags: waituntilterminated; Check: not IsVCRedistInstalled
Filename: "{tmp}\windowsdesktop-runtime-8.0-x64.exe"; Parameters: "/install /quiet /norestart"; StatusMsg: "Instalando .NET Desktop Runtime 8..."; Flags: waituntilterminated; Check: not IsWindowsDesktopRuntimeInstalled('8.')
Filename: "{tmp}\windowsdesktop-runtime-6.0-x64.exe"; Parameters: "/install /quiet /norestart"; StatusMsg: "Instalando .NET Desktop Runtime 6..."; Flags: waituntilterminated; Check: not IsWindowsDesktopRuntimeInstalled('6.')
Filename: "{app}\{#MyAppExeName}"; Description: "Abrir DBX Stats"; Flags: nowait postinstall skipifsilent

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
