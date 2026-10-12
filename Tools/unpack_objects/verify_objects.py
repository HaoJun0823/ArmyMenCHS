"""
objects.dat 严格验证器 —— 完全按游戏加载器 fileio.cpp:LoadODFSprite 的字段顺序解析。

字段顺序（fileio.cpp:1372-1436）：
    int   key             (并校验 == 目录表里的 key)
    int   width           -> srect.right
    int   height          -> srect.bottom
    int   sprite_flags
    SPOINT hotspot        (2 x SHORT = 4 字节)
    SPOINT linkspot       (2 x SHORT = 4 字节)
    int   graphicSize ; 若 >0 读 graphicSize 字节
    int   shadowSize  ; 若 >0 读 shadowSize 字节
    int   maskSize    ; 若 >0 读 maskSize 字节
    RECT  maskRect        (4 x int = 16 字节)

★ 核心判据：**每块解析结束的位置必须精确落在下一块的起始 offset 上**。
  若有偏差，说明块边界错误 → 游戏读下一块时字段全错。

用法：
    python verify_objects.py <objects.dat> [--show N] [--quiet]
"""

import sys
import os
import struct

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from objects_dat import parse_header, parse_table, split_key


def verify(path, show=20, quiet=False):
    with open(path, "rb") as f:
        buf = f.read()

    fid, palette, nobj = parse_header(buf)
    entries = parse_table(buf, nobj)

    # 目录表：按 offset 排序得到物理顺序，并算出每块的真实边界
    order = sorted(range(nobj), key=lambda i: entries[i][1])
    bounds = {}
    for pos, i in enumerate(order):
        s = entries[i][1]
        e = entries[order[pos + 1]][1] if pos + 1 < len(order) else len(buf)
        bounds[i] = (s, e)

    table_end = 1032 + nobj * 8            # 目录表结束位置
    first_data = entries[order[0]][1]

    problems = []
    ok = 0

    for pos, i in enumerate(order):
        key_expect, off = entries[i]
        s, e = bounds[i]
        actual_len = e - s

        if s < table_end:
            problems.append((key_expect, s, actual_len, None,
                             f"offset 0x{s:X} 落在目录表内(表结束于 0x{table_end:X})"))
            continue

        p = s
        if p + 28 > len(buf):
            problems.append((key_expect, s, actual_len, None, "不足以容纳头部 28 字节"))
            continue

        key, w, h, flags = struct.unpack_from("<iiii", buf, p)
        if key != key_expect:
            problems.append((key_expect, s, actual_len, None,
                             f"块内 key={key} != 目录 key={key_expect}"))
            continue
        if w <= 0 or h <= 0 or w > 4096 or h > 4096:
            problems.append((key_expect, s, actual_len, None,
                             f"尺寸异常 {w}x{h}"))
            continue
        p += 20                                  # key,w,h,flags + hotspot(4) + linkspot(4)
        # 说明：key..flags 是 16 字节，hotspot 4，linkspot 4 → 共 24，再读 graphicSize
        # 重新精确：28 = 4*4(key,w,h,flags) + 4(hotspot) + 4(linkspot) + 4(gsize)? 
        # 实际：16 + 4 + 4 = 24，然后 gsize 在 +24。故 p 应为 24。
        p = s + 24

        gsize = struct.unpack_from("<i", buf, p)[0]
        p += 4
        if gsize < 0:
            problems.append((key_expect, s, actual_len, None, f"graphicSize={gsize} 负数"))
            continue
        if p + gsize > e:
            problems.append((key_expect, s, actual_len, None,
                             f"graphicSize={gsize} 超出块边界(块长 {actual_len})"))
            continue
        p += gsize

        if p + 4 > e:
            problems.append((key_expect, s, actual_len, None, "缺 shadowSize"))
            continue
        ssize = struct.unpack_from("<i", buf, p)[0]
        p += 4
        if ssize < 0:
            problems.append((key_expect, s, actual_len, None, f"shadowSize={ssize} 负数"))
            continue
        if p + ssize > e:
            problems.append((key_expect, s, actual_len, None,
                             f"shadowSize={ssize} 超出块边界"))
            continue
        p += ssize

        if p + 4 > e:
            problems.append((key_expect, s, actual_len, None, "缺 maskSize"))
            continue
        msize = struct.unpack_from("<i", buf, p)[0]
        p += 4
        if msize < 0:
            problems.append((key_expect, s, actual_len, None, f"maskSize={msize} 负数"))
            continue
        if p + msize > e:
            problems.append((key_expect, s, actual_len, None,
                             f"maskSize={msize} 超出块边界(剩余 {e-p})"))
            continue
        p += msize

        if p + 16 > e:
            problems.append((key_expect, s, actual_len, None, "缺 maskRect(16字节)"))
            continue
        p += 16

        # ★ 核心判据
        if p != e:
            problems.append((key_expect, s, actual_len, p - s,
                             f"解析结束于 +{p-s}，但块长 {actual_len} "
                             f"(差 {actual_len-(p-s):+d})"))
            continue

        ok += 1

    if not quiet:
        print(f"file      : {path}")
        print(f"size      : {len(buf)}")
        print(f"FILEID    : {fid}")
        print(f"nObjects  : {nobj}")
        print(f"table     : 1032 .. {table_end}")
        print(f"first data: 0x{first_data:X}  (应 == {table_end})")
        if first_data != table_end:
            print(f"  ★ 数据区起点与目录表结束不符! 差 {first_data-table_end}")
        print()
        print(f"块边界精确匹配 : {ok} / {nobj}")
        print(f"异常块         : {len(problems)}")
        if problems:
            print()
            print(f"{'key':>10} {'cat':>4} {'off':>10} {'块长':>9} {'解析长':>9}  诊断")
            print("-" * 88)
            for key, off, alen, plen, msg in problems[:show]:
                cat, num, dmg = split_key(key)
                print(f"{key:>10} {cat:>4} 0x{off:>8X} {alen:>9} "
                      f"{plen if plen is not None else '?':>9}  {msg}")
            if len(problems) > show:
                print(f"... 还有 {len(problems)-show} 个")
    return ok, len(problems), problems


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 1
    show = int(args[args.index("--show") + 1]) if "--show" in args else 20
    quiet = "--quiet" in args
    ok, nbad, _ = verify(args[0], show, quiet)
    return 0 if nbad == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
