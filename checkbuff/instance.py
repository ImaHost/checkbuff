"""중복 실행 방지 + 자동 재시작 때 잠금 넘겨주기."""
import ctypes
import os
import sys
import time

APP_NAME = "버프체크기"
WINDOW_TITLE = "버프체크기"
APP_ID = "BuffChecker.Mabinogi.1"
# CHECKBUFF_INSTANCE: 테스트할 때 실행 중인 프로그램과 따로 띄우기 위한 것 (평소엔 비어 있음)
_MUTEX_NAME = "Local\\CheckBuff.SingleInstance" + os.environ.get("CHECKBUFF_INSTANCE", "")
_handle = None


def acquire(wait_sec: float = 0.0) -> bool:
    """잠금을 얻으면 True. 이미 실행 중이면 기존 창을 앞으로 가져오고 False."""
    global _handle
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateMutexW.restype = ctypes.c_void_p
    deadline = time.monotonic() + wait_sec
    while True:
        h = k32.CreateMutexW(None, False, _MUTEX_NAME)
        if ctypes.get_last_error() != 183:          # ERROR_ALREADY_EXISTS 아님
            _handle = h
            return True
        k32.CloseHandle(ctypes.c_void_p(h))
        if time.monotonic() >= deadline:
            break
        time.sleep(0.2)
    u32 = ctypes.windll.user32
    hwnd = u32.FindWindowW(None, WINDOW_TITLE)
    if hwnd:
        u32.ShowWindow(hwnd, 9)      # SW_RESTORE
        u32.SetForegroundWindow(hwnd)
    return False


def release():
    global _handle
    if _handle:
        ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(_handle))
        _handle = None


def set_taskbar_identity():
    """작업 표시줄에서 python 아이콘이 아니라 이 프로그램 아이콘으로 묶이게 한다."""
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        pass


def relaunch_args() -> list[str]:
    """재시작용 인자: 이미 관리자면 UAC 를 다시 묻지 않도록 --no-admin."""
    args = [a for a in sys.argv[1:] if a not in ("--no-admin", "--restarted")]
    if getattr(sys, "frozen", False) and args and args[0].lower().endswith(".py"):
        args = args[1:]
    return [*args, "--no-admin", "--restarted"]
