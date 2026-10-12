"""
对比两个 objects.dat 的逐 key 差异。

用途：量化"中文版到底改了哪些精灵"，从而决定汉化策略是
      (a) 逐 key 移植差异（精细）还是 (b) 整包替换（粗糙）。

用法：
    python diff_objects.py <chs.dat> <eng.dat> [--csv out.csv]

输出：
    - 调色板是否相同
    - key 集合是否相同
    - 逐 key 数据是否相同，统计"仅中文不同"的 key 数量与分类分布
"""

import sys
import os
import json
import struct
import hashlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from objects_dat import (parse_header, parse_table, split_key,
                         HEADER_SIZE)


def load(path):
    with open(path, "rb") as f:
        buf = f.read()
    fileid, palette, nobj = parse_header(buf)
    entries = parse_table(buf, nobj)
    order = sorted(range(nobj), key=lambda i: entries[i][1])
    bounds = {}
    for pos, i in enumerate(order):
        start = entries[i][1]
        end = entries[order[pos + 1]][1] if pos + 1 < len(order) else len(buf)
        bounds[i] = (start, end)
    data = {}
    for i, (key, off) in enumerate(entries):
        s, e = bounds[i]
        data[key] = buf[s:e]
    return fileid, palette, entries, data


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 1
    chs_p, eng_p = sys.argv[1], sys.argv[2]
    csv_out = None
    if "--csv" in sys.argv:
        csv_out = sys.argv[sys.argv.index("--csv") + 1]

    f1, pal1, ent1, d1 = load(chs_p)
    f2, pal2, ent2, d2 = load(eng_p)

    print(f"CHS : {chs_p}")
    print(f"      nObjects={len(ent1)}  palette_sha={hashlib.sha256(pal1).hexdigest()[:12]}")
    print(f"ENG : {eng_p}")
    print(f"      nObjects={len(ent2)}  palette_sha={hashlib.sha256(pal2).hexdigest()[:12]}")

    print()
    print(f"调色板相同 : {pal1 == pal2}")
    k1 = set(d1.keys())
    k2 = set(d2.keys())
    print(f"key 集合相同: {k1 == k2}"
          f"  (仅中文: {len(k1 - k2)}, 仅英文: {len(k2 - k1)})")
    print(f"表顺序相同  : {[e[0] for e in ent1] == [e[0] for e in ent2]}")

    common = sorted(k1 & k2)
    same = [k for k in common if d1[k] == d2[k]]
    diff = [k for k in common if d1[k] != d2[k]]
    print()
    print(f"共同 key     : {len(common)}")
    print(f"  数据相同   : {len(same)}")
    print(f"  数据不同   : {len(diff)}  <-- 这些是被汉化/改动过的精灵")

    # 分类分布
    cats = {}
    for k in diff:
        c, n, dmg = split_key(k)
        cats[c] = cats.get(c, 0) + 1
    print()
    print("不同 key 的分类分布 (category: count)：")
    for c in sorted(cats):
        print(f"  cat {c:3d} : {cats[c]}")

    # 大小差
    sz1 = sum(len(d1[k]) for k in common)
    sz2 = sum(len(d2[k]) for k in common)
    print()
    print(f"共同 key 数据总大小: CHS={sz1}  ENG={sz2}  Δ={sz1 - sz2}")

    if csv_out:
        import csv
        with open(csv_out, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["key", "category", "number", "damagelevel",
                        "size_chs", "size_eng", "status"])
            for k in sorted(k1 | k2):
                c, n, dmg = split_key(k)
                s1 = len(d1.get(k, b""))
                s2 = len(d2.get(k, b""))
                if k not in k2:
                    st = "chs_only"
                elif k not in k1:
                    st = "eng_only"
                elif d1[k] == d2[k]:
                    st = "same"
                else:
                    st = "diff"
                w.writerow([k, c, n, dmg, s1, s2, st])
        print(f"\nCSV 已写出: {csv_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
