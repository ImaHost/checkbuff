"""알림음과 음성 안내. 윈도우 시스템 소리 대신 직접 만든 소리를 비동기로 재생한다.

- buff   : 높은 '띵-' (버프 갱신 필요)
- debuff : 낮은 '딩-동' (디버프 갱신: 없음 / 30초 이하)
- speak(text): Windows 내장 한국어 음성(TTS)으로 말하기 (예: 붕괴 발생 시 "붕괴")

음량(0~100)은 소리 파일의 크기를 직접 줄여서 적용한다(winsound 는 음량 조절이 없음).
만든 소리는 %APPDATA%\\CheckBuff\\sounds 에 음량별로 저장해 두고 다시 쓴다.
"""
import asyncio
import hashlib
import io
import threading
import wave
import winsound

import numpy as np

from .config import APP_DIR

RATE = 44100
SOUND_DIR = APP_DIR / "sounds"
_lock = threading.Lock()


def _tone(freq, dur, decay=11.0, harmonic=0.35):
    t = np.linspace(0, dur, int(RATE * dur), endpoint=False)
    w = (np.sin(2 * np.pi * freq * t) + harmonic * np.sin(4 * np.pi * freq * t)) * np.exp(-t * decay)
    fade = int(RATE * 0.004)
    w[:fade] *= np.linspace(0, 1, fade)
    return w


TONES = {
    "buff": lambda: _tone(1318.5, 0.35),
    "debuff": lambda: np.concatenate([_tone(784.0, 0.22, 9), _tone(587.3, 0.35, 8)]),
}


def _gain(volume) -> float:
    """0~100 → 배율. 사람 귀에 고르게 들리도록 제곱 곡선."""
    v = max(0.0, min(100.0, float(volume))) / 100.0
    return v * v


def _write(path, samples: np.ndarray, rate: int):
    SOUND_DIR.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with wave.open(str(tmp), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(rate)
        f.writeframes(np.clip(samples, -32767, 32767).astype(np.int16).tobytes())
    tmp.replace(path)


def _play_file(path):
    try:
        winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
    except Exception:
        pass


def play(kind: str = "buff", volume: float = 40):
    """알림음 재생 (kind: buff / debuff)."""
    if volume <= 0:
        return
    kind = kind if kind in TONES else "buff"
    path = SOUND_DIR / f"{kind}_{int(volume)}.wav"
    try:
        if not path.exists():
            w = TONES[kind]()
            _write(path, w / np.abs(w).max() * 0.6 * 32767 * _gain(volume), RATE)
    except Exception:
        return
    _play_file(path)


# ---------- 음성 안내 (TTS) ----------
def _synthesize(text: str) -> tuple[np.ndarray, int] | None:
    """Windows 음성 합성 → (16bit 샘플, 샘플레이트)."""
    from winrt.windows.media.speechsynthesis import SpeechSynthesizer
    from winrt.windows.storage.streams import DataReader

    async def run():
        synth = SpeechSynthesizer()
        ko = [v for v in SpeechSynthesizer.all_voices if v.language.lower().startswith("ko")]
        if ko:
            synth.voice = ko[0]
        stream = await synth.synthesize_text_to_stream_async(text)
        size = stream.size
        reader = DataReader(stream.get_input_stream_at(0))
        await reader.load_async(size)
        buf = bytearray(size)
        reader.read_bytes(buf)
        return bytes(buf)

    data = asyncio.run(run())
    with wave.open(io.BytesIO(data), "rb") as f:
        rate, width, ch = f.getframerate(), f.getsampwidth(), f.getnchannels()
        frames = f.readframes(f.getnframes())
    if width != 2:
        return None
    s = np.frombuffer(frames, np.int16).astype(np.float64)
    if ch > 1:
        s = s.reshape(-1, ch).mean(1)
    return s, rate


def speak(text: str, volume: float = 40):
    """text 를 한국어 음성으로 한 번 말한다 (처음엔 합성하느라 0.2~0.5초 걸림, 이후엔 저장된 파일 재생)."""
    if volume <= 0 or not text:
        return
    key = hashlib.md5(text.encode("utf-8")).hexdigest()[:10]
    path = SOUND_DIR / f"tts_{key}_{int(volume)}.wav"

    def work():
        with _lock:
            try:
                if not path.exists():
                    res = _synthesize(text)
                    if res is None:
                        return
                    s, rate = res
                    peak = np.abs(s).max() or 1.0
                    _write(path, s / peak * 0.9 * 32767 * _gain(volume), rate)
            except Exception:
                return
        _play_file(path)

    threading.Thread(target=work, daemon=True).start()
