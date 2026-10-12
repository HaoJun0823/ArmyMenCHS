"""
逐像素统计两版精灵的差异：把差异像素的 RGB 值列出来（带坐标、计数），
用于判断到底是"调色板色位改动"还是"真的重画了像素"。

用法：
    python pixel_probe.py <a.dat> <b.dat> --key <k> [--top 20]
"""

import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from objects_dat import split_key                                # noqa: E402
from export_sprites import load_objects, parse_palette, decode  # noqa: E402


def main():
    a = sys.argv[1:]
    pa, pb = a[0], a[1]
    k = int(a[a.index("--key") + 1])
    top = int(a[a.index("--top") + 1]) if "--top" in a else 20

    pal_a, obj_a = load_objects(pa)
    pal_b, obj_b = load_objects(pb)
    pal_a, pal_b = parse_palette(pal_a), parse_palette(pal_b)

    ia, ha = decode(obj_a[k], pal_a)
    ib, hb = decode(obj_b[k], pal_b)
    cat, num, dmg = split_key(k)
    print(f"key {k}  c{cat} n{num} d{dmg}")
    print(f"  1998: {ia.size} kind={ha['kind']}")
    print(f"  2018: {ib.size} kind={hb['kind']}")
    if ia.size != ib.size:
        print("  !! 尺寸不同，跳过逐像素比较")
        return 1

    # 反查调色板索引
    idx_of = {}
    for i, c in enumerate(pal_a):
        idx_of.setdefault(c, []).append(i)

    pa_, pb_ = ia.load(), ib.load()
    W, H = ia.size
    pairs = Counter()
    coords = []
    for y in range(H):
        for x in range(W):
            A = pa_[x, y][:3]
            B = pb_[x, y][:3]
            if A != B:
                pairs[(A, B)] += 1
                if len(coords) < 12:
                    coords.append((x, y, A, B))

    print(f"  差异像素 {sum(pairs.values())} / {W*H}")
    print(f"  不同 (A,B) 颜色对 {len(pairs)} 种：")
    for (A, B), n in pairs.most_common(top):
        ia_ = idx_of.get(A)
        ib_ = idx_of.get(B)
        print(f"    {A} -> {B}   x{n:<6} "
              f"1998调色板索引={ia_}  2018调色板索引={ib_}")

    if coords:
        print("  前若干差异像素坐标：")
        for x, y, A, B in coords:
            print(f"    ({x:>4},{y:>4})  {A} -> {B}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
