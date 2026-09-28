"""백그라운드 감시 스레드: 캡처 → 분석 → 글리프 학습 → 추적 → UI 로 스냅샷 전달."""
import difflib
import re
import time
import traceback

import mss
import numpy as np
from PySide6.QtCore import QThread, Signal

from .glyphs import GlyphBook
from .names import NameBook
from .ocr import OcrUnavailable, WindowsOcr
from .tracker import Tracker
from .debuffs import MATCH_MIN, debuff_zone, detect_icons, label_mask, match_all, read_label
from .glyphs import glyph_key
from .tuan import TUAN_SUFFIX, base_name
from .vision import Analyzer, parse_time


AUDIT_SEC = 2.0     # 숫자 학습이 끝난 뒤에도 버프마다 이 간격으로 OCR 과 비교


def _same_digits(a: str, b: str) -> bool:
    """글리프 판독과 OCR 판독의 숫자가 같은지. OCR 은 9 를 3 으로 자주 읽으므로 둘을 같게 본다."""
    def d(s):
        return re.sub(r"\D", "", (s or "").replace("9", "3"))
    return d(a) == d(b)


class MonitorWorker(QThread):
    snapshot = Signal(object)
    scanned = Signal(object)            # 버프 선택 창용: 현재 화면에서 찾은 버프 목록
    debuff_scanned = Signal(object)     # 디버프 등록 창용: 디버프 영역에서 찾은 아이콘
    debuff_snapshot = Signal(object)    # {디버프 id: 일치 점수}
    failed = Signal(str)

    def __init__(self, cfg: dict, book: GlyphBook):
        super().__init__()
        self.cfg = cfg
        self.book = book
        self.tracker = Tracker(cfg)
        self._running = False
        self._paused = True
        self._reset_tracker = False
        self._prev_glyphs = {}          # buff key -> (t, [keys], [wide])
        self.names = NameBook()
        self._renames = []              # UI 에서 요청한 이름 교정 (key, 새 이름)
        self._name_batches = []         # 버프 선택 창에서 확정한 [(bits, 이름)]
        self._scan = False
        self._col = None
        self._suffix_cache = {}        # 뒷부분 비트맵 키 -> OCR 결과
        self._last_audit = {}          # 버프 -> 마지막 OCR 교차 확인 시각
        self._disagree = {}            # 버프 -> 글리프/OCR 연속 불일치 횟수
        self._debuff_scan = False
        self.debuff_items = []         # 감시할 디버프 [{"id", "icon"}] (UI 가 통째로 바꿔 끼움)

    def request_rename(self, key: str, name: str):
        self._renames.append((key, name))

    def request_debuff_scan(self):
        self._debuff_scan = True

    def set_debuff_items(self, items):
        self.debuff_items = [{"id": i["id"], "icons": list(i["icons"]), "mode": i.get("mode", "any")} for i in items]

    def _debuffs(self, sct):
        """디버프 영역: 등록 창용 아이콘 찾기 / 감시 중이면 등록한 아이콘이 있는지 확인."""
        region = self.cfg.get("debuff_region")
        if not region:
            return
        if self._debuff_scan:
            self._debuff_scan = False
            rgb, _ = debuff_zone(self._grab(sct, region))       # 체력바 아래·안쪽 글자는 제외
            icons = [(x, y, s, rgb[y:y + s, x:x + s].copy()) for x, y, s in detect_icons(rgb)]
            self.debuff_scanned.emit({"rgb": rgb, "icons": icons})
        items = self.debuff_items
        if items and not self._paused and self.cfg.get("debuff_enabled", True):
            rgb, bar = debuff_zone(self._grab(sct, region))     # 체력바가 있으면 그 위(디버프 줄)만
            if self.cfg.get("debuff_need_hpbar", True) and not bar:
                # 대상(보스)을 선택하지 않아 체력바가 없으면 디버프 확인 안 함
                self.debuff_snapshot.emit({"scores": {}, "secs": {}, "bar": False, "t": time.monotonic()})
                return
            found = match_all(rgb, items)
            secs = {}
            for did, (score, locs) in found.items():
                if score >= MATCH_MIN:                   # 있으면 아래 남은 시간('4M', '3')도 읽음 (여러 개면 가장 짧은 것)
                    vals = []
                    for x, y, s in locs:
                        m = label_mask(rgb, x, y, s)
                        v = read_label(m, self.book) if m is not None else None
                        if v is not None:
                            vals.append(v)
                    secs[did] = min(vals) if vals else None
            self.debuff_snapshot.emit({"scores": {k: v[0] for k, v in found.items()}, "secs": secs,
                                       "bar": True, "t": time.monotonic()})

    def request_scan(self):
        self._scan = True

    def apply_names(self, pairs):
        self._name_batches.append(pairs)

    def set_paused(self, paused: bool):
        self._paused = paused
        if paused:
            self._reset_tracker = True

    def stop(self):
        self._running = False
        self.wait(3000)

    def run(self):
        try:
            ocr = WindowsOcr("ko")
        except OcrUnavailable as e:
            self.failed.emit(str(e))
            return
        analyzer = Analyzer(self.cfg, ocr)
        self._running = True
        last_save = time.monotonic()
        last_region = None
        with mss.mss() as sct:
            while self._running:
                t0 = time.monotonic()
                if self._reset_tracker:
                    self.tracker.clear()
                    self._prev_glyphs.clear()
                    self._reset_tracker = False
                region = self.cfg.get("region")
                if region != last_region:
                    saved = self.cfg.get("name_col")
                    self._col = saved[1] if saved and saved[0] == region else None
                    last_region = region
                if region and (not self._paused or self._scan):
                    try:
                        self._tick(sct, analyzer, region)
                    except Exception:
                        self.failed.emit(traceback.format_exc(limit=3))
                        self.msleep(1000)
                try:
                    self._debuffs(sct)
                except Exception:
                    self.failed.emit(traceback.format_exc(limit=3))
                if time.monotonic() - last_save > 30:
                    self.book.save()
                    last_save = time.monotonic()
                wait = self.cfg.get("interval_ms", 500) / 1000 - (time.monotonic() - t0)
                self.msleep(int(max(0.05, wait) * 1000))
        self.book.save()
        ocr.close()

    def _grab(self, sct, region):
        x, y, w, h = region
        shot = sct.grab({"left": x, "top": y, "width": w, "height": h})
        return np.asarray(shot)[..., [2, 1, 0]].copy()

    def _find_col(self, analyzer, rgb, region):
        col = analyzer.find_name_column(rgb)
        if col is not None:
            self._col = col
            self.cfg["name_col"] = [region, col]
        return col

    def identify(self, analyzer, bits):
        """이름 비트맵 → 이름. 저장된 이름 뒤에 '(투안의노래)'가 붙어 있으면 '이름 (투안의노래)'."""
        name = self.names.lookup(bits)
        if name is not None:
            return name
        hit = self.names.lookup_prefix(bits)
        if not hit:
            return None
        base, rest = hit
        k = glyph_key(rest)
        if k not in self._suffix_cache:           # 뒷부분은 모양별로 한 번만 OCR
            words = analyzer._ocr_mask(np.pad(rest, 2))
            self._suffix_cache[k] = "".join(w.text for w in words)
        # OCR 이 '(투한의노대' 처럼 몇 글자 틀려도 인정 (한글만 남겨 유사도 비교)
        text = re.sub(r"[^가-힣]", "", self._suffix_cache[k])
        if difflib.SequenceMatcher(None, text, "투안의노래").ratio() >= 0.5:
            return f"{base_name(base)}{TUAN_SUFFIX}"
        return None

    def _do_scan(self, analyzer, rgb, region):
        """버프 선택 창용 목록: 회색(대기) 버프까지 이름과 아이콘만."""
        col = self._find_col(analyzer, rgb, region) or self._col
        rows = analyzer.scan(rgb, col) if col is not None else []
        out = []
        for r in rows:
            known = self.identify(analyzer, r.name_bits)
            out.append({"name": known or r.ocr_name, "ocr": r.ocr_name, "known": bool(known),
                        "bits": r.name_bits, "icon": r.icon, "active": r.active})
        self.scanned.emit(out)

    def _tick(self, sct, analyzer: Analyzer, region):
        while self._renames:
            key, name = self._renames.pop(0)
            b = self.tracker.buffs.get(key)
            if b is not None and b.name_bits is not None:
                self.names.add(b.name_bits, name)
            self.tracker.rename(key, name)
        while self._name_batches:
            for bits, name in self._name_batches.pop(0):
                if bits is not None:
                    self.names.add(bits, name)
            self.tracker.clear()            # 새 이름으로 다시 추적
            self._prev_glyphs.clear()

        rgb = self._grab(sct, region)
        t_start = time.monotonic()
        if self._scan:
            self._scan = False
            self._do_scan(analyzer, rgb, region)
            if self._paused:
                return
        col = self._col if self._col is not None else self._find_col(analyzer, rgb, region)
        if col is None:
            self.snapshot.emit({"rgb": rgb, "rows": [], "buffs": self.tracker.snapshot(time.monotonic()),
                                "learned": len(self.book.learned_digits()), "unknown": 0,
                                "ms": int((time.monotonic() - t_start) * 1000)})
            return
        frame = analyzer.analyze(rgb, col)
        watch = self.cfg.get("watch", {})
        need_digits = len(self.book.learned_digits()) < 10
        ocr_budget = 3

        obs, unknown, active = [], 0, []
        for row in frame.rows:
            name = self.identify(analyzer, row.name_bits)
            if name is None:
                unknown += 1
            else:
                active.append(name)                 # 흰 이름 = 지금 걸려 있는 버프
            keys = [self.book.register(g.bits) for g in row.glyphs]
            self._learn_countdown(name or f"row{row.band[0] // 4}", time.monotonic(),
                                  keys, [g.wide for g in row.glyphs])
            if name is None or not watch.get(base_name(name), False) or not row.glyphs:
                continue                    # 체크한 버프만 시간 판독
            glyph_text = self.book.read(row.glyphs)
            g_val = parse_time(glyph_text)
            time_text = o_val = None
            t_now = time.monotonic()
            audit = t_now - self._last_audit.get(name, 0.0) >= AUDIT_SEC   # 학습이 끝나도 가끔 OCR 로 교차 확인
            if (g_val is None or need_digits or audit) and ocr_budget > 0:
                ocr_budget -= 1
                self._last_audit[name] = t_now
                time_text = analyzer.ocr_text(frame.mask, row.time_box)
                self.book.vote(keys, time_text)
                o_val = parse_time(time_text)
                if g_val is not None and o_val is not None:
                    if _same_digits(glyph_text, time_text):
                        self._disagree[name] = 0
                    else:
                        g_val = None                    # 둘이 다르면 이번 프레임은 쓰지 않고 예측으로 넘김
                        self._disagree[name] = self._disagree.get(name, 0) + 1
                        if self._disagree[name] >= 3:   # 계속 어긋나면 숫자 학습이 틀린 것 → 다시 배움
                            self.book.distrust()
                            self._disagree.clear()
                            self.failed.emit("숫자 판독이 OCR 과 계속 달라 숫자 학습을 다시 시작합니다")
            remaining, source = g_val, "glyph"
            if remaining is None:
                remaining, source = o_val, "ocr"
            obs.append({"name": name, "fixed": True, "name_bits": row.name_bits,
                        "remaining": remaining, "source": source,
                        "is_red": row.is_red, "icon": row.icon, "y": row.band[0]})
        now = time.monotonic()
        self.book.solve()
        self.tracker.update(obs, now)
        self.snapshot.emit({
            "rgb": rgb,
            "rows": [(r.name_box, r.time_box) for r in frame.rows],
            "buffs": self.tracker.snapshot(now),
            "learned": len(self.book.learned_digits()),
            "unknown": unknown,
            "active_names": active,
            "ms": int((now - t_start) * 1000),
        })

    def _learn_countdown(self, key, now, keys, wide):
        prev = self._prev_glyphs.get(key)
        self._prev_glyphs[key] = (now, keys, wide)
        if not prev or len(keys) < 2 or not wide[-1] or wide[-2]:
            return
        pt, pkeys, pwide = prev
        if now - pt > 0.95 or len(pkeys) != len(keys) or pwide != wide:
            return
        if pkeys[-1] != keys[-1]:            # 단위 글자가 바뀌었으면 비교 불가
            return
        self.book.link(pkeys[-2], keys[-2])
