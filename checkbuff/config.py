"""설정 저장/불러오기 (%APPDATA%\\CheckBuff\\config.json)."""
import json
import os
from pathlib import Path

APP_DIR = Path(os.environ.get("APPDATA", Path.home())) / "CheckBuff"
CONFIG_PATH = APP_DIR / "config.json"
GLYPH_PATH = APP_DIR / "glyphs.json"

DEFAULT_KNOWN_NAMES = [
    "공격력 증가",
    "전장의 서곡",
    "행진곡",
    "퓨리 오브 더 버서커",
    "마나 실드",
    "디펜스",
    "블레이즈",
]

DEFAULTS = {
    "region": None,              # [x, y, w, h] 물리 픽셀 좌표
    "hotkey": "F10",
    "admin_task": True,          # UAC 창 없이 관리자로 실행 (작업 스케줄러)
    "interval_ms": 500,          # 체크 주기
    "threshold_sec": 30,         # 이 시간 이하면 알림창에 표시
    "expired_keep_sec": 8,       # 만료된 버프를 알림창에 남겨둘 시간
    "missing_timeout_sec": 6,    # 이 시간 동안 안 보이면 목록에서 제거
    "sound": True,
    "alert_pos": None,           # [x, y]
    "alert_locked": False,       # 잠금 = 클릭 통과 + 알림 있을 때만 표시
    "alert_scale": 1.0,
    "alert_opacity": 0.78,
    "known_names": DEFAULT_KNOWN_NAMES,
    "alert_collapsed": False,    # 알림창 이름 접기 (아이콘 + 시간만)
    # --- 디버프 ---
    "debuff_region": None,       # [x, y, w, h] 대상 체력바 위 디버프 아이콘 줄
    "debuff_hotkey": "F11",
    "debuff_enabled": True,
    "debuff_missing_sec": 1.0,   # 이 시간 이상 안 보여야 '없음' (깜빡임 대비)
    "debuff_threshold_sec": 30,  # 아이콘 아래 시간이 숫자(초)로 이 이하면 갱신 필요
    "debuff_preset": None,       # 등록 창 기본 이름 순서 (None = debuffs.DEFAULT_PRESET)
    "debuff_hide_when_none": False,
    "debuff_need_hpbar": True,
    "debuff_sound": True,        # 디버프 알림음: 갱신 '딩-동' + '있으면 알림'(붕괴) 음성
    "buff_volume": 40,           # 0~100
    "debuff_volume": 40,
    "presence_alert_pos": None,
    "presence_alert_collapsed": False,   # 영역에 대상 체력바가 보일 때만 확인 (보스를 선택하지 않았으면 무시)
    "debuff_alert_pos": None,
    "debuff_alert_collapsed": False,
    # --- 자동 투안 ---
    "tuan_enabled": False,
    "tuans": None,               # [{"summon": 키, "unsummon": 키}] 등록 순서대로 사용 (키 = {"vk", "mods", "label"})
    "tuan_delay_sec": 1.0,       # 소환 후 해제까지
    "tuan_trigger_min": 20,      # 이 범위(남은 초)에서 무작위로 소환
    "tuan_trigger_max": 25,
    "tuan_cooldown_sec": 60,     # 투안 재사용 대기
    "tuan_verify_sec": 6,        # 소환 후 이 시간 안에 '투안의 노래'가 안 보이면 실패 → 다음 투안
    "tuan_song_name": "투안의 노래",
    "tuan_game_only": True,      # 게임 창이 활성일 때만 키 입력
    "tuan_buffs": ["전장의 서곡", "행진곡", "비바체", "풍년가"],
    "auto_tuan": {},             # 버프 이름 -> 자동 투안 여부
    # --- 자동 햄 (햄 아드레날린·햄 버닝) ---
    "ham_enabled": False,
    "hams": None,                # [{"summon": 키, "unsummon": 키}]
    "ham_delay_sec": 1.0,
    "ham_trigger_min": 20,
    "ham_trigger_max": 25,
    "ham_cooldown_sec": 60,
    "ham_verify_sec": 6,         # 소환 후 이 시간 안에 버프가 갱신되지 않으면 실패 → 다음 햄
    "ham_game_only": True,
    "ham_buffs": ["햄 아드레날린", "햄 버닝"],
    "auto_ham": {},
    # --- 색상 판정 (고급) ---
    "white_min": 248,            # 흰 글자: RGB 모두 이 값 이상 (게임 글자는 정확히 255)
    "white_spread": 6,           # 흰 글자: 채널 간 차이 최대값
    "gray_level": 127,           # 사용 중이 아닌 버프 이름 색 (회색)
    "gray_tol": 2,               # 회색 글자는 정확히 127 → ±2 (넓히면 회색 배경이 글자로 잡힘)
    "red_r_min": 240,            # 빨간 글자: R 최소 (게임 글자는 정확히 255,0,0)
    "red_gb_max": 20,            # 빨간 글자: G, B 최대
    "red_diff_min": 220,         # 빨간 글자: R - max(G,B) 최소
    "outline_check": True,       # 글자 주변 검은 외곽선이 있는 픽셀만 글자로 인정
    "outline_lum": 70,           # 외곽선으로 인정할 최대 밝기
}


VISION_VERSION = 2
VISION_KEYS = ("white_min", "white_spread", "gray_level", "gray_tol", "red_r_min", "red_gb_max", "red_diff_min",
               "outline_lum")


def load() -> dict:
    cfg = dict(DEFAULTS)
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg.update(json.load(f))
    except (OSError, ValueError):
        pass
    if cfg.get("hotkey") == "F9" and not cfg.get("hotkey_migrated"):
        cfg["hotkey"] = "F10"            # F9 는 윈도우 캡처 도구와 겹침
    cfg["hotkey_migrated"] = True
    # 인식 기준을 바꾼 버전: 예전 설정 파일에 저장된 색 기준을 새 기본값으로 교체
    if cfg.get("vision_version", 0) < VISION_VERSION:
        for k in VISION_KEYS:
            cfg[k] = DEFAULTS[k]
        cfg["vision_version"] = VISION_VERSION
    return cfg


def save(cfg: dict) -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_PATH.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CONFIG_PATH)
