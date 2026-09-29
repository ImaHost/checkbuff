"""픽셀 글리프 학습기.

게임 시간 글자는 작은 픽셀 폰트라 OCR 이 9↔3 등을 자주 혼동한다. 대신 글자 모양(비트맵)을
그대로 키로 삼고, 다음 두 가지 증거로 각 모양이 어떤 숫자인지 스스로 알아낸다.

- OCR 투표: OCR 결과 글자 수 == 글리프 수 일 때 자리별로 한 표씩.
- 카운트다운 연결: 연속 프레임(1초 미만 간격)에서 마지막 자리 숫자가 바뀌면
  '새 모양 = 이전 모양 - 1' 이라는 관계가 생긴다. 이 관계로 이어진 모양들은 상대값이
  확정되므로, OCR 표를 가장 잘 설명하는 오프셋 하나만 고르면 된다.
  → OCR 이 9 를 3 으로 읽어도 나머지 숫자들의 표가 맞으면 9 로 바로잡힌다.
"""
import base64
import json
import os
from collections import Counter, defaultdict

import numpy as np


def glyph_key(bits: np.ndarray) -> str:
    h, w = bits.shape
    return f"{h}x{w}:" + np.packbits(bits).tobytes().hex()


def _mismatch(a: np.ndarray, b: np.ndarray) -> float:
    h, w = max(a.shape[0], b.shape[0]), max(a.shape[1], b.shape[1])
    pa = np.zeros((h, w), bool)
    pb = np.zeros((h, w), bool)
    pa[:a.shape[0], :a.shape[1]] = a
    pb[:b.shape[0], :b.shape[1]] = b
    return float((pa ^ pb).sum()) / max(1, int((pa | pb).sum()))


class GlyphBook:
    MAX_GLYPHS = 600

    def __init__(self, path=None):
        self.path = path
        self.bits: dict[str, np.ndarray] = {}
        self.seen: Counter = Counter()
        self.votes: dict[str, Counter] = defaultdict(Counter)
        self.edges: Counter = Counter()          # (prev_key, next_key): next = prev - 1
        self.labels: dict[str, str] = {}
        self._dirty = False
        if path:
            self.load()

    # ---------- 관측 ----------
    def register(self, bits: np.ndarray) -> str:
        k = glyph_key(bits)
        if k not in self.bits:
            if len(self.bits) >= self.MAX_GLYPHS:
                self._evict()
            self.bits[k] = bits
        self.seen[k] += 1
        return k

    def vote(self, keys: list[str], ocr_text: str | None):
        if not ocr_text:
            return
        chars = [c for c in ocr_text.replace(" ", "") if c.isdigit() or "가" <= c <= "힣"]
        if len(chars) != len(keys):
            return
        for k, c in zip(keys, chars):
            v = self.votes[k]
            v[c] += 1
            if sum(v.values()) > 60:          # 오래된 표 비중 줄이기
                for kk in v:
                    v[kk] = (v[kk] + 1) // 2
        self._dirty = True

    def link(self, prev_key: str, next_key: str):
        """prev 다음 프레임에 next 가 나타남 (next = prev - 1)."""
        if prev_key == next_key or self.seen[prev_key] < 2 or self.seen[next_key] < 1:
            return
        if _mismatch(self.bits[prev_key], self.bits[next_key]) < 0.18:
            return                              # 잡티 때문에 모양이 살짝 달라진 것일 뿐
        self.edges[(prev_key, next_key)] += 1
        self._dirty = True

    # ---------- 판정 ----------
    def solve(self):
        if not self._dirty:
            return
        self._dirty = False
        labels = {}
        # 한글 단위(분/초/시간/일): 다수결. OCR 은 '분'을 '브·부·널' 등으로 제각각 읽으므로
        # 초·시·간·일이 아닌 한글은 모두 '분'으로 모아서 센다
        for k, v in self.votes.items():
            units = Counter()
            for c, n in v.items():
                if not c.isdigit():
                    units[c if c in "초시간일" else "분"] += n
            total = sum(v.values())
            if units and total >= 2:
                c, n = units.most_common(1)[0]
                if n / total >= 0.6:
                    labels[k] = c
        labels.update(self._solve_digits())
        self.labels = labels

    def _solve_digits(self) -> dict:
        """숫자: '다음 모양 = 이전 모양 - 1' 관계로 상대값을 정하고 OCR 표로 오프셋 결정.

        한두 번 생긴 잘못된 관계(프레임 누락 등)가 섞이면 전체 번호가 밀리므로
        1) 여러 번 관찰된 관계만 쓰고, 2) 많이 관찰된 관계부터 뼈대(최대 신장 트리)를 세운 뒤,
        3) 뼈대와 모순되는 관계가 많거나, 4) 결과가 OCR 표와 뚜렷이 어긋나면 그 덩어리는 버린다."""
        if not self.edges:
            return {}
        top = max(self.edges.values())
        strong = {e: n for e, n in self.edges.items() if n >= max(2, 0.05 * top)}
        # 최대 신장 숲 (많이 본 관계부터)
        parent = {}

        def find(x):
            parent.setdefault(x, x)
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        adj = defaultdict(list)
        for (a, b), n in sorted(strong.items(), key=lambda kv: -kv[1]):
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb
                adj[a].append((b, -1))
                adj[b].append((a, +1))
        out, done = {}, set()
        for start in list(adj):
            if start in done:
                continue
            rel = {start: 0}
            stack = [start]
            while stack:
                cur = stack.pop()
                for nb, d in adj[cur]:
                    if nb not in rel:
                        rel[nb] = (rel[cur] + d) % 10
                        stack.append(nb)
            done |= rel.keys()
            if len(rel) < 4:
                continue
            # 뼈대와 모순되는 관계 비중 확인
            good = bad = 0
            for (a, b), n in strong.items():
                if a in rel and b in rel:
                    if (rel[a] - 1) % 10 == rel[b]:
                        good += n
                    else:
                        bad += n
            if bad > 0.1 * good:
                continue
            scores = sorted(((sum(self.votes[k][str((r + off) % 10)] for k, r in rel.items() if k in self.votes), off)
                             for off in range(10)), reverse=True)
            if scores[0][0] < 3 or scores[0][0] <= scores[1][0]:
                continue
            off = scores[0][1]
            cand = {k: str((r + off) % 10) for k, r in rel.items()}
            if self._contradicts_ocr(cand):
                continue
            out.update(cand)
        return out

    def _contradicts_ocr(self, cand: dict) -> bool:
        """OCR 이 확신하는 글자와 다르게 붙은 이름표가 있으면 True. (OCR 은 9→3 을 자주 헷갈리므로 그 쌍은 봐줌)"""
        for k, lab in cand.items():
            v = self.votes.get(k)
            if not v:
                continue
            total = sum(v.values())
            c, n = v.most_common(1)[0]
            if total >= 10 and n / total >= 0.8 and c.isdigit() and c != lab and {c, lab} != {"3", "9"}:
                return True
        return False

    def distrust(self):
        """판독이 OCR 과 계속 어긋날 때: 숫자 학습(관계·이름표)을 버리고 처음부터 다시 배움. 모양·OCR 표는 유지."""
        self.edges.clear()
        self.labels = {k: v for k, v in self.labels.items() if not v.isdigit()}
        self._dirty = True

    def classify(self, bits: np.ndarray) -> str | None:
        k = glyph_key(bits)
        if k in self.labels:
            return self.labels[k]
        best, best_d = None, 0.13
        for lk, lab in self.labels.items():
            b = self.bits.get(lk)
            if b is None or abs(b.shape[0] - bits.shape[0]) > 1 or abs(b.shape[1] - bits.shape[1]) > 1:
                continue
            d = _mismatch(b, bits)
            if d < best_d:
                best, best_d = lab, d
        return best

    def read(self, glyphs) -> str | None:
        out = []
        for g in glyphs:
            c = self.classify(g.bits)
            if c is None:
                return None
            out.append(c)
        return "".join(out)

    def learned_digits(self) -> set[str]:
        return {v for v in self.labels.values() if v.isdigit()}

    # ---------- 저장 ----------
    def _evict(self):
        keep = {k for k in self.labels} | {k for e in self.edges for k in e}
        victims = sorted((k for k in self.bits if k not in keep), key=lambda k: self.seen[k])
        for k in victims[: max(1, len(victims) // 4)]:
            self.bits.pop(k, None)
            self.seen.pop(k, None)
            self.votes.pop(k, None)

    def reset(self):
        self.bits.clear()
        self.seen.clear()
        self.votes.clear()
        self.edges.clear()
        self.labels.clear()

    def save(self):
        if not self.path:
            return
        data = {
            "glyphs": {k: {"h": b.shape[0], "w": b.shape[1],
                           "bits": base64.b64encode(np.packbits(b).tobytes()).decode(),
                           "seen": self.seen[k], "votes": dict(self.votes.get(k, {}))}
                       for k, b in self.bits.items()},
            "edges": [[a, b, n] for (a, b), n in self.edges.items()],
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, self.path)

    def load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return
        for k, g in data.get("glyphs", {}).items():
            raw = np.frombuffer(base64.b64decode(g["bits"]), np.uint8)
            bits = np.unpackbits(raw)[: g["h"] * g["w"]].reshape(g["h"], g["w"]).astype(bool)
            self.bits[k] = bits
            self.seen[k] = g.get("seen", 1)
            if g.get("votes"):
                self.votes[k] = Counter(g["votes"])
        for a, b, n in data.get("edges", []):
            if a in self.bits and b in self.bits:
                self.edges[(a, b)] = n
        self._dirty = True
        self.solve()
