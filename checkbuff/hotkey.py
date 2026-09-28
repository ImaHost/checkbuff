"""전역 단축키 (게임 창이 활성 상태여도 동작).

두 가지 방식을 함께 쓴다.
- RegisterHotKey: 일반적인 전역 단축키.
- GetAsyncKeyState 폴링: 게임이 키 입력을 먼저 가져가 RegisterHotKey 가 안 먹는 경우 대비.
둘 다 같은 눌림을 잡을 수 있으므로 짧은 시간 안의 중복은 한 번으로 친다.
관리자 권한으로 실행된 게임 위에서는 이 프로그램도 관리자 권한이어야 한다 (main.py 참고).
"""
import ctypes
import ctypes.wintypes as wt
import threading
import time

from PySide6.QtCore import QObject, Signal

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
MOD_NOREPEAT = 0x4000
VK = {f"F{i}": 0x6F + i for i in range(1, 13)}


class GlobalHotkey(QObject):
    pressed = Signal()
    failed = Signal(str)

    def __init__(self, key: str = "F10"):
        super().__init__()
        self.key = key
        self._tid = None
        self._stop = threading.Event()
        self._last = 0.0
        self._lock = threading.Lock()

    @property
    def vk(self):
        return VK.get(self.key, VK["F10"])

    def start(self):
        self._stop = threading.Event()
        threading.Thread(target=self._run_hotkey, daemon=True).start()
        threading.Thread(target=self._run_poll, args=(self._stop,), daemon=True).start()

    def stop(self):
        self._stop.set()
        if self._tid:
            user32.PostThreadMessageW(self._tid, WM_QUIT, 0, 0)
            self._tid = None

    def set_key(self, key: str):
        self.stop()
        self.key = key
        self.start()

    def _fire(self):
        with self._lock:
            now = time.monotonic()
            if now - self._last < 0.4:
                return
            self._last = now
        self.pressed.emit()

    def _run_hotkey(self):
        self._tid = kernel32.GetCurrentThreadId()
        if not user32.RegisterHotKey(None, 1, MOD_NOREPEAT, self.vk):
            return              # 다른 프로그램이 선점해도 폴링으로 동작함
        msg = wt.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY:
                self._fire()
        user32.UnregisterHotKey(None, 1)

    def _run_poll(self, stop: threading.Event):
        vk = self.vk
        down = True             # 시작 순간 눌려 있던 키는 무시
        while not stop.is_set():
            now_down = bool(user32.GetAsyncKeyState(vk) & 0x8000)
            if now_down and not down:
                self._fire()
            down = now_down
            time.sleep(0.03)
