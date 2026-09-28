"""버프 갱신 오버레이 (남은 시간이 기준 이하인 체크 버프만).

게임 버프창과 구분되는 작은 카드형: 아이콘 · 이름 · 큰 숫자 · 줄어드는 게이지.
남은 시간에 따라 주황→빨강, 10초 이하면 깜빡임. 이름을 접으면 아이콘과 시간만 보인다.
"""
import ctypes
import time

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QWidget

GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x80000
WS_EX_TRANSPARENT = 0x20
WS_EX_NOACTIVATE = 0x08000000

SCALE_MIN, SCALE_MAX = 0.6, 3.0
GRIP = 16                      # 오른쪽 아래 크기 조절 손잡이
GOLD = QColor(227, 181, 91)
TEXT = QColor(245, 242, 235)
GRAY = QColor(150, 150, 150)


class AlertWindow(QWidget):
    moved = Signal(list)
    collapse_toggled = Signal(bool)

    def __init__(self, cfg: dict, prefix: str = "alert", title: str = "버프 갱신", default_pos=(200, 200)):
        """prefix: 위치·접기 상태를 저장할 설정 키 앞부분 (버프 갱신 창 'alert', 디버프 창 'debuff_alert')"""
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.cfg = cfg
        self.prefix = prefix
        self.title = title
        self.default_pos = default_pos
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setMouseTracking(True)
        self.items = []
        self._drag = None
        self._press_pos = None
        self._resize = None          # (누른 전역 x, 시작 배율, 시작 폭)
        self.positioning = False     # 위치 조정 중에만 빈 창을 보여 줌
        self._closed = False
        self._toggle_rect = QRectF()
        pos = cfg.get(self._k("pos"))
        self.move(*(pos or default_pos))
        self._relayout()

    # ---------- 외부 API ----------
    def set_items(self, items):
        """items: [{name, remaining, expired, pixmap}] — 남은 시간 적은 순"""
        if self._closed:
            return
        self.items = items
        self._relayout()
        self._sync_visibility()
        self.update()

    def set_locked(self, locked: bool):
        self.cfg["alert_locked"] = locked
        hwnd = int(self.winId())
        style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        style |= WS_EX_LAYERED | WS_EX_NOACTIVATE
        style = style | WS_EX_TRANSPARENT if locked else style & ~WS_EX_TRANSPARENT
        ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
        self._relayout()
        self._sync_visibility()
        self.update()

    def set_positioning(self, on: bool):
        self.positioning = on
        if on:
            self.set_locked(False)
        else:
            self.set_locked(bool(self.cfg.get("alert_locked")))
            self.cfg[self._k("pos")] = [self.x(), self.y()]
            self.moved.emit(self.cfg[self._k("pos")])

    def set_collapsed(self, on: bool):
        self.cfg[self._k("collapsed")] = on
        self.refresh_style()

    def shutdown(self):
        self._closed = True
        self.hide()
        self.close()

    def refresh_style(self):
        self._relayout()
        self.update()

    # ---------- 레이아웃 ----------
    @property
    def _s(self):
        """창마다 크기 배율 (위치 조정 모드에서 오른쪽 아래 모서리로 조절). 없으면 공통 '알림창 크기'."""
        return float(self.cfg.get(self._k("win_scale")) or self.cfg.get("alert_scale", 1.0))

    def set_scale(self, v: float):
        self.cfg[self._k("win_scale")] = round(max(SCALE_MIN, min(SCALE_MAX, v)), 2)
        self.refresh_style()

    @property
    def collapsed(self):
        return bool(self.cfg.get(self._k("collapsed")))

    def _k(self, name):
        return f"{self.prefix}_{name}"

    def _font(self, px, weight=QFont.Bold):
        f = QFont("Malgun Gothic")
        f.setPixelSize(max(8, int(px * self._s)))
        f.setWeight(weight)
        return f

    def _relayout(self):
        s = self._s
        self.pad = int(5 * s)
        self.header_h = int(20 * s)
        self.card_h = int(36 * s)
        self.gap = int(4 * s)
        self.icon_sz = int(26 * s)
        self.time_w = int(52 * s)
        rows = self.items or ([{"name": "여기로 드래그", "placeholder": True, "remaining": None,
                                 "expired": False, "pixmap": None}] if self.positioning else [])
        self._rows = rows
        base = int(8 * s) + self.icon_sz + int(8 * s) + self.time_w + int(8 * s)
        if self.collapsed:
            self.card_w = base
        else:
            name_w = max([QFontMetrics(self._font(12)).horizontalAdvance(r["name"]) for r in rows] + [int(60 * s)])
            self.card_w = base + min(name_w, int(130 * s)) + int(6 * s)
        self.card_w = max(self.card_w, int(96 * s))
        self.setFixedSize(self.pad * 2 + self.card_w,
                          self.pad * 2 + self.header_h + len(rows) * (self.card_h + self.gap))

    def _sync_visibility(self):
        want = not self._closed and (bool(self.items) or self.positioning)
        if want and not self.isVisible():
            self.show()
        elif not want and self.isVisible():
            self.hide()

    # ---------- 그리기 ----------
    @staticmethod
    def _urgency_color(rem, threshold):
        """남은 비율에 따라 주황(기준 시간) → 빨강(0초)."""
        t = max(0.0, min(1.0, rem / max(threshold, 1)))
        return QColor(255, int(70 + 110 * t), int(60 + 10 * t))

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        s = self._s
        th = float(self.cfg.get("threshold_sec", 30))
        opacity = float(self.cfg.get("alert_opacity", 0.78))
        blink = (time.monotonic() % 0.8) < 0.4

        if self.positioning:
            p.setPen(QPen(QColor(227, 181, 91, 220), 1.5, Qt.DashLine))
            p.setBrush(QColor(8, 9, 12, int(120 * opacity)))
            p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 8 * s, 8 * s)
            # 크기 조절 손잡이 (오른쪽 아래 빗금)
            p.setPen(QPen(GOLD, 2))
            w, h = self.width(), self.height()
            for k in (4, 9, 14):
                p.drawLine(w - 3, h - 3 - k, w - 3 - k, h - 3)

        # 헤더 알약: "버프 갱신 N"  +  접기/펼치기 단추
        hf = self._font(11)
        fm = QFontMetrics(hf)
        ph = self.header_h - 4 * s
        n = sum(1 for r in self._rows if not r.get("placeholder"))
        title = f"{self.title} {n}" if n else self.title
        if self.collapsed:
            title = f"⚠ {n}" if n else "⚠"
        tw = fm.horizontalAdvance(title) + 14 * s
        box = QRectF(self.pad, self.pad, tw, ph)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(225, 55, 55, 235 if (blink and n) else 200))
        p.drawRoundedRect(box, ph / 2, ph / 2)
        p.setFont(hf)
        p.setPen(QColor(255, 255, 255))
        p.drawText(box, Qt.AlignCenter, title)
        # 접기 단추 (잠금 해제 상태에서 클릭 가능)
        tb = QRectF(self.width() - self.pad - ph, self.pad, ph, ph)
        self._toggle_rect = tb
        if not self.cfg.get("alert_locked") or self.positioning:
            p.setBrush(QColor(20, 22, 28, int(230 * opacity)))
            p.setPen(QPen(QColor(255, 255, 255, 50), 1))
            p.drawEllipse(tb)
            p.setPen(GOLD)
            p.drawText(tb, Qt.AlignCenter, "▸" if self.collapsed else "◂")

        y = self.pad + self.header_h
        for r in self._rows:
            self._card(p, QRectF(self.pad, y, self.card_w, self.card_h), r, th, opacity, blink)
            y += self.card_h + self.gap

    def _card(self, p, rect, r, th, opacity, blink):
        s = self._s
        rem = r.get("remaining")
        expired = bool(r.get("expired"))
        missing = bool(r.get("missing"))
        placeholder = bool(r.get("placeholder"))
        critical = expired or (rem is not None and rem <= 10)
        if missing:
            accent = QColor(255, 70, 70)
            critical = True
        else:
            accent = GRAY if expired or rem is None else self._urgency_color(rem, th)

        if critical and not expired and blink:
            glow = QColor(accent)
            glow.setAlpha(110)
            p.setPen(Qt.NoPen)
            p.setBrush(glow)
            p.drawRoundedRect(rect.adjusted(-2 * s, -2 * s, 2 * s, 2 * s), 9 * s, 9 * s)
        bg = QColor(18, 20, 26) if expired or placeholder else QColor(58, 20, 22)
        bg.setAlpha(int(238 * opacity))
        p.setBrush(bg)
        p.setPen(QPen(QColor(accent), 1.2))
        p.drawRoundedRect(rect, 8 * s, 8 * s)

        # 아이콘 (픽셀 아트라 부드럽게 늘리지 않음)
        isz = self.icon_sz
        ix = rect.x() + 6 * s
        iy = rect.y() + (rect.height() - isz) / 2 - 1 * s
        p.setBrush(QColor(0, 0, 0, 170))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(QRectF(ix - 1, iy - 1, isz + 2, isz + 2), 5 * s, 5 * s)
        if r.get("pixmap") is not None:
            p.setRenderHint(QPainter.SmoothPixmapTransform, False)
            p.setOpacity(0.45 if expired else 1.0)
            p.drawPixmap(QRectF(ix, iy, isz, isz).toRect(), r["pixmap"])
            p.setOpacity(1.0)

        # 이름 (접으면 생략)
        tx = ix + isz + 8 * s
        time_rect = QRectF(rect.right() - self.time_w - 8 * s, rect.y(), self.time_w, rect.height() - 4 * s)
        if not self.collapsed:
            nf = self._font(12)
            name_w = time_rect.x() - tx - 4 * s
            p.setFont(nf)
            p.setPen(GRAY if expired else TEXT)
            p.drawText(QRectF(tx, rect.y(), name_w, rect.height() - 4 * s), Qt.AlignLeft | Qt.AlignVCenter,
                       QFontMetrics(nf).elidedText(r["name"], Qt.ElideRight, int(name_w)))
        if placeholder:
            return

        # 게이지 (기준 시간 대비 남은 비율) — 카드 아래쪽 얇은 선
        bar = QRectF(rect.x() + 6 * s, rect.bottom() - 5 * s, rect.width() - 12 * s, 2.5 * s)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 25))
        p.drawRoundedRect(bar, 1.2 * s, 1.2 * s)
        if rem is not None and not expired:
            frac = max(0.0, min(1.0, rem / max(th, 1)))
            p.setBrush(accent)
            p.drawRoundedRect(QRectF(bar.x(), bar.y(), bar.width() * frac, bar.height()), 1.2 * s, 1.2 * s)

        # 숫자
        if missing:
            p.setFont(self._font(13, QFont.Black))
            p.setPen(QColor(255, 80, 80) if blink else QColor(255, 160, 160))
            p.drawText(time_rect, Qt.AlignRight | Qt.AlignVCenter, r.get("tag", "없음"))
            return
        if expired:
            p.setFont(self._font(13, QFont.Black))
            p.setPen(QColor(255, 80, 80) if blink else QColor(170, 50, 50))
            p.drawText(time_rect, Qt.AlignRight | Qt.AlignVCenter, "만료")
            return
        if rem is None:
            return
        sec = max(0, int(rem + 0.999))
        num = str(sec) if sec < 60 else f"{sec // 60}:{sec % 60:02d}"
        uf = self._font(10)
        unit = "초" if sec < 60 else ""
        uw = QFontMetrics(uf).horizontalAdvance(unit) + 2 * s if unit else 0
        col = QColor(accent)
        if critical and not blink:
            col = QColor(255, 175, 175)
        p.setFont(self._font(18, QFont.Black))
        p.setPen(col)
        p.drawText(QRectF(time_rect.x(), time_rect.y(), time_rect.width() - uw, time_rect.height()),
                   Qt.AlignRight | Qt.AlignVCenter, num)
        if unit:
            p.setFont(uf)
            p.drawText(QRectF(time_rect.right() - uw, time_rect.y() + 4 * s, uw, time_rect.height()),
                       Qt.AlignRight | Qt.AlignVCenter, unit)

    # ---------- 마우스: 드래그 이동 / 접기 단추 ----------
    def _in_grip(self, pos) -> bool:
        return self.positioning and pos.x() >= self.width() - GRIP and pos.y() >= self.height() - GRIP

    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton or not (self.positioning or not self.cfg.get("alert_locked")):
            return
        if self._in_grip(e.position()):
            self._resize = (e.globalPosition().x(), self._s, self.width())
            return
        self._drag = e.globalPosition().toPoint() - self.pos()
        self._press_pos = e.position()

    def mouseMoveEvent(self, e):
        if self._resize is not None:
            x0, s0, w0 = self._resize
            # 폭이 늘어난 비율만큼 배율을 키움 → 글자·도형을 그 크기로 새로 그려서 흐려지지 않음
            self.set_scale(s0 * max(0.2, (w0 + e.globalPosition().x() - x0) / w0))
            return
        if self._drag is not None:
            self.move(e.globalPosition().toPoint() - self._drag)
            return
        self.setCursor(Qt.SizeFDiagCursor if self._in_grip(e.position()) else Qt.ArrowCursor)

    def mouseReleaseEvent(self, e):
        if self._resize is not None:
            self._resize = None
            self.moved.emit(self.cfg.get(self._k("pos")) or [self.x(), self.y()])     # 저장 신호
            return
        if self._drag is None:
            return
        clicked = self._press_pos is not None and (e.position() - self._press_pos).manhattanLength() < 4
        self._drag = None
        if clicked and self._toggle_rect.contains(e.position()):
            self.set_collapsed(not self.collapsed)
            self.collapse_toggled.emit(self.collapsed)
            return
        self.cfg[self._k("pos")] = [self.x(), self.y()]       # 창마다 따로 저장
        self.moved.emit(self.cfg[self._k("pos")])
