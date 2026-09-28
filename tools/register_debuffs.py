"""디버프 아이콘 줄 캡처 이미지로 디버프를 등록한다.

사용: py tools/register_debuffs.py [이미지] [이름1 이름2 ...]
- 기본 이미지: assets/debuffs_12.png, 기본 이름: debuffs.DEFAULT_PRESET (왼쪽부터 순서대로)
- 이름이 같은 아이콘은 한 디버프로 묶임 (그중 하나만 있어도 '있음')

아이콘 배치(테두리 포함 한 변, 간격)는 이미지에서 자동으로 찾는다: 아이콘 테두리 윗줄은 어두운 가로선이 한 변 길이로
반복되므로, 그 반복 간격과 시작 위치를 구한 뒤 테두리 안쪽만 잘라 등록한다(모서리의 반투명 배경 영향 제거).
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from checkbuff.debuffs import DEFAULT_PRESET, DebuffBook  # noqa: E402


def grid_icons(rgb: np.ndarray, count: int):
    """아이콘마다 잘라낼 (x, y, 한 변) — 테두리 안쪽. 아이콘 테두리는 어두운 선이고 모서리 1px 은 투명하다.
    어두운 가로선이 가장 긴 행에서 테두리 폭(=아이콘 폭)과 반복 간격을, 가운데 세로줄에서 윗 테두리를 찾는다."""
    dark = rgb.astype(np.int16).mean(2) < 50
    row = int(np.argmax(dark.sum(1)))
    runs, start = [], None
    for x, v in enumerate(list(dark[row]) + [False]):
        if v and start is None:
            start = x
        elif not v and start is not None:
            runs.append((start, x))
            start = None
    runs = [r for r in runs if r[1] - r[0] >= 8]
    if not runs:
        raise SystemExit("아이콘 테두리를 찾지 못했습니다")
    width = int(np.median([r[1] - r[0] for r in runs]))          # 테두리 포함 아이콘 폭 (예: 16)
    starts = [r[0] for r in runs]
    pitch = int(np.median(np.diff(starts))) if len(starts) > 1 else width + 2
    x0 = starts[0]
    ys = np.nonzero(dark[:, x0 + width // 2])[0]
    top = int(ys.min())                                            # 윗 테두리 첫 행
    inner = width - 2
    return [(x0 + 1 + i * pitch, top, inner) for i in range(count)]


def main():
    img = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "assets" / "debuffs_12.png"
    names = sys.argv[2:] or DEFAULT_PRESET
    rgb = np.asarray(Image.open(img).convert("RGB"))
    boxes = grid_icons(rgb, len(names))
    book = DebuffBook()
    for (x, y, s), name in zip(boxes, names):
        icon = rgb[y:y + s, x:x + s].copy()                          # 테두리 안쪽 (모서리 배경 영향 제거)
        if icon.shape[0] < 8 or icon.shape[1] < 8:
            raise SystemExit(f"'{name}' 아이콘이 이미지 밖입니다: {(x, y, s)}")
        book.upsert(icon, name, True)
    book.save()
    print("저장:", book.path)
    for it in book.items:
        print(f"  {it['name']}: 아이콘 {len(it['icons'])}개")


if __name__ == "__main__":
    main()
