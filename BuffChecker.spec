# PyInstaller 빌드 설정:  py -m PyInstaller BuffChecker.spec  →  dist/BuffChecker.exe
# 한 파일짜리 exe (다른 사람에게 이 파일 하나만 주면 됨). 설정은 각자 %APPDATA%\CheckBuff 에 저장.
from PyInstaller.utils.hooks import collect_submodules

hidden = collect_submodules("winrt")

a = Analysis(
    ["main.py"],
    pathex=["."],
    datas=[("assets", "assets"), ("CHANGELOG.md", ".")],
    hiddenimports=hidden,
    excludes=["tkinter", "matplotlib", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
              "PySide6.Qt3DCore", "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtMultimedia"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="BuffChecker",
    icon="assets/icon.ico",
    console=False,
    upx=False,
    runtime_tmpdir=None,
)
