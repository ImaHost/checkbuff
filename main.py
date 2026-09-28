"""멜야옹 체크기 실행 진입점."""
import ctypes
import os
import sys


def ensure_admin():
    """관리자 권한으로 실행 (UAC 창은 처음 한 번만, 이후엔 작업 스케줄러로). checkbuff/elevate.py 참고."""
    from checkbuff import config, elevate
    elevate.ensure_admin(auto_task=config.load().get("admin_task", True))


ensure_admin()

# Qt 좌표 = 물리 픽셀 (mss 캡처 좌표와 일치시키기 위함)
os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "0"
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

from PySide6.QtGui import QIcon  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from checkbuff import instance  # noqa: E402
from checkbuff.ui.launcher import ICON_PATH, Launcher  # noqa: E402


def install_error_log():
    """콘솔 없이(pythonw) 실행될 때도 오류 원인을 알 수 있도록 %APPDATA%\\CheckBuff\\error.log 에 기록."""
    import faulthandler
    import traceback
    from datetime import datetime

    from checkbuff.config import APP_DIR
    APP_DIR.mkdir(parents=True, exist_ok=True)
    log = open(APP_DIR / "error.log", "a", encoding="utf-8", buffering=1)
    faulthandler.enable(log)

    def hook(exc_type, exc, tb):
        log.write(f"\n[{datetime.now():%Y-%m-%d %H:%M:%S}] {' '.join(sys.argv)}\n")
        log.write("".join(traceback.format_exception(exc_type, exc, tb)))
        sys.__excepthook__(exc_type, exc, tb)
    sys.excepthook = hook


def seed_defaults():
    """처음 실행하는 PC: 프로그램에 든 기본 데이터(버프 이름·숫자 학습·디버프 아이콘)를 복사.
    이미 있는 파일은 건드리지 않음 (사람마다 설정은 각자 PC 에)."""
    import shutil

    from checkbuff.config import APP_DIR
    from checkbuff.paths import asset
    APP_DIR.mkdir(parents=True, exist_ok=True)
    for name in ("names.json", "glyphs.json", "debuffs.json"):
        src, dst = asset("defaults") / name, APP_DIR / name
        if src.exists() and not dst.exists():
            shutil.copyfile(src, dst)


def main():
    install_error_log()
    seed_defaults()
    from checkbuff.updater import cleanup_old
    cleanup_old()
    # 자동 재시작으로 뜬 경우 이전 프로세스가 잠금을 놓을 때까지 잠깐 기다림
    if not instance.acquire(wait_sec=8.0 if "--restarted" in sys.argv else 0.0):
        sys.exit(0)
    instance.set_taskbar_identity()
    app = QApplication(sys.argv)
    app.setApplicationName(instance.APP_NAME)
    app.setApplicationDisplayName(instance.APP_NAME)
    app.setWindowIcon(QIcon(str(ICON_PATH)))
    win = Launcher(restarted="--restarted" in sys.argv)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
