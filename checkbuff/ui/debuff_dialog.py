"""디버프 등록 창: 디버프 영역에서 찾은 아이콘마다 이름을 붙이고 감시할지 고른다."""
import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QCheckBox, QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QScrollArea, QVBoxLayout, QWidget)

from ..debuffs import DEFAULT_PRESET
from . import style


def _pix(rgb, size=None):
    rgb = np.ascontiguousarray(rgb)
    pm = QPixmap.fromImage(QImage(rgb.data, rgb.shape[1], rgb.shape[0], rgb.strides[0], QImage.Format_RGB888).copy())
    return pm.scaled(size, size, Qt.KeepAspectRatio, Qt.FastTransformation) if size else pm


class DebuffRegisterDialog(QDialog):
    def __init__(self, scan: dict, book, preset=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("디버프 등록")
        self.setStyleSheet(style.QSS + f"""
            QDialog {{ background: {style.BG}; }}
            QFrame#tile {{ background: {style.CARD2}; border: 1px solid {style.LINE}; border-radius: 12px; }}
            QLineEdit {{ background: {style.BG}; border: 1px solid {style.LINE}; border-radius: 6px;
                        padding: 5px 8px; font-size: 13px; font-weight: 700; }}
            QLineEdit:focus {{ border-color: {style.ACCENT}; }}
        """)
        self.book = book
        self.rows = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 18)
        lay.setSpacing(12)
        t = QLabel("디버프 아이콘 등록")
        t.setStyleSheet("font-size: 18px; font-weight: 700;")
        lay.addWidget(t)
        preset = DEFAULT_PRESET if preset is None else preset
        sub = QLabel("찾은 아이콘에 이름을 붙이세요. 이름이 같은 아이콘은 한 디버프로 묶여, 그중 하나만 있어도 '있음'입니다.\n"
                     "처음 등록하는 아이콘에는 왼쪽부터 순서대로 기본 이름을 채워 두었습니다. 이름을 비우면 등록하지 않습니다.")
        sub.setObjectName("muted")
        sub.setWordWrap(True)
        lay.addWidget(sub)

        # 캡처 미리보기 (찾은 아이콘에 번호 표시)
        rgb = scan["rgb"]
        prev = _pix(rgb)
        scale = max(1, min(4, 560 // max(1, rgb.shape[1])))
        prev = prev.scaled(rgb.shape[1] * scale, rgb.shape[0] * scale, Qt.KeepAspectRatio, Qt.FastTransformation)
        p = QPainter(prev)
        for i, (x, y, s, _) in enumerate(scan["icons"]):
            p.setPen(QPen(QColor(style.ACCENT), 2))
            p.drawRect(x * scale, y * scale, s * scale, s * scale)
            p.drawText(x * scale + 2, y * scale - 3, str(i + 1))
        p.end()
        pl = QLabel()
        pl.setPixmap(prev)
        pl.setAlignment(Qt.AlignCenter)
        pl.setStyleSheet("background: #0b0c10; border-radius: 8px; padding: 8px;")
        lay.addWidget(pl)

        box = QWidget()
        grid = QGridLayout(box)
        grid.setSpacing(10)
        grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        for i, (x, y, s, icon) in enumerate(scan["icons"]):
            known = book.find(icon)
            tile = QFrame()
            tile.setObjectName("tile")
            tl = QHBoxLayout(tile)
            tl.setContentsMargins(10, 8, 10, 8)
            num = QLabel(str(i + 1))
            num.setStyleSheet(f"color: {style.ACCENT}; font-weight: 800; background: transparent; border: none;")
            tl.addWidget(num)
            ic = QLabel()
            ic.setPixmap(_pix(icon, 48))
            ic.setFixedSize(52, 52)
            ic.setAlignment(Qt.AlignCenter)
            ic.setStyleSheet("background: #0d0f14; border-radius: 8px; border: none;")
            tl.addWidget(ic)
            col = QVBoxLayout()
            ed = QLineEdit(known["name"] if known else (preset[i] if i < len(preset) else ""))
            ed.setPlaceholderText("디버프 이름")
            ed.setMinimumWidth(170)
            col.addWidget(ed)
            chk = QCheckBox("없으면 알림")
            chk.setChecked(known["watch"] if known else True)
            chk.setStyleSheet("background: transparent; border: none;")
            tag = QLabel("등록된 디버프" if known else ("새 디버프 · 순서로 채움" if i < len(preset) else "새 디버프"))
            tag.setStyleSheet(f"color: {style.OK if known else style.ACCENT}; font-size: 11px;"
                              " background: transparent; border: none;")
            row2 = QHBoxLayout()
            row2.addWidget(chk)
            row2.addStretch()
            row2.addWidget(tag)
            col.addLayout(row2)
            tl.addLayout(col, 1)
            grid.addWidget(tile, i // 2, i % 2)
            self.rows.append((icon, ed, chk))
        if not scan["icons"]:
            empty = QLabel("아이콘을 찾지 못했습니다.\n대상을 선택해 디버프가 보이는 상태에서, 아이콘 줄이 들어가도록 F11 로 다시 지정해 보세요.")
            empty.setObjectName("muted")
            empty.setAlignment(Qt.AlignCenter)
            grid.addWidget(empty, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(box)
        scroll.setStyleSheet("QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }")
        scroll.setMinimumHeight(min(360, 90 + 74 * ((len(self.rows) + 1) // 2)))
        scroll.setMinimumWidth(620)
        lay.addWidget(scroll, 1)

        foot = QHBoxLayout()
        foot.addStretch()
        cancel = QPushButton("취소")
        cancel.clicked.connect(self.reject)
        ok = QPushButton("저장")
        ok.setObjectName("primary")
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        foot.addWidget(cancel)
        foot.addWidget(ok)
        lay.addLayout(foot)

    def apply(self):
        """이름이 있는 아이콘만 등록/갱신."""
        for icon, ed, chk in self.rows:
            name = " ".join(ed.text().split())
            if name:
                self.book.upsert(icon, name, chk.isChecked())
        self.book.save()
