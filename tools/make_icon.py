"""멜야옹 체크기 아이콘 생성: assets/icon_source.png(고양이 발바닥) → assets/icon.ico, assets/icon.png

원본의 바깥쪽 연한 회색 배경을 가장자리부터 채워 나가며 투명하게 만든다 (갈색 테두리 안쪽의 흰 발바닥은 유지).
그다음 여백을 잘라 정사각형으로 맞추고 여러 크기로 저장한다.
"""
from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image

ASSETS = Path(__file__).resolve().parents[1] / "assets"


def main():
    a = np.asarray(Image.open(ASSETS / "icon_source.png").convert("RGBA")).copy()
    rgb = a[..., :3].astype(np.int16)
    bg = (rgb.min(2) >= 225) & ((rgb.max(2) - rgb.min(2)) <= 20)    # 연한 회색·흰색
    H, W = bg.shape
    outside = np.zeros_like(bg)
    q = deque([(y, x) for y in range(H) for x in (0, W - 1)] + [(y, x) for x in range(W) for y in (0, H - 1)])
    while q:
        y, x = q.popleft()
        if 0 <= y < H and 0 <= x < W and bg[y, x] and not outside[y, x]:
            outside[y, x] = True
            q.extend(((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)))
    a[outside, 3] = 0
    ys, xs = np.nonzero(a[..., 3] > 0)
    a = a[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    h, w = a.shape[:2]
    side = int(max(h, w) * 1.06)
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(Image.fromarray(a), ((side - w) // 2, (side - h) // 2))
    big = canvas.resize((256, 256), Image.LANCZOS)
    big.save(ASSETS / "icon.png")
    big.save(ASSETS / "icon.ico", sizes=[(16, 16), (20, 20), (24, 24), (32, 32), (48, 48), (64, 64),
                                         (128, 128), (256, 256)])
    print("saved", ASSETS / "icon.ico")


if __name__ == "__main__":
    main()
