"""
objects.dat 结构完整性验证：逐块解析自身结构，检查"计算长度 == 实际长度"。

对象块结构（fileio.cpp LoadODFSprite）：
    int   key
    int   width
    int   height
    int   sprite_flags
    SPOINT hotspot   (2 x SHORT)
    SPOINT linkspot  (2 x SHORT)
    int   graphicSize
    BYTE  graphic[graphicSize]
    int   shadowSize
    BYTE  shadow[shadowSize]
    int   maskSize
    BYTE  mask[maskSize]
    RECT  maskRect    (4 x int)

若计算长度与实际块长不符，说明该块被截断或混入相邻数据 → 游戏会解析错乱。

用法：
    python validate_objects.py <objects.dat> [--show N]
"""

import sys
import os
import struct

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from objects_dat import parse_header, parse_table, split_key


def load(path):
    with open(path, "rb") as f:
        buf = f.read()
    _, palette, nobj = parse_header(buf)
    entries = parse_table(buf, nobj)
    order = sorted(range(nobj), key=lambda i: entries[i][1])
    out = []
    for pos, i in enumerate(order):
        s = entries[i][1]
        e = entries[order[pos + 1]][1] if pos + 1 < len(order) else len(buf)
        out.append((entries[i][0], s, e, buf[s:e]))
    return palette, out


def expected_len(blob):
    """按结构算块应有长度。返回 (长度, 诊断) 或 (None, 原因)。"""
    if len(blob) < 28:
        return None, "块小于头部 28 字节"
    key, w, h, flags = struct.unpack_from("<iiii", blob, 0)
    gsize = struct.unpack_from("<i", blob, 24)[0]
    if gsize < 0:
        return None, f"graphicSize 负数 {gsize}"
    p = 28
    if p + gsize > len(blob):
        return None, f"graphic 越界 (需 {gsize}, 剩 {len(blob)-p})"
    p += gsize
    if p + 4 > len(blob):
        return None, "缺 shadowSize 字段"
    ssize = struct.unpack_from("<i", blob, p)[0]
    p += 4
    if ssize < 0:
        return None, f"shadowSize 负数 {ssize}"
    if p + ssize > len(blob):
        return None, f"shadow 越界 (需 {ssize}, 剩 {len(blob)-p})"
    p += ssize
    if p + 4 > len(blob):
        return None, "缺 maskSize 字段"
    msize = struct.unpack_from("<i", blob, p)[0]
    p += 4
    if msize < 0:
        return None, f"maskSize 负数 {msize}"
    if p + msize > len(blob):
        return None, f"mask 越界 (需 {msize}, 剩 {len(blob)-p})"
    p += msize
    if p + 16 > len(blob):
        return None, "缺 maskRect"
    p += 16
    return p, f"w={w} h={h} f=0x{flags:X} g={gsize} sh={ssize} mk={msize}"


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 1
    path = args[0]
    show = int(args[args.index("--show") + 1]) if "--show" in args else 15

    palette, objs = load(path)
    print(f"file   : {path}")
    print(f"objects: {len(objs)}")
    print()

    ok = 0
    bad = []
    for key, s, e, blob in objs:
        exp, diag = expected_len(blob)
        if exp is None:
            bad.append((key, len(blob), None, diag))
        elif exp != len(blob):
            bad.append((key, len(blob), exp, diag))
        else:
            ok += 1

    print(f"结构自洽 : {ok} / {len(objs)}")
    print(f"结构异常 : {len(bad)}")
    if bad:
        print()
        print(f"{'key':>10} {'cat':>4} {'实际':>9} {'应为':>9}  {'差':>7}  诊断")
        print("-" * 78)
        for key, actual, exp, diag in bad[:show]:
            cat, num, dmg = split_key(key)
            diff = (actual - exp) if exp is not None else "-"
            print(f"{key:>10} {cat:>4} {actual:>9} "
                  f"{exp if exp is not None else '?':>9} {diff:>7}  {diag}")
        if len(bad) > show:
            print(f"... 还有 {len(bad) - show} 个")
    return 0 if not bad else 2


if __name__ == "__main__":
    sys.exit(main())
