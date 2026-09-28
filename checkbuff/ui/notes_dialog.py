"""패치노트 팝업: GitHub 릴리스 설명(최신순). 연결이 안 되면 마지막으로 받은 내용이나 프로그램에 든 CHANGELOG."""
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QTextBrowser, QVBoxLayout

from ..updater import bundled_changelog
from ..version import __version__
from . import style


class NotesDialog(QDialog):
    def __init__(self, notes: list[dict], parent=None):
        super().__init__(parent)
        self.setWindowTitle("패치노트")
        self.setStyleSheet(style.QSS + f"QDialog {{ background: {style.BG}; }}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 18)
        lay.setSpacing(12)
        head = QHBoxLayout()
        t = QLabel("패치노트")
        t.setStyleSheet("font-size: 18px; font-weight: 700;")
        head.addWidget(t)
        head.addStretch()
        cur = QLabel(f"현재 v{__version__}")
        cur.setObjectName("muted")
        head.addWidget(cur)
        lay.addLayout(head)

        view = QTextBrowser()
        view.setOpenExternalLinks(True)
        view.setStyleSheet(f"QTextBrowser {{ background: {style.CARD}; border: 1px solid {style.LINE};"
                           " border-radius: 10px; padding: 12px; font-size: 13px; }")
        if notes:
            parts = []
            for n in notes:
                mark = "  ← 현재" if n["version"] == __version__ else ""
                parts.append(f"## v{n['version']}  ·  {n['date']}{mark}\n\n{n['body'].strip() or '- (설명 없음)'}\n")
            md = "\n".join(parts)
        else:
            md = bundled_changelog() or "아직 패치노트가 없습니다."
        view.setMarkdown(md)
        lay.addWidget(view, 1)

        foot = QHBoxLayout()
        foot.addStretch()
        ok = QPushButton("닫기")
        ok.setObjectName("primary")
        ok.clicked.connect(self.accept)
        foot.addWidget(ok)
        lay.addLayout(foot)
        self.resize(560, 520)
