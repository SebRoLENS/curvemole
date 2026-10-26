#ifndef MyAppVersion
  #error MyAppVersion must be provided to ISCC
#endif
#ifndef MyAppNumericVersion
  #define MyAppNumericVersion MyAppVersion
#endif
#ifndef SourceDir
  #ifndef SourceExe
    #error SourceDir or legacy SourceExe must be provided to ISCC
  #endif
#endif
#ifndef RootDir
  #error RootDir must be provided to ISCC
#endif
#ifndef OutputDir
  #define OutputDir RootDir
#endif

[Setup]
AppId={{D73E23AD-A748-4C43-A2EF-09608497017E}
AppName=CurveMole
AppVersion={#MyAppVersion}
VersionInfoVersion={#MyAppNumericVersion}
AppPublisher=Sebastiano Romi
AppPublisherURL=https://github.com/SebRoLENS/curvemole
AppSupportURL=https://github.com/SebRoLENS/curvemole/issues
AppUpdatesURL=https://github.com/SebRoLENS/curvemole/releases/latest
DefaultDirName={localappdata}\Programs\CurveMole
DefaultGroupName=CurveMole
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#OutputDir}
OutputBaseFilename=CurveMole-{#MyAppVersion}-windows-x86_64-setup
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
SetupIconFile={#RootDir}\generated-icons\curvemole.ico
UninstallDisplayIcon={app}\CurveMole.exe
ChangesAssociations=yes
CloseApplications=yes
RestartApplications=yes
AppMutex=CurveMole

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "italian"; MessagesFile: "compiler:Languages\Italian.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
#ifdef SourceDir
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
#else
Source: "{#SourceExe}"; DestDir: "{app}"; DestName: "CurveMole.exe"; Flags: ignoreversion
#endif
Source: "{#RootDir}\packaging\windows\curvemole-installed.marker"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\CurveMole"; Filename: "{app}\CurveMole.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\CurveMole"; Filename: "{app}\CurveMole.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Classes\CurveMole.Project"; ValueType: string; ValueName: ""; ValueData: "CurveMole Project"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\CurveMole.Project\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\CurveMole.exe,0"
Root: HKCU; Subkey: "Software\Classes\CurveMole.Project\shell\open"; ValueType: string; ValueName: "MultiSelectModel"; ValueData: "Player"
Root: HKCU; Subkey: "Software\Classes\CurveMole.Project\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\CurveMole.exe"" ""%1"""
Root: HKCU; Subkey: "Software\Classes\.fitproj\OpenWithProgids"; ValueType: string; ValueName: "CurveMole.Project"; ValueData: ""; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\CurveMole\Capabilities"; ValueType: string; ValueName: "ApplicationName"; ValueData: "CurveMole"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\CurveMole\Capabilities"; ValueType: string; ValueName: "ApplicationDescription"; ValueData: "Modular Scientific Curve Fitting"
Root: HKCU; Subkey: "Software\CurveMole\Capabilities\FileAssociations"; ValueType: string; ValueName: ".fitproj"; ValueData: "CurveMole.Project"
Root: HKCU; Subkey: "Software\RegisteredApplications"; ValueType: string; ValueName: "CurveMole"; ValueData: "Software\CurveMole\Capabilities"; Flags: uninsdeletevalue

; Register as an optional Open with handler; never take over data-file defaults.
Root: HKCU; Subkey: "Software\Classes\Applications\CurveMole.exe"; ValueType: string; ValueName: "FriendlyAppName"; ValueData: "CurveMole"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\Applications\CurveMole.exe\shell\open"; ValueType: string; ValueName: "MultiSelectModel"; ValueData: "Player"
Root: HKCU; Subkey: "Software\Classes\Applications\CurveMole.exe\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\CurveMole.exe"" ""%1"""
Root: HKCU; Subkey: "Software\Classes\Applications\CurveMole.exe\SupportedTypes"; ValueType: string; ValueName: ".fitproj"; ValueData: ""
Root: HKCU; Subkey: "Software\Classes\Applications\CurveMole.exe\SupportedTypes"; ValueType: string; ValueName: ".txt"; ValueData: ""
Root: HKCU; Subkey: "Software\Classes\Applications\CurveMole.exe\SupportedTypes"; ValueType: string; ValueName: ".dat"; ValueData: ""
Root: HKCU; Subkey: "Software\Classes\Applications\CurveMole.exe\SupportedTypes"; ValueType: string; ValueName: ".csv"; ValueData: ""
Root: HKCU; Subkey: "Software\Classes\Applications\CurveMole.exe\SupportedTypes"; ValueType: string; ValueName: ".tsv"; ValueData: ""
Root: HKCU; Subkey: "Software\Classes\Applications\CurveMole.exe\SupportedTypes"; ValueType: string; ValueName: ".xy"; ValueData: ""

[Run]
Filename: "{app}\CurveMole.exe"; Description: "{cm:LaunchProgram,CurveMole}"; WorkingDir: "{app}"; Flags: nowait postinstall
