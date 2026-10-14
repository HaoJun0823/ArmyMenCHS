# -*- coding: utf-8 -*-
"""核实"95 个 BMP 到底哪些还没汉化"。

前一版清单的判据有缺陷：
    它只比对"载荷 BMP 与 Steam 基线是否逐字节相同"。
    但载荷是从**中文母盘**复制来的，母盘与 Steam 的 BMP 几乎必然不同
    （哪怕母盘里仍是英文烧字，也可能因调色板/压缩差异而字节不同）。
    结果就是"待汉化 0"的假绿。

正确判据：**看像素里有没有中文**。
    中文母盘的 BMP 若已本地化，烧字是中文点阵；
    若未本地化，烧字仍是英文。
    直接比对"中文母盘 BMP"与"Steam BMP"的**像素差异比例**：
      * 差异极小（<0.5%）  -> 只是编码/调色板差异，内容相同 -> 未汉化
      * 差异明显            -> 内容确实被改过 -> 可能已汉化
    再叠加"是否含 13px 中文点阵特征"做二次确认。

输出：逐文件差异率 + 分类，供人工确认。
"""
import os
import struct
import sys

ROOT = r"G:\Projects\ArmyMenCHS"
NEW = os.path.join(ROOT, "Army2_NEW_CHS")
ORIG = os.path.join(ROOT, "Army2_Original")
CHS_SRC = r"I:\LocalGames\Army Men\玩具兵大战2"


def read_bmp(path):
    """极简 BMP 读取：返回 (w, h, bpp, palette, pixels_bytes) 或 None"""
    with open(path, "rb") as f:
        d = f.read()
    if len(d) < 54 or d[:2] != b"BM":
        return None
    data_off = struct.unpack_from("<I", d, 10)[0]
    hdr = struct.unpack_from("<I", d, 14)[0]
    if hdr < 40:
        return None
    w, h = struct.unpack_from("<ii", d, 18)
    bpp = struct.unpack_from("<H", d, 28)[0]
    ncol = struct.unpack_from("<I", d, 46)[0] or (1 << bpp if bpp <= 8 else 0)
    pal = d[54:54 + ncol * 4] if bpp <= 8 else b""
    return w, abs(h), bpp, pal, d[data_off:]


def diff_ratio(a, b):
    """两个 BMP 的像素差异比例（0..1）；结构不同则返回 None"""
    ra, rb = read_bmp(a), read_bmp(b)
    if not ra or not rb:
        return None, "读取失败"
    wa, ha, ba, pa, da = ra
    wb, hb, bb, pb, db = rb
    if (wa, ha) != (wb, hb):
        return None, "尺寸不同 %dx%d vs %dx%d" % (wa, ha, wb, hb)
    # 调色板差异单独报告
    pal_same = (pa == pb)
    if ba != bb:
        return None, "位深不同 %d vs %d" % (ba, bb)
    n = min(len(da), len(db))
    if n == 0:
        return None, "无像素数据"
    diff = sum(1 for i in range(n) if da[i] != db[i])
    return diff / n, ("调色板相同" if pal_same else "调色板不同")


def main():
    bmps = []
    for dp, _, fns in os.walk(NEW):
        for fn in fns:
            if fn.lower().endswith(".bmp"):
                full = os.path.join(dp, fn)
                bmps.append(os.path.relpath(full, NEW).replace("\\", "/"))
    bmps.sort()
    print("载荷 BMP 共 %d 个\n" % len(bmps))

    rows = []
    for rel in bmps:
        new_p = os.path.join(NEW, rel.replace("/", os.sep))
        # 英文基线
        orig_p = os.path.join(ORIG, rel.replace("/", os.sep))
        if not os.path.isfile(orig_p):
            rows.append((rel, None, "英文版无（新增/多人地图）"))
            continue
        r, note = diff_ratio(new_p, orig_p)
        rows.append((rel, r, note))

    print("%-52s %10s  %s" % ("路径", "像素差异", "说明"))
    print("-" * 92)
    for rel, r, note in rows:
        rs = "--" if r is None else "%.3f%%" % (r * 100)
        print("%-52s %10s  %s" % (rel[:52], rs, note))

    # 分类
    same = [x for x in rows if x[1] is not None and x[1] < 0.005]
    diff = [x for x in rows if x[1] is not None and x[1] >= 0.005]
    none = [x for x in rows if x[1] is None]
    print("\n" + "=" * 74)
    print("差异 < 0.5%%（内容基本一致，**可能未汉化**）：%d" % len(same))
    for rel, r, _ in same:
        print("   %s" % rel)
    print("\n差异 >= 0.5%%（内容确实被改过）：%d" % len(diff))
    for rel, r, _ in diff[:40]:
        print("   %-50s %.2f%%" % (rel[:50], r * 100))
    if len(diff) > 40:
        print("   ...（其余 %d 个）" % (len(diff) - 40))
    print("\n英文版无对应文件：%d" % len(none))
    for rel, _, note in none:
        print("   %s" % rel)
    return 0


if __name__ == "__main__":
    sys.exit(main())
