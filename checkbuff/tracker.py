"""버프별 남은 시간 추적기.

한 번 믿을 만한 값을 읽으면 '만료 시각'을 예측해 두고, 이후 판독값은 예측과 비교해서만
받아들인다. 그래서 빨간 배경 때문에 몇 초간 시간을 못 읽거나 잘못 읽어도 알림창의
카운트다운은 예측값으로 계속 흘러간다.
"""
import difflib
import re
from collections import Counter
from dataclasses import dataclass, field

TOL = 2.0          # 예측과 이 정도(초) 차이까지는 같은 값으로 봄


@dataclass
class Buff:
    key: str
    names: Counter = field(default_factory=Counter)
    expiry: float | None = None          # time.monotonic() 기준 만료 시각
    full: float = 0.0                    # 막대 표시용 최대 남은 시간
    last_seen: float = 0.0
    last_read: float = 0.0               # 마지막으로 판독값을 받아들인 시각
    is_red: bool | None = None
    icon: object = None
    source: str = ""                     # glyph / ocr
    pending: list = field(default_factory=list)
    confidence: int = 0
    expired_at: float | None = None
    y: float = 0.0
    name_bits: object = None
    fixed: bool = False                  # 사용자가 교정한 이름으로 확정됨

    @property
    def name(self):
        return self.names.most_common(1)[0][0] if self.names else self.key


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s)


class Tracker:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.buffs: dict[str, Buff] = {}

    # ---------- 이름 정규화 ----------
    def canonical(self, raw: str) -> str:
        n = _norm(raw)
        best, score = None, 0.0
        for cand in list(self.cfg.get("known_names", [])) + list(self.buffs):
            r = difflib.SequenceMatcher(None, n, _norm(cand)).ratio()
            if r > score:
                best, score = cand, r
        return best if best and score >= 0.6 else raw

    # ---------- 갱신 ----------
    def update(self, observations: list[dict], now: float):
        seen_keys = set()
        for ob in observations:
            key = ob["name"] if ob.get("fixed") else self.canonical(ob["name"])
            if key in seen_keys:
                continue
            seen_keys.add(key)
            b = self.buffs.get(key)
            if b is None:
                b = self.buffs[key] = Buff(key)
            b.names[ob["name"]] += 1
            if ob.get("fixed"):
                b.fixed = True
                b.names[key] += 5
            if ob.get("name_bits") is not None:
                b.name_bits = ob["name_bits"]
            if key in self.cfg.get("known_names", []):
                b.names[key] += 2              # 알려진 이름이 표시 이름이 되도록
            b.last_seen = now
            b.y = ob.get("y", b.y)
            if ob.get("icon") is not None:
                b.icon = ob["icon"]
            b.is_red = ob.get("is_red")
            if ob.get("remaining") is not None:
                self._accept(b, ob["remaining"], now, ob.get("is_red"), ob.get("source", ""))

        keep_expired = float(self.cfg.get("expired_keep_sec", 8))
        missing = float(self.cfg.get("missing_timeout_sec", 6))
        for key, b in list(self.buffs.items()):
            if key in seen_keys:
                continue
            unseen = now - b.last_seen
            rem = None if b.expiry is None else b.expiry - now
            if b.expired_at is not None:
                if now - b.expired_at > keep_expired:
                    del self.buffs[key]
                continue
            if unseen > 1.5 and (rem is None or rem <= 3.0):
                if rem is None:
                    del self.buffs[key]
                else:
                    b.expired_at = now
            elif unseen > missing:
                del self.buffs[key]            # 시간이 남았는데 사라짐 = 해제/취소

    def _accept(self, b: Buff, r: int, now: float, is_red, source: str):
        # 색상 교차 검증: 30초 이하면 빨간 글자, 초과면 흰 글자여야 함
        th = self.cfg.get("threshold_sec", 30)
        if is_red is True and r > th + 15:
            return
        if is_red is False and r < th - 8:
            return
        implied = now + r + 0.5                # 화면은 초 단위 내림 표시
        if b.expired_at is not None:           # 만료 처리 후 다시 보임 = 재사용
            b.expired_at = None
            b.expiry = None
        if b.expiry is None:
            self._set(b, implied, now, source)
            b.confidence = 1
            return
        diff = implied - b.expiry
        if abs(diff) <= TOL:
            b.expiry += diff * 0.3
            b.confidence = min(b.confidence + 1, 20)
            b.last_read = now
            b.source = source
            b.pending.clear()
            return
        # 예측과 다름: 여러 번 연속으로 같은 이야기를 할 때만 인정
        b.pending = [(t, e) for t, e in b.pending if now - t < 6] + [(now, implied)]
        need = 2 if (diff > 0 or b.confidence <= 2) else 3   # 갱신(증가)은 빨리, 감소는 신중히
        recent = b.pending[-need:]
        if len(recent) >= need and max(e for _, e in recent) - min(e for _, e in recent) <= TOL:
            self._set(b, sum(e for _, e in recent) / len(recent), now, source)
            b.confidence = 1
            b.pending.clear()

    @staticmethod
    def _set(b: Buff, expiry: float, now: float, source: str):
        b.expiry = expiry
        b.full = max(expiry - now, 1.0) if (b.full == 0 or expiry - now > b.full) else b.full
        b.last_read = now
        b.source = source

    def rename(self, key: str, name: str):
        b = self.buffs.pop(key, None)
        if b is None:
            return
        old = self.buffs.pop(name, None)
        if old is not None and b.expiry is None:
            b.expiry, b.full, b.last_read = old.expiry, old.full, old.last_read
        b.key = name
        b.names = Counter({name: 1000})
        b.fixed = True
        self.buffs[name] = b

    def snapshot(self, now: float) -> list[dict]:
        out = []
        for b in self.buffs.values():
            out.append({
                "key": b.key, "name": b.name, "expiry": b.expiry, "full": b.full,
                "icon": b.icon, "is_red": b.is_red, "source": b.source,
                "stale": (now - b.last_read) if b.expiry is not None else None,
                "expired": b.expired_at is not None, "y": b.y, "fixed": b.fixed,
            })
        out.sort(key=lambda d: d["y"])
        return out

    def clear(self):
        self.buffs.clear()
