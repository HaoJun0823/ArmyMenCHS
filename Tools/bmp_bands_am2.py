# -*- coding: utf-8 -*-
"""判定载荷 BMP 的实际汉化状态（避开"差异率"这个坏判据）。

★ 为什么不能用差异率：
    load_airborne.bmp 差异仅 0.28%，但**已汉化**（标题框
    "MAP 04 : AIRBORNE" -> "地图 04：飞机场"）。
    差异小是因为标题框面积本来就小。
  反之 bootcamp-*.bmp 差异 30%，那是整幅地图重绘，与文字无关。

★ 为什么不能用"是否含中文点阵"：
    BMP 是**位图**，不是点阵字库，没有可查的字体结构。

★ 可行判据：**只比较"文字条带"区域**。
    这些界面的标题都在顶部一条窄带内（y ≈ 40..70，居中）。
    把该条带裁出来并排，人眼一眼可判。

本脚本：对每个 BMP 裁出若干候选条带，拼成一张总览图，
        文件名标出来源，供人工一次看完。
"""
import os
import sys

ROOT = r"G:\Projects\ArmyMenCHS"
NEW = os.path.join(ROOT, "Army2_NEW_CHS")
ORIG = os.path.join(ROOT, "Army2_Original")
OUT = os.path.join(ROOT, "_bmp_cmp")

from PIL import Image

# 只看这些目录的图（界面/载入图），地图底图(mapXX)不含文字
SKIP_PREFIX = ("bitmaps/map", "data/")


def bands(im):
    """返回候选文字条带（y0,y1）。这些界面标题在顶部窄带内。"""
    h = im.height
    return [(0, min(h, 90)), (max(0, h - 60), h)]


def main():
    os.makedirs(OUT, exist_ok=True)
    rows = []
    for dp, _, fns in os.walk(NEW):
        for fn in fns:
            if not fn.lower().endswith(".bmp"):
                continue
            full = os.path.join(dp, fn)
            rel = os.path.relpath(full, NEW).replace("\\", "/")
            if rel.startswith(SKIP_PREFIX):
                continue
            op = os.path.join(ORIG, rel.replace("/", os.sep))
            if not os.path.isfile(op):
                continue
            rows.append((rel, full, op))
    rows.sort()
    print("参与对比的界面 BMP: %d 个" % len(rows))

    tiles = []
    for rel, new_p, orig_p in rows:
        a = Image.open(orig_p).convert("RGB")
        b = Image.open(new_p).convert("RGB")
        if a.size != b.size:
            continue
        # 取顶部条带（多数标题在此）
        y0, y1 = 0, min(a.height, 80)
        ta = a.crop((0, y0, a.width, y1))
        tb = b.crop((0, y0, b.width, y1))
        tiles.append((rel, ta, tb))

    if not tiles:
        print("无可用对比")
        return 1

    # 每行一对（英文在上、中文在下），纵向堆叠成总览
    W = max(t[1].width for t in tiles)
    per = 8
    chunks = [tiles[i:i + per] for i in range(0, len(tiles), per)]
    for ci, chunk in enumerate(chunks):
        row_h = sum(t[1].height + t[2].height + 6 for t in chunk) + 6 * len(chunk)
        canvas = Image.new("RGB", (W, row_h), (40, 40, 40))
        y = 0
        for rel, ta, tb in chunk:
            canvas.paste(ta, (0, y)); y += ta.height
            canvas.paste(tb, (0, y)); y += tb.height
            y += 6
        p = os.path.join(OUT, "bands_%02d.png" % ci)
        canvas.save(p)
        print("  -> %s  (%d 组；每组上=英文 下=中文)" % (os.path.basename(p), len(chunk)))
        for rel, _, _ in chunk:
            print("       %s" % rel)
    return 0


if __name__ == "__main__":
    sys.exit(main())
