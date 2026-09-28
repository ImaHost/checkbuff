"""버프체크기 아이콘 생성 → assets/icon.ico, assets/icon.png

디자인: 어두운 둥근 사각 타일 위에 남은 시간 링(금색, 끝부분만 빨강 = 곧 만료)과
가운데 위쪽 화살표(버프). 크게 그린 뒤 줄여서 작은 크기에서도 선명하게.
"""
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

S = 1024
OUT = Path(__file__).resolve().parents[1] / "assets"

BG_TOP = (38, 42, 54)
BG_BOTTOM = (16, 18, 24)
GOLD = (227, 181, 91)
GOLD_LIGHT = (246, 214, 142)
RED = (255, 92, 92)
TRACK = (255, 255, 255, 28)


def rounded_tile():
    grad = Image.new("RGBA", (S, S))
    px = grad.load()
    for y in range(S):
        t = y / (S - 1)
        c = tuple(int(BG_TOP[i] + (BG_BOTTOM[i] - BG_TOP[i]) * t) for i in range(3))
        for x in range(S):
            px[x, y] = c + (255,)
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle((24, 24, S - 24, S - 24), radius=220, fill=255)
    tile = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    tile.paste(grad, (0, 0), mask)
    # 윗부분 은은한 하이라이트 테두리
    ImageDraw.Draw(tile).rounded_rectangle((24, 24, S - 24, S - 24), radius=220,
                                           outline=(255, 255, 255, 30), width=6)
    return tile


def arc(draw, box, start, end, color, width):
    draw.arc(box, start, end, fill=color, width=width)
    # 둥근 끝
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    r = (box[2] - box[0]) / 2 - width / 2
    for ang in (start, end):
        a = math.radians(ang)
        x, y = cx + r * math.cos(a), cy + r * math.sin(a)
        draw.ellipse((x - width / 2, y - width / 2, x + width / 2, y + width / 2), fill=color)


def main():
    img = rounded_tile()
    layer = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    m = 190
    box = (m, m, S - m, S - m)
    w = 78
    d.ellipse(box, outline=TRACK, width=w)
    # 12시 방향에서 시계방향으로: 금색(남은 시간) → 빨강(곧 만료)
    arc(d, box, -90, 185, GOLD, w)
    arc(d, box, 205, 245, RED, w)

    # 가운데 위쪽 화살표 (버프)
    cx, cy = S / 2, S / 2 + 10
    head = [(cx, cy - 190), (cx + 150, cy - 30), (cx + 58, cy - 30), (cx + 58, cy + 170),
            (cx - 58, cy + 170), (cx - 58, cy - 30), (cx - 150, cy - 30)]
    d.polygon(head, fill=GOLD_LIGHT)
    glow = layer.filter(ImageFilter.GaussianBlur(28))
    img.alpha_composite(Image.eval(glow, lambda v: int(v * 0.45)))
    img.alpha_composite(layer)

    OUT.mkdir(exist_ok=True)
    img.resize((256, 256), Image.LANCZOS).save(OUT / "icon.png")
    img.save(OUT / "icon.ico", sizes=[(16, 16), (20, 20), (24, 24), (32, 32), (48, 48), (64, 64),
                                      (128, 128), (256, 256)])
    print("saved", OUT)


if __name__ == "__main__":
    main()
