# PyInstaller 설정 — packaging\build.ps1 에서 실행한다.
# 결과: dist\SoneFMEditor\SoneFMEditor.exe (+ _internal 폴더)
from pathlib import Path

ROOT = Path(SPECPATH).parent

datas = [
    (str(ROOT / "engine" / "models"), "engine/models"),
    (str(ROOT / "engine" / "vendor" / "README.md"), "engine/vendor"),
    (str(ROOT / "assets"), "assets"),
    (str(ROOT / "packaging" / "bin"), "bin"),          # ffmpeg.exe + LICENSE (build.ps1이 복사)
]

a = Analysis(
    [str(ROOT / "sonefm.py")],
    pathex=[str(ROOT)],
    datas=datas,
    hiddenimports=[],
    excludes=[
        # 개발용 패키지가 섞여 들어가지 않게
        "tensorflow", "keras", "tf2onnx", "onnx", "inaSpeechSegmenter", "scipy", "matplotlib",
        "pandas", "skimage", "tkinter",
        # 쓰지 않는 Qt 모듈
        "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtQml", "PySide6.QtQuick",
        "PySide6.Qt3DCore", "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtPdf",
        "PySide6.QtSql", "PySide6.QtTest",  # QtNetwork·QtOpenGL은 QtMultimedia가 필요로 한다
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="SoneFMEditor",
    icon=str(ROOT / "assets" / "app.ico"),
    console=False,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="SoneFMEditor")
