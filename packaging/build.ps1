# 설치 파일 만들기: PowerShell에서  .\packaging\build.ps1
# 1) 빌드 전용 가상환경(.venv-build) 준비  2) ffmpeg 복사  3) PyInstaller  4) Inno Setup
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$version = (Select-String -Path "app\__init__.py" -Pattern '__version__ = "(.+)"').Matches[0].Groups[1].Value
Write-Host "== 버전 $version =="

# 1) 빌드 전용 가상환경 (개발용 .venv에는 TensorFlow 등이 있어 쓰지 않는다)
if (-not (Test-Path ".venv-build\Scripts\python.exe")) {
    python -m venv .venv-build
    & .venv-build\Scripts\python -m pip install --upgrade pip
}
& .venv-build\Scripts\python -m pip install -q -r requirements.txt pyinstaller
if ($LASTEXITCODE -ne 0) { throw "패키지 설치 실패" }

# 2) ffmpeg (PATH에 있는 것을 복사)
$ffmpeg = (Get-Command ffmpeg -ErrorAction Stop).Source
New-Item -ItemType Directory -Force "packaging\bin" | Out-Null
Copy-Item $ffmpeg "packaging\bin\ffmpeg.exe" -Force
$lic = Join-Path (Split-Path -Parent (Split-Path -Parent $ffmpeg)) "LICENSE"
if (Test-Path $lic) { Copy-Item $lic "packaging\bin\FFMPEG_LICENSE.txt" -Force }

# 3) PyInstaller
& .venv-build\Scripts\pyinstaller --noconfirm --clean --distpath dist --workpath build packaging\sonefm.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller 실패" }

# 4) Inno Setup
$iscc = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
          "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
          "$env:ProgramFiles\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw "Inno Setup(ISCC.exe)을 찾을 수 없습니다. winget install JRSoftware.InnoSetup" }
& $iscc "/DAppVersion=$version" packaging\installer.iss
if ($LASTEXITCODE -ne 0) { throw "Inno Setup 실패" }

Write-Host "`n완료: dist\installer\"
Get-ChildItem dist\installer | Format-Table Name, @{n="MB";e={[math]::Round($_.Length/1MB,1)}}
