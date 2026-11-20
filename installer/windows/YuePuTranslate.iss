; Local development installer. No global Python, PATH or user-data migration.
#ifndef PayloadDir
  #ifdef LightInstaller
    #define PayloadDir "..\..\outputs\windows-installer\payload-light"
  #else
    #define PayloadDir "..\..\outputs\windows-installer\payload"
  #endif
#endif
#ifndef OutputDirectory
  #ifdef LightInstaller
    #define OutputDirectory "..\..\outputs\windows-installer\release-light"
  #else
    #define OutputDirectory "..\..\outputs\windows-installer\release"
  #endif
#endif
#ifndef PayloadFileList
  #ifdef LightInstaller
    #define PayloadFileList "..\..\outputs\windows-installer\payload-light-files.iss"
  #else
    #define PayloadFileList "..\..\outputs\windows-installer\payload-files.iss"
  #endif
#endif

#ifdef LightInstaller
  #define AppDisplay "粤普同传（轻量版）"
#else
  #define AppDisplay "粤普同传"
#endif

[Setup]
#ifdef LightInstaller
AppId={{ABFBB62E-479D-4478-9DD9-4F68FE98D93A}
DefaultDirName={localappdata}\Programs\YuePuTranslate-Light
#else
AppId={{5E8865A3-45E3-4F60-9488-24386C4B015A}
DefaultDirName={localappdata}\Programs\YuePuTranslate
#endif
AppName={#AppDisplay}
AppVersion=0.1.0-alpha.2
AppVerName=粤普同传 0.1.0 Alpha 2
AppPublisher=粤普同传贡献者
VersionInfoVersion=0.1.0.2
DefaultGroupName={#AppDisplay}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.18362
OutputDir={#OutputDirectory}
#ifdef LightInstaller
OutputBaseFilename=YuePuTranslate-0.1.0-alpha.2-Windows-x64-Light-Setup
#else
OutputBaseFilename=YuePuTranslate-0.1.0-alpha.2-Windows-x64-Setup
#endif
WizardStyle=modern
DisableWelcomePage=no
InfoBeforeFile=使用说明.txt
LicenseFile=..\..\LICENSE
Compression=lzma2/max
LZMANumBlockThreads=4
LZMAUseSeparateProcess=yes
SolidCompression=yes
#ifdef SpanDisks
DiskSpanning=yes
; Keep every data slice below GitHub Releases' 2 GiB asset limit.
DiskSliceSize=1500000000
#endif
CloseApplications=yes
RestartApplications=no
UninstallDisplayName={#AppDisplay}（Windows 开发预览）
UninstallDisplayIcon={app}\python\pythonw.exe
SetupLogging=yes

[Languages]
Name: "chinesesimp"; MessagesFile: "ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; Flags: unchecked

[Files]
#include PayloadFileList

[Icons]
Name: "{group}\{#AppDisplay}"; Filename: "{app}\python\pythonw.exe"; Parameters: "-I -B ""{app}\launch.py"""; WorkingDir: "{app}"
Name: "{group}\使用说明"; Filename: "{app}\使用说明.txt"
Name: "{autodesktop}\{#AppDisplay}"; Filename: "{app}\python\pythonw.exe"; Parameters: "-I -B ""{app}\launch.py"""; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\python\pythonw.exe"; Parameters: "-I -B ""{app}\launch.py"""; WorkingDir: "{app}"; Description: "运行粤普同传"; Flags: nowait postinstall skipifsilent

; Deliberately no [UninstallDelete], [InstallDelete] or settings registry keys.
; Inno removes only its registered files. User preferences and exports survive.
