"""GitHub 릴리스로 자동 업데이트 + 패치노트.

- 저장소에 push 하면 GitHub Actions 가 exe 를 빌드해 릴리스(v1.0.N)로 올린다 (.github/workflows/release.yml).
- 실행기는 시작할 때 최신 릴리스를 확인하고, 새 버전이 있으면 '업데이트' 버튼을 켠다.
- 업데이트: 새 exe 를 받아 옆에 두고 → 실행 중인 exe 이름을 .old 로 바꾸고(실행 중에도 이름 변경은 가능)
  → 새 exe 를 원래 이름으로 → 새 exe 실행 → 종료. 다음 실행 때 .old 를 지운다.
- 설정·학습 데이터는 %APPDATA%\\CheckBuff 에 있으므로 업데이트해도 그대로다.
"""
import json
import os
import re
import sys
import threading
import time
import urllib.request

from PySide6.QtCore import QObject, Signal

from .config import APP_DIR
from .paths import FROZEN, RES_DIR
from .version import __version__

REPO = "ImaHost/checkbuff"
API = f"https://api.github.com/repos/{REPO}/releases?per_page=30"
ASSET_NAME = "MelyaongChecker.exe"
NOTES_CACHE = APP_DIR / "release_notes.json"
UA = {"User-Agent": "MelyaongChecker-updater", "Accept": "application/vnd.github+json"}


def vtuple(v: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", v or "0")[:4])


def cleanup_old():
    """지난 업데이트에서 남은 .old 파일 삭제."""
    if FROZEN:
        old = sys.executable + ".old"
        try:
            if os.path.exists(old):
                os.remove(old)
        except OSError:
            pass


def cached_notes() -> list[dict]:
    try:
        with open(NOTES_CACHE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def bundled_changelog() -> str:
    try:
        return (RES_DIR / "CHANGELOG.md").read_text(encoding="utf-8")
    except OSError:
        return ""


class Updater(QObject):
    checked = Signal(object)        # {"latest", "newer", "asset_url", "notes": [...] } 또는 {"error"}
    progress = Signal(str)
    failed = Signal(str)
    ready_to_restart = Signal()

    def __init__(self):
        super().__init__()
        self.info = None

    # ---------- 확인 ----------
    def check_async(self):
        threading.Thread(target=self._check, daemon=True).start()

    def _check(self):
        try:
            req = urllib.request.Request(API, headers=UA)
            with urllib.request.urlopen(req, timeout=10) as r:
                releases = json.loads(r.read().decode("utf-8"))
            rels = [x for x in releases if not x.get("draft") and not x.get("prerelease")]
            notes = [{"version": x["tag_name"].lstrip("v"), "date": (x.get("published_at") or "")[:10],
                      "body": x.get("body") or ""} for x in rels]
            try:
                APP_DIR.mkdir(parents=True, exist_ok=True)
                with open(NOTES_CACHE, "w", encoding="utf-8") as f:
                    json.dump(notes, f, ensure_ascii=False)
            except OSError:
                pass
            latest = rels[0] if rels else None
            url = None
            if latest:
                url = next((a["browser_download_url"] for a in latest.get("assets", [])
                            if a["name"].lower().endswith(".exe")), None)
            lv = latest["tag_name"].lstrip("v") if latest else None
            self.info = {"latest": lv, "newer": bool(lv and vtuple(lv) > vtuple(__version__) and url),
                         "asset_url": url, "notes": notes}
        except Exception as e:
            self.info = {"error": str(e), "notes": cached_notes()}
        self.checked.emit(self.info)

    # ---------- 적용 ----------
    def apply_async(self):
        threading.Thread(target=self._apply, daemon=True).start()

    def _apply(self):
        if not FROZEN:
            self.failed.emit("소스로 실행 중이라 자동 업데이트는 exe 에서만 됩니다")
            return
        url = (self.info or {}).get("asset_url")
        if not url:
            self.failed.emit("받을 파일이 없습니다")
            return
        exe = sys.executable
        new = exe + ".new"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA["User-Agent"]})
            with urllib.request.urlopen(req, timeout=60) as r, open(new, "wb") as f:
                total = int(r.headers.get("Content-Length") or 0)
                got, last = 0, 0.0
                while True:
                    chunk = r.read(1 << 16)
                    if not chunk:
                        break
                    f.write(chunk)
                    got += len(chunk)
                    if time.monotonic() - last > 0.3:
                        last = time.monotonic()
                        pct = f"{got * 100 // total}%" if total else f"{got // 1024 // 1024}MB"
                        self.progress.emit(f"받는 중 {pct}")
            if os.path.getsize(new) < 1_000_000:
                raise OSError("받은 파일이 너무 작습니다")
            old = exe + ".old"
            if os.path.exists(old):
                os.remove(old)
            os.replace(exe, old)          # 실행 중인 exe 는 지울 수 없지만 이름은 바꿀 수 있음
            os.replace(new, exe)
        except Exception as e:
            try:
                if os.path.exists(exe + ".old") and not os.path.exists(exe):
                    os.replace(exe + ".old", exe)
                if os.path.exists(new):
                    os.remove(new)
            except OSError:
                pass
            self.failed.emit(f"업데이트 실패: {e}")
            return
        self.progress.emit("업데이트 완료 · 다시 시작합니다")
        self.ready_to_restart.emit()
