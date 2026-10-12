"""
对同一 key 的两版精灵做像素级差异高亮：不同处染洋红，相同处保持灰度。
用于快速判断"汉化文字到底写在哪"。

用法：
    python diff_highlight.py <in.png> <out.png> [--threshold 8]
"""

import os
import sys

from PIL import Image, ImageChops


def main():
    a = sys.argv[1:]
    src, dst = a[0], a[1]
    thr = int(a[a.index("--threshold") + 1]) if "--threshold" in a else 8

    im = Image.open(src).convert("RGBA")
    mid = 8
    W = im.width
    left = im.crop((0, 0, (W - mid) // 2, im.height))
    right = im.crop((W - (W - mid) // 2 + mid, 0, W, im.height))
    # 上面的切分可能因 padding 偏移而略歪，改用按半宽切
    half = W // 2
    left = im.crop((0, 0, half, im.height))
    right = im.crop((W - half, 0, W, im.height))
    if left.size != right.size:
        right = right.resize(left.size, Image.NEAREST)

    d = ImageChops.difference(left, right).convert("RGB")
    px = d.load()
    W2, H2 = d.size
    out = Image.new("RGB", (W2, H2), (25, 25, 30))
    op = out.load()
    n = 0
    for y in range(H2):
        for x in range(W2):
            r, g, b = px[x, y]
            if max(r, g, b) > thr:
                op[x, y] = (255, 0, 200)          # 差异
                n += 1
            else:
                v = 90
                op[x, y] = (v, v, v)              # 相同 -> 灰底
    sc = 6 if max(W2, H2) < 120 else 3
    out = out.resize((W2 * sc, H2 * sc), Image.NEAREST)
    out.save(dst)
    print(f"{os.path.basename(src)}: {n} 个差异像素 / {W2*H2}"
          f"  ({100.0*n/(W2*H2):.1f}%)  -> {dst}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
