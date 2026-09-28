"""디버프 감시: 대상(보스) 체력바 위 디버프 아이콘 줄에서 등록한 아이콘이 있는지 확인.

- 등록: 영역에서 아이콘을 자동으로 찾는다. 디버프 아이콘은 '테두리 한 줄은 고른 색, 안쪽은 복잡한 그림,
  테두리 바깥과는 색이 다른' 정사각형이고, 여러 개가 같은 높이에 나란히 있다.
- 감시: 등록한 아이콘 그림을 영역 전체에서 찾는다(템플릿 매칭). 디버프 순서가 바뀌어 위치가 달라져도 찾음.
"""
import base64
import json
import os
import re
import uuid

import cv2
import numpy as np

from .config import APP_DIR

DEBUFF_PATH = APP_DIR / "debuffs.json"
MATCH_MIN = 0.80        # 이 이상 비슷하면 '있음'


# ---------- 아이콘 찾기 ----------
def detect_icons(rgb: np.ndarray, sides=range(12, 25)) -> list[tuple[int, int, int]]:
    """[(x, y, 한 변)] 왼쪽부터."""
    a = rgb.astype(np.float64)
    H, W, _ = a.shape
    Ii = np.zeros((H + 1, W + 1, 3))
    Ii[1:, 1:] = a.cumsum(0).cumsum(1)
    I2 = np.zeros((H + 1, W + 1, 3))
    I2[1:, 1:] = (a * a).cumsum(0).cumsum(1)

    def box(I, y, x, h, w):
        return I[y + h, x + w] - I[y, x + w] - I[y + h, x] + I[y, x]

    cands = []
    for s in sides:
        ny, nx = H - s - 1, W - s - 1
        if ny <= 1 or nx <= 1:
            continue
        ys, xs = np.meshgrid(np.arange(1, ny), np.arange(1, nx), indexing="ij")
        n_ring = s * s - (s - 2) ** 2
        rs = box(Ii, ys, xs, s, s) - box(Ii, ys + 1, xs + 1, s - 2, s - 2)
        rs2 = box(I2, ys, xs, s, s) - box(I2, ys + 1, xs + 1, s - 2, s - 2)
        ring_mean = rs / n_ring
        ring_var = (rs2 / n_ring - ring_mean ** 2).sum(-1)
        n_in = (s - 4) ** 2
        in_mean = box(Ii, ys + 2, xs + 2, s - 4, s - 4) / n_in
        in_var = (box(I2, ys + 2, xs + 2, s - 4, s - 4) / n_in - in_mean ** 2).sum(-1)
        out_mean = (box(Ii, ys - 1, xs - 1, s + 2, s + 2) - box(Ii, ys, xs, s, s)) / ((s + 2) ** 2 - s * s)
        contrast = np.abs(ring_mean - out_mean).sum(-1)
        score = (in_var / (ring_var + 150.0)) * np.minimum(contrast, 90) / 90
        ok = (in_var > 800) & (contrast > 25)
        sel = np.nonzero(ok)
        for sc, y, x in zip(score[sel], ys[sel], xs[sel]):
            cands.append((float(sc), int(y), int(x), s))
    cands.sort(reverse=True)
    picked = []
    for sc, y, x, s in cands:          # 겹치지 않게 고르기
        if all(x + s <= px or px + ps <= x or y + s <= py or py + ps <= y for _, py, px, ps in picked):
            picked.append((sc, y, x, s))
        if len(picked) >= 40:
            break
    if not picked:
        return []
    # 아이콘은 같은 크기로 같은 높이에 나란히 있다 → 점수 합이 가장 큰 '줄'만 남김 (아래 글자 등 제외)
    s_ref = picked[0][3]
    same = [p for p in picked if abs(p[3] - s_ref) <= 1 and p[0] >= 0.2 * picked[0][0]]
    rows = {}
    for p in same:
        key = next((k for k in rows if abs(k - p[1]) <= 2), p[1])
        rows.setdefault(key, []).append(p)
    best = max(rows.values(), key=lambda r: sum(p[0] for p in r))
    return sorted((x, y, s) for _, y, x, s in best)


# ---------- 등록한 디버프 ----------
# 사용자가 알려 준 등록 순서 (영역에서 왼쪽부터 찾은 아이콘에 이 이름을 미리 채움). 같은 이름은 한 디버프로 묶임.
DEFAULT_PRESET = ["어퍼", "하이드라", "데마", "데마", "잭", "케라,미르", "물풍선", "야옹",
                  "프라가라흐", "프라가라흐", "모모", "이면"]


def _enc(a: np.ndarray) -> dict:
    return {"h": a.shape[0], "w": a.shape[1], "rgb": base64.b64encode(np.ascontiguousarray(a).tobytes()).decode()}


def _dec(d: dict) -> np.ndarray:
    return np.frombuffer(base64.b64decode(d["rgb"]), np.uint8).reshape(d["h"], d["w"], 3).copy()


KIND_REFRESH = "refresh"    # 없거나 30초 이하면 '디버프 갱신' 창에 알림 (기본)
KIND_PRESENCE = "presence"  # 있으면 '디버프 발생' 창에 알림 (예: 붕괴)


class DebuffBook:
    """디버프 = 이름 하나 + 아이콘 여러 개.
    mode 'any': 아이콘 중 하나만 있어도 '있음' (예: 데마) / 'all': 모두 있어야 '있음' (예: 프라가라흐)
    kind: KIND_REFRESH / KIND_PRESENCE"""

    def __init__(self, path=DEBUFF_PATH):
        self.path = path
        self.items: list[dict] = []        # {"id", "name", "watch", "mode", "kind", "icons": [np.ndarray]}
        self.load()

    @property
    def icon_count(self):
        return sum(len(i["icons"]) for i in self.items)

    def find(self, icon: np.ndarray) -> dict | None:
        """이미 등록한 디버프 중 같은 아이콘을 가진 것."""
        best, best_s = None, MATCH_MIN
        for it in self.items:
            for ic in it["icons"]:
                s = similarity(ic, icon)
                if s > best_s:
                    best, best_s = it, s
        return best

    def upsert(self, icon: np.ndarray, name: str, watch: bool):
        """아이콘을 이름 묶음에 넣음. 이미 다른 이름에 있던 아이콘이면 옮김."""
        old = self.find(icon)
        if old is not None and old["name"] != name:
            old["icons"] = [ic for ic in old["icons"] if similarity(ic, icon) <= MATCH_MIN]
        group = next((i for i in self.items if i["name"] == name), None)
        if group is None:
            group = {"id": uuid.uuid4().hex[:8], "name": name, "watch": watch, "mode": "any",
                     "kind": KIND_REFRESH, "icons": []}
            self.items.append(group)
        if not any(similarity(ic, icon) > 0.97 for ic in group["icons"]):     # 거의 같은 그림만 중복으로 봄
            group["icons"].append(icon.copy())
        group["watch"] = watch
        self.items = [i for i in self.items if i["icons"]]

    def get(self, did: str) -> dict | None:
        return next((i for i in self.items if i["id"] == did), None)

    def by_name(self, name: str) -> dict | None:
        return next((i for i in self.items if i["name"] == name), None)

    def remove(self, did: str):
        self.items = [i for i in self.items if i["id"] != did]

    def save(self):
        data = [{"id": i["id"], "name": i["name"], "watch": i["watch"], "mode": i.get("mode", "any"),
                 "kind": i.get("kind", KIND_REFRESH), "icons": [_enc(ic) for ic in i["icons"]]} for i in self.items]
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
        self.items = []
        for d in data:
            icons = [_dec(x) for x in d["icons"]] if "icons" in d else [_dec(d["icon"])]   # 예전 형식(아이콘 1개)
            self.items.append({"id": d["id"], "name": d["name"], "watch": d.get("watch", True),
                               "mode": d.get("mode", "any"), "kind": d.get("kind", KIND_REFRESH), "icons": icons})


# ---------- 매칭 ----------
def similarity(a: np.ndarray, b: np.ndarray) -> float:
    """같은 크기 근처의 두 아이콘이 얼마나 비슷한지 (0~1)."""
    if abs(a.shape[0] - b.shape[0]) > 2 or abs(a.shape[1] - b.shape[1]) > 2:
        return 0.0
    big, small = (a, b) if a.shape[0] * a.shape[1] >= b.shape[0] * b.shape[1] else (b, a)
    pad = cv2.copyMakeBorder(big, 2, 2, 2, 2, cv2.BORDER_REPLICATE)
    return float(cv2.matchTemplate(pad.astype(np.float32), small.astype(np.float32), cv2.TM_CCOEFF_NORMED).max())


def match_all(rgb: np.ndarray, items: list[dict]) -> dict[str, tuple]:
    """{디버프 id: (점수, [찾은 아이콘 위치 (x, y, 한 변)])}
    점수: mode 'any' 는 묶인 아이콘 중 가장 잘 맞는 것, 'all' 은 가장 안 맞는 것 (모두 있어야 높음)."""
    out = {}
    hay = rgb.astype(np.float32)
    for it in items:
        per = []
        claimed = []            # 'all' 모드: 이미 다른 아이콘이 차지한 자리 (닮은 아이콘 하나가 두 번 인정되지 않게)
        for t in it["icons"]:
            if t.shape[0] > hay.shape[0] or t.shape[1] > hay.shape[1]:
                per.append((0.0, 0, 0, 0))
                continue
            res = cv2.matchTemplate(hay, t.astype(np.float32), cv2.TM_CCOEFF_NORMED)
            if it.get("mode") == "all":
                h = t.shape[0] // 2 + 1
                for cx, cy in claimed:
                    res[max(0, cy - h):cy + h + 1, max(0, cx - h):cx + h + 1] = -1.0
            _, mx, _, loc = cv2.minMaxLoc(res)
            claimed.append(loc)
            per.append((float(mx), loc[0], loc[1], t.shape[0]))
        if not per:
            out[it["id"]] = (0.0, [])
            continue
        score = min(p[0] for p in per) if it.get("mode") == "all" else max(p[0] for p in per)
        out[it["id"]] = (score, [(x, y, s) for sc, x, y, s in per if sc >= MATCH_MIN])
    return out


# ---------- 아이콘 아래 남은 시간 ('4M', '3' 등) ----------
def label_mask(rgb: np.ndarray, x: int, y: int, s: int):
    """아이콘 바로 아래의 흰 글자 비트맵 (없으면 None). 아이콘 밑에서 처음 나오는 글자 줄만."""
    H, W, _ = rgb.shape
    y0, y1 = y + s, min(H, y + s + int(s * 1.3))
    x0, x1 = max(0, x - 3), min(W, x + s + 3)
    if y0 >= y1:
        return None
    a = rgb[y0:y1, x0:x1].astype(np.int16)
    m = (a.min(2) >= 190) & ((a.max(2) - a.min(2)) <= 50)
    rows = np.nonzero(m.any(1))[0]
    if rows.size == 0 or m.sum() < 4:
        return None
    r0 = r1 = rows[0]                      # 첫 글자 줄 (빈 줄이 나오면 끝)
    while r1 + 1 < m.shape[0] and m[r1 + 1].any():
        r1 += 1
    m = m[r0:r1 + 1]
    xs = np.nonzero(m.any(0))[0]
    return m[:, xs.min():xs.max() + 1]


def read_label(mask: np.ndarray, book) -> int | None:
    """글자 비트맵 → 남은 초. 숫자는 버프 시간에서 배운 글자 모양(같은 폰트)으로 읽고,
    숫자보다 넓은 글자는 단위: 가운데 가로줄이 꽉 차면 H(시간), 아니면 M(분). 숫자만 있으면 초."""
    from .vision import segment_glyphs
    glyphs = segment_glyphs(mask, np.zeros_like(mask), 0, 0)
    if not glyphs:
        return None
    digits, unit = "", ""
    for g in glyphs:
        h, w = g.bits.shape
        if w >= 6:
            mid = g.bits[h // 2]
            unit = "H" if mid.all() else "M"
            continue
        c = book.classify(g.bits)
        if c is None or not c.isdigit():
            return None
        digits += c
    if not digits:
        return None
    return int(digits) * {"": 1, "M": 60, "H": 3600}[unit]


# ---------- 대상 체력바 ----------
def find_hp_bar(rgb: np.ndarray):
    """영역 안 대상(보스) 체력바의 (윗줄, 아랫줄+1). 없으면 None.
    체력바는 보스마다 색이 다르다(빨강, 보라 …). 공통점: 채워진 부분은 채도 높은 색, 나머지는 무채색 짙은 회색이고,
    가로로 길며 세로로는 색이 거의 같다(가로 그라데이션만). 풀밭처럼 진한 색이라도 무늬가 있으면 제외."""
    a = rgb.astype(np.int16)
    mx, mn = a.max(2), a.min(2)
    sat = (mx - mn) >= 50
    gray = ((mx - mn) <= 8) & (mx >= 35) & (mx <= 85)
    barlike = (sat | gray).mean(1) >= 0.5
    H = a.shape[0]
    y = 0
    while y < H:
        if not barlike[y]:
            y += 1
            continue
        y0 = y
        while y < H and barlike[y]:
            y += 1
        if y - y0 >= 6:
            band = a[y0:y]
            # 세로 균일도: 줄마다 위아래 이웃 줄과 거의 같은 열의 비율
            same = (np.abs(np.diff(band, axis=0)).max(2) <= 12).mean()
            # 가로 매끈함: 체력바는 부드러운 그라데이션, 지붕·풀밭 등은 무늬 때문에 옆 픽셀과 많이 다름
            smooth = (np.abs(np.diff(band, axis=1)).max(2) <= 12).mean()
            # 채워진 부분은 선명한 색(빨강 채도 ~187, 보라 ~116). 반투명 창 너머 지붕·벽은 탁함(60~80)
            fill = sat[y0:y]
            fill_sat = float(np.median((mx - mn)[y0:y][fill])) if fill.any() else 0.0
            if (same >= 0.75 and smooth >= 0.85 and fill.mean() >= 0.01 and fill_sat >= 95
                    and y - y0 <= 60):
                return y0, y
    return None


def hp_bar_visible(rgb: np.ndarray) -> bool:
    return find_hp_bar(rgb) is not None


def debuff_zone(rgb: np.ndarray):
    """체력바가 있으면 그 위쪽(디버프 아이콘 줄)만. (영역, 체력바 유무)"""
    bar = find_hp_bar(rgb)
    if bar is None:
        return rgb, False
    return rgb[:max(1, bar[0] - 1)], True
