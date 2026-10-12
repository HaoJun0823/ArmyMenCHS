"""
不做"非黑即有色"二值化，直接比较两版精灵的**原始 RGB 值**，
输出：仅 1998 独有的颜色集合 / 仅 2018 独有的颜色集合 / 共有颜色。

用法：
    python palette_diff.py <a.dat> <b.dat> --keys <csv>
"""

import csv
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from objects_dat import split_key                                # noqa: E402
from export_sprites import load_objects, parse_palette, decode  # noqa: E402


def main():
    a = sys.argv[1:]
    pa, pb = a[0], a[1]
    with open(a[a.index("--keys") + 1], newline="", encoding="utf-8") as f:
        keys = [int(r["key"]) for r in csv.DictReader(f) if r.get("status") == "diff"]

    pal_a, obj_a = load_objects(pa)
    pal_b, obj_b = load_objects(pb)
    pal_a, pal_b = parse_palette(pal_a), parse_palette(pal_b)

    print(f"调色板差异索引: {[i for i in range(256) if pal_a[i] != pal_b[i]]}")
    for i in range(256):
        if pal_a[i] != pal_b[i]:
            print(f"  [{i}] 1998={pal_a[i]}  2018={pal_b[i]}")
    print()

    all_a, all_b = Counter(), Counter()
    for k in sorted(keys):
        ia, _ = decode(obj_a[k], pal_a)
        ib, _ = decode(obj_b[k], pal_b)
        if ia is None or ib is None:
            continue
        ca = Counter(ia.getdata())
        cb = Counter(ib.getdata())
        all_a += ca
        all_b += cb
        cat, num, dmg = split_key(k)
        only_a = set(ca) - set(cb)
        only_b = set(cb) - set(ca)
        if only_a or only_b:
            print(f"c{cat} n{num} d{dmg}:")
            for c in sorted(only_a, key=lambda z: -ca[z])[:6]:
                print(f"    仅1998  {c}  x{ca[c]}")
            for c in sorted(only_b, key=lambda z: -cb[z])[:6]:
                print(f"    仅2018  {c}  x{cb[c]}")

    print()
    print("=== 全局颜色分布 ===")
    only_a = set(all_a) - set(all_b)
    only_b = set(all_b) - set(all_a)
    print(f"1998 版独有颜色 {len(only_a)} 种:")
    for c in sorted(only_a, key=lambda z: -all_a[z]):
        print(f"    {c}  x{all_a[c]}")
    print(f"2018 版独有颜色 {len(only_b)} 种:")
    for c in sorted(only_b, key=lambda z: -all_b[z]):
        print(f"    {c}  x{all_b[c]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
