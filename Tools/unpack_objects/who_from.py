"""
检查"当前部署的 objects.dat"里若干 key 的块，分别与两个来源对比，
判断部署文件的每个差异块取自 1998(中文盘) 还是 2018(Steam)。

用法：
    python who_from.py <deployed.dat> <a.dat> <b.dat> [--keys csv]
    a.dat 标记为 A，b.dat 标记为 B
"""

import csv
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from objects_dat import parse_header, parse_table, split_key   # noqa: E402


def load(path):
    with open(path, "rb") as f:
        buf = f.read()
    _, _, nobj = parse_header(buf)
    entries = parse_table(buf, nobj)
    order = sorted(range(nobj), key=lambda i: entries[i][1])
    blocks = {}
    for pos, i in enumerate(order):
        s = entries[i][1]
        e = entries[order[pos + 1]][1] if pos + 1 < len(order) else len(buf)
        blocks[entries[i][0]] = buf[s:e]
    return blocks


def brief(b):
    key, w, h, flags = struct.unpack_from("<iiii", b, 0)
    p = 24
    gsize = struct.unpack_from("<i", b, p)[0]; p += 4 + gsize
    ssize = struct.unpack_from("<i", b, p)[0]; p += 4 + ssize
    msize = struct.unpack_from("<i", b, p)[0]; p += 4 + msize
    return f"{w}x{h} fl=0x{flags:02X} g={gsize} sh={ssize} mask={msize}"


def main():
    a = sys.argv[1:]
    dep, pa, pb = a[0], a[1], a[2]
    csv_path = a[a.index("--keys") + 1] if "--keys" in a else None

    D, A, B = load(dep), load(pa), load(pb)
    print(f"DEPLOYED {dep}")
    print(f"A(=1998)   {pa}")
    print(f"B(=2018)   {pb}")
    print()

    if csv_path:
        with open(csv_path, newline="", encoding="utf-8") as f:
            keys = [int(r["key"]) for r in csv.DictReader(f)
                    if r.get("status") == "diff"]
    else:
        keys = sorted(D)

    rows = []
    for k in keys:
        if k not in D or k not in A or k not in B:
            continue
        same_a = D[k] == A[k]
        same_b = D[k] == B[k]
        if same_a == same_b:
            tag = "?"          # 两者相同，或与两者都不同
        elif same_a:
            tag = "A(1998)"
        else:
            tag = "B(2018)"
        cat, num, dmg = split_key(k)
        rows.append((k, cat, num, dmg, tag))

    print(f"{'key':>10} {'cat':>4} {'num':>4} {'dmg':>3}  来源   部署版块摘要")
    print("-" * 96)
    for k, cat, num, dmg, tag in rows:
        print(f"{k:>10} {cat:>4} {num:>4} {dmg:>3}  {tag:<7} {brief(D[k])}")

    na = sum(1 for r in rows if r[4] == "A(1998)")
    nb = sum(1 for r in rows if r[4] == "B(2018)")
    print()
    print(f"合计 {len(rows)}: 取自 1998(A) = {na}，取自 2018(B) = {nb}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
