; Local development installer. No global Python, PATH or user-data migration.
#ifndef PayloadDir
  #define PayloadDir "..\..\outputs\windows-installer\payload"
#endif
#ifndef OutputDirectory
  #define OutputDirectory "..\..\outputs\windows-installer\release"
#endif
#ifndef PayloadFileList
  #define PayloadFileList "..\..\outputs\windows-installer\payload-files.iss"
#endif

[Setup]
AppId={{5E8865A3-45E3-4F60-9488-24386C4B015A}
AppName=粤普同传
AppVersion=0.1.0-alpha.2
AppVerName=粤普同传 0.1.0 Alpha 2
AppPublisher=粤普同传贡献者
VersionInfoVersion=0.1.0.2
DefaultDirName={localappdata}\Programs\YuePuTranslate
DefaultGroupName=粤普同传
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.18362
OutputDir={#OutputDirectory}
OutputBaseFilename=YuePuTranslate-0.1.0-alpha.2-Windows-x64-Setup
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
UninstallDisplayName=粤普同传（Windows 开发预览）
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
Name: "{group}\粤普同传"; Filename: "{app}\python\pythonw.exe"; Parameters: "-I -B ""{app}\launch.py"""; WorkingDir: "{app}"
Name: "{group}\使用说明"; Filename: "{app}\使用说明.txt"
Name: "{autodesktop}\粤普同传"; Filename: "{app}\python\pythonw.exe"; Parameters: "-I -B ""{app}\launch.py"""; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\python\pythonw.exe"; Parameters: "-I -B ""{app}\launch.py"""; WorkingDir: "{app}"; Description: "运行粤普同传"; Flags: nowait postinstall skipifsilent

; Deliberately no [UninstallDelete], [InstallDelete] or settings registry keys.
; Inno removes only its registered files. User preferences and exports survive.
