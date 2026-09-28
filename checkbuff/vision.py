"""캡처 이미지 → 버프 행(이름 비트맵, 시간 글리프, 아이콘) 분석.

버프창 구조: [아이콘] [이름] ........ [남은 시간]
- 사용 중이 아닌 버프: 이름이 회색(127,127,127), 시간 없음
- 사용 중인 버프: 이름이 흰색, 시간 흰색 (30초 이하면 빨강)

반투명 배경 대응
1) 색 판정: 게임 글자는 불투명하게 그려지므로 정확한 글자색(순백/회색 127/채도 높은 빨강)만 후보.
2) 외곽선 판정: 글자에는 검은 외곽선이 있다. 주변 1px 안에 어두운 픽셀이 없으면 배경으로 보고 버린다.
3) 시간 숫자는 픽셀 글리프(glyphs.py)로 읽고, tracker.py 가 카운트다운 예측과 대조해 검증한다.

버프 구분은 OCR 이 아니라 '이름 글자 비트맵'으로 한다 (names.py). 게임은 같은 이름을 항상
같은 픽셀로 그리므로, 버프 선택 창에서 한 번 이름을 붙여 두면 이후엔 정확히 알아본다.
"""
import re
from dataclasses import dataclass, field

import numpy as np
from PIL import Image, ImageFilter

HANGUL = re.compile(r"[가-힣]")


@dataclass
class Glyph:
    bits: np.ndarray        # bool (h, w)
    x0: int                 # 영역 기준 좌표
    y0: int
    red_ratio: float
    wide: bool = False      # 한글(분/초/시간) 등 넓은 글자


@dataclass
class Row:
    band: tuple                         # (y0, y1)
    name_box: tuple                     # (x0, y0, x1, y1)
    name_bits: np.ndarray
    time_box: tuple | None = None
    glyphs: list = field(default_factory=list)
    is_red: bool | None = None
    icon: np.ndarray | None = None
    ocr_name: str = ""                  # 버프 선택(scan)에서만 채움

    @property
    def active(self):
        return bool(self.glyphs)


@dataclass
class Frame:
    rgb: np.ndarray
    mask: np.ndarray
    rows: list


def _dilate(m: np.ndarray, r: int) -> np.ndarray:
    h, w = m.shape
    p = np.pad(m, r)
    out = np.zeros_like(m)
    for dy in range(2 * r + 1):
        for dx in range(2 * r + 1):
            out |= p[dy:dy + h, dx:dx + w]
    return out


def _runs(flags) -> list[tuple[int, int]]:
    runs, start = [], None
    for i, v in enumerate(flags):
        if v and start is None:
            start = i
        elif not v and start is not None:
            runs.append((start, i))
            start = None
    if start is not None:
        runs.append((start, len(flags)))
    return runs


class Analyzer:
    OCR_SCALE = 3

    def __init__(self, cfg: dict, ocr):
        self.cfg = cfg
        self.ocr = ocr
        self._icon_geom = None           # ((영상 크기, 이름 열), (x0, 한 변, 행 위쪽 대비 y 차이))

    # ---------- 마스크 ----------
    def masks(self, rgb: np.ndarray, include_gray: bool = False):
        c = self.cfg
        a = rgb.astype(np.int16)
        r, g, b = a[..., 0], a[..., 1], a[..., 2]
        mn, mx = a.min(2), a.max(2)
        white = (mn >= c["white_min"]) & ((mx - mn) <= c["white_spread"])
        red = (r >= c["red_r_min"]) & (g <= c["red_gb_max"]) & (b <= c["red_gb_max"]) \
            & ((r - np.maximum(g, b)) >= c["red_diff_min"])
        text = white | red
        if include_gray:
            text |= np.abs(a - c["gray_level"]).max(2) <= c["gray_tol"]
        if c["outline_check"]:
            lum = (r * 299 + g * 587 + b * 114) // 1000
            text &= _dilate(lum <= c["outline_lum"], 1)
        return text, red & text

    # ---------- OCR 보조 ----------
    def _ocr_mask(self, m: np.ndarray, scale: int | None = None):
        scale = scale or self.OCR_SCALE
        h, w = m.shape
        while max(h, w) * scale > self.ocr.max_dim and scale > 1:
            scale -= 1
        img = Image.fromarray(np.where(m, 0, 255).astype(np.uint8))
        img = img.resize((w * scale, h * scale), Image.NEAREST).filter(ImageFilter.GaussianBlur(scale / 3))
        pad = 20
        canvas = Image.new("L", (img.width + pad * 2, img.height + pad * 2), 255)
        canvas.paste(img, (pad, pad))
        words = self.ocr.recognize(canvas, scale)
        for wd in words:
            wd.x -= pad / scale
            wd.y -= pad / scale
        return words

    def find_name_column(self, rgb: np.ndarray) -> float | None:
        """아이콘과 이름의 경계 x. 회색·흰색 이름 전체를 OCR 해서 한글 단어들의 왼쪽 끝 중앙값."""
        mask, _ = self.masks(rgb, include_gray=True)
        words = [w for w in self._ocr_mask(mask) if len(HANGUL.findall(w.text)) >= 2]
        if not words:
            return None
        rows = {}
        for w in sorted(words, key=lambda w: w.x):
            rows.setdefault(round(w.cy / 6), w.x)       # 행마다 가장 왼쪽 단어
        return float(np.median(list(rows.values())))

    def ocr_text(self, mask: np.ndarray, box) -> str:
        x0, y0, x1, y1 = box
        crop = mask[max(0, y0 - 2):y1 + 2, max(0, x0 - 2):x1 + 2]
        if not crop.any():
            return ""
        return " ".join(w.text for w in self._ocr_mask(crop))

    # ---------- 행 분석 ----------
    def rows(self, rgb: np.ndarray, mask: np.ndarray, red: np.ndarray, col: float) -> list[Row]:
        cx = int(max(0, col - 1))
        area = mask[:, cx:]
        bands = [(a, b) for a, b in _runs(area.any(1)) if b - a >= 5]
        out = []
        for y0, y1 in bands:
            bh = y1 - y0
            runs = _runs(area[y0:y1].any(0))
            if not runs or runs[0][0] > bh:             # 이름 열에서 시작하지 않음 → 잡티
                continue
            clusters = [list(runs[0])]
            for a, b in runs[1:]:
                if a - clusters[-1][1] >= 2.5 * bh:
                    clusters.append([a, b])
                else:
                    clusters[-1][1] = b
            nx0, nx1 = clusters[0][0] + cx, clusters[0][1] + cx
            nb = mask[y0:y1, nx0:nx1]
            ys = np.nonzero(nb.any(1))[0]
            row = Row((y0, y1), (nx0, y0, nx1, y1), nb[ys[0]:ys[-1] + 1].copy())
            if len(clusters) > 1:
                tx0, tx1 = clusters[-1][0] + cx, clusters[-1][1] + cx
                row.time_box = (tx0, y0, tx1, y1)
                row.glyphs = segment_glyphs(mask[y0:y1, tx0:tx1], red[y0:y1, tx0:tx1], tx0, y0)
                if row.glyphs:
                    px = sum(g.bits.sum() for g in row.glyphs)
                    rp = sum(g.red_ratio * g.bits.sum() for g in row.glyphs)
                    row.is_red = (rp / max(px, 1)) > 0.5
            out.append(row)
        self._crop_icons(rgb, out, col)
        return out

    @staticmethod
    def _frame_score(dark, bright, x0, y0, side):
        """정사각형 (x0, y0, side) 가 아이콘 틀처럼 보이는 정도 (최대 2.0): 테두리는 어둡고 바로 안쪽은 밝음."""
        x1, y1 = x0 + side - 1, y0 + side - 1
        if x0 < 0 or y0 < 0 or y1 >= dark.shape[0] or x1 >= dark.shape[1]:
            return 0.0
        border = (dark[y0, x0:x1 + 1].mean() + dark[y1, x0:x1 + 1].mean()
                  + dark[y0:y1 + 1, x0].mean() + dark[y0:y1 + 1, x1].mean()) / 4
        inner = (bright[y0 + 1, x0 + 1:x1].mean() + bright[y1 - 1, x0 + 1:x1].mean()
                 + bright[y0 + 1:y1, x0 + 1].mean() + bright[y0 + 1:y1, x1 - 1].mean()) / 4
        return float(border + inner)

    @classmethod
    def _find_icon_frame(cls, dark, bright, band, col: float):
        """한 행의 아이콘 정사각형 (x0, y0, 한 변). 아이콘은 '어두운 1px 테두리 + 안쪽은 밝은 그림'.
        배경이 어두워도 되도록, 테두리가 어둡고 바로 안쪽 한 줄이 밝은 정사각형을 찾는다."""
        y0b, y1b = band
        bh = y1b - y0b
        x_max = int(col) - 1
        best, best_score = None, 1.2
        cy = (y0b + y1b) / 2
        for side in range(max(8, int(bh * 0.9)), int(bh * 2.4) + 1):
            for x0 in range(0, x_max - side + 1):
                for y0 in range(int(cy - side / 2 - 3), int(cy - side / 2 + 4)):
                    score = cls._frame_score(dark, bright, x0, y0, side)
                    if score > best_score:
                        best, best_score = (x0, y0, side), score
        return best

    def _crop_icons(self, rgb, rows, col):
        """아이콘은 모두 같은 크기로 같은 열에 있다. 영역마다 한 번만 몇 개 행에서 테두리를 찾아
        (x, 크기, 행 위치 대비 y 차이)를 정해 두고, 이후엔 그대로 잘라낸다."""
        if not rows:
            return
        key = (rgb.shape, round(col))
        if self._icon_geom is None or self._icon_geom[0] != key:
            lum = rgb.astype(np.int16).mean(2)
            dark, bright = lum < 50, lum > 70
            sample = rows[:6]
            cands = set()
            for r in sample:
                f = self._find_icon_frame(dark, bright, r.band, col)
                if f:
                    cands.add((f[0], f[2], f[1] - r.band[0]))
            # 줄마다 아이콘 그림 속 작은 네모를 틀로 착각할 수 있으므로,
            # 각 후보를 모든 줄에 대어 보고 평균 점수가 가장 높은 것을 고른다
            if cands:
                geom = max(cands, key=lambda g: np.mean([self._frame_score(dark, bright, g[0], r.band[0] + g[2], g[1])
                                                         for r in sample]))
            else:                                   # 못 찾으면 이름 바로 왼쪽을 대략
                bh = rows[0].band[1] - rows[0].band[0]
                side = int(round(1.4 * bh))
                geom = (max(0, int(col) - 3 - side), side, -int((side - bh) / 2))
            self._icon_geom = (key, geom)
        x0, side, dy = self._icon_geom[1]
        for r in rows:
            y0 = int(max(0, r.band[0] + dy))
            r.icon = rgb[y0:y0 + side, x0:x0 + side].copy()

    def analyze(self, rgb: np.ndarray, col: float) -> Frame:
        """감시용: 사용 중인(흰 이름) 버프만."""
        mask, red = self.masks(rgb)
        return Frame(rgb, mask, self.rows(rgb, mask, red, col))

    def scan(self, rgb: np.ndarray, col: float) -> list[Row]:
        """버프 선택용: 사용 중이 아닌(회색) 버프까지 전부, 행마다 OCR 로 이름 추정."""
        mask, red = self.masks(rgb, include_gray=True)
        rows = self.rows(rgb, mask, red, col)
        for r in rows:
            words = self._ocr_mask(np.pad(r.name_bits, 2))
            r.ocr_name = " ".join(re.sub(r"[^가-힣A-Za-z0-9 ]", "", w.text) for w in words).strip()
        return rows


def segment_glyphs(m: np.ndarray, red: np.ndarray, ox: int, oy: int) -> list[Glyph]:
    """빈 열을 기준으로 글자를 자른다 (픽셀 폰트라 글자 사이에 1px 이상 공백이 있음)."""
    if m.size == 0:
        return []
    out = []
    for a, b in _runs(m.any(0)):
        sub = m[:, a:b]
        rows = np.nonzero(sub.any(1))[0]
        r0, r1 = rows[0], rows[-1] + 1
        bits = sub[r0:r1]
        n = int(bits.sum())
        if n < 3:
            continue
        rr = float(red[r0:r1, a:b][bits].mean())
        out.append(Glyph(bits.copy(), ox + a, oy + r0, rr))
    if not out:
        return out
    hmax = max(g.bits.shape[0] for g in out)
    out = [g for g in out if g.bits.shape[0] >= 0.45 * hmax]   # 점 같은 잡티 제거
    for g in out:
        g.wide = g.bits.shape[1] > 0.72 * hmax
    return out


# ---------- 시간 문자열 파싱 ----------
_FIX = str.maketrans({"O": "0", "o": "0", "D": "0", "l": "1", "I": "1", "|": "1", "!": "1",
                      "S": "5", "B": "8", "Z": "2", "g": "9", "q": "9"})


def parse_time(text: str | None) -> int | None:
    """'9분 55초', '1시간 5분', '25초' → 초. 해석 불가면 None."""
    if not text:
        return None
    s = text.replace(" ", "").translate(_FIX)
    pairs = re.findall(r"(\d{1,3})([가-힣]*)", s)
    if not pairs or re.sub(r"\d{1,3}[가-힣]*", "", s):
        return None
    total, seen = 0, set()
    for num, unit in pairs:
        n = int(num)
        if "초" in unit:
            kind = "s"
        elif "일" in unit:
            kind = "d"
        elif "시" in unit or "간" in unit:
            kind = "h"
        elif unit:
            kind = "m"          # '분' (또는 OCR 이 뭉갠 분)
        else:
            return None
        if kind in seen:
            return None
        seen.add(kind)
        # 게임은 60초 이상을 항상 'N분 M초'로 표시 → '73초' 같은 값은 잘못 읽은 것
        if kind == "s" and n >= 60:
            return None
        if kind == "m" and n >= 60 and "h" in seen:
            return None
        total += n * {"d": 86400, "h": 3600, "m": 60, "s": 1}[kind]
    return total


def format_time(sec: float | None) -> str:
    if sec is None:
        return "—"
    s = max(0, int(sec + 0.999))
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}시간 {m}분"
    if m:
        return f"{m}분 {s:02d}초"
    return f"{s}초"
