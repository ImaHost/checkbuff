"""사용자가 교정한 버프 이름 기억.

게임은 같은 버프 이름을 항상 같은 픽셀로 그린다. 그래서 이름 글자 비트맵과 올바른 이름을
짝지어 두면, 다음부터는 OCR 결과와 상관없이 비트맵만 보고 정확한 이름을 알 수 있다.
"""
import base64
import json
import os

import numpy as np

from .config import APP_DIR

NAMES_PATH = APP_DIR / "names.json"


def _mismatch(a: np.ndarray, b: np.ndarray) -> float:
    h, w = max(a.shape[0], b.shape[0]), max(a.shape[1], b.shape[1])
    pa = np.zeros((h, w), bool)
    pb = np.zeros((h, w), bool)
    pa[:a.shape[0], :a.shape[1]] = a
    pb[:b.shape[0], :b.shape[1]] = b
    return float((pa ^ pb).sum()) / max(1, int((pa | pb).sum()))


class NameBook:
    def __init__(self, path=NAMES_PATH):
        self.path = path
        self.entries: list[tuple[np.ndarray, str]] = []
        self.load()

    def lookup(self, bits: np.ndarray | None) -> str | None:
        if bits is None:
            return None
        best, best_d = None, 0.10
        for b, name in self.entries:
            if abs(b.shape[0] - bits.shape[0]) > 1 or abs(b.shape[1] - bits.shape[1]) > 2:
                continue
            d = _mismatch(b, bits)
            if d < best_d:
                best, best_d = name, d
        return best or self._lookup_noisy(bits)

    def _lookup_noisy(self, bits: np.ndarray) -> str | None:
        """배경 잡음 점이 이름 둘레에 붙어 비트맵 크기가 달라진 경우.
        등록된 이름 크기의 창을 몇 픽셀씩 옮겨 가며 비교하고, 창 바깥 픽셀이 아주 적으면(잡음) 같은 이름으로 본다.
        바깥 픽셀이 많으면 '(투안의노래)' 같은 붙은 글자이므로 여기선 인정하지 않는다 (lookup_prefix 가 처리)."""
        H, W = bits.shape
        total = int(bits.sum())
        best, best_key = None, None
        for b, name in self.entries:
            h, w = b.shape
            if h > H or w > W or W - w > 40 or H - h > 8:
                continue
            nb = int(b.sum())
            for dy in range(0, H - h + 1):
                for dx in range(0, min(4, W - w) + 1):
                    win = bits[dy:dy + h, dx:dx + w]
                    if _mismatch(b, win) >= 0.08:
                        continue
                    outside = total - int(win.sum())
                    if outside > max(3, 0.06 * nb):
                        continue
                    key = (w, -_mismatch(b, win))           # 넓은(긴) 이름 우선
                    if best_key is None or key > best_key:
                        best, best_key = name, key
        return best

    def lookup_prefix(self, bits: np.ndarray | None):
        """저장된 이름 뒤에 글자가 더 붙은 경우 (예: '전장의 서곡 (투안의노래)').
        앞부분이 저장된 이름과 일치하면 (이름, 뒷부분 비트맵). 괄호 때문에 전체 높이가 커질 수 있어
        세로 위치를 옮겨 가며 비교한다. 가장 긴 이름을 우선."""
        if bits is None:
            return None
        H, W = bits.shape
        best = None
        for b, name in sorted(self.entries, key=lambda e: -e[0].shape[1]):
            h, w = b.shape
            if w + 6 > W or h > H:
                continue
            gap = bits[:, w:w + 2]
            if gap.sum() > 1:                       # 이름 바로 뒤는 띄어쓰기여야 함
                continue
            for dy in range(0, H - h + 1):
                if _mismatch(b, bits[dy:dy + h, :w]) < 0.10:
                    best = name, w
                    break
            if best:
                break
        if not best:
            return None
        name, w = best
        rest = bits[:, w:]
        cols = np.nonzero(rest.any(0))[0]
        rows = np.nonzero(rest.any(1))[0]
        if not cols.size:
            return None
        return name, rest[rows[0]:rows[-1] + 1, cols[0]:cols[-1] + 1].copy()

    def add(self, bits: np.ndarray, name: str):
        self.entries = [(b, n) for b, n in self.entries
                        if not (b.shape == bits.shape and _mismatch(b, bits) < 0.10)]
        self.entries.append((bits.copy(), name))
        self.save()

    def remove_name(self, name: str):
        self.entries = [(b, n) for b, n in self.entries if n != name]
        self.save()

    def save(self):
        data = [{"name": n, "h": b.shape[0], "w": b.shape[1],
                 "bits": base64.b64encode(np.packbits(b).tobytes()).decode()} for b, n in self.entries]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, self.path)

    def load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return
        for e in data:
            raw = np.frombuffer(base64.b64decode(e["bits"]), np.uint8)
            bits = np.unpackbits(raw)[: e["h"] * e["w"]].reshape(e["h"], e["w"]).astype(bool)
            self.entries.append((bits, e["name"]))
