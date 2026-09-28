"""스크린샷 파일로 분석기를 시험해 보는 도구.  사용: py tools/analyze_image.py 캡처.png"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from checkbuff import config  # noqa: E402
from checkbuff.ocr import WindowsOcr  # noqa: E402
from checkbuff.vision import Analyzer  # noqa: E402


def main(path):
    an = Analyzer(config.load(), WindowsOcr("ko"))
    rgb = np.asarray(Image.open(path).convert("RGB"))
    col = an.find_name_column(rgb)
    print(f"이름 열 x = {col}")
    if col is None:
        return
    for r in an.scan(rgb, col):
        if r.active:
            state = f"사용 중 · 빨강={r.is_red} · 시간 OCR={an.ocr_text(an.masks(rgb)[0], r.time_box)!r}"
        else:
            state = "대기"
        print(f"y={r.band[0]:4d}  이름(OCR)={r.ocr_name!r:24s} 비트맵={r.name_bits.shape}  {state}")
    mask, _ = an.masks(rgb, include_gray=True)
    Image.fromarray(np.where(mask, 255, 0).astype(np.uint8)).save(Path(path).with_suffix(".mask.png"))


if __name__ == "__main__":
    main(sys.argv[1])
