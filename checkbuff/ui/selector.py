"""단축키(기본 F10)로 띄우는 영역 선택 오버레이. 화면을 얼려서 보여주고 드래그로 영역을 고른다."""
import ctypes

import mss
import numpy as np
from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen
from PySide6.QtWidgets import QWidget

from .style import ACCENT


class RegionSelector(QWidget):
    selected = Signal(list)      # [x, y, w, h] (물리 픽셀, 가상 데스크톱 좌표)
    cancelled = Signal()

    def __init__(self, message: str = "버프 목록(이름 + 남은 시간)을 드래그해서 선택하세요"):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.message = message
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setCursor(Qt.CrossCursor)
        with mss.mss() as sct:
            mon = sct.monitors[0]
            shot = sct.grab(mon)
        self.origin = QPoint(mon["left"], mon["top"])
        buf = np.asarray(shot).copy()
        self._buf = buf
        self.image = QImage(buf.data, buf.shape[1], buf.shape[0], buf.strides[0], QImage.Format_ARGB32)
        self.setGeometry(mon["left"], mon["top"], mon["width"], mon["height"])
        self.start = None
        self.end = None

    def showEvent(self, e):
        # 게임이 포커스를 쥐고 있어도 이 창이 키보드(Esc)를 받도록 강제로 앞으로 가져옴
        user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
        fg_thread = user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), None)
        me = kernel32.GetCurrentThreadId()
        attached = fg_thread and fg_thread != me and user32.AttachThreadInput(me, fg_thread, True)
        user32.SetForegroundWindow(int(self.winId()))
        if attached:
            user32.AttachThreadInput(me, fg_thread, False)
        self.activateWindow()
        self.raise_()
        self.setFocus()

    def _rect(self) -> QRect:
        if not self.start or not self.end:
            return QRect()
        return QRect(self.start, self.end).normalized()

    def paintEvent(self, e):
        p = QPainter(self)
        p.drawImage(0, 0, self.image)
        p.fillRect(self.rect(), QColor(0, 0, 0, 120))
        r = self._rect()
        if r.isValid():
            p.drawImage(r, self.image, r)
            p.setPen(QPen(QColor(ACCENT), 2))
            p.drawRect(r.adjusted(-1, -1, 0, 0))
            label = f"{r.width()} × {r.height()}"
            p.setFont(QFont("Malgun Gothic", 10, QFont.Bold))
            tr = p.fontMetrics().boundingRect(label).adjusted(-8, -4, 8, 4)
            tr.moveTopLeft(QPoint(r.left(), max(0, r.top() - tr.height() - 6)))
            p.fillRect(tr, QColor(ACCENT))
            p.setPen(QColor("#1b1406"))
            p.drawText(tr, Qt.AlignCenter, label)
        # 안내문
        p.setFont(QFont("Malgun Gothic", 12, QFont.Bold))
        msg = f"{self.message}   ·   Esc 취소"
        tr = p.fontMetrics().boundingRect(msg).adjusted(-18, -10, 18, 10)
        screen = self.screen().geometry() if self.screen() else self.rect()
        tr.moveCenter(QPoint(screen.center().x() - self.origin.x(), 50))
        p.setBrush(QColor(20, 22, 28, 230))
        p.setPen(QPen(QColor(ACCENT), 1))
        p.drawRoundedRect(tr, 10, 10)
        p.setPen(QColor("#ebe7df"))
        p.drawText(tr, Qt.AlignCenter, msg)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.start = self.end = e.position().toPoint()
            self.update()
        elif e.button() == Qt.RightButton:
            self._cancel()

    def mouseMoveEvent(self, e):
        if self.start:
            self.end = e.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.LeftButton or not self.start:
            return
        r = self._rect()
        if r.width() < 20 or r.height() < 10:
            self.start = self.end = None
            self.update()
            return
        self.selected.emit([r.x() + self.origin.x(), r.y() + self.origin.y(), r.width(), r.height()])
        self.close()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self._cancel()

    def _cancel(self):
        self.cancelled.emit()
        self.close()
