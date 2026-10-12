"""
把精灵按"是否使用调色板 index 248"二值化输出，
确认 1998 盘到底把哪个色位改成了蓝色（89,132,212）。

用法：
    python pal248_mask.py <dat> --key <k> --out <png> [--pal 1998|2018]
"""

import os
import sys

from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from objects_dat import split_key                                # noqa: E402
from export_sprites import load_objects, parse_palette, decode  # noqa: E402

TARGET = 248


def main():
    a = sys.argv[1:]
    path = a[0]
    k = int(a[a.index("--key") + 1])
    out = a[a.index("--out") + 1]
    pal_raw, objs = load_objects(path)
    pal = parse_palette(pal_raw)

    im, hdr = decode(objs[k], pal)
    if im is None:
        print("decode failed")
        return 1
    cat, num, dmg = split_key(k)

    # 该 key 实际用到的调色板索引（重新解 RLE 太麻烦，这里从原图反查）
    px = im.load()
    W, H = im.size
    vis = Image.new("RGB", (W, H), (30, 30, 36))
    vp = vis.load()
    hits = 0
    for y in range(H):
        for x in range(W):
            r, g, b, _ = px[x, y]
            if (r, g, b) == tuple(pal[TARGET]):
                vp[x, y] = (255, 0, 210)
                hits += 1
            elif (r, g, b) != (0, 0, 0):
                v = (r + g + b) // 3 // 3
                vp[x, y] = (v, v, v)
    sc = 5 if max(W, H) < 160 else 2
    vis = vis.resize((W * sc, H * sc), Image.NEAREST)
    vis.save(out)
    print(f"key {k} (c{cat} n{num} d{dmg}) {W}x{H} kind={hdr['kind']}")
    print(f"  调色板[{TARGET}] = {pal[TARGET]}  命中像素 {hits}")
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
