"""메인 실행기 창."""
import sys
import time
from pathlib import Path

import numpy as np
from PySide6.QtCore import QProcess, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QIcon, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QCompleter, QDialog, QTabWidget, QSlider, QDoubleSpinBox, QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit, QPushButton,
                               QScrollArea, QSpinBox, QVBoxLayout,
                               QWidget)

from .. import config, elevate, instance, sound
from ..glyphs import GlyphBook
from ..hotkey import VK, GlobalHotkey
from ..reloader import CodeWatcher
from ..debuffs import KIND_PRESENCE, KIND_REFRESH, MATCH_MIN, DebuffBook
from ..tuan import GROUPS, AutoSummon, base_name
from ..vision import format_time
from ..worker import MonitorWorker
from . import style
from .alert import AlertWindow
from .keycapture import KeyCaptureButton
from .debuff_dialog import DebuffRegisterDialog
from .picker import BuffPickDialog
from .region_frame import RegionFrame
from .summon_card import SummonCard
from .selector import RegionSelector

from ..paths import APP_EXE, FROZEN, asset
from ..updater import Updater, cached_notes
from ..version import __version__
from .notes_dialog import NotesDialog

ROOT = Path(__file__).resolve().parents[2]
ICON_PATH = asset("icon.ico")


def to_pixmap(rgb: np.ndarray) -> QPixmap:
    rgb = np.ascontiguousarray(rgb)
    img = QImage(rgb.data, rgb.shape[1], rgb.shape[0], rgb.strides[0], QImage.Format_RGB888)
    return QPixmap.fromImage(img.copy())


def card(title: str):
    f = QFrame()
    f.setObjectName("card")
    lay = QVBoxLayout(f)
    lay.setContentsMargins(18, 16, 18, 18)
    lay.setSpacing(12)
    t = QLabel(title)
    t.setObjectName("section")
    lay.addWidget(t)
    return f, lay


class BuffBoard(QWidget):
    """감시 중인 버프 목록 (아이콘 · 이름 · 남은 시간 막대 · 상태)."""

    ROW = 44
    CHECK_W = 34
    clicked = Signal(str, str)      # key, 현재 이름 → 이름 고치기
    toggled = Signal(str)           # 이름 → 알림 대상 켜기/끄기

    def __init__(self):
        super().__init__()
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("왼쪽 체크: 갱신 알림 받기 · 이름 클릭: 이름 고치기")
        self.items = []
        self.threshold = 30
        self.setMinimumHeight(self.ROW * 3)

    def set_items(self, items, threshold):
        self.items = items
        self.threshold = threshold
        self.setMinimumHeight(max(self.ROW * 3, self.ROW * len(items)))
        self.update()

    def mouseReleaseEvent(self, e):
        i = int(e.position().y() // self.ROW)
        if e.button() == Qt.LeftButton and 0 <= i < len(self.items):
            if e.position().x() < self.CHECK_W:
                self.toggled.emit(self.items[i]["name"])
            else:
                self.clicked.emit(self.items[i]["key"], self.items[i]["name"])

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if not self.items:
            p.setPen(QColor(style.MUTED))
            p.setFont(QFont("Malgun Gothic", 10))
            p.drawText(self.rect(), Qt.AlignCenter, "체크한 버프 중 사용 중인 버프가 없습니다\n'버프 선택'에서 알림 받을 버프를 고르세요")
            return
        name_f = QFont("Malgun Gothic", 10, QFont.Bold)
        small = QFont("Malgun Gothic", 8)
        W = self.width()
        for i, it in enumerate(self.items):
            y = i * self.ROW
            r = QRectF(0, y + 3, W, self.ROW - 6)
            watched = it.get("watched", True)
            alert = watched and (it["expired"] or (it["remaining"] is not None
                                                   and it["remaining"] <= self.threshold))
            p.setOpacity(1.0 if watched else 0.45)
            p.setPen(QPen(QColor("#5a2a2e") if alert else QColor(style.LINE), 1))
            p.setBrush(QColor("#2a1a1d") if alert else QColor(style.CARD2))
            p.drawRoundedRect(r, 8, 8)
            # 알림 대상 체크박스
            p.setOpacity(1.0)
            cb = QRectF(10, y + 14, 16, 16)
            p.setPen(QPen(QColor(style.ACCENT) if watched else QColor(style.LINE2), 2))
            p.setBrush(QColor(style.ACCENT) if watched else QColor(style.CARD2))
            p.drawRoundedRect(cb, 4, 4)
            if watched:
                p.setPen(QPen(QColor("#1b1406"), 2))
                p.drawLine(int(cb.x() + 4), int(cb.y() + 8), int(cb.x() + 7), int(cb.y() + 11))
                p.drawLine(int(cb.x() + 7), int(cb.y() + 11), int(cb.x() + 12), int(cb.y() + 5))
            p.setOpacity(1.0 if watched else 0.45)
            ix = self.CHECK_W + 2
            if it["pixmap"] is not None:
                p.drawPixmap(ix, int(y + 9), 26, 26, it["pixmap"])
            tx = ix + 36
            p.setFont(name_f)
            p.setPen(QColor(style.TEXT) if not it["expired"] else QColor(style.MUTED))
            p.drawText(QRectF(tx, y + 6, W - tx - 150, 20), Qt.AlignVCenter | Qt.AlignLeft, it["name"])
            # 막대
            bar = QRectF(tx, y + 28, W - tx - 150, 5)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#0f1116"))
            p.drawRoundedRect(bar, 2.5, 2.5)
            if it["remaining"] is not None and it["full"]:
                frac = max(0.0, min(1.0, it["remaining"] / it["full"]))
                p.setBrush(QColor(style.DANGER) if alert else QColor(style.OK))
                p.drawRoundedRect(QRectF(bar.x(), bar.y(), bar.width() * frac, bar.height()), 2.5, 2.5)
            # 시간
            p.setFont(QFont("Malgun Gothic", 11, QFont.Bold))
            p.setPen(QColor(style.DANGER) if alert else QColor(style.TEXT))
            txt = "만료" if it["expired"] else format_time(it["remaining"])
            p.drawText(QRectF(W - 140, y + 4, 128, 22), Qt.AlignRight | Qt.AlignVCenter, txt)
            # 상태
            p.setFont(small)
            if it["expired"]:
                st, col = "만료됨", style.DANGER
            elif it["remaining"] is None:
                st, col = "시간 읽는 중", style.MUTED
            elif it["stale"] is not None and it["stale"] > 2.5:
                st, col = f"예측 중 · {int(it['stale'])}초 전 확인", style.ACCENT
            else:
                st, col = ("판독 · 글리프" if it["source"] == "glyph" else "판독 · OCR"), style.MUTED
            if not watched:
                st, col = "알림 끔", style.MUTED
            p.setPen(QColor(col))
            p.drawText(QRectF(W - 200, y + 24, 188, 16), Qt.AlignRight | Qt.AlignVCenter, st)
            p.setOpacity(1.0)


class RenameDialog(QDialog):
    def __init__(self, current, known, parent=None):
        super().__init__(parent)
        self.setWindowTitle("버프 이름 고치기")
        self.setStyleSheet(style.QSS + f"QDialog {{ background: {style.BG}; }}")
        lay = QVBoxLayout(self)
        tip = QLabel(f"인식된 이름: <b>{current}</b><br>올바른 이름을 입력하거나 고르세요.<br>"
                     "이 버프의 이름 글자 모양을 기억해서 다음부터는 항상 이 이름으로 표시합니다.")
        tip.setObjectName("muted")
        tip.setWordWrap(True)
        lay.addWidget(tip)
        self.combo = QComboBox()
        self.combo.setEditable(True)
        self.combo.addItems(known)
        self.combo.setCurrentText(current)
        self.combo.lineEdit().selectAll()
        lay.addWidget(self.combo)
        row = QHBoxLayout()
        row.addStretch()
        cancel = QPushButton("취소")
        cancel.clicked.connect(self.reject)
        ok = QPushButton("저장")
        ok.setObjectName("primary")
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        row.addWidget(cancel)
        row.addWidget(ok)
        lay.addLayout(row)
        self.resize(360, 170)

    def name(self):
        return " ".join(self.combo.currentText().split())


class NamesDialog(QDialog):
    def __init__(self, names, parent=None):
        super().__init__(parent)
        self.setWindowTitle("알려진 버프 이름")
        self.setStyleSheet(style.QSS + f"QDialog {{ background: {style.BG}; }}")
        lay = QVBoxLayout(self)
        tip = QLabel("한 줄에 하나씩 입력하세요. OCR 이 이름을 조금 틀리게 읽어도 이 목록으로 보정합니다.")
        tip.setObjectName("muted")
        tip.setWordWrap(True)
        lay.addWidget(tip)
        self.edit = QPlainTextEdit("\n".join(names))
        lay.addWidget(self.edit)
        row = QHBoxLayout()
        row.addStretch()
        ok = QPushButton("저장")
        ok.setObjectName("primary")
        ok.clicked.connect(self.accept)
        cancel = QPushButton("취소")
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        row.addWidget(ok)
        lay.addLayout(row)
        self.resize(380, 420)

    def names(self):
        return [n.strip() for n in self.edit.toPlainText().splitlines() if n.strip()]


class Launcher(QMainWindow):
    def __init__(self, restarted: bool = False):
        super().__init__()
        self.cfg = config.load()
        self.book = GlyphBook(config.GLYPH_PATH)
        self.worker = MonitorWorker(self.cfg, self.book)
        self.worker.snapshot.connect(self._on_snapshot)
        self.worker.failed.connect(self._on_error)
        self.worker.scanned.connect(self._on_scanned)
        self.worker.debuff_scanned.connect(self._on_debuff_scanned)
        self.worker.debuff_snapshot.connect(self._on_debuff_snapshot)
        self.debuff_book = DebuffBook()
        self.worker.set_debuff_items([i for i in self.debuff_book.items if i["watch"]])
        self.debuff_scores = {}             # 디버프 id -> 일치 점수
        self.debuff_secs = {}               # 디버프 id -> 아이콘 아래 남은 시간(초)
        self.debuff_bar = False             # 대상 체력바가 보이는지
        self.debuff_t = 0.0                 # 마지막 디버프 확인 시각
        self.debuff_missing_since = {}      # 디버프 id -> 없어진 시각
        self.debuff_alerted = set()
        self.last_debuff_beep = 0.0
        self.alert = AlertWindow(self.cfg)
        self.alert.moved.connect(lambda _: self._save())
        self.alert.collapse_toggled.connect(self._on_alert_collapsed)
        self.debuff_alert = AlertWindow(self.cfg, prefix="debuff_alert", title="디버프 갱신", default_pos=(200, 420))
        self.debuff_alert.moved.connect(lambda _: self._save())
        self.debuff_alert.collapse_toggled.connect(lambda _: self._save())
        self.presence_alert = AlertWindow(self.cfg, prefix="presence_alert", title="붕괴 알림", default_pos=(200, 620))
        self.presence_alert.moved.connect(lambda _: self._save())
        self.presence_alert.collapse_toggled.connect(lambda _: self._save())
        self.presence_alerted = set()
        self.summoners = [AutoSummon(self.cfg, g) for g in GROUPS]      # 자동 투안, 자동 햄
        self.hotkey = GlobalHotkey(self.cfg.get("hotkey", "F10"))
        self.hotkey.pressed.connect(self.select_region)
        self.hotkey.failed.connect(self._on_error)
        self.debuff_hotkey = GlobalHotkey(self.cfg.get("debuff_hotkey", "F11"))
        self.debuff_hotkey.pressed.connect(self.select_debuff_region)
        self.selector = None
        self.snapshot = None
        self.pixmaps = {}
        self.alerted = {}          # buff key -> 마지막으로 알림 상태였던 시각
        self.last_beep = 0.0
        self.running = False
        self.picking = False
        self.cfg.setdefault("watch", {})
        self.restart_pending = False
        self.restarting = False

        self.setWindowTitle(instance.WINDOW_TITLE)
        self.setWindowIcon(QIcon(str(ICON_PATH)))
        self.setStyleSheet(style.QSS)
        self._build()
        geo = self.cfg.get("window_geometry")
        if geo:
            self.setGeometry(*geo)
        else:
            self.resize(940, 640)

        # 코드 변경 자동 재시작은 소스로 실행할 때(개발)만
        self.watcher = None
        if not FROZEN:
            self.watcher = CodeWatcher()
            self.watcher.ready.connect(self._on_code_changed)
            self.watcher.error.connect(self._on_error)
        self.updater = Updater()
        self.updater.checked.connect(self._on_update_checked)
        self.updater.progress.connect(lambda m: self.update_btn.setText(m))
        self.updater.failed.connect(self._on_update_failed)
        self.updater.ready_to_restart.connect(self._restart_after_update)
        self.update_newer = False
        self.update_manual = False
        QTimer.singleShot(1500, self._check_updates)
        # 켜 둔 채로 있어도 새 버전을 알 수 있게 30분마다 다시 확인
        self.update_timer = QTimer(self)
        self.update_timer.timeout.connect(lambda: None if self.update_newer else self._check_updates())
        self.update_timer.start(30 * 60 * 1000)
        if restarted:
            QTimer.singleShot(1500, lambda: self.status_lbl.setText("코드 변경을 감지해 자동으로 다시 시작했습니다"))

        self.ui_timer = QTimer(self)
        self.ui_timer.timeout.connect(self._refresh)
        self.ui_timer.start(200)

        self.worker.start()
        self.hotkey.start()
        self.debuff_hotkey.start()
        self.alert.set_locked(bool(self.cfg.get("alert_locked")))
        self.debuff_alert.set_locked(bool(self.cfg.get("alert_locked")))
        self.presence_alert.set_locked(bool(self.cfg.get("alert_locked")))
        self._update_region_label()
        if self.cfg.get("region"):
            self.set_running(True)

    # ---------- UI 구성 ----------
    def _build(self):
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(22, 20, 22, 20)
        outer.setSpacing(16)

        # 헤더
        head = QHBoxLayout()
        tbox = QVBoxLayout()
        tbox.setSpacing(2)
        logo = QLabel()
        logo.setPixmap(QIcon(str(ICON_PATH)).pixmap(40, 40))
        head.addWidget(logo)
        head.addSpacing(10)
        t = QLabel(instance.APP_NAME)
        t.setObjectName("title")
        sub = QLabel("마비노기 버프·디버프 남은 시간 감시 · 갱신 알림")
        sub.setObjectName("subtitle")
        tbox.addWidget(t)
        tbox.addWidget(sub)
        head.addLayout(tbox)
        head.addStretch()
        self.learn_lbl = QLabel()
        self.learn_lbl.setObjectName("muted")
        head.addWidget(self.learn_lbl)
        head.addSpacing(12)
        ver = QLabel(f"v{__version__}")
        ver.setObjectName("muted")
        head.addWidget(ver, 0, Qt.AlignVCenter)
        notes = QPushButton("패치노트")
        notes.setObjectName("secondary")
        notes.clicked.connect(self._show_notes)
        head.addWidget(notes, 0, Qt.AlignVCenter)
        self.update_btn = QPushButton("업데이트 확인 중…")
        self.update_btn.setObjectName("update")
        self.update_btn.setEnabled(False)
        self.update_btn.clicked.connect(self._on_update_btn)
        head.addWidget(self.update_btn, 0, Qt.AlignVCenter)
        head.addSpacing(12)
        self.pill = QLabel()
        self.pill.setObjectName("pill")
        self.pill.setFixedHeight(24)
        head.addWidget(self.pill, 0, Qt.AlignVCenter)
        outer.addLayout(head)

        body = QHBoxLayout()
        body.setSpacing(16)
        outer.addLayout(body, 1)

        # 왼쪽: 영역 + 설정
        left = QVBoxLayout()
        left.setSpacing(16)
        body.addLayout(left, 5)

        c, lay = card("감시 영역")
        self.preview = QLabel(f"{self.cfg['hotkey']} 를 눌러 게임 화면의 버프 목록을 드래그하세요")
        self.preview.setObjectName("preview")
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumHeight(200)
        self.preview.setWordWrap(True)
        lay.addWidget(self.preview, 1)
        self.region_lbl = QLabel()
        self.region_lbl.setObjectName("muted")
        lay.addWidget(self.region_lbl)
        btns = QHBoxLayout()
        self.sel_btn = QPushButton()
        self.sel_btn.setObjectName("primary")
        self.sel_btn.clicked.connect(self.select_region)
        self.run_btn = QPushButton("감시 시작")
        self.run_btn.clicked.connect(lambda: self.set_running(not self.running))
        self.pick_btn = QPushButton("버프 선택")
        self.pick_btn.setToolTip("현재 영역의 버프 목록을 불러와 알림 받을 버프를 고르고 이름을 고칩니다")
        self.pick_btn.clicked.connect(self.scan)
        btns.addWidget(self.sel_btn, 3)
        btns.addWidget(self.pick_btn, 2)
        btns.addWidget(self.run_btn, 2)
        lay.addLayout(btns)
        left.addWidget(c, 3)

        c, lay = card("설정")
        g = QGridLayout()
        g.setHorizontalSpacing(14)
        g.setVerticalSpacing(10)

        def spin(key, lo, hi, step, suffix, dbl=False, apply=None):
            w = QDoubleSpinBox() if dbl else QSpinBox()
            w.setRange(lo, hi)
            w.setSingleStep(step)
            w.setSuffix(suffix)
            w.setValue(self.cfg[key])

            def changed(v):
                self.cfg[key] = v
                if apply:
                    apply()
                self._save()
            w.valueChanged.connect(changed)
            return w

        def lbl(text):
            x = QLabel(text)
            x.setObjectName("muted")
            return x

        g.addWidget(lbl("알림 기준"), 0, 0)
        g.addWidget(spin("threshold_sec", 5, 600, 5, " 초 이하"), 0, 1)
        g.addWidget(lbl("체크 주기"), 0, 2)
        interval = spin("interval_ms", 200, 900, 50, " ms")
        interval.setToolTip("숫자 자동 학습은 1초 미만 간격일 때만 동작합니다.")
        g.addWidget(interval, 0, 3)
        g.addWidget(lbl("알림창 크기"), 1, 0)
        g.addWidget(spin("alert_scale", 0.8, 2.5, 0.1, " 배", True,
                         lambda: [w.refresh_style() for w in self._overlays()]), 1, 1)
        g.addWidget(lbl("알림창 투명도"), 1, 2)
        g.addWidget(spin("alert_opacity", 0.2, 1.0, 0.05, "", True,
                         lambda: [w.update() for w in self._overlays()]), 1, 3)
        g.addWidget(lbl("만료 표시 유지"), 2, 0)
        g.addWidget(spin("expired_keep_sec", 0, 60, 1, " 초"), 2, 1)
        g.addWidget(lbl("영역 지정 키"), 2, 2)
        self.key_combo = QComboBox()
        self.key_combo.addItems(list(VK))
        self.key_combo.setCurrentText(self.cfg["hotkey"])
        self.key_combo.currentTextChanged.connect(self._change_hotkey)
        g.addWidget(self.key_combo, 2, 3)
        self.collapse_chk = QCheckBox("알림창 이름 접기 (아이콘+시간만)")
        self.collapse_chk.setChecked(bool(self.cfg.get("alert_collapsed")))
        self.collapse_chk.toggled.connect(self._set_collapsed)
        g.addWidget(self.collapse_chk, 3, 0, 1, 4)
        lay.addLayout(g)

        checks = QHBoxLayout()
        buff_snd = self._sound_row("sound", "buff_volume", "버프 알림음", "체크한 버프가 30초 이하가 될 때 '띵'",
                                   [("♪", "들어보기", lambda: sound.play("buff", self.cfg.get("buff_volume", 40)))])
        self.lock_chk = QCheckBox("알림창 잠금 (클릭 통과)")
        self.lock_chk.setChecked(bool(self.cfg["alert_locked"]))
        self.lock_chk.setToolTip("해제하면 알림창을 드래그해서 옮길 수 있습니다.")
        self.lock_chk.toggled.connect(self._toggle_lock)
        self.outline_chk = QCheckBox("외곽선 검사")
        self.outline_chk.setChecked(self.cfg["outline_check"])
        self.outline_chk.setToolTip("글자 주변 검은 테두리가 있는 픽셀만 글자로 인정합니다.\n"
                                    "빨간 배경 오인식을 막아 줍니다. 글자를 전혀 못 찾을 때만 끄세요.")
        self.outline_chk.toggled.connect(lambda v: (self.cfg.__setitem__("outline_check", v), self._save()))
        checks.addWidget(self.lock_chk)
        checks.addWidget(self.outline_chk)
        self.reload_chk = QCheckBox("코드 변경 시 자동 재시작")
        self.reload_chk.setChecked(self.cfg.get("auto_reload", True))
        self.reload_chk.setToolTip("프로그램 파일이 바뀌면 설정·위치를 유지한 채 알아서 다시 시작합니다.")
        self.reload_chk.toggled.connect(lambda v: (self.cfg.__setitem__("auto_reload", v), self._save()))
        checks.addWidget(self.reload_chk)
        self.admin_chk = QCheckBox("UAC 창 없이 실행")
        self.admin_chk.setToolTip("켜면 처음 한 번만 관리자 권한을 묻고, 다음부터는 묻지 않고 관리자로 실행합니다\n"
                                  "(Windows 작업 스케줄러에 이 프로그램 전용 작업을 등록)")
        self.admin_chk.setChecked(self.cfg.get("admin_task", True))
        self.admin_chk.toggled.connect(self._toggle_admin_task)
        self.reload_chk.setVisible(not FROZEN)
        checks.addStretch()
        lay.addLayout(checks)
        lay.addLayout(buff_snd)
        adm = QHBoxLayout()
        adm.addWidget(self.admin_chk)
        adm.addStretch()
        lay.addLayout(adm)

        more = QHBoxLayout()
        names_btn = QPushButton("버프 이름 목록")
        names_btn.setObjectName("ghost")
        names_btn.clicked.connect(self._edit_names)
        reset_btn = QPushButton("숫자 학습 초기화")
        reset_btn.setObjectName("ghost")
        reset_btn.clicked.connect(self._reset_glyphs)
        self.pos_btn = QPushButton("알림창·영역 위치 조정")
        self.pos_btn.setToolTip("알림창을 옮기고, 캡처 영역(버프·디버프)도 화면에서 드래그로 옮기거나 크기를 바꿉니다")
        self.region_frames = []
        self.pos_btn.setObjectName("ghost")
        self.pos_btn.clicked.connect(self._toggle_positioning)
        more.addWidget(self.pos_btn)
        more.addWidget(names_btn)
        more.addWidget(reset_btn)
        more.addStretch()
        lay.addLayout(more)
        left.addWidget(c, 2)

        # 오른쪽: 버프 현황
        c, lay = card("버프 현황")
        self.board = BuffBoard()
        self.board.clicked.connect(self._rename)
        self.board.toggled.connect(self._toggle_watch)
        lay.addWidget(self.board)
        lay.addStretch()
        self.status_lbl = QLabel()
        self.status_lbl.setObjectName("muted")
        self.status_lbl.setWordWrap(True)
        lay.addWidget(self.status_lbl)
        self.tabs = QTabWidget()
        self.tabs.addTab(c, "버프 현황")
        self.tabs.addTab(self._build_summon_tab(), "자동 소환")
        self.tabs.addTab(self._build_debuff_card(), "디버프")
        body.addWidget(self.tabs, 4)

        self.foot = foot = QLabel("Esc/우클릭 취소  ·  빨간 배경 등으로 시간이 가려지면 마지막 판독값으로 카운트다운을 이어갑니다")
        foot.setObjectName("muted")
        outer.addWidget(foot)
        self._set_pill()
        self._update_hotkey_labels()

    def _build_summon_tab(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        self.summon_cards = [SummonCard(a, self._save) for a in self.summoners]
        for c in self.summon_cards:
            lay.addWidget(c)
        warn = QLabel("※ 게임에 키를 보내는 기능입니다. 매크로 사용은 게임 약관상 제재될 수 있으니 주의하세요.")
        warn.setStyleSheet(f"color: {style.MUTED}; font-size: 11px;")
        warn.setWordWrap(True)
        lay.addWidget(warn)
        lay.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(page)
        scroll.setStyleSheet("QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }")
        return scroll

    def _update_tuan_targets(self):
        for c in getattr(self, "summon_cards", []):
            c.update_targets()

    # ---------- 업데이트 / 패치노트 ----------
    def _set_update_btn(self, text, tip, mode):
        """mode: 'newer' 새 버전 있음(초록) / 'check' 눌러서 다시 확인 / 'busy' 확인·받는 중"""
        b = self.update_btn
        b.setObjectName("update" if mode == "newer" else "secondary")
        b.style().unpolish(b)
        b.style().polish(b)
        b.setText(text)
        b.setToolTip(tip)
        b.setEnabled(mode != "busy")
        self.update_newer = mode == "newer"

    def _check_updates(self, manual=False):
        if self.update_btn.text().startswith("받는 중"):
            return
        self.update_manual = manual
        self._set_update_btn("확인 중…", "", "busy")
        self.updater.check_async()

    def _on_update_btn(self):
        if self.update_newer and FROZEN:
            self._do_update()
        else:
            self._check_updates(manual=True)

    def _on_update_checked(self, info):
        if info.get("error"):
            self._set_update_btn("다시 확인", f"업데이트 확인 실패 · 눌러서 다시 확인\n{info['error']}", "check")
        elif info.get("newer"):
            tip = ("눌러서 새 버전을 받고 다시 시작합니다 (설정은 그대로 유지)" if FROZEN
                   else "소스로 실행 중이라 자동 업데이트는 exe 에서만 됩니다")
            self._set_update_btn(f"업데이트 v{info['latest']}", tip, "newer")
            self.status_lbl.setText(f"새 버전 v{info['latest']} 이 있습니다 · 오른쪽 위 버튼으로 업데이트")
        else:
            self._set_update_btn("최신 버전 ↻", f"현재 v{__version__} (최신) · 눌러서 다시 확인", "check")
            if self.update_manual:
                self.status_lbl.setText(f"이미 최신 버전입니다 (v{__version__})")
        self.update_manual = False

    def _do_update(self):
        self._set_update_btn("받는 중…", "", "busy")
        self.updater.apply_async()

    def _on_update_failed(self, msg):
        self._set_update_btn("업데이트 다시 시도", msg, "newer")
        self._on_error(msg)

    def _restart_after_update(self):
        self.restarting = True
        self.close()

    def _show_notes(self):
        info = self.updater.info or {}
        NotesDialog(info.get("notes") or cached_notes(), self).exec()

    def _toggle_admin_task(self, v):
        self.cfg["admin_task"] = v
        self._save()
        if not elevate.is_admin():
            self.status_lbl.setText("관리자 권한으로 실행 중이 아니라 다음 실행 때 적용됩니다")
            return
        if v:
            ok = elevate.register_task()
            self.status_lbl.setText("다음부터 UAC 창 없이 실행합니다" if ok else "작업 등록에 실패했습니다")
        else:
            elevate.remove_task()
            self.status_lbl.setText("다음부터 실행할 때마다 관리자 권한을 묻습니다")

    def _set_collapsed(self, v):
        self.alert.set_collapsed(v)
        self._save()

    def _on_alert_collapsed(self, v):
        self.collapse_chk.blockSignals(True)
        self.collapse_chk.setChecked(v)
        self.collapse_chk.blockSignals(False)
        self._save()

    # ---------- 디버프 ----------
    def _build_debuff_card(self):
        c, lay = card("디버프")
        tip = QLabel(f"{self.cfg.get('debuff_hotkey', 'F11')} 로 대상(보스)의 디버프 아이콘 줄과 그 아래 체력바까지 "
                     "영역을 지정하세요. 체력바가 보일 때(보스를 선택했을 때)만, 체크한 디버프가 없거나 "
                     "아래 시간이 30초 이하(숫자만 표시)면 '디버프 갱신' 창에 알려 드려요.")
        tip.setObjectName("muted")
        tip.setWordWrap(True)
        lay.addWidget(tip)
        btns = QHBoxLayout()
        reg = QPushButton(f"영역 지정  ({self.cfg.get('debuff_hotkey', 'F11')})")
        reg.setObjectName("primary")
        reg.clicked.connect(self.select_debuff_region)
        self.debuff_scan_btn = QPushButton("아이콘 등록")
        self.debuff_scan_btn.setToolTip("새 디버프를 추가할 때만: 지금 디버프 줄에 보이는 아이콘을 찾아 등록합니다")
        self.debuff_scan_btn.clicked.connect(self.scan_debuffs)
        btns.addWidget(reg, 1)
        btns.addWidget(self.debuff_scan_btn, 1)
        lay.addLayout(btns)
        opts = QHBoxLayout()
        en = QCheckBox("디버프 감시")
        en.setChecked(self.cfg.get("debuff_enabled", True))
        en.toggled.connect(lambda v: (self.cfg.__setitem__("debuff_enabled", v), self._save()))
        hide = QCheckBox("하나도 없으면 숨김")
        hide.setToolTip("등록한 디버프가 하나도 안 보이면(대상을 안 잡았을 때 등) 창을 숨깁니다")
        hide.setChecked(self.cfg.get("debuff_hide_when_none", False))
        hide.toggled.connect(lambda v: (self.cfg.__setitem__("debuff_hide_when_none", v), self._save()))
        need_bar = QCheckBox("체력바 보일 때만")
        need_bar.setToolTip("영역에 대상 체력바가 보일 때(보스를 선택했을 때)만 디버프를 확인합니다")
        need_bar.setChecked(self.cfg.get("debuff_need_hpbar", True))
        need_bar.toggled.connect(lambda v: (self.cfg.__setitem__("debuff_need_hpbar", v), self._save()))
        opts.addWidget(en)
        opts.addWidget(need_bar)
        opts.addWidget(hide)
        snd = self._sound_row("debuff_sound", "debuff_volume", "디버프 알림음",
                              "디버프가 없거나 30초 이하면 '딩-동', 붕괴처럼 '있으면 알림' 디버프는 이름을 음성으로 말합니다",
                              [("♪", "딩-동 들어보기", lambda: sound.play("debuff", self.cfg.get("debuff_volume", 40))),
                               ("음성", "음성 들어보기 (붕괴)", lambda: sound.speak("붕괴", self.cfg.get("debuff_volume", 40)))])
        opts.addStretch()
        opts.addWidget(QLabel("지정 키"))
        dk = QComboBox()
        dk.addItems(list(VK))
        dk.setCurrentText(self.cfg.get("debuff_hotkey", "F11"))
        dk.currentTextChanged.connect(self._change_debuff_hotkey)
        opts.addWidget(dk)
        lay.addLayout(opts)
        lay.addLayout(snd)
        self.debuff_region_lbl = QLabel()
        self.debuff_region_lbl.setObjectName("muted")
        lay.addWidget(self.debuff_region_lbl)
        self.debuff_state_lbl = QLabel()
        lay.addWidget(self.debuff_state_lbl)
        self.debuff_list = QVBoxLayout()
        self.debuff_list.setSpacing(6)
        lay.addLayout(self.debuff_list)
        lay.addStretch()
        self._rebuild_debuff_list()
        return c

    def _rebuild_debuff_list(self):
        while self.debuff_list.count():
            item = self.debuff_list.takeAt(0)
            sub = item.layout()
            widgets = [item.widget()] if item.widget() else []
            while sub is not None and sub.count():
                widgets.append(sub.takeAt(0).widget())
            for w in widgets:
                if w:
                    w.hide()
                    w.setParent(None)
                    w.deleteLater()
        self.debuff_status = {}
        self._update_debuff_region_label()
        if not self.debuff_book.items:
            empty = QLabel("등록한 디버프가 없습니다")
            empty.setObjectName("muted")
            self.debuff_list.addWidget(empty)
            return
        for it in self.debuff_book.items:
            row = QHBoxLayout()
            chk = QCheckBox()
            chk.setChecked(it["watch"])
            chk.setToolTip("없으면 알림")
            chk.toggled.connect(lambda v, did=it["id"]: self._set_debuff_watch(did, v))
            row.addWidget(chk)
            ic = QLabel()
            ic.setPixmap(to_pixmap(it["icons"][0]).scaled(30, 30, Qt.KeepAspectRatio, Qt.FastTransformation))
            ic.setFixedSize(32, 32)
            row.addWidget(ic)
            name = QLabel(it["name"] + (f"  (아이콘 {len(it['icons'])})" if len(it["icons"]) > 1 else ""))
            name.setStyleSheet("font-weight: 700;")
            row.addWidget(name, 1)
            if len(it["icons"]) > 1:
                need_all = QCheckBox("모두 있어야")
                need_all.setToolTip("체크: 아이콘이 모두 있어야 '있음' (예: 프라가라흐)\n해제: 하나만 있어도 '있음' (예: 데마)")
                need_all.setChecked(it.get("mode") == "all")
                need_all.toggled.connect(lambda v, did=it["id"]: self._set_debuff_prop(did, "mode", "all" if v else "any"))
                row.addWidget(need_all)
            kind = QComboBox()
            kind.addItem("없으면 알림", KIND_REFRESH)
            kind.addItem("있으면 알림", KIND_PRESENCE)
            kind.setCurrentIndex(1 if it.get("kind") == KIND_PRESENCE else 0)
            kind.setToolTip("없으면 알림: 없거나 30초 이하면 '디버프 갱신' 창\n있으면 알림: 생기면 '디버프 발생' 창 (예: 붕괴)")
            kind.currentIndexChanged.connect(lambda _, did=it["id"], c_=kind: self._set_debuff_prop(did, "kind", c_.currentData()))
            row.addWidget(kind)
            st = QLabel("—")
            st.setMinimumWidth(56)
            st.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.debuff_status[it["id"]] = st
            row.addWidget(st)
            rm = QPushButton("✕")
            rm.setObjectName("ghost")
            rm.setToolTip("등록 삭제")
            rm.clicked.connect(lambda _=False, did=it["id"]: self._remove_debuff(did))
            row.addWidget(rm)
            self.debuff_list.addLayout(row)

    def _update_debuff_region_label(self):
        r = self.cfg.get("debuff_region")
        self.debuff_region_lbl.setText(f"영역: x {r[0]}, y {r[1]}  ·  {r[2]} × {r[3]} px" if r else "영역이 지정되지 않았습니다")

    def _debuffs_changed(self):
        self.debuff_book.save()
        self.worker.set_debuff_items([i for i in self.debuff_book.items if i["watch"]])
        self.debuff_missing_since.clear()
        self._rebuild_debuff_list()

    def _set_debuff_prop(self, did, key, value):
        it = self.debuff_book.get(did)
        if it is not None:
            it[key] = value
            self._debuffs_changed()

    def _sound_row(self, on_key, vol_key, label, tip, tests):
        """[알림음 켜기] [음량 슬라이더] [값] [들어보기…]"""
        row = QHBoxLayout()
        chk = QCheckBox(label)
        chk.setToolTip(tip)
        chk.setChecked(self.cfg.get(on_key, True))
        chk.toggled.connect(lambda v: (self.cfg.__setitem__(on_key, v), self._save()))
        row.addWidget(chk)
        vol = QSlider(Qt.Horizontal)
        vol.setRange(0, 100)
        vol.setValue(int(self.cfg.get(vol_key, 40)))
        vol.setFixedWidth(120)
        vol.setToolTip("음량")
        val = QLabel(f"{vol.value()}%")
        val.setObjectName("muted")
        val.setFixedWidth(36)
        vol.valueChanged.connect(lambda v: (self.cfg.__setitem__(vol_key, v), val.setText(f"{v}%")))
        vol.sliderReleased.connect(self._save)
        row.addWidget(QLabel("음량"))
        row.addWidget(vol)
        row.addWidget(val)
        for text, t_tip, fn in tests:
            b = QPushButton(text)
            b.setObjectName("ghost")
            b.setToolTip(t_tip)
            b.clicked.connect(lambda _=False, f=fn: f())
            row.addWidget(b)
        row.addStretch()
        return row

    def _overlays(self):
        return [self.alert, self.debuff_alert, self.presence_alert]

    def _set_debuff_watch(self, did, v):
        for it in self.debuff_book.items:
            if it["id"] == did:
                it["watch"] = v
        self._debuffs_changed()

    def _remove_debuff(self, did):
        self.debuff_book.remove(did)
        self._debuffs_changed()

    def _change_debuff_hotkey(self, key):
        self.cfg["debuff_hotkey"] = key
        self.debuff_hotkey.set_key(key)
        self._save()

    def select_debuff_region(self):
        if self.selector is not None:
            return
        self.selector = RegionSelector("보스를 선택한 상태에서 디버프 아이콘 줄과 그 아래 체력바까지 드래그하세요")
        self.selector.selected.connect(self._on_debuff_region)
        self.selector.destroyed.connect(lambda: setattr(self, "selector", None))
        self.selector.show()

    def _on_debuff_region(self, r):
        """영역만 지정 (디버프는 이미 등록돼 있음). 새 아이콘 등록은 디버프 탭의 '아이콘 등록' 버튼으로."""
        self.cfg["debuff_region"] = r
        self._save()
        self._rebuild_debuff_list()
        self.tabs.setCurrentIndex(2)
        if not self.running:
            self.set_running(True)

    def scan_debuffs(self):
        if not self.cfg.get("debuff_region"):
            self.select_debuff_region()
            return
        self.debuff_scan_btn.setText("찾는 중…")
        self.debuff_scan_btn.setEnabled(False)
        self.worker.request_debuff_scan()

    def _on_debuff_scanned(self, scan):
        self.debuff_scan_btn.setText("아이콘 등록")
        self.debuff_scan_btn.setEnabled(True)
        if self.picking:
            return
        self.picking = True
        self.showNormal()
        self.raise_()
        self.activateWindow()
        self.tabs.setCurrentIndex(2)
        d = DebuffRegisterDialog(scan, self.debuff_book, self.cfg.get("debuff_preset"), self)
        ok = d.exec()
        self.picking = False
        if ok:
            d.apply()
            self._debuffs_changed()

    def _on_debuff_snapshot(self, snap):
        self.debuff_scores = snap["scores"]
        self.debuff_bar = snap.get("bar", True)
        self.debuff_secs = snap.get("secs", {})
        self.debuff_t = snap["t"]

    def _refresh_debuffs(self, now):
        """없어진(일치 점수 낮은) 체크 디버프를 잠깐(깜빡임 대비) 지켜본 뒤 '디버프 갱신' 창에 표시."""
        fresh = (self.running and self.cfg.get("debuff_enabled", True) and self.cfg.get("debuff_region")
                 and now - self.debuff_t < 3.0)
        active = fresh and self.debuff_bar           # 체력바가 있을 때만 (보스를 선택했을 때만) 확인
        if not active:
            self.debuff_missing_since.clear()
        if hasattr(self, "debuff_state_lbl"):
            if not fresh:
                txt, col = "감시 안 함", style.MUTED
            elif not self.debuff_bar:
                txt, col = "체력바 없음 · 확인 안 함 (보스를 선택하면 확인합니다)", style.MUTED
            else:
                txt, col = "체력바 확인됨 · 디버프 확인 중", style.OK
            self.debuff_state_lbl.setText(txt)
            self.debuff_state_lbl.setStyleSheet(f"color: {col}; font-size: 12px; font-weight: 600;")
        watched = [i for i in self.debuff_book.items if i["watch"] and i.get("kind", KIND_REFRESH) == KIND_REFRESH]
        presence = [i for i in self.debuff_book.items if i["watch"] and i.get("kind") == KIND_PRESENCE]
        th_d = float(self.cfg.get("debuff_threshold_sec", 30))
        present = {i["id"]: self.debuff_scores.get(i["id"], 0.0) >= MATCH_MIN for i in self.debuff_book.items}
        for it in self.debuff_book.items:
            st = self.debuff_status.get(it["id"])
            if st is None:
                continue
            if not active or it["id"] not in self.debuff_scores:
                st.setText("—")
                st.setStyleSheet(f"color: {style.MUTED};")
            elif it.get("kind") == KIND_PRESENCE:
                on = present[it["id"]]
                st.setText("들어감!" if on else "없음")
                st.setStyleSheet(f"color: {style.DANGER if on else style.MUTED}; font-weight: 700;")
            elif present[it["id"]]:
                sec = self.debuff_secs.get(it["id"])
                low = sec is not None and sec <= th_d
                st.setText(("있음" if sec is None else format_time(sec)) if not low else f"{sec}초")
                st.setStyleSheet(f"color: {style.ACCENT if low else style.OK}; font-weight: 700;")
            else:
                st.setText("없음")
                st.setStyleSheet(f"color: {style.DANGER}; font-weight: 700;")
        missing, low = [], []
        if active:
            wait = float(self.cfg.get("debuff_missing_sec", 1.0))
            for it in watched:
                if present.get(it["id"]):
                    self.debuff_missing_since.pop(it["id"], None)
                    sec = self.debuff_secs.get(it["id"])
                    if sec is not None and sec <= th_d:        # '5M' 이 아니라 30초 이하 숫자
                        low.append((it, sec))
                    continue
                since = self.debuff_missing_since.setdefault(it["id"], now)
                if now - since >= wait:
                    missing.append(it)
            if self.cfg.get("debuff_hide_when_none") and not any(present.get(i["id"]) for i in watched):
                missing, low = [], []
        items = [{"name": i["name"], "missing": True, "remaining": None, "expired": False,
                  "pixmap": to_pixmap(i["icons"][0])} for i in missing]
        items += [{"name": i["name"], "missing": False, "remaining": float(sec), "expired": False,
                   "pixmap": to_pixmap(i["icons"][0])} for i, sec in sorted(low, key=lambda x: x[1])]
        self.debuff_alert.set_items(items)
        ids = {i["id"] for i in missing} | {i["id"] for i, _ in low}
        if self.cfg.get("debuff_sound", True) and ids - self.debuff_alerted and now - self.last_debuff_beep > 3:
            sound.play("debuff", self.cfg.get("debuff_volume", 40))
            self.last_debuff_beep = now
        self.debuff_alerted = ids

        # 있으면 알림 (붕괴 등): 별도 알림창 + 음성으로 이름을 한 번 말함 (디버프 알림음 설정을 따름)
        occurred = [i for i in presence if active and present.get(i["id"])]
        self.presence_alert.set_items([{"name": i["name"], "missing": True, "tag": "들어감",
                                        "remaining": None, "expired": False, "pixmap": to_pixmap(i["icons"][0])}
                                       for i in occurred])
        pids = {i["id"] for i in occurred}
        if self.cfg.get("debuff_sound", True):
            for i in occurred:
                if i["id"] not in self.presence_alerted:
                    sound.speak(i["name"], self.cfg.get("debuff_volume", 40))
        self.presence_alerted = pids

    # ---------- 동작 ----------
    def select_region(self):
        if self.selector is not None:
            return
        self.selector = RegionSelector()
        self.selector.selected.connect(self._on_region)
        self.selector.destroyed.connect(lambda: setattr(self, "selector", None))
        self.selector.show()

    def _on_region(self, r):
        self.cfg["region"] = r
        self._save()
        self._update_region_label()
        self.worker.set_paused(True)
        self.set_running(True)
        self.scan()

    def scan(self):
        if not self.cfg.get("region"):
            self.select_region()
            return
        if not self.running:
            self.set_running(True)
        self.pick_btn.setText("불러오는 중…")
        self.pick_btn.setEnabled(False)
        self.worker.request_scan()

    def _on_scanned(self, rows):
        self.pick_btn.setEnabled(True)
        self._update_pick_label()
        if self.picking:
            return
        self.picking = True
        self.showNormal()
        self.raise_()
        self.activateWindow()
        d = BuffPickDialog(rows, self.cfg, self)
        ok = d.exec()
        self.picking = False
        if not ok:
            return
        pairs = []
        for r, name, watched in d.result_rows():
            self.cfg["watch"][name] = watched
            if name not in self.cfg["known_names"]:
                self.cfg["known_names"].append(name)
            pairs.append((r["bits"], name))     # 확인한 이름은 모두 기억
        self.worker.apply_names(pairs)
        for key, states in d.summon_states().items():
            self.cfg.setdefault(f"auto_{key}", {}).update(states)
        self._update_tuan_targets()
        self._save()

    def _toggle_watch(self, name):
        self.cfg["watch"][name] = not self.cfg["watch"].get(name, False)
        self._save()

    def _toggle_positioning(self):
        """알림창 위치 + 캡처 영역(버프·디버프)을 화면에서 함께 조정."""
        on = not self.alert.positioning
        for w in self._overlays():
            w.set_positioning(on)
            w.set_items(w.items)
        if on:
            for key, label, color in (("region", "버프 영역", style.ACCENT), ("debuff_region", "디버프 영역", "#6fb7ff")):
                r = self.cfg.get(key)
                if r:
                    f = RegionFrame(r, label, color)
                    f.changed.connect(lambda reg, k=key: self._on_frame_changed(k, reg))
                    f.show()
                    self.region_frames.append(f)
        else:
            self._close_region_frames()
            self._save()
        self.pos_btn.setText("위치 조정 완료" if on else "알림창·영역 위치 조정")

    def _close_region_frames(self):
        for f in self.region_frames:
            f.close()
        self.region_frames = []

    def _on_frame_changed(self, key, reg):
        """영역 틀을 놓을 때마다 바로 저장 → 감시도 새 영역으로 (버프 영역이면 이름 열 위치를 다시 찾음)."""
        self.cfg[key] = reg
        if key == "region":
            self._update_region_label()
        else:
            self._update_debuff_region_label()
        self._save()

    def _update_pick_label(self, new_count=0):
        if self.pick_btn.isEnabled():
            self.pick_btn.setText(f"버프 선택 · 미등록 {new_count}" if new_count else "버프 선택")

    def set_running(self, on: bool):
        if on and not self.cfg.get("region") and not self.cfg.get("debuff_region"):
            self.select_region()
            return
        self.running = on
        self.worker.set_paused(not on)
        self.run_btn.setText("감시 정지" if on else "감시 시작")
        self.run_btn.setObjectName("danger" if on else "")
        self.run_btn.setStyle(self.run_btn.style())
        if not on:
            self.snapshot = None
            self.alert.set_items([])
            self.debuff_alert.set_items([])
            self.presence_alert.set_items([])
        self._set_pill()

    def _set_pill(self, err=False):
        if err:
            text, bg, fg = "오류", "#3a1d20", style.DANGER
        elif self.running:
            text, bg, fg = "● 감시 중", "#16301f", style.OK
        else:
            text, bg, fg = "대기", style.CARD2, style.MUTED
        self.pill.setText(text)
        self.pill.setStyleSheet(f"background:{bg}; color:{fg};")

    def _change_hotkey(self, key):
        self.cfg["hotkey"] = key
        self.hotkey.set_key(key)
        self._update_hotkey_labels()
        self._save()

    def _update_hotkey_labels(self):
        self.sel_btn.setText(f"영역 지정  ({self.cfg['hotkey']})")
        if not self.snapshot:
            self.preview.setText(f"{self.cfg['hotkey']} 를 눌러 게임 화면의 버프 목록을 드래그하세요")

    def _rename(self, key, current):
        d = RenameDialog(current, self.cfg["known_names"], self)
        if not d.exec() or not d.name():
            return
        name = d.name()
        self.worker.request_rename(key, name)
        if current in self.cfg["watch"] and name not in self.cfg["watch"]:
            self.cfg["watch"][name] = self.cfg["watch"][current]
        if name not in self.cfg["known_names"]:
            self.cfg["known_names"].append(name)
            self._save()

    def _toggle_lock(self, v):
        self.alert.set_locked(v)
        self.debuff_alert.set_locked(v)
        self.presence_alert.set_locked(v)
        self._save()

    def _edit_names(self):
        d = NamesDialog(self.cfg["known_names"], self)
        if d.exec():
            self.cfg["known_names"] = d.names()
            self._save()

    def _reset_glyphs(self):
        if QMessageBox.question(self, "숫자 학습 초기화",
                                "학습한 숫자 모양을 모두 지웁니다. UI 크기/해상도를 바꿨을 때 사용하세요.") \
                == QMessageBox.Yes:
            self.book.reset()
            self.book.save()

    def _update_region_label(self):
        r = self.cfg.get("region")
        self.region_lbl.setText(f"영역: x {r[0]}, y {r[1]}  ·  {r[2]} × {r[3]} px" if r else "영역이 지정되지 않았습니다")

    def _save(self):
        config.save(self.cfg)

    # ---------- 스냅샷 ----------
    def _on_error(self, msg):
        self.status_lbl.setText(msg)
        self._set_pill(err=True)

    def _on_snapshot(self, snap):
        if not self.running:
            return
        self.snapshot = snap
        for b in snap["buffs"]:
            if b["icon"] is not None and b["icon"].size:
                self.pixmaps[b["key"]] = to_pixmap(b["icon"])
        self._draw_preview(snap)
        self.learn_lbl.setText(f"숫자 학습 {snap['learned']}/10")
        self.status_lbl.setText(f"분석 {snap['ms']} ms  ·  감지된 행 {len(snap['rows'])}개")
        self._set_pill()

    def _draw_preview(self, snap):
        pm = to_pixmap(snap["rgb"])
        p = QPainter(pm)
        for name_box, time_box in snap["rows"]:
            p.setPen(QPen(QColor(style.OK), 1))
            x0, y0, x1, y1 = name_box
            p.drawRect(QRectF(x0, y0, x1 - x0, y1 - y0))
            if time_box:
                p.setPen(QPen(QColor(style.ACCENT), 1))
                x0, y0, x1, y1 = time_box
                p.drawRect(QRectF(x0, y0, x1 - x0, y1 - y0))
        p.end()
        target = self.preview.size()
        self.preview.setPixmap(pm.scaled(target.width() - 4, target.height() - 4, Qt.KeepAspectRatio,
                                         Qt.FastTransformation if pm.width() < target.width() / 2
                                         else Qt.SmoothTransformation))

    def _refresh(self):
        th = self.cfg["threshold_sec"]
        now = time.monotonic()
        items = []
        if self.snapshot:
            for b in self.snapshot["buffs"]:
                rem = None if b["expiry"] is None else b["expiry"] - now
                items.append({**b, "remaining": rem, "pixmap": self.pixmaps.get(b["key"]),
                              "watched": self.cfg["watch"].get(base_name(b["name"]), False)})
        self.board.set_items(items, th)
        self._update_pick_label(self.snapshot.get("unknown", 0) if self.snapshot else 0)
        def urgent(i):
            return i["expired"] or (i["remaining"] is not None and i["remaining"] <= th)

        alerts = [i for i in items if i["watched"] and urgent(i)]
        if self.cfg.get("expired_keep_sec", 8) == 0:
            alerts = [i for i in alerts if not i["expired"]]
        # 기준 시간 이하만: 남은 시간 적은 순 → 만료
        alerts.sort(key=lambda i: (i["expired"], i["remaining"] if i["remaining"] is not None else 0))
        self.alert.set_items([{"name": i["name"], "remaining": i["remaining"], "expired": i["expired"],
                               "pixmap": i["pixmap"]} for i in alerts])
        self._maybe_beep(items, alerts, th, now)
        active = self.snapshot.get("active_names", []) if self.snapshot else []
        watched_items = [i for i in items if i["watched"]]
        for auto, card in zip(self.summoners, getattr(self, "summon_cards", [])):
            auto.update(watched_items, active, now)
            card.tick(now)
        self._refresh_debuffs(now)

    def _maybe_beep(self, items, alerts, th, now):
        """버프마다 한 번만 울린다. 다시 갱신되어(기준 + 5초 초과) 돌아온 뒤에야 재알림."""
        remaining = {i["key"]: i["remaining"] for i in items}
        for k in list(self.alerted):
            rem = remaining.get(k, "gone")
            if rem == "gone":
                if now - self.alerted[k] > 20:     # 잠깐 안 보인 건 같은 버프로 취급
                    del self.alerted[k]
            elif rem is not None and rem > th + 5:
                del self.alerted[k]
        new = False
        for i in alerts:
            if i["expired"]:
                continue
            if i["key"] not in self.alerted:
                new = True
            self.alerted[i["key"]] = now
        if new and self.cfg.get("sound") and now - self.last_beep > 3:
            sound.play("buff", self.cfg.get("buff_volume", 40))
            self.last_beep = now

    # ---------- 자동 재시작 ----------
    def _on_code_changed(self, files):
        if not self.cfg.get("auto_reload", True):
            return
        self.status_lbl.setText("코드 변경 감지: " + ", ".join(files) + " → 다시 시작합니다")
        self.restart_pending = True
        self._try_restart()

    def _try_restart(self):
        # 버프 선택 창·이름 입력·영역 지정 중이면 끝날 때까지 미룸
        if QApplication.activeModalWidget() is not None or self.selector is not None or self.picking:
            QTimer.singleShot(1000, self._try_restart)
            return
        self.restarting = True
        self.close()

    def closeEvent(self, e):
        # 타이머가 알림창을 다시 띄우지 않도록 먼저 멈추고, 모든 창을 닫은 뒤 앱을 확실히 종료
        self.ui_timer.stop()
        if self.watcher:
            self.watcher.timer.stop()
        self._close_region_frames()
        self.alert.shutdown()
        self.debuff_alert.shutdown()
        self.presence_alert.shutdown()
        self.debuff_hotkey.stop()
        if self.selector is not None:
            self.selector.close()
        g = self.geometry()
        self.cfg["window_geometry"] = [g.x(), g.y(), g.width(), g.height()]
        self._save()
        self.hotkey.stop()
        self.worker.stop()
        super().closeEvent(e)
        if self.restarting:
            instance.release()
            elevate.reset_env_for_child()     # 새 exe 가 이전 exe 의 임시 폴더를 이어 쓰지 않도록
            if FROZEN:
                QProcess.startDetached(sys.executable, instance.relaunch_args(), str(APP_EXE.parent))
            else:
                QProcess.startDetached(sys.executable, [str(ROOT / "main.py"), *instance.relaunch_args()], str(ROOT))
        QApplication.instance().quit()
