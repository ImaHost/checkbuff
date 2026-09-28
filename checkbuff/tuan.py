"""자동 소환: 체크한 버프가 곧 끝나면 펫을 [소환 키] → (대기) → [해제 키] 로 불러 버프를 다시 걸게 한다.

그룹마다 따로 동작한다 (설정 키 앞부분 = 그룹 key):
- 투안 (tuan): 노래 버프(전장의 서곡·행진곡·비바체·풍년가). 소환 후 '투안의 노래'가 새로 켜지거나 대상 버프가
  갱신/'(투안의노래)'로 바뀌면 성공. 이미 '버프이름 (투안의노래)'가 걸려 있으면 그 버프는 소환하지 않음.
- 햄 (ham): 햄 아드레날린·햄 버닝. 대상 버프가 갱신되면 성공.

공통:
- 소환 시점: 버프마다 20~25초(설정) 사이에서 무작위로 정함. 버프가 갱신되면 새로 정함.
- 펫을 여러 마리 등록 가능. 한 번 쓴 펫은 재사용 대기(기본 60초) 동안 쓰지 않음.
- 확인 시간 안에 성공 신호가 없으면 실패로 보고 곧바로 다음 펫을 소환.
- 게임 창이 활성일 때만 키를 보냄. 여러 그룹이 동시에 키를 보내지 않도록 한 번에 한 그룹씩.
"""
import random
import re
import threading
import time
from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal

from . import keys

TUAN_SUFFIX = " (투안의노래)"
MIN_GAP = 1.0          # 키 입력 사이 최소 간격 (초)
MAX_SUMMONERS = 3
MAX_TUANS = MAX_SUMMONERS
_KEY_LOCK = threading.Lock()     # 그룹끼리 키 입력이 섞이지 않게


@dataclass(frozen=True)
class SummonGroup:
    key: str                     # 설정 키 앞부분
    title: str                   # 화면 표시 이름 (투안, 햄)
    buffs: tuple                 # 기본 대상 버프
    song: str | None = None      # 소환하면 켜지는 버프 (성공 확인용)
    cover_suffix: str | None = None   # 이 접미사가 붙은 버프가 있으면 소환 불필요


GROUPS = (
    SummonGroup("tuan", "투안", ("전장의 서곡", "행진곡", "비바체", "풍년가"), "투안의 노래", TUAN_SUFFIX),
    SummonGroup("ham", "햄", ("햄 아드레날린", "햄 버닝")),
)
DEFAULT_TUAN_BUFFS = list(GROUPS[0].buffs)


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def base_name(name: str) -> str:
    """'전장의 서곡 (투안의노래)' → '전장의 서곡'"""
    return name[:-len(TUAN_SUFFIX)] if name and name.endswith(TUAN_SUFFIX) else name


def is_group_buff(group: SummonGroup, name: str, cfg: dict) -> bool:
    n = _norm(name)
    return bool(n) and any(_norm(t) == n for t in cfg.get(f"{group.key}_buffs") or group.buffs)


def is_tuan_buff(name: str, cfg: dict) -> bool:
    return is_group_buff(GROUPS[0], name, cfg)


def migrate(cfg: dict):
    """예전 설정(투안 소환/해제 키 한 쌍) → 목록. 각 그룹 목록이 없으면 빈 칸 하나."""
    if not cfg.get("tuans"):
        s, u = cfg.get("tuan_summon_key"), cfg.get("tuan_unsummon_key")
        cfg["tuans"] = [{"summon": s, "unsummon": u}]
    for g in GROUPS:
        if not cfg.get(f"{g.key}s"):
            cfg[f"{g.key}s"] = [{"summon": None, "unsummon": None}]
        cfg.setdefault(f"auto_{g.key}", {})


class AutoSummon(QObject):
    status = Signal(str)

    def __init__(self, cfg: dict, group: SummonGroup = GROUPS[0]):
        super().__init__()
        self.cfg = cfg
        self.group = group
        migrate(cfg)
        self.trigger_at: dict[str, float] = {}   # 버프 -> 이번 회차 소환 시점(남은 초)
        self.tries: dict[str, int] = {}          # 버프 -> 이번 회차 시도 횟수
        self.done: set[str] = set()              # 이번 회차에 성공한 버프
        self.ready_at: dict[int, float] = {}     # 펫 번호 -> 재사용 가능 시각
        self.pending = None                      # 확인 대기 중인 소환
        self.busy = False
        self.last_key = 0.0
        self._last_wait_msg = 0.0

    # ---------- 설정 ----------
    def c(self, name, default=None):
        return self.cfg.get(f"{self.group.key}_{name}", default)

    @property
    def summoners(self) -> list[dict]:
        return self.cfg.get(f"{self.group.key}s") or []

    tuans = summoners        # 예전 이름

    def usable(self) -> list[int]:
        return [i for i, t in enumerate(self.summoners) if t.get("summon") and t.get("unsummon")]

    def targets(self) -> list[str]:
        at, watch = self.cfg.get(f"auto_{self.group.key}", {}), self.cfg.get("watch", {})
        return [n for n, on in at.items() if on and watch.get(n) and is_group_buff(self.group, n, self.cfg)]

    def ready(self) -> str | None:
        """실행할 수 없는 이유 (None 이면 실행 가능)."""
        if not self.c("enabled"):
            return "꺼짐"
        if not self.usable():
            return f"{self.group.title}의 소환 키와 해제 키를 등록하세요"
        return None

    def cooldown_left(self, idx: int, now: float | None = None) -> float:
        now = time.monotonic() if now is None else now
        return max(0.0, self.ready_at.get(idx, 0.0) - now)

    def _range(self):
        lo, hi = float(self.c("trigger_min", 20)), float(self.c("trigger_max", 25))
        return min(lo, hi), max(lo, hi)

    # ---------- 판단 ----------
    def update(self, items: list[dict], active_names, now: float):
        """launcher 가 0.2초마다 호출.
        items: 체크한 버프 [{name, remaining, expired}], active_names: 지금 버프 목록에 켜져 있는 이름들"""
        g = self.group
        lo, hi = self._range()
        active = set(active_names or [])
        song = self.c("song_name", g.song) if g.song else None
        by_name = {i["name"]: i for i in items}

        def covered(n):
            if not g.cover_suffix:
                return False
            return f"{n}{g.cover_suffix}" in active or f"{n}{g.cover_suffix}" in by_name

        def refreshed(n):
            it = by_name.get(n)
            return bool(it and not it["expired"] and it["remaining"] is not None and it["remaining"] > hi + 5)

        # 1) 직전 소환 결과 확인
        if self.pending:
            p = self.pending
            if self.busy or now < p["keys_done"]:
                return
            ok = (song is not None and song in active and not p["song_before"]) \
                or any(covered(n) or refreshed(n) for n in p["names"])
            if ok:
                self.done.update(p["names"])
                self.pending = None
                self._say(f"{time.strftime('%H:%M:%S')} {g.title} {p['idx'] + 1} 성공 · {', '.join(p['names'])}")
            elif now >= p["keys_done"] + float(self.c("verify_sec", 6)):
                self.pending = None
                why = f"'{song}' 안 보임" if song else "버프 갱신 안 됨"
                self._say(f"{g.title} {p['idx'] + 1} 실패 ({why}) → 다음 {g.title} 시도")
            else:
                return

        # 2) 소환이 필요한 버프 찾기
        max_tries = max(3, len(self.usable()))
        due = []
        for n in self.targets():
            it = by_name.get(n)
            if it is None:
                continue
            if refreshed(n):                          # 갱신됨 → 다음 회차 준비
                self.trigger_at.pop(n, None)
                self.tries.pop(n, None)
                self.done.discard(n)
                continue
            if covered(n) or n in self.done:
                continue
            trig = self.trigger_at.setdefault(n, random.uniform(lo, hi))
            rem = it["remaining"]
            if (it["expired"] or (rem is not None and rem <= trig)) and self.tries.get(n, 0) < max_tries:
                due.append(n)
        if not due or self.busy or now - self.last_key < MIN_GAP or self.ready():
            return
        if self.c("game_only", True) and not keys.game_is_foreground():
            return                                    # 게임 창이 아니면 대기 (시도 횟수 소모 안 함)

        # 3) 재사용 가능한 펫 고르기 (등록 순서대로)
        free = [i for i in self.usable() if self.cooldown_left(i, now) <= 0]
        if not free:
            wait = min(self.cooldown_left(i, now) for i in self.usable())
            if now - self._last_wait_msg > 5:
                self._last_wait_msg = now
                self._say(f"모든 {g.title} 재사용 대기 중 · {wait:.0f}초 뒤 소환 ({', '.join(due)})")
            return
        idx = free[0]
        for n in due:
            self.tries[n] = self.tries.get(n, 0) + 1
        delay = float(self.c("delay_sec", 1.0))
        self.ready_at[idx] = now + float(self.c("cooldown_sec", 60))
        self.pending = {"idx": idx, "names": due, "song_before": bool(song and song in active),
                        "keys_done": now + delay + 0.3}
        self.fire(idx, reason=", ".join(due))

    # ---------- 키 입력 ----------
    def fire(self, idx: int, reason: str = "", countdown: float = 0.0):
        if self.busy or idx >= len(self.summoners):
            return
        self.busy = True
        threading.Thread(target=self._run, args=(idx, reason, countdown), daemon=True).start()

    def _say(self, msg):
        self.status.emit(msg)

    def _run(self, idx, reason, countdown):
        title = self.group.title
        try:
            for left in range(int(countdown), 0, -1):
                self._say(f"{left}초 뒤 {title} {idx + 1} 테스트… 게임 창을 눌러 두세요")
                time.sleep(1)
            t = self.summoners[idx]
            delay = float(self.c("delay_sec", 1.0))
            with _KEY_LOCK:
                keys.press(t["summon"])
                self._say(f"{title} {idx + 1} 소환 [{t['summon']['label']}] → {delay:g}초 뒤 해제"
                          + (f" · {reason}" if reason else ""))
                time.sleep(delay)
                keys.press(t["unsummon"])
            if countdown:
                self._say(f"{time.strftime('%H:%M:%S')} {title} {idx + 1} 테스트 완료")
        except Exception as e:
            self._say(f"키 입력 실패: {e}")
            self.pending = None
        finally:
            self.last_key = time.monotonic()
            if self.pending:
                self.pending["keys_done"] = time.monotonic()
            self.busy = False


AutoTuan = AutoSummon      # 예전 이름
