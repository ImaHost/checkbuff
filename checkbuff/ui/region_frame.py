"""캡처 영역 조정 틀: 화면 위에 영역을 테두리로 보여 주고, 드래그로 이동·크기 조절.

- 안쪽 드래그 = 이동, 가장자리·모서리 드래그 = 크기 조절.
- 테두리와 이름표는 영역 '바깥 여백'에 그린다. 영역 안쪽은 거의 투명(알파 1)이라
  조정하는 동안에도 캡처(시간 읽기)에 영향을 주지 않는다. (완전히 투명하면 마우스가 통과해 버려서 알파 1)
"""
from PySide6.QtCore import QPoint, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QWidget

M_SIDE, M_TOP = 8, 24          # 영역 바깥 여백 (위쪽은 이름표 자리)
GRIP = 10                      # 가장자리로 인정하는 폭
MIN_W, MIN_H = 40, 16


class RegionFrame(QWidget):
    changed = Signal(list)     # [x, y, w, h]

    def __init__(self, region, label: str, color: str):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setMouseTracking(True)
        self.label = label
        self.color = QColor(color)
        self._drag = None          # (구역, 누른 전역 좌표, 시작 geometry)
        self.setToolTip(f"{label}: 안쪽을 드래그하면 이동, 가장자리·모서리를 드래그하면 크기 조절")
        self.set_region(region)

    # ---------- 영역 <-> 창 ----------
    def set_region(self, r):
        x, y, w, h = r
        self.setGeometry(x - M_SIDE, y - M_TOP, w + 2 * M_SIDE, h + M_TOP + M_SIDE)

    def region(self) -> list:
        g = self.geometry()
        return [g.x() + M_SIDE, g.y() + M_TOP, g.width() - 2 * M_SIDE, g.height() - M_TOP - M_SIDE]

    def _inner(self) -> QRect:
        return QRect(M_SIDE, M_TOP, self.width() - 2 * M_SIDE, self.height() - M_TOP - M_SIDE)

    # ---------- 그리기 ----------
    def paintEvent(self, e):
        p = QPainter(self)
        inner = self._inner()
        # 여백: 옅은 색 (영역 바깥이라 캡처에 안 들어감)
        band = QColor(self.color)
        band.setAlpha(55)
        p.fillRect(self.rect(), band)
        p.setCompositionMode(QPainter.CompositionMode_Source)
        p.fillRect(inner, QColor(0, 0, 0, 1))                  # 안쪽: 거의 투명, 마우스는 받음
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)
        # 테두리·손잡이는 영역 바깥에만 (영역 안쪽 픽셀은 절대 건드리지 않음)
        pen = QPen(self.color, 2, Qt.DashLine)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawRect(QRectF(inner).adjusted(-3, -3, 3, 3))
        p.setPen(Qt.NoPen)
        p.setBrush(self.color)
        L, T, R, B = inner.left(), inner.top(), inner.right() + 1, inner.bottom() + 1
        for x, y in ((L - 8, T - 8), (R, T - 8), (L - 8, B), (R, B)):
            p.drawRect(x, y, 8, 8)
        # 이름표 (위쪽 여백)
        f = QFont("Malgun Gothic")
        f.setPixelSize(12)
        f.setBold(True)
        p.setFont(f)
        r = self.region()
        text = f"{self.label}  {r[2]}×{r[3]}"
        tw = QFontMetrics(f).horizontalAdvance(text) + 14
        tag = QRectF(M_SIDE - 2, 2, min(tw, self.width() - M_SIDE), M_TOP - 5)
        p.setBrush(self.color)
        p.drawRoundedRect(tag, 5, 5)
        p.setPen(QColor(20, 18, 10))
        p.drawText(tag.adjusted(7, 0, -4, 0), Qt.AlignVCenter | Qt.AlignLeft,
                   QFontMetrics(f).elidedText(text, Qt.ElideRight, int(tag.width() - 10)))

    # ---------- 마우스 ----------
    def _zone(self, pos: QPoint) -> str:
        inner = self._inner()
        x, y = pos.x(), pos.y()
        z = ""
        if y <= inner.top() + GRIP // 2 and y >= inner.top() - GRIP:
            z += "t"
        elif y >= inner.bottom() - GRIP // 2:
            z += "b"
        if x <= inner.left() + GRIP // 2:
            z += "l"
        elif x >= inner.right() - GRIP // 2:
            z += "r"
        if not z and y < inner.top() - GRIP:
            return "move"                    # 이름표를 잡아도 이동
        return z or "move"

    _CURSORS = {"t": Qt.SizeVerCursor, "b": Qt.SizeVerCursor, "l": Qt.SizeHorCursor, "r": Qt.SizeHorCursor,
                "tl": Qt.SizeFDiagCursor, "br": Qt.SizeFDiagCursor, "tr": Qt.SizeBDiagCursor,
                "bl": Qt.SizeBDiagCursor, "move": Qt.SizeAllCursor}

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag = (self._zone(e.position().toPoint()), e.globalPosition().toPoint(), QRect(self.geometry()))

    def mouseMoveEvent(self, e):
        if self._drag is None:
            self.setCursor(self._CURSORS[self._zone(e.position().toPoint())])
            return
        zone, start, g0 = self._drag
        d = e.globalPosition().toPoint() - start
        g = QRect(g0)
        if zone == "move":
            g.moveTo(g0.topLeft() + d)
        else:
            min_w, min_h = MIN_W + 2 * M_SIDE, MIN_H + M_TOP + M_SIDE
            if "l" in zone:
                g.setLeft(min(g0.left() + d.x(), g0.right() - min_w))
            if "r" in zone:
                g.setRight(max(g0.right() + d.x(), g0.left() + min_w))
            if "t" in zone:
                g.setTop(min(g0.top() + d.y(), g0.bottom() - min_h))
            if "b" in zone:
                g.setBottom(max(g0.bottom() + d.y(), g0.top() + min_h))
        self.setGeometry(g)
        self.update()

    def mouseReleaseEvent(self, e):
        if self._drag is not None:
            self._drag = None
            self.changed.emit(self.region())
