"""버프 선택 창: 캡처한 버프를 타일로 보여 주고, 클릭으로 알림 받을 버프를 고른다."""
import numpy as np
from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QCompleter, QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QScrollArea, QVBoxLayout, QWidget)

from ..tuan import GROUPS, is_group_buff
from . import style

COLS = 4
TILE_W, TILE_H = 168, 196
SELECT_BG = "#2b2414"


def _icon_pixmap(rgb, size):
    if rgb is None or not getattr(rgb, "size", 0):
        return None
    rgb = np.ascontiguousarray(rgb)
    img = QImage(rgb.data, rgb.shape[1], rgb.shape[0], rgb.strides[0], QImage.Format_RGB888).copy()
    # 게임 아이콘은 픽셀 아트라 부드럽게 늘리면 뭉개짐 → 최근접 보간으로 선명하게 확대
    return QPixmap.fromImage(img).scaled(size, size, Qt.KeepAspectRatio, Qt.FastTransformation)


class BuffTile(QFrame):
    toggled = Signal()

    def __init__(self, row, checked, completer, cfg, auto_states):
        super().__init__()
        self.row = row
        self.cfg = cfg
        self.checked = checked
        self.setFixedSize(TILE_W, TILE_H)
        self.setCursor(Qt.PointingHandCursor)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 12)
        lay.setSpacing(6)

        top = QHBoxLayout()
        self.state = QLabel("● 사용 중" if row["active"] else "대기")
        self.state.setStyleSheet(f"color: {style.OK if row['active'] else style.MUTED};"
                                 "font-size: 11px; font-weight: 700; background: transparent; border: none;")
        self.badge = QLabel("✓")
        self.badge.setFixedSize(22, 22)
        self.badge.setAlignment(Qt.AlignCenter)
        top.addWidget(self.state)
        top.addStretch()
        top.addWidget(self.badge)
        lay.addLayout(top)

        self.icon = QLabel()
        self.icon.setFixedSize(64, 64)
        self.icon.setAlignment(Qt.AlignCenter)
        pm = _icon_pixmap(row["icon"], 60)
        if pm:
            self.icon.setPixmap(pm)
        self.icon.setStyleSheet(f"background: #0d0f14; border: 1px solid {style.LINE}; border-radius: 10px;")
        lay.addWidget(self.icon, 0, Qt.AlignHCenter)

        self.edit = QLineEdit(row["name"])
        self.edit.setAlignment(Qt.AlignCenter)
        self.edit.setPlaceholderText("이름 입력")
        self.edit.setCompleter(completer)
        self.edit.setToolTip("이름이 틀렸으면 눌러서 고치세요")
        self.edit.textChanged.connect(self._restyle)
        lay.addWidget(self.edit)

        self.tag = QLabel()
        self.tag.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.tag)

        # 소환 대상 버프에만: 자동 투안(노래 버프) / 자동 햄(햄 아드레날린·햄 버닝)
        self.group = next((g for g in GROUPS if is_group_buff(g, self.name, cfg)), None)
        title = self.group.title if self.group else ""
        self.tuan = QCheckBox(f"{'♪' if self.group and self.group.key == 'tuan' else '★'} 자동 {title}")
        self.tuan.setChecked(bool(self.group and auto_states.get(self.group.key, {}).get(row["name"], False)))
        self.tuan.setToolTip(f"곧 끝나면 {title}을(를) 소환했다가 해제해서 버프를 다시 걸게 합니다.\n"
                             "(실행기의 '자동 소환' 탭에서 키를 등록하세요)")
        self.tuan.setStyleSheet(f"QCheckBox {{ color: {style.ACCENT}; font-size: 12px; font-weight: 700;"
                                " background: transparent; border: none; }")
        lay.addWidget(self.tuan, 0, Qt.AlignHCenter)
        self.edit.textChanged.connect(self._update_tuan)
        self._restyle()

    @property
    def name(self):
        return " ".join(self.edit.text().split())

    @property
    def needs_name(self):
        return not self.row["known"] and self.name == self.row["name"] or not self.name

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.set_checked(not self.checked)
            self.toggled.emit()

    def set_checked(self, v):
        if not self.name:
            v = False               # 이름 없는 버프는 선택 불가
        self.checked = v
        self._restyle()

    @property
    def tuan_eligible(self):
        return self.group is not None and is_group_buff(self.group, self.name, self.cfg)

    def _update_tuan(self):
        self.tuan.setVisible(self.tuan_eligible)
        self.tuan.setEnabled(self.checked)       # 알림 대상으로 고른 버프만 자동 투안 가능

    def _restyle(self):
        sel = self.checked
        self.setStyleSheet(
            f"BuffTile {{ background: {SELECT_BG if sel else style.CARD2};"
            f" border: {2 if sel else 1}px solid {style.ACCENT if sel else style.LINE}; border-radius: 14px; }}"
            f"BuffTile:hover {{ border-color: {style.ACCENT}; }}")
        self.badge.setStyleSheet(
            f"background: {style.ACCENT if sel else 'transparent'}; color: #1b1406; font-weight: 900;"
            f"border-radius: 11px; border: {'none' if sel else '1px solid ' + style.LINE};")
        self.badge.setText("✓" if sel else "")
        warn = self.needs_name
        self.edit.setStyleSheet(
            "QLineEdit { background: transparent; border: none;"
            f" border-bottom: 1px solid {style.ACCENT if warn else 'transparent'};"
            f" color: {style.TEXT}; font-size: 14px; font-weight: 700; padding: 2px; }}"
            f"QLineEdit:hover, QLineEdit:focus {{ border-bottom: 1px solid {style.ACCENT}; }}")
        if not self.name:
            self.tag.setText("이름을 입력하세요")
            col = style.DANGER
        elif warn:
            self.tag.setText("✎ 이름 확인 필요")
            col = style.ACCENT
        elif self.name != self.row["name"]:
            self.tag.setText("✔ 고친 이름으로 기억")
            col = style.OK
        else:
            self.tag.setText("기억된 이름")
            col = style.MUTED
        self.tag.setStyleSheet(f"color: {col}; font-size: 11px; background: transparent; border: none;")
        if hasattr(self, "tuan"):
            self._update_tuan()


class BuffPickDialog(QDialog):
    """캡처한 화면의 버프 목록. 알림 받을 버프를 고르고, 틀린 이름을 고친다."""

    FILTERS = [("all", "전체"), ("active", "사용 중"), ("checked", "알림 받는 버프"), ("name", "이름 확인 필요")]

    def __init__(self, rows, cfg, parent=None):
        super().__init__(parent)
        self.setWindowTitle("버프 선택")
        self.setStyleSheet(style.QSS + f"""
            QDialog {{ background: {style.BG}; }}
            QLineEdit#search {{ background: {style.CARD2}; border: 1px solid {style.LINE}; border-radius: 16px;
                               padding: 6px 14px; font-size: 13px; min-width: 180px; }}
            QLineEdit#search:focus {{ border-color: {style.ACCENT}; }}
            QPushButton#chip {{ background: transparent; border: 1px solid {style.LINE}; border-radius: 15px;
                               padding: 5px 14px; font-size: 12px; color: {style.MUTED}; }}
            QPushButton#chip:checked {{ background: {style.ACCENT}; border-color: {style.ACCENT}; color: #1b1406; }}
            QPushButton#chip:hover:!checked {{ color: {style.TEXT}; border-color: {style.ACCENT}; }}
        """)
        watch = cfg.get("watch", {})
        auto_states = {g.key: cfg.get(f"auto_{g.key}", {}) for g in GROUPS}
        completer = QCompleter(cfg.get("known_names", []), self)
        self.tiles = [BuffTile(r, bool(r["name"]) and watch.get(r["name"], False), completer, cfg,
                               auto_states) for r in rows]
        for t in self.tiles:
            t.toggled.connect(self._update)
            t.edit.textChanged.connect(self._update)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(14)

        # 머리글
        head = QHBoxLayout()
        tbox = QVBoxLayout()
        tbox.setSpacing(2)
        t = QLabel("알림 받을 버프를 골라주세요")
        t.setStyleSheet("font-size: 18px; font-weight: 700;")
        sub = QLabel("타일을 누르면 선택됩니다. 선택한 버프가 사용 중일 때 남은 시간을 확인해 "
                     "30초 이하가 되면 알려 드려요.")
        sub.setObjectName("muted")
        tbox.addWidget(t)
        tbox.addWidget(sub)
        head.addLayout(tbox, 1)
        self.counter = QLabel()
        self.counter.setStyleSheet(f"color: {style.ACCENT}; font-size: 22px; font-weight: 800;")
        head.addWidget(self.counter, 0, Qt.AlignRight | Qt.AlignVCenter)
        lay.addLayout(head)

        # 필터 + 검색
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.filter_group = QButtonGroup(self)
        self.chips = {}
        for key, label in self.FILTERS:
            b = QPushButton(label)
            b.setObjectName("chip")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(self._apply_filter)
            self.filter_group.addButton(b)
            self.chips[key] = (b, label)
            bar.addWidget(b)
        self.chips["all"][0].setChecked(True)
        bar.addStretch()
        self.search = QLineEdit()
        self.search.setObjectName("search")
        self.search.setPlaceholderText("🔍 이름 검색")
        self.search.textChanged.connect(self._apply_filter)
        bar.addWidget(self.search)
        lay.addLayout(bar)

        # 타일 격자
        box = QWidget()
        self.grid = QGridLayout(box)
        self.grid.setContentsMargins(2, 2, 2, 2)
        self.grid.setSpacing(12)
        self.grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.empty = QLabel("버프를 찾지 못했습니다.\n영역에 버프 아이콘과 이름이 모두 들어가도록 다시 지정해 보세요.")
        self.empty.setObjectName("muted")
        self.empty.setAlignment(Qt.AlignCenter)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(box)
        scroll.setStyleSheet("QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }")
        visible_rows = min(3, max(1, (len(rows) + COLS - 1) // COLS))
        scroll.setMinimumHeight(visible_rows * (TILE_H + 12) + 8)
        scroll.setMinimumWidth(COLS * (TILE_W + 12) + 24)
        lay.addWidget(scroll, 1)

        # 아래 버튼
        foot = QHBoxLayout()
        all_btn = QPushButton("모두 선택")
        all_btn.setObjectName("ghost")
        all_btn.clicked.connect(lambda: self._set_all(True))
        none_btn = QPushButton("모두 해제")
        none_btn.setObjectName("ghost")
        none_btn.clicked.connect(lambda: self._set_all(False))
        foot.addWidget(all_btn)
        foot.addWidget(none_btn)
        foot.addStretch()
        cancel = QPushButton("취소")
        cancel.clicked.connect(self.reject)
        self.ok = QPushButton()
        self.ok.setObjectName("primary")
        self.ok.setDefault(True)
        self.ok.clicked.connect(self.accept)
        foot.addWidget(cancel)
        foot.addWidget(self.ok)
        lay.addLayout(foot)

        self._apply_filter()
        self._update()

    # ---------- 상태 ----------
    def _set_all(self, v):
        for t in self.tiles:
            if t.isVisible():
                t.set_checked(v)
        self._update()

    def _match(self, t, mode, q):
        if q and q.replace(" ", "") not in t.name.replace(" ", ""):
            return False
        return {"all": True, "active": t.row["active"], "checked": t.checked, "name": t.needs_name}[mode]

    def _apply_filter(self):
        mode = next(k for k, (b, _) in self.chips.items() if b.isChecked())
        q = self.search.text().strip()
        while self.grid.count():
            self.grid.takeAt(0)
        shown = [t for t in self.tiles if self._match(t, mode, q)]
        for t in self.tiles:
            t.setVisible(t in shown)
        for i, t in enumerate(shown):
            self.grid.addWidget(t, i // COLS, i % COLS)
        self.empty.setVisible(not shown)
        if not shown:
            self.empty.setText("조건에 맞는 버프가 없습니다" if self.tiles else
                               "버프를 찾지 못했습니다.\n영역에 버프 아이콘과 이름이 모두 들어가도록 다시 지정해 보세요.")
            self.grid.addWidget(self.empty, 0, 0, 1, COLS)

    def _update(self):
        n = sum(t.checked for t in self.tiles)
        counts = {"all": len(self.tiles), "active": sum(t.row["active"] for t in self.tiles),
                  "checked": n, "name": sum(t.needs_name for t in self.tiles)}
        for k, (b, label) in self.chips.items():
            b.setText(f"{label}  {counts[k]}")
        self.counter.setText(f"{n}개 선택")
        self.ok.setText(f"저장 ({n}개 알림)" if n else "저장")

    def sizeHint(self):
        return QSize(COLS * (TILE_W + 12) + 60, 640)

    def summon_states(self):
        """{그룹 key: {이름: 자동 소환 여부}} — 소환 대상 버프만"""
        out = {g.key: {} for g in GROUPS}
        for t in self.tiles:
            if t.name and t.tuan_eligible:
                out[t.group.key][t.name] = t.checked and t.tuan.isChecked()
        return out

    def result_rows(self):
        """[(원본 행, 확정 이름, 알림 여부)] — 이름이 빈 행은 제외"""
        return [(t.row, t.name, t.checked) for t in self.tiles if t.name]
