"""코드 변경 감지 → 자동 재시작 신호.

.py 파일이 바뀌면 저장이 끝날 때까지(한 번 더 확인해 변화 없음) 기다린 뒤,
1) 문법 검사, 2) 별도 프로세스에서 실제로 import 해 보기를 통과해야 ready 를 보낸다.
여러 파일을 고치는 도중이라 서로 안 맞는 상태면 재시작하지 않고 error 로 알려서
실행 중인 프로그램이 죽지 않게 한다.
"""
import py_compile
import sys
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QTimer, Signal

ROOT = Path(__file__).resolve().parents[1]
IMPORT_CHECK = f"import sys; sys.path.insert(0, {str(ROOT)!r}); import checkbuff.ui.launcher"


def _snapshot():
    files = [ROOT / "main.py", *(ROOT / "checkbuff").rglob("*.py")]
    out = {}
    for f in files:
        try:
            out[f] = f.stat().st_mtime_ns
        except OSError:
            pass
    return out


class CodeWatcher(QObject):
    ready = Signal(list)        # 바뀐 파일 목록
    error = Signal(str)

    def __init__(self, interval_ms: int = 1000):
        super().__init__()
        self._base = _snapshot()
        self._pending = None
        self._reported = None
        self._checking = None       # import 검사 중인 스냅샷
        self._proc = None
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._check)
        self.timer.start(interval_ms)

    def _check(self):
        if self._proc is not None:
            return
        now = _snapshot()
        if now == self._base:
            self._pending = None
            return
        if now != self._pending:            # 아직 저장 중일 수 있음 → 다음 확인까지 대기
            self._pending = now
            return
        if now == self._reported:           # 이미 오류를 알린 상태 그대로
            return
        changed = [f for f in now if now.get(f) != self._base.get(f)]
        for f in changed:
            try:
                py_compile.compile(str(f), doraise=True)
            except py_compile.PyCompileError as e:
                self._fail(now, f"{f.name}: {e.msg.strip().splitlines()[-1]}")
                return
        # 실제로 불러와 보기 (다른 프로세스라 실행 중인 프로그램에는 영향 없음)
        self._checking = (now, changed)
        self._proc = QProcess(self)
        self._proc.finished.connect(self._on_import_checked)
        exe = Path(sys.executable)
        py = exe.with_name("python.exe") if exe.name.lower() == "pythonw.exe" else exe
        self._proc.start(str(py), ["-c", IMPORT_CHECK])

    def _on_import_checked(self, code, _status):
        proc, self._proc = self._proc, None
        now, changed = self._checking
        if code != 0:
            err = bytes(proc.readAllStandardError()).decode("utf-8", "replace").strip().splitlines()
            self._fail(now, err[-1] if err else f"종료 코드 {code}")
            return
        if _snapshot() != now:              # 검사 중에 또 바뀜 → 다음 확인에서 다시
            return
        self.timer.stop()
        self.ready.emit([f.name for f in changed])

    def _fail(self, snap, msg):
        if self._reported != snap:
            self._reported = snap
            self.error.emit(f"코드 오류로 재시작을 미룹니다\n{msg}")
