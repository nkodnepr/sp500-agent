; ============================================================
;  Установщик Stock Agent для Windows (Inno Setup)
;
;  Что получается на выходе: один файл StockAgent-Setup.exe,
;  который человек без технических навыков просто запускает
;  двойным кликом. Python, консоль и распаковка архивов не нужны.
;
;  Установка идёт ДЛЯ ТЕКУЩЕГО ПОЛЬЗОВАТЕЛЯ (PrivilegesRequired=lowest):
;  Windows не показывает окно UAC с запросом прав администратора —
;  на чужом или рабочем компьютере прав админа может просто не быть.
;  Программа кладётся в {localappdata}\Programs\StockAgent.
;
;  Как собрать:
;    1. python build_exe.py --onedir      (создаёт dist\StockAgent\)
;    2. ISCC.exe installer\StockAgent.iss (создаёт dist_installer\)
;  Обычно этого делать вручную не нужно — сборку выполняет
;  GitHub Actions, см. .github/workflows/build-exe.yml
; ============================================================

#define AppName "Stock Agent"
#define AppVersion "1.0.0"
#define AppExeName "StockAgent.exe"
#define AppPublisher "Stock Agent"

[Setup]
; AppId должен оставаться НЕИЗМЕННЫМ между версиями — по нему Windows
; понимает, что это обновление уже установленной программы, а не вторая
; её копия рядом.
AppId={{8F3C1B7A-2E64-4E1D-9C55-6A0D2F7B4E91}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
VersionInfoVersion={#AppVersion}

; Установка без прав администратора. {autopf} при lowest-правах
; разворачивается в {localappdata}\Programs — папку пользователя.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
DefaultDirName={autopf}\StockAgent
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes

OutputDir=..\dist_installer
OutputBaseFilename=StockAgent-Setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#AppExeName}
UninstallDisplayName={#AppName}

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
; Всё содержимое папки, собранной PyInstaller в режиме --onedir
Source: "..\dist\StockAgent\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Инструкция пользователя — кладём рядом, если она есть в репозитории
Source: "..\USER_GUIDE.pdf"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
Source: "..\USER_GUIDE.md"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

; ВАЖНО: раздела [UninstallDelete] здесь намеренно нет.
; Данные пользователя (watchlist.db и кэш обученных моделей) лежат в
; %LOCALAPPDATA%\StockAgent — ОТДЕЛЬНО от папки с программой (см.
; _default_data_dir в config.py). Поэтому удаление или переустановка
; программы не стирает список отслеживания и обученные модели.
