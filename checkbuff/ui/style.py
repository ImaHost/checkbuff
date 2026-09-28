from ..paths import asset, qss_url

BG = "#12141a"
CARD = "#1a1d25"
CARD2 = "#20242e"
LINE = "#2a2f3b"
LINE2 = "#4a5162"      # 체크박스·보조 버튼 테두리 (배경과 확실히 구분되도록 밝게)
TEXT = "#ebe7df"
MUTED = "#8a90a0"
ACCENT = "#e3b55b"
DANGER = "#ff5c5c"
OK = "#4fc98e"

CHECK = qss_url(asset("check.png"))
DOWN = qss_url(asset("down.png"))

QSS = f"""
* {{ font-family: 'Malgun Gothic', 'Segoe UI'; color: {TEXT}; }}
QMainWindow, QWidget#root {{ background: {BG}; }}
QFrame#card {{ background: {CARD}; border: 1px solid {LINE}; border-radius: 12px; }}
QLabel#title {{ font-size: 20px; font-weight: 700; }}
QLabel#subtitle {{ color: {MUTED}; font-size: 12px; }}
QLabel#section {{ font-size: 13px; font-weight: 700; color: {ACCENT}; letter-spacing: 1px; }}
QLabel#muted {{ color: {MUTED}; font-size: 12px; }}
QLabel#preview {{ background: #0b0c10; border: 1px dashed {LINE}; border-radius: 8px; color: {MUTED}; }}
QLabel#pill {{ border-radius: 11px; padding: 3px 12px; font-size: 12px; font-weight: 700; }}

/* 버튼: 기본 / 주요(금색) / 보조(테두리) / 위험 */
QPushButton {{
    background: {CARD2}; border: 1px solid {LINE2}; border-radius: 8px;
    padding: 9px 16px; font-size: 13px; font-weight: 600;
}}
QPushButton:hover {{ border-color: {ACCENT}; color: {ACCENT}; }}
QPushButton:pressed {{ background: #171a21; }}
QPushButton:disabled {{ color: #555a66; border-color: #23272f; }}
QPushButton#primary {{ background: {ACCENT}; color: #1b1406; border: none; }}
QPushButton#primary:hover {{ background: #f0c671; color: #1b1406; }}
QPushButton#primary:disabled {{ background: #4a4230; color: #8a7c5c; }}
QPushButton#danger {{ background: #3a1d20; border-color: #6a3035; color: #ffb3b3; }}
QPushButton#ghost, QPushButton#secondary {{
    background: #1d2029; border: 1px solid {LINE2}; border-radius: 7px;
    color: {TEXT}; padding: 6px 12px; font-size: 12px; font-weight: 600;
}}
QPushButton#ghost:hover, QPushButton#secondary:hover {{ border-color: {ACCENT}; color: {ACCENT}; background: #262a35; }}
QPushButton#update {{ background: {OK}; color: #0c2015; border: none; padding: 5px 12px; font-size: 12px;
                      font-weight: 800; border-radius: 11px; }}
QPushButton#update:hover {{ background: #6fe0a8; color: #0c2015; }}
QPushButton#update:disabled {{ background: {CARD2}; color: {MUTED}; border: 1px solid {LINE}; }}

QSpinBox, QDoubleSpinBox {{
    background: {CARD2}; border: 1px solid {LINE2}; border-radius: 6px; padding: 4px 8px; min-width: 96px;
}}
QSpinBox:focus, QDoubleSpinBox:focus {{ border-color: {ACCENT}; }}
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 16px; }}
QComboBox {{ background: {CARD2}; border: 1px solid {LINE2}; border-radius: 6px; padding: 4px 26px 4px 8px; min-width: 70px; }}
QComboBox:hover {{ border-color: {ACCENT}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox::down-arrow {{ image: url({DOWN}); width: 12px; height: 12px; }}
QComboBox QAbstractItemView {{ background: {CARD2}; border: 1px solid {LINE2}; selection-background-color: {ACCENT}; selection-color: #1b1406; }}

/* 체크박스: 꺼짐 = 밝은 테두리의 빈 칸, 켜짐 = 금색 칸 + 체크 표시 */
QCheckBox {{ spacing: 8px; font-size: 13px; }}
QCheckBox::indicator {{ width: 18px; height: 18px; border-radius: 5px; border: 2px solid {LINE2}; background: #14161c; }}
QCheckBox::indicator:hover {{ border-color: {ACCENT}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; image: url({CHECK}); }}
QCheckBox::indicator:disabled {{ border-color: #2c313c; background: #181a20; }}
QCheckBox:disabled {{ color: #5c6270; }}

QPlainTextEdit, QTextBrowser {{ background: {CARD2}; border: 1px solid {LINE}; border-radius: 8px; padding: 6px; font-size: 13px; }}
QScrollArea {{ border: none; background: transparent; }}
QTabWidget::pane {{ border: none; }}
QTabBar::tab {{ background: transparent; color: {MUTED}; padding: 8px 16px; margin-right: 4px;
               border: 1px solid {LINE}; border-bottom: none; border-top-left-radius: 8px; border-top-right-radius: 8px;
               font-size: 13px; font-weight: 700; }}
QTabBar::tab:selected {{ background: {CARD}; color: {ACCENT}; border-color: {LINE2}; }}
QTabBar::tab:hover:!selected {{ color: {TEXT}; }}
QSlider::groove:horizontal {{ height: 4px; background: {LINE2}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: {TEXT}; width: 14px; margin: -6px 0; border-radius: 7px; }}
QToolTip {{ background: {CARD2}; border: 1px solid {LINE2}; color: {TEXT}; padding: 6px; }}
"""
