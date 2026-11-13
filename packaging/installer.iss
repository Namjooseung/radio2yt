; Inno Setup 스크립트 — packaging\build.ps1 에서 실행한다.
; 결과: dist\installer\SoneFM-YoutubeEditor-Setup-<버전>.exe (GitHub가 한글 파일 이름을 지우므로 영문)

#ifndef AppVersion
  #define AppVersion "1.0"
#endif
#define AppName "SoneFM 유튜브 편집기"
#define AppExe "SoneFMEditor.exe"

[Setup]
AppId={{6E3B2C1A-5F4D-4B8E-9A7C-2D1F0E8B3C55}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=SoneFM 96.3
DefaultDirName={autopf}\SoneFM 유튜브 편집기
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; 관리자 권한 없이도 설치 가능 (기본: 현재 사용자용). 설치 화면에서 모든 사용자용도 고를 수 있다.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\dist\installer
OutputBaseFilename=SoneFM-YoutubeEditor-Setup-{#AppVersion}
SetupIconFile=..\assets\app.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2/ultra64
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"

[Tasks]
Name: "desktopicon"; Description: "바탕화면에 바로가기 만들기"; GroupDescription: "바로가기:"

[Files]
Source: "..\dist\SoneFMEditor\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\{#AppName} 제거"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "지금 실행"; Flags: nowait postinstall skipifsilent
