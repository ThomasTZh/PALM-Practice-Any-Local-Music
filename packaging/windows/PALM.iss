; PALM per-user Windows installer.
; Build with:
;   ISCC.exe /DPayloadDir=<staged payload> /DAppVersion=<version>
;           /DOutputDir=<dist> /DOutputBaseFilename=PALM-<version>-windows-x86_64-installer PALM.iss
; The payload is the same staged tree as the portable ZIP. The installer only
; touches the app directory; %LOCALAPPDATA%\palm is user data.

#ifndef AppVersion
  #define AppVersion "0.1.0-dev"
#endif
#ifndef PayloadDir
  #define PayloadDir "..\..\dist\palm-0.1.0-dev-windows-x86_64"
#endif
#ifndef OutputDir
  #define OutputDir "..\..\dist"
#endif
#ifndef OutputBaseFilename
  #define OutputBaseFilename "PALM-" + AppVersion + "-windows-x86_64-installer"
#endif

[Setup]
AppId={{8F8C62F2-9B42-4A38-9E3B-6E2C1D4C7A11}
AppName=PALM
AppVerName=PALM {#AppVersion}
AppVersion={#AppVersion}
AppPublisher=PALM
DefaultDirName={localappdata}\Programs\PALM
DefaultGroupName=PALM
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir={#OutputDir}
OutputBaseFilename={#OutputBaseFilename}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
UninstallDisplayName=PALM
UninstallDisplayIcon={app}\PALM.exe
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
SetupLogging=yes
AllowNoIcons=yes

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"; Flags: checkedonce

[Files]
Source: "{#PayloadDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{userprograms}\PALM"; Filename: "{app}\PALM.exe"; WorkingDir: "{app}"
Name: "{userdesktop}\PALM"; Filename: "{app}\PALM.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\PALM.exe"; Description: "Launch PALM"; Flags: nowait postinstall skipifsilent unchecked

[Code]
var
  DeleteData: Boolean;

function InitializeUninstall(): Boolean;
begin
  Result := True;
  DeleteData := False;
  { Scripted/silent uninstall never removes user data. The interactive default
    is to keep data; only an explicit "No" removes the PALM data root. }
  if not UninstallSilent then
  begin
    if MsgBox(
      'Remove the PALM application files only?' + #13#10#13#10 +
      'Yes: remove the app and keep projects, models and tools.' + #13#10 +
      'No: also delete %LOCALAPPDATA%\palm (practice data).',
      mbConfirmation, MB_YESNO or MB_DEFBUTTON1) = IDNO then
      DeleteData := True;
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if (CurUninstallStep = usPostUninstall) and DeleteData then
    DelTree(ExpandConstant('{localappdata}\palm'), True, True, True);
end;
