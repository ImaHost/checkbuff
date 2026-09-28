"""버프체크기 실행 진입점."""
import ctypes
import os
import sys


def ensure_admin():
    """마비노기는 관리자 권한으로 돌아가므로, 그 위에서 단축키를 받으려면 이쪽도 관리자여야 한다.
    UAC 창에서 '아니요'를 누르면 일반 권한으로 그냥 실행한다."""
    if os.environ.get("CHECKBUFF_NO_ADMIN") or "--no-admin" in sys.argv:
        return
    try:
        if ctypes.windll.shell32.IsUserAnAdmin():
            return
        if getattr(sys, "frozen", False):            # exe: 자기 자신을 다시 실행
            argv, cwd = [*sys.argv[1:], "--no-admin"], os.path.dirname(sys.executable)
        else:                                        # 소스: python main.py
            script = os.path.abspath(sys.argv[0])
            argv, cwd = [script, *sys.argv[1:], "--no-admin"], os.path.dirname(script)
        args = " ".join(f'"{a}"' for a in argv)
        rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, args, cwd, 1)
        if rc > 32:
            sys.exit(0)
    except Exception:
        pass


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
