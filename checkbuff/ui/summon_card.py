"""자동 소환 카드 (투안 / 햄 공용): 사용 여부, 소환 시점, 해제 대기, 재사용, 펫별 소환·해제 키."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QDoubleSpinBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton,
                               QSpinBox, QVBoxLayout)

from ..tuan import MAX_SUMMONERS, AutoSummon
from . import style
from .keycapture import KeyCaptureButton


class SummonCard(QFrame):
    def __init__(self, auto: AutoSummon, save):
        super().__init__()
        self.setObjectName("card")
        self.auto = auto
        self.cfg = auto.cfg
        self.g = auto.group
        self.save = save
        self.cd_labels = []
        auto.status.connect(lambda m: self.status.setText(m))

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 16)
        lay.setSpacing(10)
        top = QHBoxLayout()
        title = QLabel(f"자동 {self.g.title}")
        title.setObjectName("section")
        top.addWidget(title)
        top.addSpacing(10)
        self.enable = QCheckBox("사용")
        self.enable.setChecked(bool(auto.c("enabled")))
        self.enable.toggled.connect(lambda v: self._set("enabled", v, refresh=True))
        top.addWidget(self.enable)
        top.addStretch()
        game_only = QCheckBox("게임 창일 때만")
        game_only.setToolTip("마비노기 창이 앞에 있을 때만 키를 보냅니다 (다른 창에 키가 눌리는 것 방지)")
        game_only.setChecked(auto.c("game_only", True))
        game_only.toggled.connect(lambda v: self._set("game_only", v))
        top.addWidget(game_only)
        lay.addLayout(top)

        g = QGridLayout()
        g.setHorizontalSpacing(8)
        g.setVerticalSpacing(8)
        g.addWidget(self._lbl("소환 시점"), 0, 0)
        rng = QHBoxLayout()
        rng.addWidget(self._spin("trigger_min", 5, 120, 1, " 초", 20))
        rng.addWidget(self._lbl("~"))
        rng.addWidget(self._spin("trigger_max", 5, 120, 1, " 초", 25))
        rng.addWidget(self._lbl("남았을 때 (무작위)"))
        rng.addStretch()
        g.addLayout(rng, 0, 1, 1, 3)
        g.addWidget(self._lbl("해제까지"), 1, 0)
        g.addWidget(self._spin("delay_sec", 0.2, 10.0, 0.1, " 초", 1.0, dbl=True), 1, 1)
        g.addWidget(self._lbl("재사용"), 1, 2)
        g.addWidget(self._spin("cooldown_sec", 5, 600, 5, " 초", 60), 1, 3)
        lay.addLayout(g)

        self.rows_box = QVBoxLayout()
        self.rows_box.setSpacing(6)
        lay.addLayout(self.rows_box)
        self.add_btn = QPushButton(f"+ {self.g.title} 추가")
        self.add_btn.setObjectName("secondary")
        self.add_btn.clicked.connect(self._add)
        lay.addWidget(self.add_btn, 0, Qt.AlignLeft)
        self.targets_lbl = QLabel()
        self.targets_lbl.setWordWrap(True)
        lay.addWidget(self.targets_lbl)
        buffs = ", ".join(self.cfg.get(f"{self.g.key}_buffs") or self.g.buffs)
        self.status = QLabel(f"{buffs} 가 곧 끝나면 {self.g.title}을(를) 소환했다가 해제합니다")
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        self.rebuild_rows()
        self.update_targets()

    # ---------- 공용 ----------
    @staticmethod
    def _lbl(t):
        x = QLabel(t)
        x.setObjectName("muted")
        return x

    def _set(self, name, value, refresh=False):
        self.cfg[f"{self.g.key}_{name}"] = value
        self.save()
        if refresh:
            self.update_targets()

    def _spin(self, name, lo, hi, step, suffix, default, dbl=False):
        w = QDoubleSpinBox() if dbl else QSpinBox()
        w.setRange(lo, hi)
        w.setSingleStep(step)
        w.setSuffix(suffix)
        w.setValue(self.auto.c(name, default))
        w.valueChanged.connect(lambda v: self._set(name, v))
        return w

    @property
    def summoners(self):
        return self.cfg[f"{self.g.key}s"]

    # ---------- 펫 목록 ----------
    def rebuild_rows(self):
        # 이전 줄 제거: deleteLater 만 하면 이번 화면 갱신 동안 남아서 카드를 덮으므로 즉시 숨기고 떼어냄
        while self.rows_box.count():
            sub = self.rows_box.takeAt(0).layout()
            while sub is not None and sub.count():
                w = sub.takeAt(0).widget()
                if w:
                    w.hide()
                    w.setParent(None)
                    w.deleteLater()
        self.cd_labels = []
        small = "QPushButton { padding: 5px 8px; font-size: 12px; }"
        for i, t in enumerate(self.summoners):
            row = QHBoxLayout()
            row.setSpacing(5)
            name = QLabel(f"{self.g.title} {i + 1}")
            name.setStyleSheet(f"color: {style.ACCENT}; font-weight: 700;")
            row.addWidget(name)
            for key, tip in (("summon", "소환"), ("unsummon", "해제")):
                b = KeyCaptureButton(t.get(key))
                b.setMinimumWidth(64)
                b.setStyleSheet(small)
                b.setToolTip(f"{tip} 키 — 클릭 후 키를 누르세요 (Esc 취소, Backspace 지우기)")
                b.changed.connect(lambda combo, i=i, key=key: self._set_key(i, key, combo))
                row.addWidget(self._lbl(tip))
                row.addWidget(b, 1)
            cd = QLabel("")
            cd.setObjectName("muted")
            cd.setFixedWidth(52)
            cd.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.cd_labels.append(cd)
            row.addWidget(cd)
            test = QPushButton("▶")
            test.setObjectName("secondary")
            test.setToolTip(f"테스트: 3초 뒤 이 {self.g.title}을(를) 소환→해제합니다. 그 사이 게임 창을 눌러 두세요")
            test.clicked.connect(lambda _=False, i=i: self._test(i))
            row.addWidget(test)
            if len(self.summoners) > 1:
                rm = QPushButton("✕")
                rm.setObjectName("ghost")
                rm.setToolTip("삭제")
                rm.clicked.connect(lambda _=False, i=i: self._remove(i))
                row.addWidget(rm)
            self.rows_box.addLayout(row)
        self.add_btn.setVisible(len(self.summoners) < MAX_SUMMONERS)

    def _set_key(self, i, key, combo):
        self.summoners[i][key] = combo
        self.save()
        self.update_targets()

    def _add(self):
        if len(self.summoners) < MAX_SUMMONERS:
            self.summoners.append({"summon": None, "unsummon": None})
            self.save()
            self.rebuild_rows()

    def _remove(self, i):
        del self.summoners[i]
        self.auto.ready_at.clear()
        self.save()
        self.rebuild_rows()
        self.update_targets()

    def _test(self, i):
        t = self.summoners[i]
        if not t.get("summon") or not t.get("unsummon"):
            self.status.setText(f"{self.g.title} {i + 1}의 소환 키와 해제 키를 먼저 등록하세요")
            return
        self.auto.fire(i, reason="테스트", countdown=3)

    # ---------- 표시 ----------
    def update_targets(self):
        names = self.auto.targets()
        why = self.auto.ready()
        if not names:
            txt = f"대상 없음 — '버프 선택'에서 {'·'.join(self.g.buffs)} 타일의 '자동 {self.g.title}'을 체크하세요"
            col = style.MUTED
        else:
            txt = "대상: " + ", ".join(names)
            col = style.ACCENT if not why else style.MUTED
        if names and why and why != "꺼짐":
            txt += f"  ({why})"
        self.targets_lbl.setText(txt)
        self.targets_lbl.setStyleSheet(f"color: {col}; font-size: 12px; font-weight: 600;")

    def tick(self, now):
        for i, lbl in enumerate(self.cd_labels):
            left = self.auto.cooldown_left(i, now)
            lbl.setText(f"대기 {left:.0f}초" if left > 0 else "")
