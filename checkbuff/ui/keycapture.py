"""누르면 다음 키 입력을 받아 등록하는 버튼 (Ctrl/Alt/Shift 조합 가능, Esc 취소, Backspace 지우기)."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QPushButton

from ..keys import VK_CONTROL, VK_MENU, VK_SHIFT, combo_label

_MOD_KEYS = {Qt.Key_Control, Qt.Key_Alt, Qt.Key_Shift, Qt.Key_Meta, Qt.Key_AltGr}


class KeyCaptureButton(QPushButton):
    changed = Signal(object)        # dict 또는 None

    def __init__(self, combo=None, parent=None):
        super().__init__(parent)
        self.combo = combo
        self.capturing = False
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumWidth(110)
        self.clicked.connect(self._start)
        self._refresh()

    def _refresh(self):
        if self.capturing:
            self.setText("키를 누르세요…")
        else:
            self.setText(self.combo["label"] if self.combo else "등록 안 됨")
        self.setToolTip("클릭한 뒤 등록할 키를 누르세요. Esc 취소, Backspace 지우기")

    def _start(self):
        self.capturing = True
        self._refresh()
        self.grabKeyboard()

    def _stop(self):
        self.capturing = False
        self.releaseKeyboard()
        self._refresh()

    def focusOutEvent(self, e):
        if self.capturing:
            self._stop()
        super().focusOutEvent(e)

    def keyPressEvent(self, e):
        if not self.capturing:
            return super().keyPressEvent(e)
        if e.key() in _MOD_KEYS:
            return
        if e.key() == Qt.Key_Escape:
            self._stop()
            return
        if e.key() == Qt.Key_Backspace:
            self.combo = None
            self._stop()
            self.changed.emit(None)
            return
        vk = e.nativeVirtualKey()
        if not vk:
            return
        mods = []
        m = e.modifiers()
        if m & Qt.ControlModifier:
            mods.append(VK_CONTROL)
        if m & Qt.AltModifier:
            mods.append(VK_MENU)
        if m & Qt.ShiftModifier:
            mods.append(VK_SHIFT)
        self.combo = {"vk": int(vk), "mods": mods, "label": combo_label(int(vk), mods)}
        self._stop()
        self.changed.emit(self.combo)
