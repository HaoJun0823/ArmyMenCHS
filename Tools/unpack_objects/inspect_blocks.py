"""
并排比较同一个 key 在两个 objects.dat 中的块级字段。

用途：判断"1998 版 vs 2018 版"的差异是
    (a) 只有像素数据变了（美术修订）
    (b) 元数据变了（尺寸 / hotspot / linkspot / maskRect / 阴影 / 掩膜）
只有 (b) 才可能影响碰撞检测（吉普车被油桶卡住属于此类）。

用法：
    python inspect_blocks.py <chs.dat> <eng.dat> --keys <csv> [--out dir]
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
    fid, palette, nobj = parse_header(buf)
    entries = parse_table(buf, nobj)
    order = sorted(range(nobj), key=lambda i: entries[i][1])
    blocks = {}
    for pos, i in enumerate(order):
        s = entries[i][1]
        e = entries[order[pos + 1]][1] if pos + 1 < len(order) else len(buf)
        blocks[entries[i][0]] = buf[s:e]
    return buf, palette, entries, blocks


def parse_block(b):
    """严格按 fileio.cpp:LoadODFSprite 字段顺序拆块。"""
    key, w, h, flags = struct.unpack_from("<iiii", b, 0)
    hot = struct.unpack_from("<hh", b, 16)
    link = struct.unpack_from("<hh", b, 20)
    p = 24
    gsize = struct.unpack_from("<i", b, p)[0]; p += 4
    g = b[p:p + gsize]; p += gsize
    ssize = struct.unpack_from("<i", b, p)[0]; p += 4
    sh = b[p:p + ssize]; p += ssize
    msize = struct.unpack_from("<i", b, p)[0]; p += 4
    mk = b[p:p + msize]; p += msize
    rect = struct.unpack_from("<4i", b, p) if p + 16 <= len(b) else None
    p += 16
    return {
        "key": key, "w": w, "h": h, "flags": flags,
        "hotspot": hot, "linkspot": link,
        "gsize": gsize, "graphic": g,
        "ssize": ssize, "shadow": sh,
        "msize": msize, "mask": mk,
        "maskRect": rect,
        "consumed": p, "total": len(b),
    }


def sha(b):
    import hashlib
    return hashlib.sha256(b).hexdigest()[:12] if b else "-"


def main():
    a = sys.argv[1:]
    chs, eng = a[0], a[1]
    csv_path = a[a.index("--keys") + 1] if "--keys" in a else None
    out = a[a.index("--out") + 1] if "--out" in a else None

    buf1, pal1, ent1, blk1 = load(chs)
    buf2, pal2, ent2, blk2 = load(eng)

    print(f"CHS {chs}")
    print(f"ENG {eng}")
    print(f"调色板相同: {pal1 == pal2}   (CHS={sha(pal1)} ENG={sha(pal2)})")
    if pal1 != pal2:
        diff = [i for i in range(256)
                if pal1[i * 4:i * 4 + 4] != pal2[i * 4:i * 4 + 4]]
        print(f"  调色板不同索引 {len(diff)} 个: {diff[:40]}")
    print()

    keys = []
    if csv_path:
        with open(csv_path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row.get("status") == "diff":
                    keys.append(int(row["key"]))
    else:
        keys = sorted(k for k in blk1 if blk1[k] != blk2.get(k))

    if out:
        os.makedirs(out, exist_ok=True)

    hdr = (f"{'key':>10} {'cat':>4} {'num':>4} {'dmg':>3} | "
           f"{'w x h':>10} {'flags':>6} {'hot':>8} {'link':>8} | "
           f"{'g':>7} {'sh':>6} {'mk':>6} | maskRect | verdict")
    print(hdr)
    print("-" * len(hdr))

    for k in keys:
        if k not in blk1 or k not in blk2:
            print(f"{k:>10}  MISSING in one side")
            continue
        A, B = parse_block(blk1[k]), parse_block(blk2[k])
        cat, num, dmg = split_key(k)

        meta_diff = []
        if (A["w"], A["h"]) != (B["w"], B["h"]):
            meta_diff.append(f"尺寸 {A['w']}x{A['h']} -> {B['w']}x{B['h']}")
        if A["flags"] != B["flags"]:
            meta_diff.append(f"flags 0x{A['flags']:02X} -> 0x{B['flags']:02X}")
        if A["hotspot"] != B["hotspot"]:
            meta_diff.append(f"hotspot {A['hotspot']} -> {B['hotspot']}")
        if A["linkspot"] != B["linkspot"]:
            meta_diff.append(f"linkspot {A['linkspot']} -> {B['linkspot']}")
        if A["ssize"] != B["ssize"]:
            meta_diff.append(f"shadowSize {A['ssize']} -> {B['ssize']}")
        if A["msize"] != B["msize"]:
            meta_diff.append(f"maskSize {A['msize']} -> {B['msize']}")
        if A["maskRect"] != B["maskRect"]:
            meta_diff.append(f"maskRect {A['maskRect']} -> {B['maskRect']}")
        if A["mask"] != B["mask"]:
            meta_diff.append("掩膜像素不同")
        if A["graphic"] != B["graphic"]:
            meta_diff.append(f"图形不同({A['gsize']}B/{B['gsize']}B)")

        verdict = "元数据+像素" if meta_diff else "同"
        print(f"{k:>10} {cat:>4} {num:>4} {dmg:>3} | "
              f"{A['w']:>4}x{A['h']:<5} 0x{A['flags']:02X}   "
              f"{str(A['hotspot']):>8} {str(A['linkspot']):>8} | "
              f"{A['gsize']:>7} {A['ssize']:>6} {A['msize']:>6} | "
              f"{str(A['maskRect']):>28} | {verdict}")
        for d in meta_diff:
            print(f"{'':>10}   - {d}")

        if out:
            with open(os.path.join(out, f"k{k}_c{cat}_n{num}_d{dmg}.txt"), "w",
                      encoding="utf-8") as f:
                f.write(f"key={k} cat={cat} num={num} dmg={dmg}\n")
                f.write(f"CHS: {chs}\n  {A}\n\n")
                f.write(f"ENG: {eng}\n  {B}\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
