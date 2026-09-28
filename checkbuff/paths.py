"""파일 위치: 소스로 실행할 때와 exe(PyInstaller)로 실행할 때 모두 맞게."""
import sys
from pathlib import Path

FROZEN = getattr(sys, "frozen", False)
# 프로그램에 딸린 파일(아이콘, 기본 데이터)이 있는 곳
RES_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
ASSETS = RES_DIR / "assets"
# 실행 파일(또는 main.py)이 있는 곳
APP_EXE = Path(sys.executable) if FROZEN else Path(__file__).resolve().parents[1] / "main.py"


def asset(name: str) -> Path:
    return ASSETS / name


def qss_url(p: Path) -> str:
    """QSS 의 url() 에 넣을 경로 (슬래시로)."""
    return str(p).replace("\\", "/")
